"""布局优化器 - 主排布编排。

职责:
  1. 接收模块选择 {module_id: quantity}, 用 group_organizer 分解为群组实例。
  2. 逐组放置: 调 position_finder.find_best_position, 失败则按 decompose_to 降级。
  3. 构建已放置模块/床位/道路实例(含坐标变换)。
  4. 计算指标 + 床周边道路校验。
  5. 显式参数传递(无环境变量), 保证稳定性。

道路判定:
  模块内仅配置通道可通行，每个真实开口必须接入同一公共道路。
  公共道路不低于 1.2m；内部通道保持原设计，邻近床位校验实际绕行。
"""
from __future__ import annotations

import sys
from copy import copy
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

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
    normalize_rotation,
    group_grid_geometry,
    transform_direction,
    transform_module_polygon,
)
from group_organizer import decompose_group, organize_groups  # noqa: E402
from position_finder import find_best_position, can_place  # noqa: E402

from road_connectivity import RoadNetwork  # noqa: E402
from circulation_paths import (audit_bed_routes, repair_corridor, PUBLIC_WIDTH_M,
                               MAX_REPAIR_ROUNDS)  # noqa: E402


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
    cells, (group_length, _) = group_grid_geometry(group_def, module_config)
    for entry, off_x, off_y, occ_l_m, occ_w_m in cells:
        mirror = normalize_mirror(entry.get("mirror", "none"))
        arr_rot = normalize_rotation(entry.get("rotation"))
        effective_rot = (arr_rot + (90 if group_rotated else 0)) % 360
        if group_rotated:
            off_x, off_y = off_y, group_length - off_x - occ_l_m
            occ_l_m, occ_w_m = occ_w_m, occ_l_m

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
    return {
        "used_length_m": round(max_x, 3),
        "used_width_m": round(max_y, 3),
        "used_area_m2": round(used_area, 3),
        "road_area_m2": 0.0,
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


def _align_remainder_columns(groups, modules, beds, network, site, reserved, width):
    """Straighten a minority of remainder rows after a feasible packing exists.

    Large configured groups establish the packing; smaller decomposed groups
    sometimes attach to a neighbouring wall instead of following their own
    column. Move only to an existing majority line, retaining every module.
    """
    largest = {g.module_id: max(p.module_count for p in groups if p.module_id == g.module_id)
               for g in groups}
    columns = defaultdict(list)
    for index, group in enumerate(groups):
        if group.module_count < largest[group.module_id]:
            across = group.width_m if group.rotated else group.length_m
            columns[group.module_id, group.rotated, round(across, 3)].append(index)
    moves = []
    for indices in columns.values():
        lines = Counter(round(groups[i].y if groups[i].rotated else groups[i].x, 3) for i in indices)
        target, count = lines.most_common(1)[0]
        if count < 2 or count * 2 <= len(indices):
            continue
        moves.extend((i, target) for i in indices
                     if abs((groups[i].y if groups[i].rotated else groups[i].x) - target) > .001)
    if not moves or not network.evaluate().valid or not audit_bed_routes(network)['route_access_valid']:
        return groups, modules, beds, network
    for index, target in moves:
        group = groups[index]
        others = groups[:index] + groups[index + 1:]
        x, y = (group.x, target) if group.rotated else (target, group.y)
        rect = (x, y, group.length_m, group.width_m)
        if not can_place(rect, others, site, group._group_def):
            continue
        if any(x < rx+rw-1e-9 and x+group.length_m > rx+1e-9
               and y < ry+rh-1e-9 and y+group.width_m > ry+1e-9 for rx, ry, rw, rh in reserved):
            continue
        updated = copy(group)
        updated.x, updated.y = x, y
        updated.modules, group_beds, group_roads = [], [], []
        _build_group_contents(group._group_def, group.modules[0].config, x, y, group.rotated,
                              updated.modules, group_beds, group_roads)
        proposed = list(groups)
        proposed[index] = updated
        trial_modules = [m for g in proposed for m in g.modules]
        trial = RoadNetwork(site, trial_modules, public_width_m=width)
        if not trial.evaluate().valid or not audit_bed_routes(trial)['route_access_valid']:
            continue
        groups, modules, network = proposed, trial_modules, trial
        beds = []
        for g in groups:
            _build_group_contents(g._group_def, g.modules[0].config, g.x, g.y, g.rotated,
                                  [], beds, [])
    return groups, modules, beds, network


def _align_supplemental_singles(groups, modules, beds, network, site, reserved, width):
    """Locally align a stranded remainder only if the whole plan stays valid.

    Do this after finding a feasible plan: changing early packing decisions can
    move the corridor repair and lose an otherwise feasible bed combination.
    """
    targets = []
    for index, group in enumerate(groups):
        if group.module_count != 1:
            continue
        peers = [g for g in groups if g.module_id == group.module_id and g.module_count > 1]
        if not peers:
            continue
        rotated = sum(g.module_count for g in peers if g.rotated)
        normal = sum(g.module_count for g in peers if not g.rotated)
        if rotated != normal and group.rotated != (rotated > normal):
            targets.append((index, rotated > normal))
    if not targets or not network.evaluate().valid or not audit_bed_routes(network)['route_access_valid']:
        return groups, modules, beds, network
    for index, preferred in targets:
        group = groups[index]
        others = groups[:index] + groups[index + 1:]
        remaining = [m for g in others for m in g.modules]
        trial_base = RoadNetwork(site, remaining, public_width_m=width)
        definition = dict(group._group_def, _align_supplement=True)
        config = group.modules[0].config
        accepted, attempts = None, 0
        def valid(candidate):
            nonlocal accepted, attempts
            x, y, rotated, _, _ = candidate
            if rotated != preferred or attempts >= 32:
                return False
            attempts += 1
            content = ([], [], [])
            _build_group_contents(definition, config, x, y, rotated, *content)
            if not trial_base.evaluate(content[0], include_roads=False).valid:
                return False
            complete = RoadNetwork(site, remaining + content[0], public_width_m=width)
            if not audit_bed_routes(complete)['route_access_valid']:
                return False
            accepted = content
            return True
        position = find_best_position(definition, config, others, site, candidate_validator=valid,
                                      clearance_m=width, reserved_rects=reserved)
        if position is None:
            continue
        updated = copy(group)
        updated.x, updated.y, updated.rotated, updated.length_m, updated.width_m = position
        updated.modules = accepted[0]
        groups = list(groups)
        groups[index] = updated
        # Keep bed ordering identical to group/module order for diagnostics.
        modules, beds = [], []
        for g in groups:
            rebuilt, group_beds, group_roads = [], [], []
            _build_group_contents(g._group_def, g.modules[0].config, g.x, g.y, g.rotated,
                                  rebuilt, group_beds, group_roads)
            modules.extend(rebuilt)
            beds.extend(group_beds)
        network = RoadNetwork(site, modules, public_width_m=width)
    return groups, modules, beds, network


def calculate_layout(
    modules_selection: Dict[str, int],
    site_polygon,
    allow_decompose: bool = True,
    road_check: bool = True,
    public_road_width_m: float = 1.2,
    allow_width_fallback: bool = False,
    _reserved_corridors=(),
) -> LayoutResult:
    """主排布入口。

    :param modules_selection: {module_id: quantity} 例如 {"A": 4, "C": 8}
    :param site_polygon: 场地多边形(米, 左下角为原点), 由 config_loader.get_site_polygon 构造
    :param allow_decompose: 放不下时是否按 decompose_to 降级
    :param road_check: 是否在候选放置时过滤堵路方案；最终连通检查始终执行
    :return: LayoutResult
    """
    from compute_budget import check_budget
    check_budget()
    site_polygon = [tuple(p) for p in site_polygon]
    if public_road_width_m < PUBLIC_WIDTH_M:
        raise ValueError('公共通道净宽不能小于 1.2 米')
    main_corridors = list(_reserved_corridors)

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

    connectivity_candidates_checked = 0
    # At a fixed placement state, identical groups have identical feasibility.
    # Oversized capacity probes otherwise repeat the same expensive failed search.
    failed_positions = set()
    network = RoadNetwork(site_polygon, public_width_m=public_road_width_m)
    i = 0
    while i < len(pending):
        check_budget()
        group_def = pending[i]
        module_id = group_def["module_id"]
        group_type = group_def["group_type"]

        if module_id not in module_cache:
            module_cache[module_id] = load_module_config(module_id)
        module_config = module_cache[module_id]

        accepted_contents = None

        def preserves_access(candidate):
            nonlocal connectivity_candidates_checked, accepted_contents
            connectivity_candidates_checked += 1
            x, y, rotated, _, _ = candidate
            trial_modules, trial_beds, trial_roads = [], [], []
            _build_group_contents(group_def, module_config, x, y, rotated,
                                  trial_modules, trial_beds, trial_roads)
            if not network.evaluate(trial_modules, include_roads=False).valid:
                return False
            accepted_contents = (trial_modules, trial_beds, trial_roads)
            return True

        failure_key = (module_id, group_type, len(placed_groups))
        known_failure = failure_key in failed_positions
        result = None if known_failure else find_best_position(
            group_def, module_config, placed_groups, site_polygon,
            candidate_validator=preserves_access if road_check else None,
            clearance_m=public_road_width_m if road_check else 0,
            reserved_rects=main_corridors)
        if result is None and road_check and not known_failure:
            # Opposite-facing entrances may be the only route into a concave lobe.
            # Reuse quarter-turn geometry instead of adding another layout engine.
            original = group_def
            group_def = dict(original, arrangement=[dict(entry,
                row=int(original.get('rows', 1))-1-int(entry.get('row', 0)),
                col=int(original.get('cols', 1))-1-int(entry.get('col', 0)),
                rotation=(normalize_rotation(entry.get('rotation'))+180) % 360)
                for entry in original.get('arrangement', [])])
            result = find_best_position(group_def, module_config, placed_groups, site_polygon,
                                        candidate_validator=preserves_access, clearance_m=public_road_width_m,
                                        reserved_rects=main_corridors)
            if result is None:
                group_def = original
        if result is None:
            failed_positions.add(failure_key)
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
        if accepted_contents is None:
            accepted_contents = ([], [], [])
            _build_group_contents(group_def, module_config, x, y, rotated, *accepted_contents)
        new_modules, new_beds, new_roads = accepted_contents
        network.commit(new_modules)
        placed_modules.extend(new_modules)
        beds.extend(new_beds)
        roads.extend(new_roads)
        pg.modules = new_modules
        placed_groups.append(pg)
        i += 1

    # Always audit the final layout, including when candidate filtering is disabled.
    # No fabricated perimeter rectangles or whole-site polygons can mask blockage.
    if road_check and not unplaced:
        placed_groups, placed_modules, beds, network = _align_remainder_columns(
            placed_groups, placed_modules, beds, network, site_polygon, main_corridors, public_road_width_m)
        placed_groups, placed_modules, beds, network = _align_supplemental_singles(
            placed_groups, placed_modules, beds, network, site_polygon, main_corridors, public_road_width_m)
    checked = network.evaluate()
    roads = checked.roads
    for x, y, w, h in main_corridors:
        roads.append(RoadArea(name='贯通主通道', polygon_m=[(x,y),(x+w,y),(x+w,y+h),(x,y+h)], source='main'))
    metrics = _compute_metrics(placed_groups, beds, site_polygon, roads)
    no_access = [dict(module_id=beds[index].module_id, bed_id=beds[index].bed_id,
                      group_type=beds[index].group_type, layout_bed_index=index + 1)
                 for index in checked.blocked_indices]
    metrics.update(
        road_area_m2=round(checked.reachable_area, 3),
        unusable_open_area_m2=round(checked.unusable_area, 6),
        road_component_count=checked.component_count,
        road_connectivity_checked=True,
        road_candidate_filter_enabled=bool(road_check),
        road_connected=checked.valid,
        road_model="explicit_aisles_and_public_clearance",
        public_road_width_m=public_road_width_m,
        road_width_reduced=False,
        main_corridor_width_m=PUBLIC_WIDTH_M,
        main_corridor_count=len(main_corridors),
        main_corridors=[{'x': x, 'y': y, 'width': w, 'height': h} for x, y, w, h in main_corridors],
        road_opening_errors=checked.opening_errors,
        road_opening_errors_count=len(checked.opening_errors),
        connectivity_candidates_checked=connectivity_candidates_checked,
        beds_without_road_access=no_access,
        beds_without_road_access_count=len(no_access),
    )
    path_check = (audit_bed_routes(network) if checked.valid and not unplaced else
                  {'route_access_valid': False, 'route_audit_skipped': '布局不完整或通道未连通'})
    metrics.update(path_check)
    success = not unplaced and checked.valid and path_check['route_access_valid']
    messages = []
    if unplaced:
        messages.append(f"未能在边界、不重叠及道路连通约束下放置 {len(unplaced)} 个群组")
    if no_access:
        messages.append(f"{len(no_access)} 张床的内部通道未接入主路")
    if checked.opening_errors:
        messages.append(f"{len(checked.opening_errors)} 处通道开口或直接连接未通过检查")
    if checked.valid and not unplaced and not path_check['route_access_valid']:
        messages.append(path_check.get('route_error', '邻近床位实际路径绕行超出 20 米，请减少模块或调整场地'))
    message = "；".join(messages)

    layout = LayoutResult(
        site_polygon=site_polygon,
        groups=placed_groups,
        beds=beds,
        roads=roads,
        metrics=metrics,
        success=success,
        message=message,
        unplaced=unplaced,
    )
    if (road_check and not unplaced and checked.valid and not path_check['route_access_valid']
            and len(main_corridors) < MAX_REPAIR_ROUNDS):
        corridor = repair_corridor(site_polygon, path_check.get('route_failures', []), main_corridors)
        if corridor:
            return calculate_layout(modules_selection, site_polygon, allow_decompose, road_check,
                                    public_road_width_m, False, (*main_corridors, corridor))
    return layout


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
                "holes_m": [[[round(x, 3), round(y, 3)] for x, y in ring] for ring in r.holes_m],
            }
            for r in result.roads
        ],
        "unplaced": result.unplaced,
    }
