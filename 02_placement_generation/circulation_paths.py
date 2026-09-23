"""Project path policy, not statutory evacuation-compliance verification."""
import math
import numpy as np
import shapely
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import box
from shapely.ops import unary_union

PUBLIC_WIDTH_M = 1.2
NEIGHBOUR_RADIUS_M = 20.0
MAX_EXTRA_PATH_M = 20.0
MAX_REPAIR_ROUNDS = 4
MAX_GRAPH_NODES = 160000


def route_distances(domain, points, extra_x=(), extra_y=(), distance_limit=math.inf):
    """Shortest orthogonal paths on a compressed geometry-checked graph.

    Each edge is covered by walkable geometry: no wall crossings or raster
    corner shortcuts. This is not an exact continuous Euclidean geodesic.
    """
    if not points:
        return np.empty((0, 0))
    if len(points) > 2000:
        raise ValueError('单次路径校验最多支持 2000 个床位，请分区生成')
    vertices = shapely.get_coordinates(domain)
    xs = sorted(set(round(float(x), 6) for x in [*vertices[:, 0], *extra_x, *(p[0] for p in points)]))
    ys = sorted(set(round(float(y), 6) for y in [*vertices[:, 1], *extra_y, *(p[1] for p in points)]))
    nx, ny = len(xs), len(ys)
    if nx * ny > MAX_GRAPH_NODES:
        raise ValueError('路径校验规模超出当前计算上限，请减少模块数量')
    coordinates = np.stack(np.meshgrid(xs, ys), axis=-1).reshape(-1, 2)
    ids = np.arange(nx * ny).reshape(ny, nx)
    starts = np.concatenate((ids[:, :-1].ravel(), ids[:-1, :].ravel()))
    ends = np.concatenate((ids[:, 1:].ravel(), ids[1:, :].ravel()))
    # The walkable geometry is already snapped to millimetres. Reset only its
    # precision model before applying the much smaller numerical tolerance:
    # buffering at 1e-7 on a .001 precision grid can collapse valid aisles.
    covered_domain = shapely.set_precision(domain, 0).buffer(1e-7, join_style=2)
    shapely.prepare(covered_domain)
    edges = shapely.linestrings(np.stack((coordinates[starts], coordinates[ends]), axis=1))
    keep = shapely.covers(covered_domain, edges)
    starts, ends = starts[keep], ends[keep]
    lengths = np.linalg.norm(coordinates[starts] - coordinates[ends], axis=1)
    # Same geometry-checked edges; compiled sparse shortest paths avoid millions
    # of Python heap operations. Bound the temporary distance matrix to 16 rows.
    graph = csr_matrix((np.concatenate((lengths, lengths)),
                        (np.concatenate((starts, ends)), np.concatenate((ends, starts)))),
                       shape=(len(coordinates), len(coordinates)))
    xi, yi = {v: i for i, v in enumerate(xs)}, {v: i for i, v in enumerate(ys)}
    point_ids = [yi[round(p[1], 6)] * nx + xi[round(p[0], 6)] for p in points]
    sources, inverse = np.unique(point_ids, return_inverse=True)
    distances = np.empty((len(sources), len(points)))
    for offset in range(0, len(sources), 16):
        # The module is also imported standalone by geometry tests.
        from compute_budget import check_budget
        check_budget()
        batch = dijkstra(graph, directed=True, indices=sources[offset:offset + 16],
                         limit=distance_limit)
        distances[offset:offset + 16] = batch[:, point_ids]
    return distances[inverse]


