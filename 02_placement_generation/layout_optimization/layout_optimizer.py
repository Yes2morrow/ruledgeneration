"""布局优化器 - 主排布编排。

职责:
  1. 接收模块选择 {module_id: quantity}, 用 group_organizer 分解为群组实例。
  2. 逐组放置: 调 position_finder.find_best_position, 失败则按 decompose_to 降级。
  3. 构建已放置模块/床位/道路实例(含坐标变换)。
  4. 计算指标 + 床周边道路校验。
  5. 显式参数传递(无环境变量), 保证稳定性。

底层逻辑保证(每个床周边有道路):
  - 模块内道路: module_config.road_areas (渲染为道路)。
  - 组内模块间道路: internal_spacing > 0 即道路。
  - 组间道路: 群组间间距(external_spacing, 区分x/y)间隙。
  - 布局后校验: 每张床外扩 0.3m 环带必须与某条道路相交(有出路)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_LAYOUT_DIR = Path(__file__).resolve().parent
_PLACEMENT = _LAYOUT_DIR.parent
_PROJ = _PLACEMENT.parent
if str(_PLACEMENT) not in sys.path:
    sys.path.insert(0, str(_PLACEMENT))
if str(_PLACEMENT / "intra_module_rules") not in sys.path:
    sys.path.insert(0, str(_PLACEMENT / "intra_module_rules"))
if str(_PLACEMENT / "inter_module_rules") not in sys.path:
    sys.path.insert(0, str(_PLACEMENT / "inter_module_rules"))
if str(_PROJ / "01_pre_selection") not in sys.path:
    sys.path.insert(0, str(_PROJ / "01_pre_selection"))

from config_loader import load_module_config  # noqa: E402
from geometry import (  # noqa: E402
    BedInstance,
    LayoutResult,
    PlacedGroup,
    PlacedModule,
    RoadArea,
    normalize_mirror,
    polygon_bbox,
    polygons_overlap,
    transform_direction,
    transform_module_polygon,
)
from group_organizer import decompose_group, organize_groups  # noqa: E402
from position_finder import calculate_group_size, find_best_position  # noqa: E402

# 床周边道路校验: 床外扩环带宽度(米)
_ROAD_CHECK_MARGIN_M = 0.3


def _build_group_contents(
    group_def: dict,
    module_config: dict,
    gx: float,
    gy: float,
    group_rotated: bool,
    placed_modules: List[PlacedModule],
    beds: List[BedInstance],
    roads: List[RoadArea],
) -> None:
    """根据 arrangement 构建组内所有模块/床位/道路实例, 追加到对应列表。"""
    module_id = group_def["module_id"]
    group_type = group_def["group_type"]

    mod_l_mm = float(module_config["dimensions"]["length_mm"])
    mod_w_mm = float(module_config["dimensions"]["width_mm"])
    mod_l_m = mod_l_mm / 1000.0
    mod_w_m = mod_w_mm / 1000.0

    internal = group_def.get("internal_spacing", {}) or {}
    h_gap = float(internal.get("horizontal_gap_m", 0.0))
    v_gap = float(internal.get("vertical_gap_m", 0.0))
    arrangement = group_def.get("arrangement", []) or []
    cols = int(group_def.get("cols", 1))

    for entry in arrangement:
        row = int(entry.get("row", 0))
        col = int(entry.get("col", 0))
        mirror = normalize_mirror(entry.get("mirror", "none"))
        arr_rot = int(entry.get("rotation", 0) or 0)
        effective_rot = (arr_rot + (90 if group_rotated else 0)) % 360

        # 模块在组内偏移(米)
        if group_rotated:
            off_x = row * (mod_w_m + v_gap)
            off_y = (cols - 1 - col) * (mod_l_m + h_gap)
            occ_l_m, occ_w_m = mod_w_m, mod_l_m
        else:
            off_x = col * (mod_l_m + h_gap)
            off_y = row * (mod_w_m + v_gap)
            occ_l_m, occ_w_m = mod_l_m, mod_w_m

        mx = gx + off_x
        my = gy + off_y

        pm = PlacedModule(
            module_id=module_id,
            group_type=group_type,
            x=mx,
            y=my,
            rotation=effective_rot,
            mirror=mirror,
            length_mm=mod_l_mm,
            width_mm=mod_w_mm,
            occ_length_m=occ_l_m,
            occ_width_m=occ_w_m,
            config=module_config,
        )
        placed_modules.append(pm)

        # 床位
        for bed in module_config.get("beds_layout", []):
            bed_poly_mm, _ = transform_module_polygon(
                bed["polygon"], mod_l_mm, mod_w_mm, mirror, effective_rot
            )
            bed_poly_m = [(mx + x / 1000.0, my + y / 1000.0) for x, y in bed_poly_mm]
            head_dir = transform_direction(bed.get("head_direction", "north"), mirror, effective_rot)
            beds.append(
                BedInstance(
                    bed_id=int(bed["bed_id"]),
                    module_id=module_id,
                    group_type=group_type,
                    polygon_m=bed_poly_m,
                    head_direction=head_dir,
                    head_position_m=float(bed.get("head_position_mm", 0)) / 1000.0,
                )
            )

        # 模块内道路
        for road in module_config.get("road_areas", []) or []:
            road_poly_mm, _ = transform_module_polygon(
                road["polygon"], mod_l_mm, mod_w_mm, mirror, effective_rot
            )
            road_poly_m = [(mx + x / 1000.0, my + y / 1000.0) for x, y in road_poly_mm]
            roads.append(RoadArea(name=road.get("name", "aisle"), polygon_m=road_poly_m, source="module"))

        # 模块周边道路: 模块外接矩形按 external_spacing 的 x/y 外扩环带, 代表组间间距通道。
        # 保证模块内 road_areas 为空时(如 G 模块), 边缘床仍能通过组间道路出行。
        ext = group_def.get("external_spacing") or {}
        ex = float(ext.get("horizontal_gap_m", 1.5)) if isinstance(ext, dict) else 1.5
        ey = float(ext.get("vertical_gap_m", 1.5)) if isinstance(ext, dict) else 1.5
        perimeter = [
            (mx - ex, my - ey),
            (mx + occ_l_m + ex, my - ey),
            (mx + occ_l_m + ex, my + occ_w_m + ey),
            (mx - ex, my + occ_w_m + ey),
        ]
        roads.append(RoadArea(name="perimeter", polygon_m=perimeter, source="module_perimeter"))


def _pair_group_spacing_xy(ga: PlacedGroup, gb: PlacedGroup) -> Tuple[float, float]:
    """两个已放置群组间的 (水平, 垂直) 间距, 取双方对应方向最大值。

    每方从 PlacedGroup.external_spacing (区分x/y) 取值, 缺失回退 1.5m。
    """
    sa = ga.external_spacing or {}
    sb = gb.external_spacing or {}
    ax = float(sa.get("horizontal_gap_m", 1.5)) if isinstance(sa, dict) else 1.5
    ay = float(sa.get("vertical_gap_m", 1.5)) if isinstance(sa, dict) else 1.5
    bx = float(sb.get("horizontal_gap_m", 1.5)) if isinstance(sb, dict) else 1.5
    by = float(sb.get("vertical_gap_m", 1.5)) if isinstance(sb, dict) else 1.5
    return max(ax, bx), max(ay, by)


def _add_gap_roads(
    groups: List[PlacedGroup],
    roads: List[RoadArea],
) -> None:
    """把组间间距间隙登记为道路(用于校验/渲染)。

    简化实现: 组间间隙用两个相邻组矩形之间的条带表示, 水平/垂直方向分别用对应间距。
    """
    for i, ga in enumerate(groups):
        for gb in groups[i + 1:]:
            sx, sy = _pair_group_spacing_xy(ga, gb)
            _emit_gap_road(ga.rect, gb.rect, sx, sy, roads)


def _emit_gap_road(rect_a, rect_b, sx, sy, roads):
    """若两矩形在某方向相邻(净距≈对应方向间距), 在其间隙画一条道路条带。"""
    ax, ay, aw, ah = rect_a
    bx, by, bw, bh = rect_b
    # 水平相邻: x方向净距 ≈ sx, 且 y方向有重叠
    if abs(abs(bx - (ax + aw)) - sx) < 0.05 and not (by + bh <= ay or ay + ah <= by):
        x0 = min(ax + aw, bx)
        x1 = max(ax + aw, bx)
        y0 = max(ay, by)
        y1 = min(ay + ah, by + bh)
        if y1 > y0:
            roads.append(RoadArea("gap_h", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "external_gap"))
    # 垂直相邻: y方向净距 ≈ sy, 且 x方向有重叠
    if abs(abs(by - (ay + ah)) - sy) < 0.05 and not (bx + bw <= ax or ax + aw <= bx):
        y0 = min(ay + ah, by)
        y1 = max(ay + ah, by)
        x0 = max(ax, bx)
        x1 = min(ax + aw, bx + bw)
        if x1 > x0:
            roads.append(RoadArea("gap_v", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "external_gap"))


def _bed_has_road_access(bed: BedInstance, roads: List[RoadArea]) -> bool:
    """校验床周边是否有道路: 床外扩 _ROAD_CHECK_MARGIN_M 环带与任一道路相交。"""
    minx, miny, maxx, maxy = polygon_bbox(bed.polygon_m)
    # 外扩环带(外框 - 内框)
    outer = [
        (minx - _ROAD_CHECK_MARGIN_M, miny - _ROAD_CHECK_MARGIN_M),
        (maxx + _ROAD_CHECK_MARGIN_M, miny - _ROAD_CHECK_MARGIN_M),
        (maxx + _ROAD_CHECK_MARGIN_M, maxy + _ROAD_CHECK_MARGIN_M),
        (minx - _ROAD_CHECK_MARGIN_M, maxy + _ROAD_CHECK_MARGIN_M),
    ]
    for road in roads:
        if polygons_overlap(outer, road.polygon_m):
            return True
    return False


def _compute_metrics(
    groups: List[PlacedGroup], beds: List[BedInstance], site_polygon, roads: List[RoadArea]
) -> dict:
    site_area = _polygon_area(site_polygon)
    if not groups:
        return {
            "used_length_m": 0.0,
            "used_width_m": 0.0,
            "used_area_m2": 0.0,
            "road_area_m2": 0.0,
            "site_area_m2": round(site_area, 3),
            "utilization": 0.0,
            "total_groups": 0,
            "total_modules": 0,
            "total_beds": 0,
        }
    max_x = max(g.x + g.length_m for g in groups)
    max_y = max(g.y + g.width_m for g in groups)
    used_area = sum(g.length_m * g.width_m for g in groups)
    # 统计道路面积：包括模块内部道路、perimeter、组间 gap，但不包括整片 site_open_area
    road_area = sum(
        _polygon_area(r.polygon_m)
        for r in roads
        if r.source != "site_open_area"
    )
    return {
        "used_length_m": round(max_x, 3),
        "used_width_m": round(max_y, 3),
        "used_area_m2": round(used_area, 3),
        "road_area_m2": round(road_area, 3),
        "site_area_m2": round(site_area, 3),
        "utilization": round(used_area / site_area * 100, 2) if site_area > 0 else 0.0,
        "total_groups": len(groups),
        "total_modules": sum(len(g.modules) for g in groups),
        "total_beds": len(beds),
    }


def _polygon_area(polygon) -> float:
    n = len(polygon)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def calculate_layout(
    modules_selection: Dict[str, int],
    site_polygon,
    allow_decompose: bool = True,
    road_check: bool = True,
) -> LayoutResult:
    """主排布入口。

    :param modules_selection: {module_id: quantity} 例如 {"A": 4, "C": 8}
    :param site_polygon: 场地多边形(米, 左下角为原点), 由 config_loader.get_site_polygon 构造
    :param allow_decompose: 放不下时是否按 decompose_to 降级
    :param road_check: 是否校验床周边道路
    :return: LayoutResult
    """
    site_polygon = [tuple(p) for p in site_polygon]

    # 1. 分解为群组实例
    pending: List[dict] = []
    for module_id, qty in modules_selection.items():
        try:
            instances = organize_groups(module_id, qty)
        except ValueError as e:
            return LayoutResult(site_polygon=site_polygon, success=False, message=str(e))
        for inst in instances:
            inst["module_id"] = module_id
            pending.append(inst)

    placed_groups: List[PlacedGroup] = []
    placed_modules: List[PlacedModule] = []
    beds: List[BedInstance] = []
    roads: List[RoadArea] = []
    unplaced: List[dict] = []

    module_cache: Dict[str, dict] = {}

    i = 0
    while i < len(pending):
        group_def = pending[i]
        module_id = group_def["module_id"]
        group_type = group_def["group_type"]

        if module_id not in module_cache:
            module_cache[module_id] = load_module_config(module_id)
        module_config = module_cache[module_id]

        result = find_best_position(group_def, module_config, placed_groups, site_polygon)
        if result is None:
            # 尝试降级
            if allow_decompose:
                fallback = decompose_group(module_id, group_type)
                if fallback:
                    for fb in fallback:
                        fb["module_id"] = module_id
                    pending[i:i + 1] = fallback
                    continue
            # 无法放置
            unplaced.append(
                {
                    "module_id": module_id,
                    "group_type": group_type,
                    "module_count": group_def.get("module_count", 1),
                }
            )
            i += 1
            continue

        x, y, rotated, length_m, width_m = result
        pg = PlacedGroup(
            group_type=group_type,
            module_id=module_id,
            x=x,
            y=y,
            rotated=rotated,
            length_m=length_m,
            width_m=width_m,
            rows=int(group_def.get("rows", 1)),
            cols=int(group_def.get("cols", 1)),
            module_count=int(group_def.get("module_count", 1)),
            external_spacing=group_def.get("external_spacing") or {},
            modules=[],
        )
        pg._group_def = group_def  # type: ignore[attr-defined]

        # 构建组内模块/床/道路
        group_modules_before = len(placed_modules)
        _build_group_contents(
            group_def, module_config, x, y, rotated, placed_modules, beds, roads
        )
        pg.modules = placed_modules[group_modules_before:]
        placed_groups.append(pg)
        i += 1

    # 组间间隙道路(用于校验/渲染)
    _add_gap_roads(placed_groups, roads)

    # 将场地未布置区域整体判定为交通/道路区域
    roads.insert(
        0,
        RoadArea(
            name="site_open_area",
            polygon_m=site_polygon,
            source="site_open_area",
        ),
    )

    # 指标
    metrics = _compute_metrics(placed_groups, beds, site_polygon, roads)

    # 床周边道路校验
    if road_check and beds:
        no_access = []
        for bed in beds:
            if not _bed_has_road_access(bed, roads):
                no_access.append(
                    {
                        "module_id": bed.module_id,
                        "group_type": bed.group_type,
                        "bed_id": bed.bed_id,
                    }
                )
        metrics["beds_without_road_access"] = no_access
        metrics["beds_without_road_access_count"] = len(no_access)

    success = len(unplaced) == 0
    message = "" if success else f"未能放置 {len(unplaced)} 个群组"

    return LayoutResult(
        site_polygon=site_polygon,
        groups=placed_groups,
        beds=beds,
        roads=roads,
        metrics=metrics,
        success=success,
        message=message,
        unplaced=unplaced,
    )


def layout_result_to_dict(result: LayoutResult) -> dict:
    """将 LayoutResult 序列化为 JSON 友好的字典(供 WebUI/CLI 输出)。"""
    return {
        "success": result.success,
        "message": result.message,
        "site_polygon": [list(p) for p in result.site_polygon],
        "metrics": result.metrics,
        "groups": [
            {
                "module_id": g.module_id,
                "group_type": g.group_type,
                "x": round(g.x, 3),
                "y": round(g.y, 3),
                "rotated": g.rotated,
                "length_m": round(g.length_m, 3),
                "width_m": round(g.width_m, 3),
                "rows": g.rows,
                "cols": g.cols,
                "module_count": g.module_count,
                "external_spacing": g.external_spacing,
                "modules": [
                    {
                        "x": round(m.x, 3),
                        "y": round(m.y, 3),
                        "rotation": m.rotation,
                        "mirror": m.mirror,
                        "occ_length_m": round(m.occ_length_m, 3),
                        "occ_width_m": round(m.occ_width_m, 3),
                    }
                    for m in g.modules
                ],
            }
            for g in result.groups
        ],
        "beds": [
            {
                "bed_id": b.bed_id,
                "module_id": b.module_id,
                "group_type": b.group_type,
                "polygon_m": [[round(x, 3), round(y, 3)] for x, y in b.polygon_m],
                "head_direction": b.head_direction,
            }
            for b in result.beds
        ],
        "roads": [
            {
                "name": r.name,
                "source": r.source,
                "polygon_m": [[round(x, 3), round(y, 3)] for x, y in r.polygon_m],
            }
            for r in result.roads
        ],
        "unplaced": result.unplaced,
    }
