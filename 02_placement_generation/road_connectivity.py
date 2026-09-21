"""Validate real aisle openings and public-road clearance, separately.

Only configured aisles are traversable inside modules. An opening against a
wall cannot be rescued by a route through another opening around that wall.
"""
from dataclasses import dataclass, field
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

    def _geometry(self, module):
        key = (id(module.config), module.x, module.y, module.rotation, module.mirror)
        if key in self._cache:
            return self._cache[key]

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
        self._trial = None
