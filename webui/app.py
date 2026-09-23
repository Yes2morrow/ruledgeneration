"""WebUI配置编辑器后端 - 提供YAML配置文件的CRUD API和可视化预览。

说明:
    现有群组配置文件中 `arrangement` 项写成单行形式:
        - row: 0, col: 0, rotation: 0, mirror: none
    这在 YAML 中属于非法语法(同一行出现多个映射值), PyYAML 的 safe_load 会抛出
    ScannerError。为了让编辑器能够正常加载并编辑这些文件, 这里采用"容错加载":
    先尝试标准解析, 失败后将上述行改写为流式映射:
        - {row: 0, col: 0, rotation: 0, mirror: none}
    再重新解析。用户在界面中保存后, 文件会被规范化为合法 YAML。
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("webui")
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = PROJECT_ROOT / "configs"
WEBUI_DIR = Path(__file__).resolve().parent

# 添加项目路径(便于后续扩展引用项目内模块)
sys.path.insert(0, str(PROJECT_ROOT / "01_pre_selection"))
sys.path.insert(0, str(PROJECT_ROOT / "05_config_and_tools"))
sys.path.insert(0, str(PROJECT_ROOT / "02_placement_generation" / "layout_optimization"))

# 程序最终结果输出目录(统一放到项目 06_output_results, WebUI 仅做静态代理)
LAYOUT_OUTPUT_DIR = PROJECT_ROOT / "06_output_results"
LAYOUT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 运行状态/日志(内存中, 按 runId 索引)
JOB_LOGS: dict[str, dict] = {}
JOB_LOCK = threading.Lock()


def _init_job(run_id: str) -> None:
    with JOB_LOCK:
        JOB_LOGS[run_id] = {"done": False, "error": None, "result": None, "logs": []}


def _job_log(run_id: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {message}"
    with JOB_LOCK:
        JOB_LOGS.setdefault(run_id, {"done": False, "error": None, "result": None, "logs": []})
        JOB_LOGS[run_id]["logs"].append(line)
    logger.info("[运行状态][%s] %s", run_id, message)


def _job_done(run_id: str, result: Optional[dict] = None, error: Optional[str] = None) -> None:
    with JOB_LOCK:
        JOB_LOGS.setdefault(run_id, {"done": False, "error": None, "result": None, "logs": []})
        JOB_LOGS[run_id]["done"] = True
        JOB_LOGS[run_id]["result"] = result
        JOB_LOGS[run_id]["error"] = error

app = FastAPI(title="规则系统2.0 配置编辑器", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件(材质图片存放于程序本体 03_visualization/textures, webui 仅作静态代理)
app.mount("/static", StaticFiles(directory=str(WEBUI_DIR / "static")), name="static")
app.mount("/outputs", StaticFiles(directory=str(LAYOUT_OUTPUT_DIR)), name="outputs")
app.mount("/textures", StaticFiles(directory=str(PROJECT_ROOT / "03_visualization" / "textures")), name="textures")


# --------------------------------------------------------------------------- #
# 容错 YAML 加载
# --------------------------------------------------------------------------- #
# 匹配 arrangement 单行形式: "- row: 0, col: 0, rotation: 0, mirror: none"
_ARRANGE_LINE = re.compile(
    r"(\s*-\s*)row:\s*(\d+)\s*,\s*col:\s*(\d+)\s*,\s*rotation:\s*(\d+)\s*,\s*mirror:\s*([A-Za-z_]+)"
)


def _repair_arrangement(text: str) -> str:
    """将非法的单行 arrangement 改写为合法的流式映射。"""
    return _ARRANGE_LINE.sub(
        lambda m: f"{m.group(1)}{{row: {m.group(2)}, col: {m.group(3)}, rotation: {m.group(4)}, mirror: {m.group(5)}}}",
        text,
    )


def load_config_tolerant(filepath: Path) -> dict:
    """容错加载 YAML 文件。

    返回字典结构:
        {
            "data": dict | None,     # 解析后的结构(失败时为 None)
            "text": str,             # 原始文本
            "error": str | None,     # 解析错误信息
            "repaired": bool,        # 是否经过自动修复
        }
    """
    raw = filepath.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
        return {"data": data, "text": raw, "error": None, "repaired": False}
    except yaml.YAMLError as e:
        # 尝试修复 arrangement 行后重新解析
        repaired_text = _repair_arrangement(raw)
        if repaired_text != raw:
            try:
                data = yaml.safe_load(repaired_text)
                return {"data": data, "text": raw, "error": None, "repaired": True}
            except yaml.YAMLError as e2:
                return {"data": None, "text": raw, "error": str(e2), "repaired": True}
        return {"data": None, "text": raw, "error": str(e), "repaired": False}


def dump_yaml(data: Any) -> str:
    """将结构化数据序列化为 YAML 文本(保持中文可读、不排序键)。"""
    return yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1000,  # 避免长行被自动折行(例如 polygon 数组)
    )


def _config_path(category: str, filename: str) -> Path:
    """根据类别和文件名构造完整路径, 并校验落在 configs 目录内。"""
    base = (CONFIG_ROOT / category).resolve()
    filepath = (base / filename).resolve()
    # 防止路径穿越
    if not str(filepath).startswith(str(base)):
        raise HTTPException(status_code=400, detail="非法的文件名")
    return filepath


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def index():
    """返回主页面"""
    html_path = WEBUI_DIR / "static" / "index.html"
    return html_path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# YAML 辅助接口(供前端文本编辑器使用)
# --------------------------------------------------------------------------- #
class YamlTextIn(BaseModel):
    text: str


class YamlDataIn(BaseModel):
    data: Any


@app.post("/api/yaml/parse")
async def yaml_parse(payload: YamlTextIn):
    """解析 YAML 文本为结构化数据(带自动修复)。"""
    text = payload.text
    try:
        data = yaml.safe_load(text)
        return {"data": data, "error": None, "repaired": False}
    except yaml.YAMLError as e:
        repaired = _repair_arrangement(text)
        if repaired != text:
            try:
                data = yaml.safe_load(repaired)
                return {"data": data, "error": None, "repaired": True}
            except yaml.YAMLError as e2:
                return {"data": None, "error": str(e2), "repaired": True}
        return {"data": None, "error": str(e), "repaired": False}


@app.post("/api/yaml/dump")
async def yaml_dump(payload: YamlDataIn):
    """将结构化数据序列化为 YAML 文本。"""
    return {"text": dump_yaml(payload.data)}


# --------------------------------------------------------------------------- #
# 模块配置
# --------------------------------------------------------------------------- #
@app.get("/api/configs/modules")
async def list_module_configs():
    """列出所有模块配置文件"""
    module_dir = CONFIG_ROOT / "modules"
    files = sorted(module_dir.glob("module_*.yaml"))
    result = []
    for f in files:
        loaded = load_config_tolerant(f)
        data = loaded["data"] or {}
        result.append({
            "filename": f.name,
            "module_id": data.get("module_id"),
            "name": data.get("name"),
            "type": data.get("type"),
            "parse_error": loaded["error"],
        })
    return result


@app.get("/api/configs/modules/{filename}")
async def get_module_config(filename: str):
    """获取单个模块配置(同时返回原始文本与结构化数据)"""
    filepath = _config_path("modules", filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return load_config_tolerant(filepath)


@app.put("/api/configs/modules/{filename}")
async def update_module_config(filename: str, body: dict):
    """更新模块配置。可传 {data: {...}} 或 {text: "..."}。"""
    filepath = _config_path("modules", filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    _write_config(filepath, body)
    return {"ok": True, "message": "保存成功"}


# --------------------------------------------------------------------------- #
# 群组配置
# --------------------------------------------------------------------------- #
@app.get("/api/configs/groups")
async def list_group_configs():
    """列出所有群组配置文件"""
    group_dir = CONFIG_ROOT / "groups"
    files = sorted(group_dir.glob("group_*.yaml"))
    result = []
    for f in files:
        loaded = load_config_tolerant(f)
        data = loaded["data"] or {}
        group_types = []
        for g in (data.get("groups") or []):
            if isinstance(g, dict) and g.get("group_type"):
                group_types.append(g["group_type"])
        result.append({
            "filename": f.name,
            "module_id": data.get("module_id"),
            "group_types": group_types,
            "parse_error": loaded["error"],
        })
    return result


@app.get("/api/configs/groups/{filename}")
async def get_group_config(filename: str):
    """获取单个群组配置(同时返回原始文本与结构化数据)"""
    filepath = _config_path("groups", filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return load_config_tolerant(filepath)


@app.put("/api/configs/groups/{filename}")
async def update_group_config(filename: str, body: dict):
    """更新群组配置。可传 {data: {...}} 或 {text: "..."}。"""
    filepath = _config_path("groups", filename)
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    _write_config(filepath, body)
    return {"ok": True, "message": "保存成功"}


def _write_config(filepath: Path, body: dict) -> None:
    """根据请求体写入文件: 优先 text(原始文本), 否则 data(序列化)。"""
    if "text" in body and isinstance(body["text"], str):
        filepath.write_text(body["text"], encoding="utf-8")
    elif "data" in body:
        filepath.write_text(dump_yaml(body["data"]), encoding="utf-8")
    else:
        raise HTTPException(status_code=400, detail="请求体需包含 data 或 text 字段")


# --------------------------------------------------------------------------- #
# 布局生成接口(generate / recommend 两种模式)
# --------------------------------------------------------------------------- #
class LayoutRequest(BaseModel):
    mode: str = "recommend"  # generate | recommend
    evacuees: int
    length: float
    width: float
    days: int = 3
    strategy: Optional[str] = None  # comfort | economy | balanced
    recommendationMode: str = "match_input"  # match_input=跟人数一致 | fill=排满 (recommend 模式生效)
    selectedModules: Optional[dict] = None  # generate 模式必填


@app.get("/api/modules/catalog")
async def module_catalog():
    """返回模块目录(含步长、床位、成本、颜色), 供前端购物车使用。

    实际实现统一在 config_loader, 此接口直接调用，避免重复定义。
    """
    from config_loader import get_module_catalog
    return get_module_catalog()


def _run_layout_sync(req: LayoutRequest, run_id: str) -> dict:
    """在线程池中执行排布, 并通过 _job_log 上报进度。"""
    from service_adapter import generate_plan_payload, generate_recommendation_payload

    def progress(msg: str) -> None:
        _job_log(run_id, msg)

    progress("开始接收排布任务")
    if req.mode == "generate":
        if not req.selectedModules:
            raise ValueError("generate 模式必须提供 selectedModules")
        progress("校验手动选择的模块数量")
        payload = generate_plan_payload(
            evacuees=req.evacuees,
            length=req.length,
            width=req.width,
            days=req.days,
            selected_modules=req.selectedModules,
            strategy_key=req.strategy,
            output_dir=str(LAYOUT_OUTPUT_DIR),
            run_id=run_id,
            progress_callback=progress,
        )
    else:
        progress("自动推荐合适模块")
        payload = generate_recommendation_payload(
            evacuees=req.evacuees,
            length=req.length,
            width=req.width,
            days=req.days,
            strategy_key=req.strategy,
            recommendation_mode=req.recommendationMode,
            output_dir=str(LAYOUT_OUTPUT_DIR),
            run_id=run_id,
            progress_callback=progress,
        )

    # 把绝对路径转换为可访问的 URL
    out_files = payload.get("layout", {}).get("outputFiles", {})
    png_url = None
    if out_files.get("layoutPng"):
        png_url = "/outputs/" + Path(out_files["layoutPng"]).name
    structure_png_url = None
    if out_files.get("structurePng"):
        structure_png_url = "/outputs/" + Path(out_files["structurePng"]).name
    payload["layout"]["pngUrl"] = png_url
    payload["layout"]["structurePngUrl"] = structure_png_url
    payload["runId"] = run_id
    progress("排布完成, 输出图片与 JSON 已写入 06_output_results")
    logger.info("[启动排布] 成功 runId=%s pngUrl=%s outputFiles=%s", run_id, png_url, out_files)
    return payload


@app.post("/api/layout")
async def generate_layout(req: LayoutRequest):
    """提交排布任务, 立即返回 runId 与状态查询地址。

    实际计算在线程池中异步执行, 前端通过 /api/layout/status/{runId} 轮询进度。
    """
    run_id = f"webui_{req.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger.info("[启动排布] runId=%s mode=%s evacuees=%s site=%sx%s days=%s recmode=%s selected=%s",
                run_id, req.mode, req.evacuees, req.length, req.width, req.days,
                req.recommendationMode, req.selectedModules)
    _init_job(run_id)

    loop = asyncio.get_event_loop()

    def _work() -> None:
        try:
            result = _run_layout_sync(req, run_id)
            _job_done(run_id, result=result)
        except ValueError as e:
            logger.warning("[启动排布] 业务校验失败: %s", e)
            _job_log(run_id, f"参数校验失败: {e}")
            _job_done(run_id, error=str(e))
        except Exception as e:
            logger.exception("[启动排布] 运行时异常")
            _job_log(run_id, f"运行异常: {e}")
            _job_done(run_id, error=f"排布服务内部错误: {e}")

    loop.run_in_executor(None, _work)
    return {"runId": run_id, "statusUrl": f"/api/layout/status/{run_id}"}


@app.get("/api/layout/status/{run_id}")
async def layout_status(run_id: str):
    """查询排布任务状态与日志; 完成后返回完整结果。"""
    with JOB_LOCK:
        info = JOB_LOGS.get(run_id)
    if not info:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return info


if __name__ == "__main__":
    import socket
    import uvicorn

    def _port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    port = 3000
    if not _port_free(port):
        port = 3001
    print(f"[WebUI] 启动端口: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
