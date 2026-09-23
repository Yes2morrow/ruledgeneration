"""服务适配器 - 生成布局方案 payload, 对接 CLI / CloudRun API。

职责:
  1. generate_plan_payload: generate 模式, 直接用用户给的 selected_modules 排布。
  2. generate_recommendation_payload: recommend 模式, 用 module_selector 自动选模块再排布。
  3. 两者都调用 calculate_layout + render_layout, 输出 JSON + PNG。
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("service_adapter")

_CST = timezone(timedelta(hours=8))


def create_run_id(prefix: str = "run") -> str:
    """生成全局唯一 run_id。

    原实现为 f"{prefix}_{strftime('%Y%m%d_%H%M%S')}", 只精确到秒,
    多个小程序同秒并发请求会撞 ID, 导致产物文件互相覆盖。
    现追加完整 uuid4 十六进制串，避免短编号被枚举。
    """
    ts = datetime.now(_CST).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}_{uuid.uuid4().hex}"

_CURRENT = Path(__file__).resolve().parent
_RULE_ROOT = _CURRENT.parent
for _sub in (
    _RULE_ROOT / "01_pre_selection",
    _RULE_ROOT / "02_placement_generation" / "layout_optimization",
    _RULE_ROOT / "03_visualization",
):
    if str(_sub) not in sys.path:
        sys.path.insert(0, str(_sub))

from config_loader import load_all_module_configs  # noqa: E402
from layout_optimizer import calculate_layout, layout_result_to_dict  # noqa: E402
from renderer import render_layout  # noqa: E402

_STRATEGY_PREF = {
    "comfort": ["舒适型", "均衡型", "经济型"],
    "economy": ["经济型", "均衡型", "舒适型"],
    "balanced": ["均衡型", "经济型", "舒适型"],
}
_STRATEGY_LABEL = {
    "comfort": "舒适型",
    "economy": "经济型",
    "balanced": "平衡型",
}

# 模块展示信息(从 config_loader 统一获取, 避免重复定义)

def normalize_selected_modules(selected_modules=None) -> Dict[str, int]:
    """规范化模块选择输入(支持 dict 或 list)。"""
    configs = load_all_module_configs()
    normalized: Dict[str, int] = {}
    if not selected_modules:
        return normalized

    def checked_quantity(code, value):
        if code not in configs:
            raise ValueError(f'未知模块: {code}')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f'{code} 模块数量必须是非负整数')
        if value > 2000:
            raise ValueError(f'{code} 模块数量不能超过 2000')
        if not float(value).is_integer():
            raise ValueError(f'{code} 模块数量必须是非负整数')
        return int(value)

    if isinstance(selected_modules, dict):
        items = selected_modules.items()
        for code, qty in items:
            c = str(code).upper()
            q = checked_quantity(c, qty)
            if q > 0:
                normalized[c] = q
        return normalized

    if isinstance(selected_modules, list):
        if len(selected_modules) > len(configs):
            raise ValueError('模块列表过长或含重复模块')
        seen = set()
        for item in selected_modules:
            if not isinstance(item, dict):
                raise ValueError('模块列表条目必须是对象')
            module = item.get('module') or {}
            if not isinstance(module, dict):
                raise ValueError('模块描述必须是对象')
            code = str(item.get("code") or module.get("name") or "").upper()
            if code in seen:
                raise ValueError('模块列表含重复模块')
            seen.add(code)
            q = checked_quantity(code, item.get("quantity", 0))
            if q > 0:
                normalized[code] = q
        return normalized

    raise ValueError("selected_modules 只支持 dict 或 list")


def validate_selection_rules(selected_modules: Dict[str, int]) -> List[str]:
    """校验模块数量是否符合步长规则。"""
    from config_loader import module_step

    issues = []
    for code, qty in selected_modules.items():
        step = module_step(code)
        if step > 1 and qty % step != 0:
            issues.append(f"{code} 模块数量必须按 {step} 的倍数调整, 当前为 {qty}")
    return issues


def summarize_selection(selected_modules: Dict[str, int], target_beds: int = 0) -> dict:
    configs = load_all_module_configs()
    total_qty = sum(selected_modules.values())
    total_types = len(selected_modules)
    total_beds = sum(
        int(configs[mid]["beds"]) * qty for mid, qty in selected_modules.items()
    )
    total_cost = sum(
        int(configs[mid]["cost"]) * qty for mid, qty in selected_modules.items()
    )
    return {
        "targetBeds": int(target_beds or 0),
        "totalQuantity": total_qty,
        "totalTypes": total_types,
        "totalBeds": total_beds,
        "totalCost": total_cost,
        "bedGap": total_beds - int(target_beds or 0),
        "isEnough": total_beds >= int(target_beds or 0),
    }


def _infer_space_type(selected_modules: Dict[str, int], fallback: str) -> str:
    """按床位占比推断空间类型。"""
    configs = load_all_module_configs()
    beds_by_type: Dict[str, int] = {}
    for mid, qty in selected_modules.items():
        mtype = configs[mid]["type"]
        beds_by_type[mtype] = beds_by_type.get(mtype, 0) + int(configs[mid]["beds"]) * qty
    if not beds_by_type:
        return fallback
    return max(beds_by_type.items(), key=lambda x: x[1])[0]


def summarize_layout(layout: dict, selection_summary: dict) -> dict:
    """Summarize what actually fits; keep the requested selection separately."""
    placed = {}
    for group in layout.get("groups", []):
        mid = group["module_id"]
        placed[mid] = placed.get(mid, 0) + len(group.get("modules", []))
    summary = summarize_selection(placed, selection_summary["targetBeds"])
    beds = len(layout.get("beds", []))
    summary.update(
        totalBeds=beds,
        bedGap=beds - summary["targetBeds"],
        isEnough=beds >= summary["targetBeds"],
        unplacedBeds=max(0, selection_summary["totalBeds"] - beds),
        unplacedQuantity=max(0, selection_summary["totalQuantity"] - summary["totalQuantity"]),
    )
    return summary


def _noop(msg: str) -> None:
    pass


def _run_layout_and_render(
    selected_modules: Dict[str, int],
    site_polygon,
    output_dir: Optional[Path],
    run_id: str,
    progress_callback=None,
    render_structure: bool = True,
    finalize: bool = True,
) -> dict:
    """执行排布 + 渲染, 返回 layout + 输出文件信息。

    :param render_structure: 是否额外渲染结构校对图。
        结构图是开发校对用的, 小程序端只需要展示图; 云端默认关闭可省一半渲染耗时。
    """
    cb = progress_callback or _noop
    cb("开始计算布局")
    from capacity_service import checked_layout, check_cart
    result = checked_layout(selected_modules, site_polygon, finalize=finalize)
    if not result.success or result.unplaced:
        xs, ys = zip(*site_polygon)
        validation = check_cart(max(xs) - min(xs), max(ys) - min(ys), selected_modules)
        raise ValueError(validation['message'])
    cb(f"布局计算完成: 放置 {len(result.groups)} 个群组, {len(result.beds)} 张床")
    payload = layout_result_to_dict(result)

    output_files = {}
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        png_path = output_dir / f"layout_{run_id}.png"
        cb("渲染展示图")
        render_layout(result, str(png_path), show_structure=False)

        structure_png_path = None
        if render_structure:
            cb("渲染结构校对图")
            structure_png_path = output_dir / f"layout_{run_id}_structure.png"
            render_layout(result, str(structure_png_path), show_structure=True)

        json_path = output_dir / f"layout_{run_id}.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        output_files = {
            "layoutPng": str(png_path),
            "layoutJson": str(json_path),
        }
        if structure_png_path is not None:
            output_files["structurePng"] = str(structure_png_path)

        logger.info("[渲染输出] PNG=%s JSON=%s STRUCTURE=%s", png_path, json_path, structure_png_path)

    payload["outputFiles"] = output_files
    return payload


def generate_plan_payload(
    evacuees: int,
    length: float,
    width: float,
    days: int,
    selected_modules=None,
    strategy_key: Optional[str] = None,
    output_dir: Optional[str] = None,
    run_id: Optional[str] = None,
    progress_callback=None,
    render_structure: bool = True,
) -> dict:
    """generate 模式: 用户已指定模块, 直接排布。"""
    from module_selector import build_recommendation_profile, validate_inputs
    from capacity_service import validate_dimensions

    cb = progress_callback or _noop
    validate_dimensions(length, width)
    area = float(length) * float(width)
    cb("校验输入参数")
    validate_inputs(int(evacuees), area, int(days))

    cb("规范化已选模块")
    selected = normalize_selected_modules(selected_modules)
    if not selected:
        raise ValueError("generate 模式必须提供 selected_modules")

    issues = validate_selection_rules(selected)
    if issues:
        raise ValueError("; ".join(issues))

    summary = summarize_selection(selected, int(evacuees))
    if summary["totalBeds"] < int(evacuees):
        raise ValueError(
            f"当前模块仅 {summary['totalBeds']} 床, 低于目标 {evacuees} 床"
        )

    profile = build_recommendation_profile(int(evacuees), area, int(days))
    space_type = _infer_space_type(selected, profile["space_type"])

    run_id = run_id or create_run_id("plan")
    out_dir = Path(output_dir) if output_dir else _RULE_ROOT / "06_output_results"
    cb(f"已选择模块: {selected}, 开始排布")

    layout = _run_layout_and_render(
        selected,
        __import__("config_loader").get_site_polygon(length_m=float(length), width_m=float(width)),
        out_dir,
        run_id,
        progress_callback=cb,
        render_structure=render_structure,
    )

    return {
        "runId": run_id,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "generate",
        "site": {"evacuees": int(evacuees), "length": float(length), "width": float(width), "days": int(days), "area": area},
        "spaceType": space_type,
        "strategy": {"key": strategy_key or "", "label": _STRATEGY_LABEL.get(strategy_key or "", "自动推荐")},
        "recommendationProfile": profile,
        "selectedModules": selected,
        "selectionSummary": summary,
        "summary": summarize_layout(layout, summary),
        "layout": layout,
    }


def generate_recommendation_payload(
    evacuees: int,
    length: float,
    width: float,
    days: int,
    strategy_key: Optional[str] = None,
    recommendation_mode: str = "match_input",
    output_dir: Optional[str] = None,
    run_id: Optional[str] = None,
    progress_callback=None,
    render_structure: bool = True,
    preview_only: bool = False,
) -> dict:
    """recommend 模式: 自动选择模块再排布。

    :param recommendation_mode: match_input=跟人数一致; fill=排满场地
    """
    from config_loader import get_site_polygon
    from module_selector import build_recommendation_profile, select_modules, validate_inputs
    from capacity_service import checked_layout, site_capacity, validate_dimensions

    cb = progress_callback or _noop

    if recommendation_mode not in ("match_input", "fill"):
        raise ValueError("recommendation_mode 只支持 match_input / fill")

    cb("校验输入参数")
    validate_dimensions(length, width)
    area = float(length) * float(width)
    validate_inputs(int(evacuees), area, int(days))

    cb("构建推荐画像")
    profile = build_recommendation_profile(int(evacuees), area, int(days))
    # strategy_key 覆盖偏好序
    if strategy_key and strategy_key in _STRATEGY_PREF:
        profile["module_preferences"] = list(_STRATEGY_PREF[strategy_key])
        cb(f"应用策略偏好: {_STRATEGY_LABEL.get(strategy_key, strategy_key)}")

    site = get_site_polygon(length_m=float(length), width_m=float(width))
    cb("自动选择模块组合")
    selected = select_modules(int(evacuees), site, profile, layout_runner=checked_layout,
                              recommendation_mode=recommendation_mode)
    if not selected:
        raise ValueError("无法在当前场地推荐合适模块, 请增大场地或减少人数")
    cb(f"推荐模块: {selected}")

    issues = validate_selection_rules(selected)
    summary = summarize_selection(selected, int(evacuees))
    if summary['totalBeds'] < int(evacuees):
        capacity = site_capacity(float(length), float(width))
        if capacity['maxEvacuees'] < int(evacuees):
            raise ValueError(f'当前场地按现有排布规则最大可设定人数为 {capacity["maxEvacuees"]} 人，请减少人数或增大场地。')
        # The preferred mix may be less dense than another verified configuration.
        from module_selector import refine_bed_match, _modules_by_type
        selected = refine_bed_match(capacity['capacitySelection'], int(evacuees), site,
                                    _modules_by_type(profile['module_preferences']), checked_layout)
        summary = summarize_selection(selected, int(evacuees))
    space_type = _infer_space_type(selected, profile["space_type"])

    run_id = run_id or create_run_id("rec")
    out_dir = None if preview_only else (Path(output_dir) if output_dir else _RULE_ROOT / "06_output_results")

    layout = _run_layout_and_render(
        selected,
        site,
        out_dir,
        run_id,
        progress_callback=cb,
        render_structure=render_structure,
        # The cart needs verified quantities only. Defer visual tidying until
        # a plan is requested so loading recommendations stays on the fast path.
        finalize=not preview_only,
    )

    return {
        "runId": run_id,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "recommend",
        "site": {"evacuees": int(evacuees), "length": float(length), "width": float(width), "days": int(days), "area": area},
        "strategy": {"key": strategy_key or "", "label": _STRATEGY_LABEL.get(strategy_key or "", "自动推荐")},
        "recommendationMode": recommendation_mode,
        "spaceType": space_type,
        "recommendationProfile": profile,
        "selectedModules": selected,
        "selectionSummary": summary,
        "summary": summarize_layout(layout, summary),
        "selectionIssues": issues,
        "layout": layout,
    }
