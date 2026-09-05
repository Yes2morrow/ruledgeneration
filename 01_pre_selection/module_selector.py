"""模块选择策略(recommend 模式) - 配置驱动, 替代原项目 solution_optimizer 的复杂搜索。

设计原则: 简单 + 稳定 + 可解释。
  1. validate_inputs: 人均面积 >= 3 m²/人。
  2. build_recommendation_profile: 按密度分级(高/中/低) -> 空间类型 -> 模块偏好序。
  3. select_modules: 贪心填充
     - 在偏好序的首选类型中, 选 priority 最高的模块, 按 step(最小 group module_count) 递增
     - 达到 evacuees 目标床位后, 用 calculate_layout 验证能否放下
     - 放不下则按 step 递减, 直到放得下或归零; 归零则切到下一偏好类型
     - 单类型不足时, 用次偏好类型的小模块补齐
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from config_loader import (
    load_all_module_configs,
    load_module_config,
    module_step,
)


# --------------------------------------------------------------------------- #
# 输入校验 + 推荐画像 (复刻原 core_calculations 规则)
# --------------------------------------------------------------------------- #
def validate_inputs(N: int, S: float, days: int) -> float:
    """校验输入, 返回人均面积。"""
    if not isinstance(N, int) or N <= 0:
        raise ValueError("避难人数必须是正整数")
    if S <= 0:
        raise ValueError("场地面积必须大于 0")
    if days < 1:
        raise ValueError("安置时长不能小于 1 天")
    s0 = S / N
    if s0 < 3:
        raise ValueError(
            f"人均空间不足: 当前 {s0:.2f} m^2/人, 最低要求 3 m^2/人"
        )
    return round(s0, 2)


def _classify_density_level(per_capita_area: float, evacuees: int, days: int) -> str:
    if per_capita_area <= 4.2:
        return "高密度/高压"
    if evacuees >= 180 and per_capita_area <= 9.0:
        return "高密度/高压"
    if per_capita_area <= 7.2:
        return "中密度"
    if evacuees >= 120 and per_capita_area <= 10.5:
        return "中密度"
    if days >= 30 and per_capita_area <= 8.8:
        return "中密度"
    return "低密度"


_TYPE_ORDER = ["经济型", "均衡型", "舒适型"]


def _shift_space_type(base_type: str, shift: int) -> str:
    idx = _TYPE_ORDER.index(base_type)
    target = max(0, min(len(_TYPE_ORDER) - 1, idx + shift))
    return _TYPE_ORDER[target]


_PREFERENCE_MAP = {
    "舒适型": ["舒适型", "均衡型", "经济型"],
    "均衡型": ["均衡型", "经济型", "舒适型"],
    "经济型": ["经济型", "均衡型", "舒适型"],
}


def build_recommendation_profile(N: int, S: float, days: int) -> dict:
    """构建推荐画像: 密度分级 -> 空间类型 -> 模块偏好序。"""
    s0 = validate_inputs(N, S, days)
    density = _classify_density_level(s0, N, days)

    if density == "高密度/高压":
        people_priority = "经济型"
        people_locked = s0 <= 3.8 or N >= 240
    elif density == "中密度":
        people_priority = "均衡型"
        people_locked = False
    else:
        people_priority = "舒适型"
        people_locked = False

    if days <= 3:
        time_shift = -1 if (density == "中密度" and s0 < 7.8) else 0
        time_label = "短期安置"
    elif days >= 30:
        time_shift = 0 if density == "高密度/高压" else 1
        time_label = "长期安置"
    else:
        time_shift = 0
        time_label = "中期安置"

    if people_locked and time_shift > 0:
        final_type = people_priority
    else:
        final_type = _shift_space_type(people_priority, time_shift)

    return {
        "space_type": final_type,
        "module_preferences": list(_PREFERENCE_MAP[final_type]),
        "people_priority": people_priority,
        "people_locked": people_locked,
        "time_label": time_label,
        "time_shift": time_shift,
        "density_level": density,
        "per_capita_area": s0,
    }


def _modules_by_type(type_pref_order: List[str]) -> List[Tuple[str, dict]]:
    """按偏好序展开所有模块: [(module_id, config), ...], 同类型内按 priority 升序。"""
    all_configs = load_all_module_configs()
    result: List[Tuple[str, dict]] = []
    for mtype in type_pref_order:
        same_type = [
            (mid, cfg) for mid, cfg in all_configs.items() if cfg.get("type") == mtype
        ]
        same_type.sort(key=lambda x: int(x[1].get("priority", 99)))
        result.extend(same_type)
    return result


# --------------------------------------------------------------------------- #
# 贪心选择
# --------------------------------------------------------------------------- #
def _total_beds(selection: Dict[str, int], module_configs: Dict[str, dict]) -> int:
    return sum(
        int(module_configs[mid].get("beds", 0)) * qty
        for mid, qty in selection.items()
    )


def select_modules(
    evacuees: int,
    site_polygon,
    recommendation_profile: dict,
    layout_runner=None,
    recommendation_mode: str = "match_input",
) -> Dict[str, int]:
    """贪心选择模块组合, 使床位 >= evacuees 且能被 layout_runner 放下。

    :param evacuees: 目标人数/床位
    :param site_polygon: 场地多边形
    :param recommendation_profile: build_recommendation_profile 的返回
    :param layout_runner: 可调用对象 (selection, site) -> LayoutResult; 默认 calculate_layout
    :param recommendation_mode: match_input=跟人数一致(最少床位达标); fill=排满(在场地内尽量多放)
    :return: {module_id: quantity}
    """
    if layout_runner is None:
        # 延迟导入避免循环依赖
        import sys
        from pathlib import Path

        _proj = Path(__file__).resolve().parents[1]
        _layout_dir = _proj / "02_placement_generation" / "layout_optimization"
        if str(_layout_dir) not in sys.path:
            sys.path.insert(0, str(_layout_dir))
        from layout_optimizer import calculate_layout as layout_runner  # type: ignore

    all_configs = load_all_module_configs()
    type_pref = recommendation_profile["module_preferences"]
    candidates = _modules_by_type(type_pref)

    if not candidates:
        return {}

    # 主选: 偏好序首类型中 priority 最高的模块
    primary_type = type_pref[0]
    primary_modules = [
        (mid, cfg) for mid, cfg in candidates if cfg.get("type") == primary_type
    ]
    if not primary_modules:
        primary_modules = candidates[:1]

    primary_id, primary_cfg = primary_modules[0]
    primary_step = module_step(primary_id)
    primary_beds = int(primary_cfg.get("beds", 1))

    # 计算达到目标所需的主模块数量(向上取整到 step)
    needed = math.ceil(evacuees / max(primary_beds, 1))
    needed = ((needed + primary_step - 1) // primary_step) * primary_step

    # 从 needed 开始按 step 递减, 找到能放下的最大数量
    best_selection: Dict[str, int] = {}
    for qty in range(needed, 0, -primary_step):
        sel = {primary_id: qty}
        result = layout_runner(sel, site_polygon, allow_decompose=True, road_check=False)
        if result.success and not result.unplaced:
            best_selection = sel
            break

    # 主模块归零仍放不下, 或床位不足 -> 用次偏好小模块补齐
    total_beds = _total_beds(best_selection, all_configs)
    if total_beds < evacuees:
        best_selection = _fill_with_secondary(
            best_selection,
            evacuees,
            site_polygon,
            candidates,
            primary_id,
            layout_runner,
        )

    # 排满模式: 达标后继续加模块, 直到放不下为止
    if recommendation_mode == "fill":
        best_selection = _fill_site_to_capacity(
            best_selection, site_polygon, candidates, layout_runner
        )

    return best_selection


def _fill_site_to_capacity(
    selection: Dict[str, int],
    site_polygon,
    candidates: List[Tuple[str, dict]],
    layout_runner,
) -> Dict[str, int]:
    """排满模式: 按 priority 顺序继续追加模块, 只要还能放下就加。"""
    filled = dict(selection)
    # 与主选逻辑一致: priority 升序尝试追加
    ordered = sorted(candidates, key=lambda x: int(x[1].get("priority", 99)))
    progressed = True
    while progressed:
        progressed = False
        for mid, _cfg in ordered:
            step = module_step(mid)
            trial = dict(filled)
            trial[mid] = trial.get(mid, 0) + step
            result = layout_runner(trial, site_polygon, allow_decompose=True, road_check=False)
            if result.success and not result.unplaced:
                filled = trial
                progressed = True
                break
    return filled


def _fill_with_secondary(
    selection: Dict[str, int],
    evacuees: int,
    site_polygon,
    candidates: List[Tuple[str, dict]],
    exclude_id: str,
    layout_runner,
) -> Dict[str, int]:
    """用次偏好模块补齐床位缺口(贪心, 每加一个就校验能否放下)。"""
    all_configs = load_all_module_configs()
    # 次选: 跳过主选, 选 priority 最高、step 最小的
    secondary = [(mid, cfg) for mid, cfg in candidates if mid != exclude_id]
    # 按 step 升序, priority 升序排(小步长优先, 便于精细补齐)
    secondary.sort(key=lambda x: (module_step(x[0]), int(x[1].get("priority", 99))))

    for sec_id, sec_cfg in secondary:
        if _total_beds(selection, all_configs) >= evacuees:
            break
        sec_step = module_step(sec_id)
        sec_beds = int(sec_cfg.get("beds", 1))
        # 补齐到目标
        gap = evacuees - _total_beds(selection, all_configs)
        add_qty = math.ceil(gap / max(sec_beds, 1))
        add_qty = ((add_qty + sec_step - 1) // sec_step) * sec_step
        if add_qty <= 0:
            continue
        trial = dict(selection)
        trial[sec_id] = trial.get(sec_id, 0) + add_qty
        result = layout_runner(trial, site_polygon, allow_decompose=True, road_check=False)
        if result.success and not result.unplaced:
            selection = trial
        else:
            # 尝试减半再加
            half = max(sec_step, add_qty // 2)
            half = ((half + sec_step - 1) // sec_step) * sec_step
            if half > 0 and half < add_qty:
                trial2 = dict(selection)
                trial2[sec_id] = trial2.get(sec_id, 0) + half
                r2 = layout_runner(trial2, site_polygon, allow_decompose=True, road_check=False)
                if r2.success and not r2.unplaced:
                    selection = trial2

    return selection