def audit_bed_routes(network):
    """Bedside access points use real aisles; public space needs 1.2m width.

    Internal aisles retain configured geometry. Actual exits are not supplied,
    so this does not claim to check distances to safety exits.
    """
    radius = PUBLIC_WIDTH_M / 2 - .0005
    public = network.site.difference(network.obstacles)
    areas = [public.buffer(-radius, join_style=2)]
    points, centres, extra_x, extra_y = [], [], [], []
    for footprint, beds, aisles, ports, _, _ in network.items:
        areas.extend(aisles)
        for aisle in aisles:
            x, y = aisle.representative_point().coords[0]
            extra_x.append(x)
            extra_y.append(y)
        for mouths in ports:
            for port in mouths:
                # Bridge each checked mouth to the public centre space, but
                # never turn another module's wall into walkable space.
                areas.append(port.buffer(radius + .001, cap_style=2).intersection(public))
        for bed in beds:
            contacts = [bed.boundary.intersection(aisle) for aisle in aisles]
            contact = max(contacts, key=lambda item: item.length, default=None)
            if contact is None or contact.length < 1e-6:
                return {'route_access_valid': False, 'route_error': '床位缺少通道接入点', 'route_failures': []}
            point = contact.interpolate(.5, normalized=True)
            points.append((point.x, point.y))
            centres.append((bed.centroid.x, bed.centroid.y))
    # The cutoff is based on access-point distance, which may exceed the bed
    # centre radius by the dimensions of both beds.
    try:
        distances = route_distances(unary_union(areas), points, extra_x, extra_y)
    except ValueError as error:
        return {'route_access_valid': False, 'route_error': str(error), 'route_failures': []}
    failures, count, maximum_extra = [], 0, 0.0
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            if math.dist(centres[i], centres[j]) > NEIGHBOUR_RADIUS_M:
                continue
            count += 1
            distance = float(distances[i, j])
            direct = math.dist(points[i], points[j])
            extra = distance - direct
            if math.isfinite(extra):
                maximum_extra = max(maximum_extra, extra)
            if extra > MAX_EXTRA_PATH_M + .001:
                failures.append({'bed_a': i + 1, 'bed_b': j + 1,
                                 'from': points[i], 'to': points[j],
                                 'direct_m': round(direct, 3),
                                 'path_m': round(distance, 3) if math.isfinite(distance) else None})
    failures.sort(key=lambda f: (f['path_m'] or 1e9) - f['direct_m'], reverse=True)
    return {'route_access_valid': not failures, 'route_neighbour_radius_m': NEIGHBOUR_RADIUS_M,
            'route_max_extra_allowed_m': MAX_EXTRA_PATH_M, 'route_metric': 'rectilinear_walkable_graph',
            'route_pairs_checked': count, 'route_failures_count': len(failures),
            'route_max_extra_m': round(maximum_extra, 3), 'route_failures': failures[:20],
            'evacuation_distance_checked': False}


def _shape(rect):
    x, y, width, height = rect
    return box(x, y, x + width, y + height)


def repair_corridor(site_polygon, failures, existing):
    """Add a full-span cross-aisle near the worst detour (rectangle input only).

    This is a bounded repair heuristic. Actual paths are the acceptance rule,
    so already adequate natural aisles need no extra periodic reserved strips.
    """
    xs, ys = zip(*site_polygon)
    left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
    if set(map(tuple, site_polygon)) != {(left, bottom), (right, bottom), (right, top), (left, top)}:
        return None
    width = PUBLIC_WIDTH_M
    for failure in failures:
        a, b = failure['from'], failure['to']
        vertical = abs(a[1] - b[1]) >= abs(a[0] - b[0])
        for along_y in (vertical, not vertical):
            if along_y:
                x = min(right - 2 * width, max(left + width, (a[0] + b[0]) / 2 - width / 2))
                candidate = (round(x, 3), bottom, width, top - bottom)
            else:
                y = min(top - 2 * width, max(bottom + width, (a[1] + b[1]) / 2 - width / 2))
                candidate = (left, round(y, 3), right - left, width)
            shape = _shape(candidate)
            if not box(left, bottom, right, top).covers(shape):
                continue
            if not any(shape.intersection(_shape(old)).area > min(shape.area, _shape(old).area) * .5 for old in existing):
                return candidate
    return None
