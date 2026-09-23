"""规则系统 2.0 云托管 API。

设计要点(面向多小程序并发):
  1. 生产模式使用 COS 产物 + MySQL 租约队列；SQLite/本地盘仅供开发。
  2. CPU 密集的排布/渲染走线程池, 用信号量限流, 不阻塞事件循环。
  3. 同步 /api/plan|/api/recommend 与异步 /api/jobs 双轨, 共用 _execute_plan 内核。
  4. 仅信任微信网关链路，按 AppID + 用户隔离，生产必须关闭公网入口。
  5. 对外只返回可访问 URL, 绝不回传容器绝对路径、请求头或环境变量。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

os.environ.setdefault("MPLBACKEND", "Agg")

_APP_DIR = Path(__file__).resolve().parent          # .../cloudrun_app
RULE_ROOT = _APP_DIR.parent
LOCAL_ROOT = Path(os.environ.get('LOCAL_STORAGE_ROOT', str(RULE_ROOT / 'generated_runs')))
LOCAL_ROOT.mkdir(parents=True, exist_ok=True)

# uvicorn 以 "cloudrun_app.main:app" 方式导入时, sys.path 里只有项目根目录,
# 没有 cloudrun_app 本身, 导致下面 `import storage` 失败。这里显式补上。
for _p in (
    str(_APP_DIR),
    str(RULE_ROOT / "05_config_and_tools"),
    str(RULE_ROOT / "01_pre_selection"),
    str(RULE_ROOT / "02_placement_generation" / "layout_optimization"),
    str(RULE_ROOT / "03_visualization"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI, HTTPException, Request, status          # noqa: E402
from fastapi.middleware.cors import CORSMiddleware                    # noqa: E402
from fastapi.responses import FileResponse, JSONResponse              # noqa: E402
from pydantic import BaseModel, Field, field_validator # noqa: E402

from config_loader import get_module_catalog as _get_catalog          # noqa: E402
from service_adapter import (                                         # noqa: E402
    create_run_id,
    generate_plan_payload,
    generate_recommendation_payload,
    validate_selection_rules,
)
from storage import build_storage                                     # noqa: E402
from contract import to_v1_contract                                   # noqa: E402
from ratelimit import SlidingWindowLimiter                            # noqa: E402
from tenant import assert_allowed, header_names, read_tenant, owner_key # noqa: E402
from job_queue import build_job_queue                                # noqa: E402
from compute_budget import start_budget, reset_budget                 # noqa: E402
from deployment import validate_production                           # noqa: E402
from request_limits import RequestSizeLimit                          # noqa: E402

validate_production()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rule-system-api-v2")

# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
CST = timezone(timedelta(hours=8))
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

MAX_INFLIGHT = int(os.environ.get("MAX_INFLIGHT", "1"))              # 每进程并发上限
ADMIT_TIMEOUT = float(os.environ.get("ADMIT_TIMEOUT_SECONDS", "1"))  # 同步排队等待上限
MAX_ASYNC_PENDING = int(os.environ.get("MAX_ASYNC_PENDING", str(MAX_INFLIGHT * 4)))
IDEMPOTENT_TTL = int(os.environ.get("IDEMPOTENT_TTL_SECONDS", "60"))
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "10"))
DEBUG_HEADER_NAMES = os.environ.get("DEBUG_HEADER_NAMES", "") == "1"
_PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

_metrics_lock = threading.Lock()
_metrics = {"inflight": 0, "admitted": 0, "rejected": 0, "completed": 0, "failed": 0}

# 幂等缓存: 参数指纹 -> (过期时间戳, 结果)
_IDEMPOTENT: Dict[str, tuple] = {}
_IDEMPOTENT_LOCK = threading.Lock()

_storage = build_storage(LOCAL_ROOT, _PUBLIC_BASE_URL)
_limiter = SlidingWindowLimiter(RATE_LIMIT, 60.0)
# Cart edits must not consume the small generation quota (default 10/minute).
_validation_limiter = SlidingWindowLimiter(int(os.environ.get('VALIDATION_RATE_LIMIT_PER_MIN', '60')), 60.0)
# 任务状态查询必须与生成分开限流: 前端轮询频率远高于生成频率(1 次生成需要对
# 应几十次查询), 共用配额会把轮询打成 429, 让已经排上队的任务看起来像失败。
_query_limiter = SlidingWindowLimiter(int(os.environ.get('QUERY_RATE_LIMIT_PER_MIN', '120')), 60.0)

_admit = asyncio.Semaphore(MAX_INFLIGHT)          # 同步路径准入(快速失败)
_cpu_slot = threading.BoundedSemaphore(MAX_INFLIGHT)  # 真正保护 CPU/内存
_jobs = build_job_queue(os.environ.get('JOB_DB_PATH', str(LOCAL_ROOT / 'jobs.sqlite3')),
                        max_pending=MAX_ASYNC_PENDING)
_worker_stop = threading.Event()


def _now() -> datetime:
    return datetime.now(CST)


def _bump(key: str, delta: int = 1) -> None:
    with _metrics_lock:
        _metrics[key] = _metrics.get(key, 0) + delta


def _async_pending_count() -> int:
    return _jobs.pending_count()


# --------------------------------------------------------------------------- #
# 应用
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    """冷启动预热: 导入 matplotlib、加载贴图与配置, 把首请求延迟压到只剩计算。"""
    t0 = time.perf_counter()
    try:
        import renderer  # noqa: PLC0415

        renderer.get_texture_handler()
        _get_catalog()
        logger.info("[预热] 完成, 耗时 %.2fs", time.perf_counter() - t0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[预热] 失败(不影响服务启动): %s", exc)
    _worker_stop.clear()
    executor = ThreadPoolExecutor(max_workers=MAX_INFLIGHT, thread_name_prefix='job-worker')
    for _ in range(MAX_INFLIGHT):
        executor.submit(_worker_loop)
    yield
    _worker_stop.set()
    executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title="Rule System 2.0 CloudRun API",
    version="2.0.0",
    description="规则系统 2.0 — 云托管接口, 支持多小程序并发生成布局图",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestSizeLimit)

_SKIP_TENANT_PATHS = {"/health", "/", "/metrics", "/favicon.ico"}


@app.middleware("http")
async def tenant_and_quota(request: Request, call_next):
    if request.url.path in _SKIP_TENANT_PATHS or request.url.path.startswith("/api/runs/files/"):
        return await call_next(request)

    tenant = read_tenant(request)
    request.state.tenant = tenant

    try:
        assert_allowed(tenant)
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    key = tenant["userKey"] or tenant["appid"] or (request.client.host if request.client else "anon")
    path = request.url.path
    # 只读状态查询(轮询任务进度/容量校验进度/回放结果)单独计配额, 不与生成抢占。
    is_status_query = request.method == "GET" and (
        path.startswith("/api/jobs/")
        or path.startswith("/api/preflight/")
        or path.startswith("/api/runs/")
    )
    if is_status_query:
        limiter = _query_limiter
    elif path.startswith("/api/preflight"):
        limiter = _validation_limiter
    else:
        limiter = _limiter
    if not limiter.allow(key):
        retry_after = max(1, int(limiter.retry_after(key)) + 1)
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "请求过于频繁, 请稍后再试"},
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)


# --------------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------------- #
class RecommendRequest(BaseModel):
    # 允许用字段名 asyncMode 或别名 async 传参
    model_config = {"populate_by_name": True, "allow_inf_nan": False}

    evacuees: int = Field(..., ge=1, le=2000)
    length: float = Field(..., gt=0, le=2000)
    width: float = Field(..., gt=0, le=2000)
    days: int = Field(..., ge=1, le=365)
    strategyKey: str | None = Field(default=None, pattern='^(comfort|economy|balanced|)$')
    recommendationMode: str = Field(default="match_input", pattern="^(fill|match_input)$")
    renderStructure: bool = Field(default=False, description="是否额外生成结构校对图(开发校对用)")
    previewOnly: bool = Field(default=False, description="只试排推荐，不渲染上传图片")
    # 客户端可显式要求走异步(对外字段名是 "async", 但 async 是 Python 保留字, 故用 alias)
    asyncMode: bool = Field(default=False, alias="async", description="true 时请改用 /api/jobs 提交")


class PlanRequest(RecommendRequest):
    selectedModules: Dict[str, int] | List[dict] | None = None
    runId: str | None = None

    @field_validator('selectedModules', mode='before')
    @classmethod
    def check_selection(cls, value):
        if value is None:
            return None
        from service_adapter import normalize_selected_modules
        selected = normalize_selected_modules(value)
        if sum(selected.values()) > 2000:
            raise ValueError('单次最多支持 2000 个模块，请分区生成')
        from service_adapter import summarize_selection
        if summarize_selection(selected)['totalBeds'] > 2000:
            raise ValueError('单次最多支持 2000 张床，请分区生成')
        issues = validate_selection_rules(selected)
        if issues:
            raise ValueError('; '.join(issues))
        return selected


class JobSubmitRequest(PlanRequest):
    mode: str = Field(default="plan", pattern="^(plan|recommend)$")


class PreflightRequest(PlanRequest):
    changedModule: str | None = Field(default=None, pattern="^[A-G]$")


class ValidateSelectionRequest(BaseModel):
    selectedModules: Dict[str, int] | List[dict] | None = None

    _validate_modules = field_validator('selectedModules', mode='before')(PlanRequest.check_selection.__func__)


# 显式重建请求模型, 避免容器运行时首次请求才触发注解延迟解析。
RecommendRequest.model_rebuild()
PlanRequest.model_rebuild()
JobSubmitRequest.model_rebuild()
ValidateSelectionRequest.model_rebuild()


# --------------------------------------------------------------------------- #
# 核心执行
# --------------------------------------------------------------------------- #
def _fingerprint(tenant: dict, payload: dict, mode: str) -> str:
    # runId 每次不同、asyncMode 只是传输方式; 旧客户端若仍带 timeLimitSeconds 也不纳入幂等判定
    payload = {
        k: v for k, v in payload.items()
        if k not in ("runId", "async", "asyncMode", "timeLimitSeconds")
    }
    raw = json.dumps({"a": owner_key(tenant), "m": mode, "p": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _idempotent_get(fp: str):
    now = time.time()
    with _IDEMPOTENT_LOCK:
        hit = _IDEMPOTENT.get(fp)
        if not hit:
            return None
        if hit[0] > now:
            return hit[1]
        _IDEMPOTENT.pop(fp, None)
    return None


def _idempotent_put(fp: str, result: dict) -> None:
    expire = time.time() + IDEMPOTENT_TTL
    with _IDEMPOTENT_LOCK:
        if len(_IDEMPOTENT) > 2000:
            now = time.time()
            for k in [k for k, v in _IDEMPOTENT.items() if v[0] <= now]:
                _IDEMPOTENT.pop(k, None)
        _IDEMPOTENT[fp] = (expire, result)


def _upload_outputs(
    run_dir: Path, tenant: dict, run_id: str, files: dict, require_layout: bool = False
) -> dict:
    """上传产物到存储后端, 返回对外可访问地址映射。

    require_layout=True 时(正式生成, 非 previewOnly 试排), 排布图是必需产物:
    缺失或上传失败一律抛错, 让任务明确失败, 而不是返回空 URL 让前端显示兜底静态图
    造成"生成成功但看不到图"的假成功。
    """
    date_part = _now().strftime("%Y/%m")
    appid = re.sub(r"[^A-Za-z0-9_-]", "_", tenant["appid"] or "unknown")
    public: dict = {}

    mapping = {
        "layoutPng": (f"layout_{run_id}.png", "image/png"),
        "structurePng": (f"layout_{run_id}_structure.png", "image/png"),
        "layoutJson": (f"layout_{run_id}.json", "application/json"),
    }
    for key, (filename, content_type) in mapping.items():
        local = files.get(key)
        if not local or not Path(local).exists():
            if key == "layoutPng" and require_layout:
                raise RuntimeError("排布图未生成")
            continue
        # Reclaimed attempts must not overwrite a newer worker's image.
        object_key = f"plans/{date_part}/{appid}/{run_dir.name}/{filename}"
        try:
            public[key] = _storage.put_file(Path(local), object_key, content_type)["url"]
            if key == 'layoutPng' and require_layout and not public[key]:
                raise RuntimeError('未配置可访问的图片地址')
        except Exception as exc:  # noqa: BLE001
            logger.error("[上传失败] runId=%s key=%s err=%s", run_id, key, exc)
            if key == "layoutPng" and require_layout:
                raise RuntimeError(f"排布图上传失败: {exc}") from exc
            public[key] = ""
    return public


def _execute_plan(
    payload: PlanRequest,
    mode: str,
    tenant: dict,
    run_id: str,
    admit_timeout: Optional[float] = ADMIT_TIMEOUT,
    persist_result: bool = True,
) -> dict:
    """执行推荐/排布 + 上传产物。运行在线程池中, 是纯 CPU/IO 密集逻辑。"""
    if admit_timeout is None:
        _cpu_slot.acquire()
        acquired = True
    else:
        acquired = _cpu_slot.acquire(timeout=admit_timeout)
        if not acquired:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="服务繁忙, 请稍后重试",
                headers={"Retry-After": "2"},
            )

    workdir = None
    budget = None
    _bump("inflight")
    try:
        budget = start_budget()
        workdir = Path(tempfile.mkdtemp(prefix=f"run_{run_id}_", dir=str(LOCAL_ROOT)))
        common = dict(
            evacuees=payload.evacuees,
            length=payload.length,
            width=payload.width,
            days=payload.days,
            strategy_key=payload.strategyKey,
            output_dir=str(workdir),
            run_id=run_id,
            render_structure=payload.renderStructure,
        )
        if mode == "recommend":
            raw = generate_recommendation_payload(
                recommendation_mode=payload.recommendationMode, preview_only=payload.previewOnly, **common
            )
        else:
            raw = generate_plan_payload(
                selected_modules=payload.selectedModules, **common
            )

        local_files = (raw.get("layout") or {}).get("outputFiles") or {}
        # previewOnly 只是推荐试排, 不渲染也就没有排布图; 其余场景排布图为必需产物。
        public_files = _upload_outputs(
            workdir, tenant, run_id, local_files,
            require_layout=not (mode == 'recommend' and payload.previewOnly),
        )

        result = to_v1_contract(raw, _get_catalog(), public_files)
        result["tenant"] = tenant["appid"]
        result["storage"] = _storage.name

        # Ownership is stored privately, never returned with user identifiers.
        if persist_result:
            _storage.put_json(f"results/{run_id}.json", {'owner': owner_key(tenant), 'result': result})

        _bump("completed")
        return result
    finally:
        if budget is not None:
            reset_budget(budget)
        _bump("inflight", -1)
        _cpu_slot.release()
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)


async def _run_offloaded(fn, *args):
    """把同步阻塞逻辑丢到线程池, 保持事件循环可响应 /health。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


