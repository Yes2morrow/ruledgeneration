from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("LAYOUT_EXPORT_ANALYSIS_REPORT", "0")

RULE_ROOT = Path(__file__).resolve().parents[1]
GENERATED_ROOT = RULE_ROOT / "generated_runs"
GENERATED_ROOT.mkdir(parents=True, exist_ok=True)

sys.path.append(str(RULE_ROOT / "05_config_and_tools"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from service_adapter import (  # noqa: E402
    create_run_id,
    generate_plan_payload,
    generate_recommendation_payload,
    get_module_catalog,
    validate_selection_rules,
)


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class RecommendRequest(BaseModel):
    evacuees: int = Field(..., ge=1)
    length: float = Field(..., gt=0)
    width: float = Field(..., gt=0)
    days: int = Field(..., ge=1)
    strategyKey: Optional[str] = None
    recommendationMode: str = Field(default="match_input", pattern="^(fill|match_input)$")
    timeLimitSeconds: float = Field(default=20.0, gt=0)


class PlanRequest(RecommendRequest):
    selectedModules: Optional[Dict[str, int] | List[dict]] = None
    runId: Optional[str] = None


class ValidateSelectionRequest(BaseModel):
    selectedModules: Optional[Dict[str, int] | List[dict]] = None


app = FastAPI(
    title="Rule System CloudRun API",
    version="1.0.0",
    description="规则系统云托管接口，提供模块目录、推荐组合、方案生成与文件下载。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_safe_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(status_code=400, detail="runId 格式不合法")
    return run_id


def _build_run_directory(run_id: str) -> Path:
    safe_run_id = _ensure_safe_run_id(run_id)
    run_dir = GENERATED_ROOT / safe_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _normalize_public_url(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


def _external_url_for(request: Request, route_name: str, **path_params) -> str:
    return _normalize_public_url(str(request.url_for(route_name, **path_params)))


def _build_public_file_map(request: Request, run_id: str, payload: dict) -> dict:
    file_urls = {}
    for key, file_path in payload.get("outputFiles", {}).items():
        filename = Path(file_path).name
        file_urls[key] = _external_url_for(request, "get_run_file", run_id=run_id, filename=filename)
    return file_urls


def _write_public_summary(run_dir: Path, payload: dict, public_files: dict) -> None:
    summary_path = run_dir / f"plan_summary_{run_dir.name}.json"
    if not summary_path.exists():
        return

    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_data["outputFiles"] = public_files
    summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/health")
def healthcheck() -> dict:
    return {
        "ok": True,
        "service": "rule-system-api",
        "mode": "cloudrun-container",
    }


@app.get("/")
def root() -> dict:
    return {
        "ok": True,
        "service": "rule-system-api",
        "message": "服务已启动，可访问 /health、/api/modules、/api/recommend、/api/plan",
    }


@app.get("/api/modules")
def get_modules() -> dict:
    return {
        "generatedAt": create_run_id("catalog"),
        "modules": get_module_catalog(),
    }


@app.post("/api/recommend")
def recommend(payload: RecommendRequest) -> dict:
    try:
        return generate_recommendation_payload(
            evacuees=payload.evacuees,
            length=payload.length,
            width=payload.width,
            days=payload.days,
            strategy_key=payload.strategyKey,
            recommendation_mode=payload.recommendationMode,
            time_limit_seconds=payload.timeLimitSeconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"推荐生成失败：{exc}") from exc


@app.post("/api/validate-selection")
def validate_selection(payload: ValidateSelectionRequest) -> dict:
    issues = validate_selection_rules(payload.selectedModules)
    return {
        "isValid": not issues,
        "issues": issues,
    }


@app.post("/api/plan")
def generate_plan(payload: PlanRequest, request: Request) -> dict:
    run_id = payload.runId or create_run_id("layout")
    run_dir = _build_run_directory(run_id)

    try:
        result = generate_plan_payload(
            evacuees=payload.evacuees,
            length=payload.length,
            width=payload.width,
            days=payload.days,
            strategy_key=payload.strategyKey,
            recommendation_mode=payload.recommendationMode,
            selected_modules=payload.selectedModules,
            output_dir=str(run_dir),
            run_id=run_id,
            time_limit_seconds=payload.timeLimitSeconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"方案生成失败：{exc}") from exc

    public_files = _build_public_file_map(request, run_id, result)
    _write_public_summary(run_dir, result, public_files)

    result["outputFiles"] = public_files
    result["runFiles"] = {
        "summary": _external_url_for(request, "get_run_summary", run_id=run_id),
        "textureOnlyPreview": public_files.get("textureOnly"),
        "withLabelsPreview": public_files.get("withLabels"),
    }
    return result


@app.get("/api/runs/{run_id}")
def get_run_summary(run_id: str) -> dict:
    safe_run_id = _ensure_safe_run_id(run_id)
    summary_path = GENERATED_ROOT / safe_run_id / f"plan_summary_{safe_run_id}.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="未找到该运行结果")
    return json.loads(summary_path.read_text(encoding="utf-8"))


@app.get("/api/runs/{run_id}/files/{filename}", name="get_run_file")
def get_run_file(run_id: str, filename: str) -> FileResponse:
    safe_run_id = _ensure_safe_run_id(run_id)
    safe_filename = Path(filename).name
    file_path = GENERATED_ROOT / safe_run_id / safe_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="未找到目标文件")
    return FileResponse(file_path)
