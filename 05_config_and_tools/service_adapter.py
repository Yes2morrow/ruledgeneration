from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional


CURRENT_DIR = Path(__file__).resolve().parent
RULE_ROOT = CURRENT_DIR.parent

sys.path.append(str(RULE_ROOT / "01_pre_selection"))
sys.path.append(str(RULE_ROOT / "02_placement_generation" / "inter_module_rules"))
sys.path.append(str(RULE_ROOT / "02_placement_generation" / "intra_module_rules"))
sys.path.append(str(RULE_ROOT / "02_placement_generation" / "layout_optimization"))
sys.path.append(str(RULE_ROOT / "03_visualization"))

from core_calculations import (  # noqa: E402
    build_recommendation_profile,
    modules,
    select_modules,
    validate_inputs,
)
from arrangement_rules import calculate_aisle_width, generate_group_arrangement  # noqa: E402
from auto_retry_layout import calculate_smart_layout_with_retry  # noqa: E402
from module_spacing_manager import calculate_group_dimensions_for_search  # noqa: E402
from visualization import draw_layout  # noqa: E402


MODULE_DISPLAY_CONFIG = {
    "A": {
        "id": 0,
        "name": "模块A",
        "description": "独立隔间+公共储物+服务性台面",
        "image": "cloud://yingjiapp-3g1osjhra1d2c5c1.7969-yingjiapp-3g1osjhra1d2c5c1-1369315501/images/cart/1.png",
        "step": 2,
        "rule_text": "需按 2 的倍数增减",
    },
    "B": {
        "id": 1,
        "name": "模块B",
        "description": "独立储物+可活动空间",
        "image": "cloud://yingjiapp-3g1osjhra1d2c5c1.7969-yingjiapp-3g1osjhra1d2c5c1-1369315501/images/cart/2.png",
        "step": 1,
        "rule_text": "可按单个模块增减",
    },
    "C": {
        "id": 2,
        "name": "模块C",
        "description": "利用过道",
        "image": "cloud://yingjiapp-3g1osjhra1d2c5c1.7969-yingjiapp-3g1osjhra1d2c5c1-1369315501/images/cart/3.png",
        "step": 2,
        "rule_text": "需按 2 的倍数增减",
    },
    "D": {
        "id": 3,
        "name": "模块D",
        "description": "利用过道",
        "image": "cloud://yingjiapp-3g1osjhra1d2c5c1.7969-yingjiapp-3g1osjhra1d2c5c1-1369315501/images/cart/4.png",
        "step": 1,
        "rule_text": "可按单个模块增减",
    },
    "E": {
        "id": 4,
        "name": "模块E",
        "description": "公共储物+服务性台面",
        "image": "cloud://yingjiapp-3g1osjhra1d2c5c1.7969-yingjiapp-3g1osjhra1d2c5c1-1369315501/images/cart/5.png",
        "step": 1,
        "rule_text": "可按单个模块增减",
    },
    "F": {
        "id": 5,
        "name": "模块F",
        "description": "可活动空间",
        "image": "cloud://yingjiapp-3g1osjhra1d2c5c1.7969-yingjiapp-3g1osjhra1d2c5c1-1369315501/images/cart/6.png",
        "step": 1,
        "rule_text": "可按单个模块增减",
    },
    "G": {
        "id": 6,
        "name": "模块G",
        "description": "独立储物",
        "image": "cloud://yingjiapp-3g1osjhra1d2c5c1.7969-yingjiapp-3g1osjhra1d2c5c1-1369315501/images/cart/7.png",
        "step": 1,
        "rule_text": "可按单个模块增减",
    },
}

STRATEGY_PREFERENCE_MAP = {
    "comfort": ["舒适型", "均衡型", "经济型"],
    "economy": ["经济型", "均衡型", "舒适型"],
    "balanced": ["均衡型", "经济型", "舒适型"],
}

STRATEGY_LABEL_MAP = {
    "comfort": "舒适型",
    "economy": "经济型",
    "balanced": "平衡型",
}

RECOMMENDATION_MODE_LABEL_MAP = {
    "fill": "铺满优先",
    "match_input": "人数匹配",
}