def _handle_sync(payload: PlanRequest, mode: str, request: Request) -> dict:
    tenant = getattr(request.state, "tenant", {"appid": "unknown", "userKey": ""})
    fp = _fingerprint(tenant, payload.model_dump(mode="json"), mode)

    cached = _idempotent_get(fp)
    if cached:
        return {**cached, "idempotentHit": True}

    run_id = create_run_id(mode)
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="runId 格式不合法")

    _bump("admitted")
    try:
        result = _execute_plan(payload, mode, tenant, run_id)
    except HTTPException:
        _bump("failed")
        raise
    except ValueError as exc:
        _bump("failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        _bump("failed")
        raise HTTPException(
            status_code=408,
            detail="生成超时, 请改用 /api/jobs 异步接口",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        _bump("failed")
        logger.exception("[生成失败] runId=%s", run_id)
        raise HTTPException(status_code=500, detail='方案生成失败，请稍后重试') from exc

    _idempotent_put(fp, result)
    return result


async def _admit_and_run(payload: PlanRequest, mode: str, request: Request) -> dict:
    """准入控制: 并发满了直接 429 + Retry-After, 不排队堆积。"""
    if _admit.locked():
        _bump("rejected")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="服务繁忙, 请稍后重试",
            headers={"Retry-After": "2"},
        )
    async with _admit:
        return await _run_offloaded(_handle_sync, payload, mode, request)


# --------------------------------------------------------------------------- #
# 基础端点
# --------------------------------------------------------------------------- #
@app.get("/health")
def healthcheck() -> dict:
    """轻量探活: 不加载任何重资源, 供平台 readiness 探测。"""
    return {
        "ok": True,
        "service": "rule-system-api-v2",
        "mode": "cloudrun-container",
        "storage": _storage.name,
        "inflight": _metrics.get("inflight", 0),
        "asyncPending": _async_pending_count(),
    }


@app.get("/")
def root() -> dict:
    return {
        "ok": True,
        "service": "rule-system-api-v2",
        "message": "可访问 /health、/api/modules、/api/recommend、/api/plan、/api/jobs",
    }


@app.get("/metrics")
def metrics() -> dict:
    """内部监控。只输出计数, 不输出任何凭据或请求头。"""
    with _metrics_lock:
        data = dict(_metrics)
    data["asyncPending"] = _async_pending_count()
    data["storage"] = _storage.name
    return data


@app.get("/api/modules")
def get_modules() -> dict:
    return {
        "generatedAt": _now().strftime("%Y-%m-%d %H:%M:%S"),
        "modules": _get_catalog(),
    }


@app.post("/api/validate-selection")
def validate_selection(payload: ValidateSelectionRequest) -> dict:
    from service_adapter import normalize_selected_modules
    try:
        issues = validate_selection_rules(normalize_selected_modules(payload.selectedModules))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"isValid": not issues, "issues": issues}


