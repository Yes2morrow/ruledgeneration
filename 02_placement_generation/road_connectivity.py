"""Validate real aisle openings and public-road clearance, separately.

Only configured aisles are traversable inside modules. An opening against a
wall cannot be rescued by a route through another opening around that wall.
"""
from dataclasses import dataclass, field, replace
from functools import lru_cache
import shapely
import numpy as np
from shapely.geometry import Polygon, LineString, GeometryCollection, box
from shapely.ops import unary_union
from geometry import RoadArea, transform_module_polygon

GRID_M = .001
EPS = 1e-6


def _polygon(points):
    shape = Polygon([(round(x, 3), round(y, 3)) for x, y in points])
    if not shape.is_valid or shape.is_empty:
        raise ValueError('场地或模块多边形无效，无法校验道路')
    return shapely.set_precision(shape, GRID_M)


def _parts(shape, kind='Polygon'):
    if shape.is_empty:
        return []
    if shape.geom_type == kind:
        return [shape]
    return [p for p in getattr(shape, 'geoms', []) if p.geom_type == kind and not p.is_empty]


@lru_cache(maxsize=4096)
def _opening_contact(port, footprint, openings, width):
    """Geometry-only cache: unchanged neighbouring mouths need no new overlay."""
    contact = port.intersection(footprint)
    if contact.length <= EPS:
        return (), False
    matches = tuple((n, shared) for n, other in enumerate(openings)
                    if (shared := port.intersection(other)).length >= width-GRID_M)
    closed = contact.difference(unary_union([p for _, p in matches])).length > EPS
    return matches, closed


@lru_cache(maxsize=4096)
def _opening_apron(port, footprint, width):
    """Keep a clear public-road landing directly outside each real entrance."""
    x0,y0,x1,y1 = port.bounds
    left,bottom,right,top = footprint.bounds
    if abs(x0-x1) < EPS:
        bounds = (x0-width,y0,x0,y1) if abs(x0-left) < EPS else (x0,y0,x0+width,y1)
    else:
        bounds = (x0,y0-width,x1,y0) if abs(y0-bottom) < EPS else (x0,y0,x1,y0+width)
    return shapely.set_precision(box(*bounds), GRID_M)


@dataclass
class RoadCheck:
    blocked_indices: list = field(default_factory=list)
    opening_errors: list = field(default_factory=list)
    reachable_area: float = 0
    unusable_area: float = 0
    component_count: int = 0
    roads: list = field(default_factory=list)

    @property
    def valid(self):
        return not self.blocked_indices and not self.opening_errors