def create_run_id(prefix: str = "plan") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _safe_int(value) -> int:
    if isinstance(value, bool):
        raise ValueError("布尔值不能作为数量")
    return int(value)


def _normalize_recommendation_mode(recommendation_mode: Optional[str]) -> str:
    mode = recommendation_mode or "match_input"
    if mode not in RECOMMENDATION_MODE_LABEL_MAP:
        raise ValueError(f"不支持的推荐模式：{mode}")
    return mode


def get_module_catalog() -> List[dict]:
    catalog = []
    for code, module_info in modules.items():
        display = MODULE_DISPLAY_CONFIG[code]
        catalog.append({
            "id": display["id"],
            "code": code,
            "name": display["name"],
            "type": module_info["type"],
            "description": display["description"],
            "image": display["image"],
            "bedsPerUnit": module_info["beds"],
            "costPerUnit": module_info["cost"],
            "step": display["step"],
            "ruleText": display["rule_text"],
        })
    return sorted(catalog, key=lambda item: item["id"])


def normalize_selected_modules(selected_modules=None) -> Dict[str, int]:
    normalized: Dict[str, int] = {}
    if not selected_modules:
        return normalized

    if isinstance(selected_modules, dict):
        items = selected_modules.items()
        for module_code, quantity in items:
            code = str(module_code).upper()
            if code not in modules:
                continue
            qty = _safe_int(quantity)
            if qty > 0:
                normalized[code] = qty
        return normalized

    if isinstance(selected_modules, list):
        for item in selected_modules:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            if not code:
                module_info = item.get("module")
                if isinstance(module_info, dict):
                    code = module_info.get("name")
            code = str(code).upper() if code else ""
            if code not in modules:
                continue
            qty = _safe_int(item.get("quantity", 0))
            if qty > 0:
                normalized[code] = qty
        return normalized

    raise ValueError("selected_modules 只支持 dict 或 list")


def validate_selection_rules(selected_modules=None) -> List[str]:
    normalized = normalize_selected_modules(selected_modules)
    issues = []
    for code, quantity in normalized.items():
        step = MODULE_DISPLAY_CONFIG[code]["step"]
        if quantity % step != 0:
            issues.append(f"{code} 模块数量必须按 {step} 的倍数调整，当前为 {quantity}")
    return issues


def build_cart_items(selected_modules=None) -> List[dict]:
    normalized = normalize_selected_modules(selected_modules)
    cart_items = []
    for item in get_module_catalog():
        cart_items.append({
            **item,
            "quantity": normalized.get(item["code"], 0),
        })
    return cart_items


def cart_items_to_selection_map(cart_items: List[dict]) -> Dict[str, int]:
    return normalize_selected_modules(cart_items)


def summarize_cart_items(cart_items: List[dict], target_beds: int = 0) -> dict:
    total_quantity = sum(item["quantity"] for item in cart_items)
    total_types = sum(1 for item in cart_items if item["quantity"] > 0)
    total_beds = sum(item["quantity"] * item["bedsPerUnit"] for item in cart_items)
    bed_gap = total_beds - int(target_beds or 0)
    return {
        "targetBeds": int(target_beds or 0),
        "totalQuantity": total_quantity,
        "totalTypes": total_types,
        "totalBeds": total_beds,
        "bedGap": bed_gap,
        "isEnough": total_beds >= int(target_beds or 0),
    }


def resolve_module_preferences(strategy_key: Optional[str], recommendation_profile: dict) -> List[str]:
    if strategy_key and strategy_key in STRATEGY_PREFERENCE_MAP:
        return list(STRATEGY_PREFERENCE_MAP[strategy_key])
    return list(recommendation_profile["module_preferences"])


def _run_quietly(func, *args, quiet: bool = True, **kwargs):
    if not quiet:
        return func(*args, **kwargs)

    buffer = StringIO()
    previous_disable_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with redirect_stdout(buffer), redirect_stderr(buffer):
            return func(*args, **kwargs)
    finally:
        logging.disable(previous_disable_level)