def _preflight(payload, wait=False):
    from capacity_service import preflight
    # wait=True 用于队列 worker: 槽位被占用时应一直等, 不能把排队中的任务直接判失败。
    # 注意 threading.Semaphore.acquire(timeout=-1) 不等于无限等待——只有 value>0 时能拿到,
    # 一旦为 0 会立即返回 False(负超时), 让已排队任务被标成 failed。
    if not _cpu_slot.acquire(timeout=None if wait else ADMIT_TIMEOUT):
        raise HTTPException(status_code=429, detail='服务繁忙，请稍后重试场地校验')
    budget = None
    try:
        budget = start_budget()
        return preflight(payload.evacuees, payload.length, payload.width, payload.days,
                         payload.strategyKey, payload.selectedModules, payload.changedModule)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if budget is not None:
            reset_budget(budget)
        _cpu_slot.release()


@app.post('/api/preflight')
async def preflight_selection(payload: PreflightRequest, request: Request):
    if payload.asyncMode:
        return await _run_offloaded(_queue_preflight, payload, request.state.tenant)
    return await _run_offloaded(_preflight, payload)


def _queue_preflight(payload, tenant):
    return _enqueue(payload, 'capacity', tenant)


def _enqueue(payload, kind, tenant):
    data = payload.model_dump(mode='json')
    try:
        run_id = _jobs.submit(create_run_id(kind), _fingerprint(tenant, data, kind),
                              owner_key(tenant), kind, data,
                              {'appid': tenant['appid'], 'owner': owner_key(tenant)})
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={'Retry-After': '5'}) from exc
    return {'runId': run_id, 'status': 'queued', 'statusUrl': f'/api/jobs/{run_id}'}


