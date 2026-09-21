"""Road connectivity on the same millimetre geometry serialized by the API.

The configured model treats site minus bed footprints as potential circulation.
A usable component must share an edge with the site boundary; corner contact
does not connect components. Walls, doors and minimum aisle widths are not
present in the current configuration and are not inferred from artwork.
"""
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union

from geometry import RoadArea

GRID_M = 0.001
CONTACT_EPS_M = 1e-7


def _polygon(points):
    shape = Polygon([(round(x, 3), round(y, 3)) for x, y in points])
    if not shape.is_valid:
        raise ValueError('场地或床位多边形无效，无法校验道路连通性')
    return shapely.set_precision(shape, GRID_M)


@dataclass
class RoadCheck:
    blocked_indices: list
    reachable_area: float
    isolated_area: float
    component_count: int
    roads: list


class RoadNetwork:
    """Cache the existing bed union once per placement step, not per candidate."""

    def __init__(self, site_polygon, beds, *, site_shape=None):
        self.site = site_shape if site_shape is not None else _polygon(site_polygon)
        self.polygons = np.asarray([_polygon(b.polygon_m) for b in beds], dtype=object)
        self.obstacles = unary_union(self.polygons)
        self.boundaries = shapely.boundary(self.polygons)
        self._trial = None

    def evaluate(self, new_beds=(), *, include_roads=True):
        added = np.asarray([_polygon(b.polygon_m) for b in new_beds], dtype=object)
        obstacles = self.obstacles.union(unary_union(added)) if len(added) else self.obstacles
        free = self.site.difference(obstacles)
        parts = ([free] if free.geom_type == 'Polygon' and not free.is_empty
                 else [p for p in getattr(free, 'geoms', []) if p.geom_type == 'Polygon' and not p.is_empty])
        reachable, isolated = [], []
        for part in parts:
            (reachable if part.boundary.intersection(self.site.boundary).length > CONTACT_EPS_M
             else isolated).append(part)
        boundary = unary_union(reachable).boundary if reachable else LineString()
        boundaries = np.concatenate((self.boundaries, shapely.boundary(added))) if len(added) else self.boundaries
        contacts = shapely.length(shapely.intersection(boundaries, boundary))
        blocked = np.flatnonzero(contacts <= CONTACT_EPS_M).tolist()
        self._trial = (new_beds, added, obstacles)
        roads = []
        if include_roads:
            for source, regions in [('walkable', reachable), ('isolated_open_area', isolated)]:
                for index, region in enumerate(regions):
                    roads.append(RoadArea(
                        name=f'{source}_{index + 1}', source=source,
                        polygon_m=list(region.exterior.coords)[:-1],
                        holes_m=[list(ring.coords)[:-1] for ring in region.interiors],
                    ))
        return RoadCheck(blocked, sum(p.area for p in reachable), sum(p.area for p in isolated), len(parts), roads)

    def commit(self, new_beds):
        """Reuse the accepted candidate's union instead of rebuilding all old beds."""
        if self._trial is not None and self._trial[0] is new_beds:
            _, added, obstacles = self._trial
        else:
            added = np.asarray([_polygon(b.polygon_m) for b in new_beds], dtype=object)
            obstacles = self.obstacles.union(unary_union(added))
        self.polygons = np.concatenate((self.polygons, added))
        self.boundaries = np.concatenate((self.boundaries, shapely.boundary(added)))
        self.obstacles = obstacles
        self._trial = None