def _selection_list_from_map(selected_map: Dict[str, int]) -> List[dict]:
    selection_list = []
    for code in sorted(selected_map.keys(), key=lambda item: MODULE_DISPLAY_CONFIG[item]["id"]):
        selection_list.append({
            "module": modules[code],
            "quantity": selected_map[code],
        })
    return selection_list


def _selection_map_from_list(selection_list: List[dict]) -> Dict[str, int]:
    result = {}
    for item in selection_list or []:
        module_info = item.get("module", {})
        code = module_info.get("name")
        quantity = _safe_int(item.get("quantity", 0))
        if code in modules and quantity > 0:
            result[code] = quantity
    return result


def _calculate_totals(selection_list: List[dict]) -> tuple[int, float]:
    total_beds = sum(item["module"]["beds"] * item["quantity"] for item in selection_list)
    total_cost = sum(item["module"]["cost"] * item["quantity"] for item in selection_list)
    return total_beds, total_cost


def _expand_group_configs(selection_list: List[dict]) -> List[dict]:
    group_configs = []
    for item in selection_list:
        arrangement = generate_group_arrangement(item["module"]["name"], item["quantity"])
        for group in arrangement:
            repeat_count = int(group.get("count", 1))
            group_base = {k: v for k, v in group.items() if k != "count"}
            for _ in range(repeat_count):
                group_configs.append(deepcopy(group_base))
    return group_configs


def _group_sort_key(group: dict, axis: str = "area") -> tuple:
    length, width = calculate_group_dimensions_for_search(group, rotated=False)
    area = length * width
    longest_side = max(length, width)
    shortest_side = min(length, width)
    if axis == "length":
        primary = length
    elif axis == "width":
        primary = width
    else:
        primary = area
    return (-primary, -longest_side, -shortest_side, group["module"]["name"])