def _worker_loop():
    while not _worker_stop.is_set():
        try:
            job = _jobs.claim()
        except Exception:
            logger.exception('领取任务失败')
            _worker_stop.wait(1)
            continue
        if job is None:
            _worker_stop.wait(.25)
            continue
        heartbeat_stop = threading.Event()

        def renew(leased_job=job, stopped=heartbeat_stop):
            while not stopped.wait(10):
                try:
                    _jobs.heartbeat(leased_job)
                except Exception:
                    logger.exception('更新任务租约失败 runId=%s', leased_job['id'])

        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        try:
            if job['kind'] == 'capacity':
                result = _preflight(PreflightRequest(**job['payload']), wait=True)
            else:
                result = _execute_plan(JobSubmitRequest(**job['payload']), job['kind'],
                                       job['tenant'], job['id'], admit_timeout=None, persist_result=False)
            committed = _jobs.finish(job, result=result)
            if committed and job['kind'] != 'capacity':
                # Queue state is authoritative. Only the lease winner may archive
                # the replay; a failed archive never erases a completed queue result.
                try:
                    _storage.put_json(f"results/{job['id']}.json", {'owner': job['owner'], 'result': result})
                except Exception:
                    logger.exception('结果归档失败；仍可从任务队列读取 runId=%s', job['id'])
        except Exception as exc:
            logger.exception('任务失败 runId=%s', job['id'])
            message = str(exc) if isinstance(exc, (ValueError, TimeoutError)) else '任务处理失败，请稍后重试'
            try:
                _jobs.finish(job, error=message)
            except Exception:
                logger.exception('保存任务失败状态失败；租约过期后将重试')
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=1)


