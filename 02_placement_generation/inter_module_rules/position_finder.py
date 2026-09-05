"""位置寻找器 - 在场地多边形内为群组寻找最佳放置位置。

统一逻辑(替代原项目按模块类型特化的 finder):
  1. 完全配置驱动: 群组间距查 external_spacing (区分水平/垂直), 缺失回退 1.5m,
     不再硬编码 A=2.0/C=1.5。
  2. 场地为任意多边形(支持矩形退化), 用 rect_in_polygon 做边界检查。
  3. 候选生成: 原点 + 已放置群组的右侧/上方/右上角 + 网格搜索。
  4. 打分: 少旋转 > 高网格度(对齐边+正确间距邻居) > 小 footprint > 左下优先。
  5. 群组间距取双方对应方向间距的最大值, 满足各自要求。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_PLACEMENT = Path(__file__).resolve().parents[1]
if str(_PLACEMENT) not in sys.path:
    sys.path.insert(0, str(_PLACEMENT))

from geometry import (  # noqa: E402
    Point,
    Polygon,
    rect_in_polygon,
    rects_violate_spacing,
)

# 用于网格搜索的候选去重容差(米)
_EPS = 0.05

# 紧凑度权重：越大越优先选择方形/紧凑布局，减少长条形排列。
# 与 footprint 同单位(m^2)，可直接相加。
_COMPACTNESS_WEIGHT = 1.0

# 长宽比惩罚权重： footprint * (max(长/宽, 宽/长) - 1) * 该权重。
# 越大越避免细长条，优先接近方形的布局。
_ASPECT_WEIGHT = 0.5


def calculate_group_size(group_def: dict, module_config: dict, rotated: bool) -> Tuple[float, float]:
    """计算群组占地尺寸(米)。

    rotated=True 时组整体顺时针旋转 90 度, length 与 width 互换。
    """
    mod_l = module_config["dimensions"]["length_mm"] / 1000.0
    mod_w = module_config["dimensions"]["width_mm"] / 1000.0
    rows = group_def.get("rows", 1)
    cols = group_def.get("cols", 1)
    internal = group_def.get("internal_spacing", {}) or {}
    h_gap = float(internal.get("horizontal_gap_m", 0.0))
    v_gap = float(internal.get("vertical_gap_m", 0.0))

    length_m = cols * mod_l + max(0, cols - 1) * h_gap
    width_m = rows * mod_w + max(0, rows - 1) * v_gap
    if rotated:
        return width_m, length_m
    return length_m, width_m


def _axis_spacing(group_def: dict, field: str = "external_spacing") -> Tuple[float, float]:
    """从 group_def 取指定间距字段的 (水平, 垂直) 间距, 缺失轴回退 1.5m。"""
    sp = group_def.get(field) or {}
    if not isinstance(sp, dict):
        return 1.5, 1.5
    return float(sp.get("horizontal_gap_m", 1.5)), float(sp.get("vertical_gap_m", 1.5))


def _pair_spacing(group_a: dict, group_b: dict) -> Tuple[float, float]:
    """两个群组间的最小轴对齐间距 (水平, 垂直), 取双方对应方向最大值。

    每方从 external_spacing (区分x/y) 取值, 缺失回退 1.5m。
    """
    ax, ay = _axis_spacing(group_a)
    bx, by = _axis_spacing(group_b)
    return max(ax, bx), max(ay, by)


def can_place(
    rect: Tuple[float, float, float, float],
    placed: List,
    site_polygon: Polygon,
    group_def: dict,
) -> bool:
    """检查群组外接矩形是否可放置: 在场地多边形内 + 不与任何已放置群组违反间距。

    placed 元素需有 .rect 属性和 ._group_def (群组定义, 含间距字段)。
    group_def 用于读取当前群组间距字段, 与每个已放置群组按同类/异类取间距。
    """
    # 场地边界
    if not rect_in_polygon(rect, site_polygon):
        return False
    # 与已放置群组的间距
    for p in placed:
        spacing = _pair_spacing(group_def, getattr(p, "_group_def", group_def))
        if rects_violate_spacing(rect, p.rect, spacing):
            return False
    return True


def _generate_candidates(
    placed: List,
    site_polygon: Polygon,
    group_w: float,
    group_h: float,
    group_def: dict,
) -> List[Point]:
    """生成候选放置位置 (x, y)。

    来源: 原点 + 已放置群组右侧/上方/右上角(用与该群组的实际间距) + 已放置边界网格。
    与每个已放置群组的间距取双方对应方向最大值(水平/垂直分离)。
    """
    candidates: List[Point] = [(0.0, 0.0)]

    for p in placed:
        sx, sy = _pair_spacing(group_def, getattr(p, "_group_def", group_def))
        px, py, pw, ph = p.rect
        # 右侧(同一基线 y) - 水平间距
        candidates.append((px + pw + sx, py))
        # 上方(同一基线 x) - 垂直间距
        candidates.append((px, py + ph + sy))
        # 右上角
        candidates.append((px + pw + sx, py + ph + sy))
        # 左下角对齐到已放置的 y(紧凑列)
        candidates.append((0.0, py + ph + sy))

    # 网格: 用已放置群组的 x/y 边界值组合(含间距偏移, 提高命中率)
    xs = {0.0}
    ys = {0.0}
    for p in placed:
        sx, sy = _pair_spacing(group_def, getattr(p, "_group_def", group_def))
        px, py, pw, ph = p.rect
        xs.add(px)
        xs.add(px + pw)
        xs.add(px + pw + sx)
        ys.add(py)
        ys.add(py + ph)
        ys.add(py + ph + sy)

    for x in sorted(xs):
        for y in sorted(ys):
            candidates.append((x, y))

    # 去重(容差)
    unique: List[Point] = []
    seen = set()
    for x, y in candidates:
        key = (round(x / _EPS), round(y / _EPS))
        if key in seen:
            continue
        seen.add(key)
        unique.append((x, y))
    # 左下优先: y 升序, x 升序
    unique.sort(key=lambda p: (p[1], p[0]))
    return unique


def _compactness_score(
    candidate: Tuple[float, float, bool, float, float],
    placed: List,
) -> float:
    """计算当前候选加入后的布局紧凑度。

    使用各群组中心到整体质心的距离平方均值(转动惯量)。
    越小表示布局越接近方形，群组间平均通勤距离越短。
    """
    x, y, rotated, w, h = candidate
    centers = [(x + w / 2, y + h / 2)]
    for p in placed:
        px, py, pw, ph = p.rect
        centers.append((px + pw / 2, py + ph / 2))

    n = len(centers)
    if n <= 1:
        return 0.0

    cx = sum(c[0] for c in centers) / n
    cy = sum(c[1] for c in centers) / n
    return sum((c[0] - cx) ** 2 + (c[1] - cy) ** 2 for c in centers) / n


def _grid_score(
    candidate: Tuple[float, float, bool, float, float],
    placed: List,
    group_def: dict,
) -> int:
    """网格度 = 对齐边数 + 正确间距邻居数。

    合并原 alignment(跨行坐标对齐) 与 adjacency(零间距贴合, 原恒0死代码,
    现重定义为"按 external_spacing 留间距的紧邻")。

    - 对齐边: 候选四条边的坐标与任意已放置群组对应轴边坐标相同
              (跨行也算), 每条 +1。奖励行列对齐形成规整网格。
    - 正确间距邻居: 候选按 external_spacing(sx/sy) 紧邻某已放置群组
                    (留了规矩间距且投影重叠), 每个邻居 +2。比单纯对齐
                    更宝贵, 它保证道路宽度正确、路口贯通。
    """
    x, y, rotated, w, h = candidate
    score = 0

    # 对齐边(原 alignment)
    candidate_edges = [
        (x, True),      # 左边 x
        (x + w, True),  # 右边 x
        (y, False),     # 下边 y
        (y + h, False), # 上边 y
    ]
    for value, is_x in candidate_edges:
        for p in placed:
            px, py, pw, ph = p.rect
            placed_edges = {px, px + pw} if is_x else {py, py + ph}
            if any(abs(value - e) < _EPS for e in placed_edges):
                score += 1
                break

    # 正确间距邻居(原 adjacency 重定义: 零间距 -> 规矩间距)
    for p in placed:
        sx, sy = _pair_spacing(group_def, getattr(p, "_group_def", group_def))
        px, py, pw, ph = p.rect
        y_overlap = not (y + h <= py + _EPS or y >= py + ph - _EPS)
        x_overlap = not (x + w <= px + _EPS or x >= px + pw - _EPS)
        # 候选在 p 右侧, 留水平间距 sx
        if y_overlap and abs(x - (px + pw + sx)) < _EPS:
            score += 2
        # 候选在 p 上方, 留垂直间距 sy
        if x_overlap and abs(y - (py + ph + sy)) < _EPS:
            score += 2
        # 候选在 p 左侧
        if y_overlap and abs(x + w + sx - px) < _EPS:
            score += 2
        # 候选在 p 下方
        if x_overlap and abs(y + h + sy - py) < _EPS:
            score += 2
    return score


def _score(
    candidate: Tuple[float, float, bool, float, float],
    placed: List,
    site_polygon: Polygon,
    group_def: dict,
) -> tuple:
    """候选位置打分, 越小越优。

    优先级: 少旋转 > 高网格度(对齐边+正确间距邻居) > 小(footprint+长宽比+紧凑度) > 左下优先。

    网格度合并了对齐(跨行坐标对齐)与正确间距邻居(按 external_spacing 紧邻),
    鼓励形成规整网格与贯通道路(十字路口)。
    """
    x, y, rotated, w, h = candidate
    rot_penalty = 1 if rotated else 0

    # 网格度(对齐边 + 正确间距邻居)
    grid = _grid_score(candidate, placed, group_def)

    # footprint: 布局外接矩形面积(希望紧凑)
    max_x = max([x + w] + [p.rect[0] + p.rect[2] for p in placed] + [0.0])
    max_y = max([y + h] + [p.rect[1] + p.rect[3] for p in placed] + [0.0])
    footprint = max_x * max_y

    # 长宽比惩罚：越细长代价越高，优先接近方形
    aspect_ratio = max(max_x / max_y, max_y / max_x) if max_x > 0 and max_y > 0 else 1.0
    aspect_penalty = footprint * (aspect_ratio - 1.0) * _ASPECT_WEIGHT

    # 紧凑度：惩罚长条形布局，优先方形/多行布局以降低通勤距离
    compactness = _compactness_score(candidate, placed)

    shape_cost = (
        footprint
        + aspect_penalty
        + _COMPACTNESS_WEIGHT * compactness
    )
    # 网格度独立作为主排序键: 优先形成规整网格与贯通道路(十字路口)。
    # 在旋转相同的情况下, 高网格度 > 紧凑度/footprint。
    return (rot_penalty, -grid, shape_cost, y, x)


def find_best_position(
    group_def: dict,
    module_config: dict,
    placed: List,
    site_polygon: Polygon,
) -> Optional[Tuple[float, float, bool, float, float]]:
    """为群组寻找最佳放置位置。

    返回 (x, y, rotated, length_m, width_m) 或 None。
    placed 元素需有 .rect 和 ._group_def 属性(由 layout_optimizer 设置)。
    """
    normal_w, normal_h = calculate_group_size(group_def, module_config, rotated=False)
    rotated_w, rotated_h = calculate_group_size(group_def, module_config, rotated=True)

    candidates: List[Tuple[float, float, bool, float, float]] = []

    # 正常方向候选
    for x, y in _generate_candidates(placed, site_polygon, normal_w, normal_h, group_def):
        rect = (x, y, normal_w, normal_h)
        if can_place(rect, placed, site_polygon, group_def):
            candidates.append((x, y, False, normal_w, normal_h))

    # 旋转方向候选
    for x, y in _generate_candidates(placed, site_polygon, rotated_w, rotated_h, group_def):
        rect = (x, y, rotated_w, rotated_h)
        if can_place(rect, placed, site_polygon, group_def):
            candidates.append((x, y, True, rotated_w, rotated_h))

    if not candidates:
        return None

    best = min(candidates, key=lambda c: _score(c, placed, site_polygon, group_def))
    return best