def _build_group_order_variants(group_configs: List[dict]) -> List[List[dict]]:
    if not group_configs:
        return []

    variants = []
    seen_signatures = set()

    ordered_groups = [
        group_configs,
        sorted(group_configs, key=lambda group: _group_sort_key(group, "area")),
        sorted(group_configs, key=lambda group: _group_sort_key(group, "length")),
        sorted(group_configs, key=lambda group: _group_sort_key(group, "width")),
    ]

    for variant in ordered_groups:
        signature = tuple(
            (
                group["module"]["name"],
                group.get("group_type", ""),
                group.get("rows", 1),
                group.get("cols", 1),
            )
            for group in variant
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        variants.append([deepcopy(group) for group in variant])

    return variants


def _score_layout_result(groups: List[dict], all_length: float, all_width: float) -> tuple:
    if not groups:
        return (0.0, 0.0, 0.0, 0.0)

    max_x = 0.0
    max_y = 0.0
    for group in groups:
        x, y = group["position"]
        length, width = calculate_group_dimensions_for_search(group, rotated=group.get("rotated", False))
        max_x = max(max_x, x + length)
        max_y = max(max_y, y + width)

    length_utilization = max_x / max(all_length, 1e-6)
    width_utilization = max_y / max(all_width, 1e-6)
    footprint_ratio = (max_x * max_y) / max(all_length * all_width, 1e-6)
    balance_score = -abs(length_utilization - width_utilization)
    return (
        min(length_utilization, width_utilization),
        footprint_ratio,
        max(length_utilization, width_utilization),
        balance_score,
    )


def _build_layout_metrics(groups: List[dict], all_length: float, all_width: float) -> dict:
    if not groups:
        return {
            "usedLength": 0.0,
            "usedWidth": 0.0,
            "lengthUtilization": 0.0,
            "widthUtilization": 0.0,
            "footprintRatio": 0.0,
        }

    max_x = 0.0
    max_y = 0.0
    for group in groups:
        x, y = group["position"]
        length, width = calculate_group_dimensions_for_search(group, rotated=group.get("rotated", False))
        max_x = max(max_x, x + length)
        max_y = max(max_y, y + width)

    return {
        "usedLength": round(max_x, 3),
        "usedWidth": round(max_y, 3),
        "lengthUtilization": round(max_x / max(all_length, 1e-6), 4),
        "widthUtilization": round(max_y / max(all_width, 1e-6), 4),
        "footprintRatio": round((max_x * max_y) / max(all_length * all_width, 1e-6), 4),
    }


def _finalize_layout(
    selection_list: List[dict],
    space_type: str,
    all_length: float,
    all_width: float,
    quiet: bool = True,
) -> Optional[dict]:
    aisle = calculate_aisle_width(space_type)
    base_group_configs = _expand_group_configs(selection_list)
    best_groups = None
    best_score = None

    for variant_groups in _build_group_order_variants(base_group_configs):
        fits, positions, rotations = _run_quietly(
            calculate_smart_layout_with_retry,
            variant_groups,
            aisle,
            all_width,
            all_length,
            modules_selection=selection_list,
            max_retries=3,
            quiet=quiet,
        )

        if not fits:
            continue

        for index, group in enumerate(variant_groups):
            group["position"] = positions[index]
            group["rotated"] = rotations[index] if index < len(rotations) else False

        current_score = _score_layout_result(variant_groups, all_length, all_width)
        if best_score is None or current_score > best_score:
            best_score = current_score
            best_groups = [deepcopy(group) for group in variant_groups]

    if not best_groups:
        return None

    total_beds, total_cost = _calculate_totals(selection_list)
    return {
        "modules": selection_list,
        "total_beds": total_beds,
        "total_cost": total_cost,
        "groups": best_groups,
        "aisle": aisle,
        "layout_score": best_score,
    }


def _build_capacity_notice(requested_evacuees: int, max_feasible_evacuees: int) -> str:
    return (
        f"当前场地在现有规则下最多可落地约 {max_feasible_evacuees} 人；"
        f"输入的 {requested_evacuees} 人已超出上限，现返回最大容纳推荐方案。"
    )


def _build_capacity_estimate(
    requested_evacuees: int,
    effective_evacuees: int,
    max_feasible_evacuees: Optional[int] = None,
    capacity_limited: bool = False,
    message: Optional[str] = None,
) -> dict:
    return {
        "requestedEvacuees": int(requested_evacuees),
        "effectiveEvacuees": int(effective_evacuees),
        "maxFeasibleEvacuees": int(max_feasible_evacuees or effective_evacuees or 0),
        "capacityLimited": bool(capacity_limited),
        "message": message or "",
    }


def _infer_space_type_from_selection_map(selected_map: Dict[str, int], fallback_space_type: str) -> str:
    beds_by_type: Dict[str, int] = {}
    for code, quantity in selected_map.items():
        module_type = modules[code]["type"]
        beds_by_type[module_type] = beds_by_type.get(module_type, 0) + modules[code]["beds"] * quantity
    if not beds_by_type:
        return fallback_space_type
    return max(beds_by_type.items(), key=lambda item: item[1])[0]


def _estimate_max_capacity_layout(
    requested_evacuees: int,
    all_length: float,
    all_width: float,
    days: int,
    strategy_key: Optional[str] = None,
    quiet: bool = True,
    time_limit_seconds: Optional[float] = 20.0,
) -> Optional[dict]:
    """使用自动推荐链路二分搜索当前场地的最大可落地人数。"""
    area = all_length * all_width
    upper_bound = min(max(int(area // 3), 1), max(int(requested_evacuees), 1))
    per_eval_limit = min(8.0, max(3.0, float(time_limit_seconds or 20.0) / 2.0))

    best_payload = None
    best_beds = 0
    low = 1
    high = upper_bound

    while low <= high:
        mid = (low + high) // 2
        try:
            validate_inputs(mid, area, days)
        except ValueError:
            high = mid - 1
            continue

        recommendation_profile = build_recommendation_profile(mid, area, days)
        module_preferences = resolve_module_preferences(strategy_key, recommendation_profile)
        layout_result = _run_quietly(
            select_modules,
            module_preferences,
            mid,
            all_length,
            all_width,
            time_limit_seconds=per_eval_limit,
            quiet=quiet,
        )

        if layout_result:
            layout_metrics = _build_layout_metrics(layout_result["groups"], all_length, all_width)
            current_beds = int(layout_result.get("total_beds", 0))
            if current_beds >= best_beds:
                best_beds = current_beds
                best_payload = {
                    "spaceType": recommendation_profile["space_type"],
                    "modulePreferences": module_preferences,
                    "recommendationProfile": recommendation_profile,
                    "modules": layout_result["modules"],
                    "selectedModules": _selection_map_from_list(layout_result["modules"]),
                    "groups": layout_result["groups"],
                    "totalBeds": current_beds,
                    "totalCost": layout_result["total_cost"],
                    "fillRatio": layout_result.get("fill_ratio", layout_metrics["footprintRatio"]),
                    "layoutMetrics": layout_metrics,
                    "solutionLevel": "capacity_limit",
                }
            low = mid + 1
        else:
            high = mid - 1

    if best_payload is not None:
        return best_payload

    # 自动推荐完全无解时，退回到经济型 D-only 的保底估算。
    d_area_m2 = (modules["D"]["length"] / 1000.0) * (modules["D"]["width"] / 1000.0)
    upper_bound = max(1, int((all_length * all_width) / max(d_area_m2, 1e-6)) + 2)
    best_layout = None
    low = 0
    high = upper_bound

    while low < high:
        mid = (low + high + 1) // 2
        selection_map = {"D": mid}
        selection_list = _selection_list_from_map(selection_map)
        layout_result = _finalize_layout(
            selection_list,
            "经济型",
            all_length,
            all_width,
            quiet=quiet,
        )
        if layout_result:
            low = mid
            best_layout = layout_result
        else:
            high = mid - 1

    if best_layout is None:
        return None

    layout_metrics = _build_layout_metrics(best_layout["groups"], all_length, all_width)
    return {
        "spaceType": "经济型",
        "modulePreferences": ["经济型", "均衡型", "舒适型"],
        "recommendationProfile": {
            "space_type": "经济型",
            "module_preferences": ["经济型", "均衡型", "舒适型"],
            "people_priority": "经济型",
            "people_locked": True,
            "time_label": "短期安置" if days <= 3 else ("长期安置" if days >= 30 else "中期安置"),
            "time_shift": 0,
            "density_level": "高密度/高压",
            "per_capita_area": round(area / max(best_layout["total_beds"], 1), 2),
            "capacity_mode": "max_capacity_fallback",
        },
        "modules": best_layout["modules"],
        "selectedModules": _selection_map_from_list(best_layout["modules"]),
        "groups": best_layout["groups"],
        "totalBeds": best_layout["total_beds"],
        "totalCost": best_layout["total_cost"],
        "fillRatio": layout_metrics["footprintRatio"],
        "layoutMetrics": layout_metrics,
        "solutionLevel": "capacity_limit",
    }


def build_plan_text(summary: dict, recommendation_profile: dict, strategy_key: Optional[str]) -> str:
    strategy_label = STRATEGY_LABEL_MAP.get(strategy_key or "", "自动推荐")
    recommendation_mode = _normalize_recommendation_mode(summary.get("recommendationMode"))
    selected_modules_text = "、".join(
        f"{code}x{quantity}" for code, quantity in summary["selectedModules"].items()
    ) or "无"

    lines = [
        f"生成时间：{summary['generatedAt']}",
        f"推荐方式：{strategy_label}",
        f"推荐模式：{RECOMMENDATION_MODE_LABEL_MAP[recommendation_mode]}",
        f"空间类型：{summary['spaceType']}",
        f"目标床位：{summary['targetBeds']} 床",
        f"当前床位：{summary['totalBeds']} 床",
        f"模块总数：{summary['totalQuantity']} 个",
        f"模块明细：{selected_modules_text}",
        f"人均面积：{recommendation_profile['per_capita_area']:.2f} 平方米/人",
        f"人数优先判断：{recommendation_profile['people_priority']}",
        f"安置时长判断：{recommendation_profile['time_label']}",
    ]
    if summary.get("requestedBeds") and summary["requestedBeds"] != summary["targetBeds"]:
        lines.append(f"原始输入人数：{summary['requestedBeds']} 人")
    capacity_estimate = summary.get("capacityEstimate") or {}
    if capacity_estimate.get("capacityLimited") and capacity_estimate.get("message"):
        lines.append(f"容量提醒：{capacity_estimate['message']}")
    return "\n".join(lines)


def generate_recommendation_payload(
    evacuees: int,
    length: float,
    width: float,
    days: int,
    strategy_key: Optional[str] = None,
    recommendation_mode: str = "match_input",
    quiet: bool = True,
    time_limit_seconds: Optional[float] = 20.0,
) -> dict:
    evacuees = _safe_int(evacuees)
    days = _safe_int(days)
    length = float(length)
    width = float(width)
    area = length * width
    requested_evacuees = evacuees
    recommendation_mode = _normalize_recommendation_mode(recommendation_mode)

    hard_input_error = None
    try:
        validate_inputs(evacuees, area, days)
    except ValueError as exc:
        if "人均空间不足" not in str(exc):
            raise
        hard_input_error = str(exc)

    if hard_input_error is None:
        recommendation_profile = build_recommendation_profile(evacuees, area, days)
        module_preferences = resolve_module_preferences(strategy_key, recommendation_profile)
        recommended_layout = _run_quietly(
            select_modules,
            module_preferences,
            evacuees,
            length,
            width,
            time_limit_seconds=time_limit_seconds,
            recommendation_mode=recommendation_mode,
            quiet=quiet,
        )
    else:
        recommendation_profile = {
            "space_type": "经济型",
            "module_preferences": ["经济型", "均衡型", "舒适型"],
            "people_priority": "经济型",
            "people_locked": True,
            "time_label": "短期安置" if days <= 3 else ("长期安置" if days >= 30 else "中期安置"),
            "time_shift": 0,
            "density_level": "高密度/高压",
            "per_capita_area": round(area / max(evacuees, 1), 2),
        }
        module_preferences = list(recommendation_profile["module_preferences"])
        recommended_layout = None

    effective_evacuees = evacuees
    capacity_estimate = _build_capacity_estimate(
        requested_evacuees=requested_evacuees,
        effective_evacuees=evacuees,
    )

    if recommended_layout is None:
        capacity_layout = _estimate_max_capacity_layout(
            requested_evacuees=requested_evacuees,
            all_length=length,
            all_width=width,
            days=days,
            strategy_key=strategy_key,
            quiet=quiet,
            time_limit_seconds=time_limit_seconds,
        )
        max_feasible_evacuees = capacity_layout["totalBeds"] if capacity_layout else 0
        if capacity_layout and max_feasible_evacuees > 0 and max_feasible_evacuees < requested_evacuees:
            effective_evacuees = max_feasible_evacuees
            notice = _build_capacity_notice(requested_evacuees, max_feasible_evacuees)
            capacity_estimate = _build_capacity_estimate(
                requested_evacuees=requested_evacuees,
                effective_evacuees=effective_evacuees,
                max_feasible_evacuees=max_feasible_evacuees,
                capacity_limited=True,
                message=notice,
            )
            recommendation_profile = {
                **capacity_layout.get("recommendationProfile", recommendation_profile),
                "space_type": capacity_layout["spaceType"],
                "module_preferences": capacity_layout["modulePreferences"],
                "capacity_mode": "max_capacity",
            }
            module_preferences = list(capacity_layout["modulePreferences"])
            recommended_layout = {
                "modules": capacity_layout["modules"],
                "groups": capacity_layout["groups"],
                "total_beds": capacity_layout["totalBeds"],
                "total_cost": capacity_layout["totalCost"],
                "fill_ratio": capacity_layout["fillRatio"],
                "final_score": None,
                "solution_level": capacity_layout["solutionLevel"],
            }

    selected_modules = _selection_map_from_list(recommended_layout.get("modules", [])) if recommended_layout else {}
    actual_space_type = _infer_space_type_from_selection_map(selected_modules, recommendation_profile["space_type"])
    cart_items = build_cart_items(selected_modules)
    summary = summarize_cart_items(cart_items, effective_evacuees)
    summary["requestedBeds"] = requested_evacuees
    summary["effectiveTargetBeds"] = effective_evacuees
    summary["capacityEstimate"] = capacity_estimate

    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "site": {
            "evacuees": effective_evacuees,
            "requestedEvacuees": requested_evacuees,
            "length": length,
            "width": width,
            "days": days,
            "area": area,
        },
        "strategy": {
            "key": strategy_key or "",
            "label": STRATEGY_LABEL_MAP.get(strategy_key or "", "自动推荐"),
        },
        "recommendationMode": recommendation_mode,
        "spaceType": actual_space_type,
        "scenarioSpaceType": recommendation_profile["space_type"],
        "modulePreferences": module_preferences,
        "recommendationProfile": recommendation_profile,
        "capacityEstimate": capacity_estimate,
        "selectedModules": selected_modules,
        "cartItems": cart_items,
        "summary": summary,
        "recommendationMeta": {
            "recommendationMode": recommendation_mode,
            "fillRatio": recommended_layout.get("fill_ratio") if recommended_layout else None,
            "finalScore": recommended_layout.get("final_score") if recommended_layout else None,
            "solutionLevel": recommended_layout.get("solution_level") if recommended_layout else None,
            "timeLimitSeconds": time_limit_seconds,
        },
        "selectionIssues": validate_selection_rules(selected_modules),
    }


def generate_plan_payload(
    evacuees: int,
    length: float,
    width: float,
    days: int,
    strategy_key: Optional[str] = None,
    recommendation_mode: str = "match_input",
    selected_modules=None,
    output_dir: Optional[str] = None,
    run_id: Optional[str] = None,
    quiet: bool = True,
    time_limit_seconds: Optional[float] = 20.0,
) -> dict:
    evacuees = _safe_int(evacuees)
    days = _safe_int(days)
    length = float(length)
    width = float(width)
    area = length * width
    recommendation_mode = _normalize_recommendation_mode(recommendation_mode)

    if selected_modules is None:
        recommendation_payload = generate_recommendation_payload(
            evacuees=evacuees,
            length=length,
            width=width,
            days=days,
            strategy_key=strategy_key,
            recommendation_mode=recommendation_mode,
            quiet=quiet,
            time_limit_seconds=time_limit_seconds,
        )
        recommendation_profile = recommendation_payload["recommendationProfile"]
        module_preferences = recommendation_payload["modulePreferences"]
        effective_evacuees = recommendation_payload.get("capacityEstimate", {}).get("effectiveEvacuees", evacuees)
    else:
        validate_inputs(evacuees, area, days)
        recommendation_profile = build_recommendation_profile(evacuees, area, days)
        module_preferences = resolve_module_preferences(strategy_key, recommendation_profile)
        effective_evacuees = evacuees
        recommendation_payload = {
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "site": {
                "evacuees": evacuees,
                "requestedEvacuees": evacuees,
                "length": length,
                "width": width,
                "days": days,
                "area": area,
            },
            "strategy": {
                "key": strategy_key or "",
                "label": STRATEGY_LABEL_MAP.get(strategy_key or "", "自动推荐"),
            },
            "recommendationMode": recommendation_mode,
            "spaceType": recommendation_profile["space_type"],
            "modulePreferences": module_preferences,
            "recommendationProfile": recommendation_profile,
            "selectedModules": {},
            "cartItems": [],
            "summary": {
                "targetBeds": evacuees,
                "totalQuantity": 0,
                "totalTypes": 0,
                "totalBeds": 0,
                "bedGap": -evacuees,
                "isEnough": False,
            },
            "recommendationMeta": {
                "recommendationMode": recommendation_mode,
                "fillRatio": None,
                "finalScore": None,
                "solutionLevel": "manual_selection",
                "timeLimitSeconds": time_limit_seconds,
            },
            "capacityEstimate": _build_capacity_estimate(evacuees, evacuees),
            "selectionIssues": [],
        }

    selected_map = (
        normalize_selected_modules(selected_modules)
        if selected_modules is not None
        else recommendation_payload["selectedModules"]
    )
    actual_space_type = _infer_space_type_from_selection_map(selected_map, recommendation_payload["spaceType"])
    selection_issues = validate_selection_rules(selected_map)
    if selection_issues:
        raise ValueError("；".join(selection_issues))

    selection_list = _selection_list_from_map(selected_map)
    cart_items = build_cart_items(selected_map)
    summary = summarize_cart_items(cart_items, int(effective_evacuees))
    summary["requestedBeds"] = int(evacuees)
    summary["effectiveTargetBeds"] = int(effective_evacuees)
    summary["capacityEstimate"] = recommendation_payload.get("capacityEstimate", _build_capacity_estimate(evacuees, effective_evacuees))
    if summary["totalBeds"] < int(effective_evacuees):
        raise ValueError(f"当前仅有 {summary['totalBeds']} 床，低于目标 {effective_evacuees} 床")

    layout_result = _finalize_layout(
        selection_list,
        actual_space_type,
        float(length),
        float(width),
        quiet=quiet,
    )
    if not layout_result:
        raise ValueError("当前模块组合无法生成有效布局，请调整购物车中的模块数量")

    output_path = Path(output_dir) if output_dir else RULE_ROOT / "06_output_results"
    output_path.mkdir(parents=True, exist_ok=True)
    run_id = run_id or create_run_id("layout")
    texture_file = output_path / f"layout_texture_only_{run_id}.png"
    labels_file = output_path / f"layout_with_labels_{run_id}.png"
    latest_texture_file = output_path / "layout_texture_only.png"
    latest_labels_file = output_path / "layout_with_labels.png"

    _run_quietly(
        draw_layout,
        deepcopy(layout_result["groups"]),
        layout_result["aisle"],
        float(length),
        float(width),
        show_labels=False,
        output_filename=str(texture_file),
        quiet=quiet,
    )
    _run_quietly(
        draw_layout,
        deepcopy(layout_result["groups"]),
        layout_result["aisle"],
        float(length),
        float(width),
        show_labels=True,
        output_filename=str(labels_file),
        quiet=quiet,
    )

    shutil.copyfile(texture_file, latest_texture_file)
    shutil.copyfile(labels_file, latest_labels_file)

    layout_metrics = _build_layout_metrics(layout_result["groups"], float(length), float(width))

    plan_summary = {
        "runId": run_id,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "spaceType": actual_space_type,
        "scenarioSpaceType": recommendation_payload.get("scenarioSpaceType", recommendation_profile["space_type"]),
        "recommendationMode": recommendation_payload.get("recommendationMode", recommendation_mode),
        "strategy": recommendation_payload["strategy"],
        "targetBeds": int(effective_evacuees),
        "requestedBeds": int(evacuees),
        "totalBeds": layout_result["total_beds"],
        "totalCost": round(layout_result["total_cost"], 2),
        "totalQuantity": summary["totalQuantity"],
        "totalTypes": summary["totalTypes"],
        "selectedModules": selected_map,
        "site": recommendation_payload["site"],
        "recommendationProfile": recommendation_profile,
        "recommendationMeta": recommendation_payload["recommendationMeta"],
        "capacityEstimate": recommendation_payload.get("capacityEstimate", _build_capacity_estimate(evacuees, effective_evacuees)),
        "layoutMetrics": layout_metrics,
        "outputFiles": {
            "textureOnly": str(texture_file),
            "withLabels": str(labels_file),
            "latestTextureOnly": str(latest_texture_file),
            "latestWithLabels": str(latest_labels_file),
        },
    }
    plan_summary["textSummary"] = build_plan_text(plan_summary, recommendation_profile, strategy_key)

    json_path = output_path / f"plan_summary_{run_id}.json"
    txt_path = output_path / f"plan_summary_{run_id}.txt"
    json_path.write_text(json.dumps(plan_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(plan_summary["textSummary"], encoding="utf-8")

    return {
        "runId": run_id,
        "recommendation": recommendation_payload,
        "cartItems": cart_items,
        "summary": summary,
        "layout": {
            "totalBeds": layout_result["total_beds"],
            "totalCost": round(layout_result["total_cost"], 2),
            "groupCount": len(layout_result["groups"]),
            "selectedModules": selected_map,
            "layoutMetrics": layout_metrics,
        },
        "outputFiles": {
            "textureOnly": str(texture_file),
            "withLabels": str(labels_file),
            "latestTextureOnly": str(latest_texture_file),
            "latestWithLabels": str(latest_labels_file),
            "summaryJson": str(json_path),
            "summaryText": str(txt_path),
        },
        "textSummary": plan_summary["textSummary"],
    }