if DEBUG_HEADER_NAMES:
    @app.get("/api/_debug/header-names")
    def debug_header_names(request: Request) -> dict:
        """仅返回请求头的**名称**列表(不含值), 用于上线前核对网关注入字段。

        受 DEBUG_HEADER_NAMES=1 控制, 默认关闭。
        """
        return {"headerNames": header_names(request)}


# --------------------------------------------------------------------------- #
# 同步接口
# --------------------------------------------------------------------------- #
@app.post("/api/recommend")
async def recommend(payload: RecommendRequest, request: Request) -> dict:
    if payload.asyncMode:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="请使用 POST /api/jobs 提交异步任务",
        )
    return await _admit_and_run(payload, "recommend", request)


@app.post("/api/plan")
async def generate_plan(payload: PlanRequest, request: Request) -> dict:
    if payload.asyncMode:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="请使用 POST /api/jobs 提交异步任务",
        )
    return await _admit_and_run(payload, "plan", request)


# --------------------------------------------------------------------------- #
# 异步接口
# --------------------------------------------------------------------------- #
@app.post('/api/jobs', status_code=status.HTTP_202_ACCEPTED)
def submit_job(payload: JobSubmitRequest, request: Request) -> dict:
    return _enqueue(payload, payload.mode, request.state.tenant)


