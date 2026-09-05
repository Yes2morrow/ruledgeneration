"""几何工具与数据结构 - 排布系统的坐标变换基础。

坐标系约定:
  场地坐标系: 原点在场地左下角 (0, 0), x 轴=长度方向(米), y 轴=宽度方向(米)。
  模块内部坐标系: 原点在模块左下角 (0, 0), x 轴=length_mm, y 轴=width_mm (毫米)。
  组坐标系: 原点在组左下角 (0, 0), row 从下往上 (0,1,...), col 从左往右 (0,1,...)。

变换顺序: 原始模块坐标 --mirror--> --rotation--> 模块在组内局部坐标。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple, Sequence

Point = Tuple[float, float]
Polygon = List[Point]


# --------------------------------------------------------------------------- #
# 基础多边形运算
# --------------------------------------------------------------------------- #
def polygon_bbox(polygon: Polygon) -> Tuple[float, float, float, float]:
    """返回 (min_x, min_y, max_x, max_y)。"""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """射线法判断点是否在多边形内(含边界), 先用 bbox 快速排除。"""
    x, y = point
    minx, miny, maxx, maxy = polygon_bbox(polygon)
    if x < minx - 1e-9 or x > maxx + 1e-9 or y < miny - 1e-9 or y > maxy + 1e-9:
        return False
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """两线段是否相交(严格相交, 共线视为不相交以避免边界误判)。"""

    def ccw(a: Point, b: Point, c: Point) -> float:
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    return False


def polygons_overlap(a: Polygon, b: Polygon) -> bool:
    """两个多边形是否相交(边相交或包含)。bbox 快速排除。"""
    ax0, ay0, ax1, ay1 = polygon_bbox(a)
    bx0, by0, bx1, by1 = polygon_bbox(b)
    if ax1 < bx0 - 1e-9 or bx1 < ax0 - 1e-9 or ay1 < by0 - 1e-9 or by1 < ay0 - 1e-9:
        return False
    na, nb = len(a), len(b)
    # 边相交
    for i in range(na):
        p1, p2 = a[i], a[(i + 1) % na]
        for j in range(nb):
            p3, p4 = b[j], b[(j + 1) % nb]
            if _segments_intersect(p1, p2, p3, p4):
                return True
    # 包含
    for p in a:
        if point_in_polygon(p, b):
            return True
    for p in b:
        if point_in_polygon(p, a):
            return True
    return False


# --------------------------------------------------------------------------- #
# 轴对齐矩形间距检查 (用于组间 external_spacing)
# --------------------------------------------------------------------------- #
def rects_violate_spacing(
    rect1: Tuple[float, float, float, float],
    rect2: Tuple[float, float, float, float],
    spacing,
) -> bool:
    """两个轴对齐矩形是否违反最小轴对齐间距。

    rect = (x, y, w, h) 左下角 + 宽高。
    spacing 可为单值(横纵相同)或 (sx, sy) 分别表示水平/垂直最小间距。
    违反 = 两方向净距都 < 对应间距 (含重叠)。即只要有一个方向间距 >= 对应值就合法。
    spacing=0 时退化为重叠检查。
    """
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2
    if isinstance(spacing, (tuple, list)):
        sx, sy = float(spacing[0]), float(spacing[1])
    else:
        sx = sy = float(spacing)
    dx = max(x1, x2) - min(x1 + w1, x2 + w2)  # x方向净距(负=重叠)
    dy = max(y1, y2) - min(y1 + h1, y2 + h2)
    return dx < sx - 1e-9 and dy < sy - 1e-9


def rect_in_polygon(
    rect: Tuple[float, float, float, float], polygon: Polygon
) -> bool:
    """轴对齐矩形是否完全落在多边形内(四个角点都在多边形内)。"""
    x, y, w, h = rect
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return all(point_in_polygon(c, polygon) for c in corners)


# --------------------------------------------------------------------------- #
# 朝向变换
# --------------------------------------------------------------------------- #
_DIR_VECTORS = {
    "north": (0, 1),
    "south": (0, -1),
    "east": (1, 0),
    "west": (-1, 0),
}
_INV_VECTORS = {v: k for k, v in _DIR_VECTORS.items()}


def transform_direction(direction: str, mirror: str, rotation: int) -> str:
    """变换床头朝向。

    mirror: none/vertical(上下镜像, y翻转)/horizontal(左右镜像, x翻转)/both
    rotation: 0 或 90 (顺时针)。
    """
    v = _DIR_VECTORS.get(direction)
    if v is None:
        return direction
    vx, vy = v
    m = mirror or "none"
    if m in ("vertical", "both"):
        vy = -vy
    if m in ("horizontal", "both"):
        vx = -vx
    if rotation in (90, 90.0):
        # 顺时针 90 度: (vx, vy) -> (vy, -vx)
        vx, vy = vy, -vx
    return _INV_VECTORS.get((vx, vy), direction)


# --------------------------------------------------------------------------- #
# 模块内部多边形变换 (mm 单位)
# --------------------------------------------------------------------------- #
def transform_module_polygon(
    polygon_mm: Sequence[Point],
    length_mm: float,
    width_mm: float,
    mirror: str,
    rotation: int,
) -> Tuple[Polygon, Tuple[float, float]]:
    """将模块内部多边形(mm)按 mirror 和 rotation 变换。

    变换顺序: 先 mirror 再 rotation。
    返回 (变换后的多边形 mm, 变换后占用尺寸 (occ_length_mm, occ_width_mm))。
    """
    pts: List[Point] = [(float(x), float(y)) for x, y in polygon_mm]
    m = mirror or "none"
    if m in ("vertical", "both"):
        pts = [(x, width_mm - y) for x, y in pts]
    if m in ("horizontal", "both"):
        pts = [(length_mm - x, y) for x, y in pts]
    if rotation in (90, 90.0):
        # 顺时针 90: (x,y) -> (y, L - x), 新尺寸 W×L
        pts = [(y, length_mm - x) for x, y in pts]
        return pts, (width_mm, length_mm)
    return pts, (length_mm, width_mm)


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class PlacedModule:
    """已放置的模块实例。"""

    module_id: str
    group_type: str
    # 在场地中的左下角坐标(米)
    x: float
    y: float
    rotation: int
    mirror: str
    # 模块原始尺寸(mm)
    length_mm: float
    width_mm: float
    # 变换后占用尺寸(米)
    occ_length_m: float
    occ_width_m: float
    # 模块配置(含 beds_layout, road_areas)
    config: dict

    @property
    def rect(self) -> Tuple[float, float, float, float]:
        """场地轴对齐外接矩形 (x, y, w, h) 米。"""
        return (self.x, self.y, self.occ_length_m, self.occ_width_m)


@dataclass
class PlacedGroup:
    """已放置的群组实例。"""

    group_type: str
    module_id: str
    # 在场地中的左下角坐标(米)
    x: float
    y: float
    rotated: bool  # 组整体是否旋转 90 度
    # 组尺寸(米)
    length_m: float
    width_m: float
    rows: int
    cols: int
    module_count: int
    # 群组间外部间距 {horizontal_gap_m, vertical_gap_m}(米, 区分x/y)
    external_spacing: dict = field(default_factory=dict)
    modules: List[PlacedModule] = field(default_factory=list)

    @property
    def rect(self) -> Tuple[float, float, float, float]:
        return (self.x, self.y, self.length_m, self.width_m)


@dataclass
class BedInstance:
    """已放置的床位实例。"""

    bed_id: int
    module_id: str
    group_type: str
    # 在场地中的多边形(米)
    polygon_m: Polygon
    head_direction: str  # 变换后的床头朝向
    head_position_m: float


@dataclass
class RoadArea:
    """道路区域(米, 场地坐标)。"""

    name: str
    polygon_m: Polygon
    source: str  # "module" | "internal_gap" | "external_gap"


@dataclass
class LayoutResult:
    """排布结果。"""

    site_polygon: Polygon  # 场地多边形(米)
    groups: List[PlacedGroup] = field(default_factory=list)
    beds: List[BedInstance] = field(default_factory=list)
    roads: List[RoadArea] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    success: bool = False
    message: str = ""
    unplaced: List[dict] = field(default_factory=list)  # 未能放置的模块


def normalize_mirror(mirror) -> str:
    """规范化 mirror 字段。"""
    if mirror is None:
        return "none"
    m = str(mirror).strip().lower()
    if m in ("none", "vertical", "horizontal", "both"):
        return m
    return "none"