class RoadNetwork:
    def __init__(self, site_polygon, modules=(), *, public_width_m=1.2):
        if not np.isfinite(public_width_m) or public_width_m < 1.0:
            raise ValueError('公共道路净宽不能小于 1.0 米')
        self.site = _polygon(site_polygon)
        self.width = float(public_width_m)
        self._cache = {}
        self.items = [self._geometry(m) for m in modules]
        self.obstacles = unary_union([g[0] for g in self.items])
        self._trial = None
        self._ports = {}
        self._opening_templates = {}
        self._bounds = np.asarray([item[0].bounds for item in self.items], dtype=float).reshape(-1, 4)
        self._rectangular_site = self.site.equals(box(*self.site.bounds))

    def _opening_bounds(self, module):
        key = (id(module.config), module.rotation, module.mirror)
        if key not in self._opening_templates:
            geometry = self._geometry(replace(module, x=0.0, y=0.0))
            ports = [p for mouths in geometry[3] for p in mouths]
            self._opening_templates[key] = (
                np.asarray([p.bounds for p in ports], dtype=float).reshape(-1, 4),
                np.asarray([_opening_apron(p, geometry[0], self.width).bounds for p in ports],
                           dtype=float).reshape(-1, 4))
        offset = np.array([module.x, module.y, module.x, module.y])
        return tuple(np.round(bounds + offset, 3) for bounds in self._opening_templates[key])

    def _obviously_blocked_opening(self, modules):
        """Conservative rejection before allocating translated polygons.

        Untouched straight mouths require their whole rectangular landing.
        Touching mouths (including partial shared openings), off-grid modules
        and concave site boundaries still use the full topology checks below.
        """
        if not modules or any(abs(v / GRID_M - round(v / GRID_M)) > 1e-6
                              for m in modules for v in (m.x, m.y)):
            return False
        added = np.asarray([(m.x, m.y, m.x + m.occ_length_m, m.y + m.occ_width_m)
                            for m in modules])
        obstacles = np.concatenate((self._bounds, np.round(added, 3)))
        new_openings = [self._opening_bounds(m) for m in modules]
        for index, module in enumerate(modules):
            ports, aprons = new_openings[index]
            other_ids = np.delete(np.arange(len(obstacles)), len(self.items) + index)
            others = obstacles[other_ids]
            for port, apron in zip(ports, aprons):
                touch = (np.maximum(port[:2], others[:, :2]) <=
                         np.minimum(port[2:], others[:, 2:]) + EPS).all(axis=1)
                if np.any(touch):
                    # If a mouth touches a wall, total shared opening length
                    # below the minimum cannot pass the full contact check.
                    # Ambiguous/partially shared contacts still fall through.
                    axis = 1 if abs(port[0] - port[2]) < EPS else 0
                    for other_id in other_ids[touch]:
                        rect = obstacles[other_id]
                        contact = min(port[axis+2], rect[axis+2]) - max(port[axis], rect[axis])
                        if contact <= EPS:
                            continue
                        if other_id < len(self.items):
                            other_ports = np.asarray([p.bounds for mouths in self.items[other_id][3]
                                                      for p in mouths]).reshape(-1, 4)
                        else:
                            other_ports = new_openings[other_id-len(self.items)][0]
                        overlap = np.minimum(port[2:], other_ports[:, 2:]) - np.maximum(port[:2], other_ports[:, :2])
                        shared = np.maximum(overlap[(overlap >= -EPS).all(axis=1), axis], 0).sum()
                        if shared < self.width-GRID_M:
                            return True
                    continue
                if self._rectangular_site:
                    left, bottom, right, top = self.site.bounds
                    if apron[0] < left-EPS or apron[1] < bottom-EPS or apron[2] > right+EPS or apron[3] > top+EPS:
                        return True
                overlap = np.minimum(apron[2:], others[:, 2:]) - np.maximum(apron[:2], others[:, :2])
                if np.any(np.prod(np.maximum(overlap, 0), axis=1) > EPS):
                    return True
        return False

    def _geometry(self, module):
        key = (id(module.config), module.x, module.y, module.rotation, module.mirror)
        if key in self._cache:
            return self._cache[key]

        # On the millimetre grid, translation preserves all aisle/bed incidence
        # and side openings. Reuse the origin template instead of rebuilding its
        # polygons, unions and intersections for every rejected dense candidate.
        # Off-grid positions retain the scalar path (rounding need not commute).
        if ((module.x != 0 or module.y != 0)
                and abs(module.x / GRID_M - round(module.x / GRID_M)) < 1e-6
                and abs(module.y / GRID_M - round(module.y / GRID_M)) < 1e-6):
            source = self._geometry(replace(module, x=0.0, y=0.0))
            # Translate the whole template in one vectorized operation. Each
            # rejected candidate used to dispatch transform/precision per bed,
            # aisle and port, hundreds of thousands of times for a dense cart.
            flat = [source[0], *source[1], *source[2],
                    *(g for ports in source[3] for g in ports), *source[4]]
            shifted = iter(shapely.set_precision(shapely.transform(
                np.asarray(flat, dtype=object),
                lambda xy: xy + (module.x, module.y)), GRID_M))
            item = (next(shifted), [next(shifted) for _ in source[1]],
                    [next(shifted) for _ in source[2]],
                    [[next(shifted) for _ in ports] for ports in source[3]],
                    tuple(next(shifted) for _ in source[4]), source[5])
            if len(self._cache) >= 1024:
                self._cache.clear()
            self._cache[key] = item
            return item

        def shape(points):
            poly, _ = transform_module_polygon(points, module.length_mm, module.width_mm,
                                                module.mirror, module.rotation)
            return _polygon([(module.x+x/1000, module.y+y/1000) for x, y in poly])

        length, width = module.length_mm, module.width_mm
        footprint = shape([(0,0),(length,0),(length,width),(0,width)])
        beds = [shape(b['polygon']) for b in module.config.get('beds_layout', [])]
        aisles = _parts(unary_union([shape(r['polygon']) for r in module.config.get('road_areas', [])]))
        # Split by module side so a corner cannot join unrelated mouths.
        corners = list(footprint.exterior.coords)
        sides = [LineString([a,b]) for a,b in zip(corners,corners[1:])]
        ports = [[p for side in sides for p in _parts(road.intersection(side), 'LineString')
                  if p.length > EPS] for road in aisles]
        bed_links = [tuple(n for n, aisle in enumerate(aisles)
                           if bed.boundary.intersection(aisle).length > EPS) for bed in beds]
        item = (footprint, beds, aisles, ports, tuple(unary_union(p) for p in ports), bed_links)
        if len(self._cache) >= 1024:
            self._cache.clear()
        self._cache[key] = item
        return item

    def evaluate(self, new_modules=(), *, include_roads=True):
        if not include_roads and self._obviously_blocked_opening(new_modules):
            self._trial = None
            return RoadCheck(opening_errors=[{'reason': '开口前方公共道路不足或被模块挤窄'}])
        added = [self._geometry(m) for m in new_modules]
        items = self.items + added
        self._trial = None
        added_bounds = [g[0].bounds for g in added]
        nodes = [(i, road, ports) for i, (_, _, roads, openings, _, _) in enumerate(items)
                 for road, ports in zip(roads, openings)]
        by_module = [[n for n, node in enumerate(nodes) if node[0] == i] for i in range(len(items))]
        tree = shapely.STRtree([g[0] for g in items])
        adjacency = [set() for _ in nodes]
        errors, external_ports = [], []
        local_ports = {}

        def error(node, opening, reason):
            errors.append(dict(module_index=nodes[node][0], aisle_index=node,
                               opening_index=opening, reason=reason))

        # A newly added module is the likeliest source of a rejected opening.
        order = sorted(range(len(nodes)), key=lambda n:nodes[n][0] < len(self.items))
        for n in order:
            i, road, ports = nodes[n]
            if not ports:
                error(n, -1, '内部通道没有配置开口')
            for k, port in enumerate(ports):
                cached = self._ports.get((n,k))
                if cached is not None:
                    external, links, bounds = cached
                    ax,ay,bx,by = bounds
                    affected = any(min(bx,x1)-max(ax,x0)>EPS and min(by,y1)-max(ay,y0)>EPS
                                   for x0,y0,x1,y1 in added_bounds)
                    if not affected:
                        adjacency[n].update(links)
                        external_ports.append((n,k,external))
                        local_ports[n,k] = cached
                        continue
                covered = []
                links = set()
                if port.intersection(self.site.boundary).length > EPS:
                    error(n, k, '开口朝向场地外，不能替代场内道路')
                for j in tree.query(port, predicate='intersects'):
                    if i == j:
                        continue
                    matches, closed = _opening_contact(port, items[j][0], items[j][4], self.width)
                    for local_index, shared in matches:
                        other = by_module[j][local_index]
                        adjacency[n].add(other)
                        adjacency[other].add(n)
                        links.add(other)
                        covered.append(shared)
                    if closed:
                        error(n, k, '开口被相邻墙面遮挡或直接连接净宽不足')
                if errors and not include_roads:
                    return RoadCheck(opening_errors=errors)
                external = port.difference(unary_union(covered)) if covered else port
                for segment in _parts(external, 'LineString'):
                    apron = _opening_apron(segment, items[i][0], self.width)
                    if not self.site.covers(apron):
                        error(n, k, '开口前方没有足够宽的场内公共道路')
                    for j in tree.query(apron, predicate='intersects'):
                        if i != j and apron.intersection(items[j][0]).area > EPS:
                            error(n, k, '开口前方公共道路被相邻模块挤窄')
                    if errors and not include_roads:
                        return RoadCheck(opening_errors=errors)
                external_ports.append((n, k, external))
                local_ports[n,k] = (external, links, _opening_apron(port,items[i][0],self.width).bounds)
        # Reject touching walls before doing expensive global geometry.
        if errors and not include_roads:
            return RoadCheck(opening_errors=errors)
        obstacles = self.obstacles.union(unary_union([g[0] for g in added])) if added else self.obstacles
        self._trial = (new_modules, added, obstacles, local_ports)

        public = self.site.difference(obstacles)
        radius = self.width/2-GRID_M/2  # Millimetre tolerance for exact-width corridors.
        cores = _parts(public.buffer(-radius, quad_segs=4))
        exits = [p for p in cores if p.buffer(radius+EPS, quad_segs=4).intersection(self.site.boundary).length > EPS]
        main = max(exits, key=lambda p:p.area) if exits else GeometryCollection()
        reachable = main.buffer(radius+EPS, quad_segs=4).intersection(public)
        contact_area = reachable.buffer(GRID_M)
        shapely.prepare(contact_area)
        reached = set()
        exterior = [(n,k,port) for n,k,port in external_ports if not port.is_empty]
        ports_array = np.asarray([p for _,_,p in exterior],dtype=object)
        covered = shapely.covers(contact_area, ports_array)
        missing = np.flatnonzero(~covered)
        covered[missing] = shapely.length(shapely.difference(ports_array[missing],contact_area)) <= GRID_M
        for (n,k,port), valid in zip(exterior,covered):
            if not valid:
                error(n, k, '开口未完整接入满足净宽的同一公共道路')
            else:
                reached.add(n)
        if errors and not include_roads:
            return RoadCheck(opening_errors=errors)
        pending = list(reached)
        while pending:
            for other in adjacency[pending.pop()] - reached:
                reached.add(other)
                pending.append(other)

        blocked, index = [], 0
        for i, (_, _, _, _, _, bed_links) in enumerate(items):
            for links in bed_links:
                if not any(by_module[i][n] in reached for n in links):
                    blocked.append(index)
                index += 1
        for n in set(range(len(nodes))) - reached:
            error(n, -1, '通道分区未接入主路')
        if not include_roads:
            return RoadCheck(blocked, errors)
        internal = unary_union([nodes[n][1] for n in reached])
        unused = public.difference(reachable)
        result = RoadCheck(blocked, errors, reachable.area+internal.area, unused.area, len(cores))
        if include_roads:
            for source, geometry in [('walkable',reachable),('module',internal),('nonroad_open_area',unused)]:
                for number, region in enumerate(_parts(geometry)):
                    result.roads.append(RoadArea(f'{source}_{number+1}',list(region.exterior.coords)[:-1],source,
                                                [list(r.coords)[:-1] for r in region.interiors]))
        return result

    def commit(self, new_modules):
        if self._trial is not None and self._trial[0] is new_modules:
            _, added, obstacles, *ports = self._trial
            self._ports = ports[0] if ports else {}
        else:
            added = [self._geometry(m) for m in new_modules]
            obstacles = self.obstacles.union(unary_union([g[0] for g in added]))
            self._ports = {}
        self.items.extend(added)
        self.obstacles = obstacles
        self._bounds = np.asarray([item[0].bounds for item in self.items], dtype=float).reshape(-1, 4)
        self._trial = None