@app.get('/api/jobs/{run_id}')
@app.get('/api/preflight/{run_id}')
def get_job(run_id: str, request: Request) -> dict:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(status_code=400, detail='runId 格式不合法')
    info = _jobs.get(run_id, owner_key(request.state.tenant))
    if info is None:
        raise HTTPException(status_code=404, detail='任务不存在或已过期')
    if info.get('result'):
        _refresh_files(info['result'])
    return info


def _refresh_files(result):
    for files in (result.get('outputFiles'), (result.get('layout') or {}).get('outputFiles')):
        if files:
            for key, url in files.items():
                if url:
                    files[key] = _storage.refresh_url(url)
    return result


# --------------------------------------------------------------------------- #
# 结果回放
# --------------------------------------------------------------------------- #
@app.get("/api/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    """按 runId 重新取回方案结果。预签名 URL 过期后可再次调用换新地址。"""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="runId 格式不合法")
    job = _jobs.get(run_id, owner_key(request.state.tenant))
    if job and job['status'] == 'succeeded':
        return _refresh_files(job['result'])
    data = _storage.get_json(f"results/{run_id}.json")
    if data is None or data.get('owner') != owner_key(request.state.tenant):
        raise HTTPException(status_code=404, detail="未找到该运行结果")
    return _refresh_files(data['result'])


@app.get("/api/runs/files/{file_path:path}")
def get_local_file(file_path: str, expires: int = 0, signature: str = "") -> FileResponse:
    """仅 LocalStorage(单实例/本地调试)模式使用。

    云存储模式下前端直接访问预签名 URL, 不走这里。带路径穿越防护。
    """
    if _storage.name != 'local' or not _storage.verify_url(file_path, expires, signature):
        raise HTTPException(status_code=404, detail='未找到目标文件')
    root = (LOCAL_ROOT / 'plans').resolve()
    try:
        target = (LOCAL_ROOT / file_path).resolve()
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="未找到目标文件") from None
    if root not in target.parents or not target.is_file() or target.suffix not in (".png", ".json"):
        raise HTTPException(status_code=404, detail="未找到目标文件")
    return FileResponse(target)
