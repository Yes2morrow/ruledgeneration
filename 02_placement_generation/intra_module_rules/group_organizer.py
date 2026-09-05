"""通用群组生成器 - 从 YAML 配置加载群组规则, 替代原项目各模块独立的 organizer。

设计要点:
  1. 完全配置驱动: 群组定义来自 configs/groups/group_X.yaml, 零硬编码。
  2. organize_groups: 按数量贪心分解为群组实例(大群组优先, fill 兜底)。
  3. decompose_group: 单群组放不下时按 decompose_to 链降级。
  4. 不再为 A/B/C/D/E/F/G 各写一个 organizer 文件, 统一逻辑。
"""
from __future__ import annotations

import copy
import math
import os
import sys
from pathlib import Path
from typing import List, Optional

# 注入 01_pre_selection 路径以导入 config_loader
_PROJ_ROOT = Path(__file__).resolve().parents[2]
_PRE_SEL = _PROJ_ROOT / "01_pre_selection"
if str(_PRE_SEL) not in sys.path:
    sys.path.insert(0, str(_PRE_SEL))

from config_loader import (  # noqa: E402
    get_group_defs,
    get_group_def_by_type,
    get_decompose_to,
)

_PRIORITY_RANK = {"preferred": 0, "flexible": 1, "fill": 2}


def _priority_rank(priority: str) -> int:
    return _PRIORITY_RANK.get(priority, 3)


def _instance(def_: dict) -> dict:
    """从群组定义创建一个实例(深拷贝, 避免共享引用)。"""
    inst = copy.deepcopy(def_)
    return inst


def organize_groups(module_id: str, quantity: int) -> List[dict]:
    """根据模块 ID 和数量生成群组实例列表。

    贪心策略: 按 module_count 降序、layout_priority 优先级排序, 优先用大群组填充,
    剩余用最小 fill 群组兜底。返回的每个实例是该群组定义的深拷贝。

    例: organize_groups('A', 8) 可能返回 2 个 A_group_two(4模块) 实例。
    """
    if quantity <= 0:
        return []

    defs = get_group_defs(module_id)
    if not defs:
        raise ValueError(f"模块 {module_id} 无群组配置")

    # 排序: module_count 降序, 同尺寸优先 preferred
    ordered = sorted(
        defs,
        key=lambda g: (-g.get("module_count", 1), _priority_rank(g.get("layout_priority", "fill"))),
    )

    plan: List[dict] = []
    remaining = quantity

    for def_ in ordered:
        if remaining <= 0:
            break
        mc = def_.get("module_count", 1)
        if mc <= 0:
            continue
        if mc <= remaining:
            n = remaining // mc
            for _ in range(n):
                plan.append(_instance(def_))
                remaining -= mc

    # 剩余无法被大群组整除的部分, 用最小 fill 群组补齐
    if remaining > 0:
        fill_defs = [g for g in defs if g.get("layout_priority") == "fill"]
        if not fill_defs:
            # 退而用最小 module_count 的群组
            fill_defs = defs
        smallest = min(fill_defs, key=lambda g: g.get("module_count", 1))
        sm_count = smallest.get("module_count", 1)
        if sm_count == 1:
            for _ in range(remaining):
                plan.append(_instance(smallest))
            remaining = 0
        else:
            # 单模块数 != 1, 补 ceil 个(可能略超, 由 layout 阶段决定取舍)
            n = math.ceil(remaining / sm_count)
            for _ in range(n):
                plan.append(_instance(smallest))
            remaining = 0

    return plan


def decompose_group(module_id: str, group_type: str) -> List[dict]:
    """群组降级分解: 按 decompose_to 拆分为更小的群组实例。

    返回的实例数 = ceil(原 module_count / 目标 module_count)。
    若已是最小单元(decompose_to 为 None), 返回空列表。
    """
    target = get_decompose_to(module_id, group_type)
    if target is None:
        return []

    orig_def = get_group_def_by_type(module_id, group_type)
    target_def = get_group_def_by_type(module_id, target)
    if not orig_def or not target_def:
        return []

    orig_count = orig_def.get("module_count", 1)
    target_count = target_def.get("module_count", 1)
    if target_count <= 0:
        return []

    n = max(1, math.ceil(orig_count / target_count))
    return [_instance(target_def) for _ in range(n)]


def full_decompose_chain(module_id: str, group_type: str) -> List[str]:
    """返回完整降级链 group_type 列表(含自身)。"""
    chain = [group_type]
    seen = {group_type}
    current = group_type
    while True:
        nxt = get_decompose_to(module_id, current)
        if nxt is None or nxt in seen:
            break
        chain.append(nxt)
        seen.add(nxt)
        current = nxt
    return chain


def estimate_group_footprint(group_def: dict, module_config: dict) -> tuple:
    """估算群组占地尺寸(米)。

    用于 organize 阶段快速判断可行性, 精确尺寸在 layout 阶段计算。
    返回 (length_m, width_m)。
    """
    length_mm = module_config["dimensions"]["length_mm"]
    width_mm = module_config["dimensions"]["width_mm"]
    mod_l = length_mm / 1000.0
    mod_w = width_mm / 1000.0

    rows = group_def.get("rows", 1)
    cols = group_def.get("cols", 1)
    internal = group_def.get("internal_spacing", {}) or {}
    h_gap = float(internal.get("horizontal_gap_m", 0.0))
    v_gap = float(internal.get("vertical_gap_m", 0.0))

    length_m = cols * mod_l + max(0, cols - 1) * h_gap
    width_m = rows * mod_w + max(0, rows - 1) * v_gap
    return length_m, width_m
