"""Optional final tidying. Feasibility and every selected bed take precedence.

Use actual module edges across all types, not just group bounding boxes. Move
groups as rigid units; configured internal geometry is never squeezed or scaled.
All proposals are disposable until the complete road and route audits pass.
"""
from collections import defaultdict
from copy import copy
from itertools import product
import logging
import time

from geometry import rects_violate_spacing
from position_finder import can_place
from road_connectivity import RoadNetwork
from circulation_paths import audit_bed_routes
from compute_budget import check_budget

EPS = .001
MAX_MOVING_GROUPS = 24
MAX_CANDIDATES = 64
MAX_SEARCH_STATES = 192
MAX_TIDY_SECONDS = 5.0
logger = logging.getLogger(__name__)


class TidyingUnavailable(Exception):
    """Optional tidying did not finish; do not cache this as a final result."""


def _check_deadline(deadline):
    check_budget()
    if time.monotonic() >= deadline:
        raise TimeoutError('Final tidying budget exhausted')


def _edges(group, axis):
    if axis == 0:
        return ({round(m.x, 3) for m in group.modules},
                {round(m.x + m.occ_length_m, 3) for m in group.modules})
    return ({round(m.y, 3) for m in group.modules},
            {round(m.y + m.occ_width_m, 3) for m in group.modules})


def _references(groups, index, axis):
    """Column lines come from rows above/below; row lines from columns beside.

    This avoids pulling a whole neighbouring column into a popular x position.
    Each group votes once per edge, regardless of how many rows it contains.
    """
    group = groups[index]
    cross = 1-axis
    start, size = group.rect[cross], group.rect[cross+2]
    maps = (defaultdict(set), defaultdict(set))
    for i, other in enumerate(groups):
        if i == index:
            continue
        a, length = other.rect[cross], other.rect[cross+2]
        if min(start+size, a+length) - max(start, a) > EPS:
            continue
        for mapping, values in zip(maps, _edges(other, axis)):
            for value in values:
                mapping[value].add(i)
    return maps


def _axis_score(group, axis, value, refs):
    shift = value-group.rect[axis]
    return sum(min(2, len(mapping.get(round(edge+shift, 3), ())))
               for mapping, edges in zip(refs, _edges(group, axis)) for edge in edges)


def _choices(group, axis, refs, neighbours, width):
    current = group.rect[axis]
    # A finishing operation should stay in the existing neighbourhood.
    reach = max(width, min(6.0, group.rect[axis+2]))
    values = {round(current, 3)}
    for mapping, edges in zip(refs, _edges(group, axis)):
        for anchor in mapping:
            for edge in edges:
                candidate = round(current+anchor-edge, 3)
                if abs(candidate-current) <= reach+EPS:
                    values.add(candidate)
    ranked = sorted(values, key=lambda v: (-_axis_score(group, axis, v, refs), abs(v-current), v))
    aligned = ranked[:4]
    # Joining a closed wall or leaving a landing can make an otherwise aligned
    # neighbour feasible. These are optional candidates, never acceptance rules.
    contact = set()
    for mapping in refs:
        for anchor in mapping:
            for edge in set.union(*_edges(group, axis)):
                for gap in (0, -width, width):
                    candidate = round(current+anchor-edge+gap, 3)
                    if abs(candidate-current) <= reach+EPS:
                        contact.add(candidate)
    contact.difference_update(aligned)
    nearby = sorted(contact, key=lambda v: (abs(v-current), v))
    boundaries = set()
    for other in neighbours:
        cross = 1-axis
        if min(group.rect[cross]+group.rect[cross+2], other.rect[cross]+other.rect[cross+2]) < max(group.rect[cross], other.rect[cross])-EPS:
            continue
        for end in (other.rect[axis]-group.rect[axis+2], other.rect[axis]+other.rect[axis+2]):
            if abs(end-current) <= reach+EPS:
                boundaries.add(round(end, 3))
    boundaries.difference_update(aligned)
    boundary_choices = sorted(boundaries, key=lambda v: (abs(v-current), v))[:2]
    return list(dict.fromkeys([*aligned, *boundary_choices, *nearby[:max(0, 3-len(boundary_choices))], round(current, 3)]))


def _positions(groups, index, width):
    group = groups[index]
    refs = [_references(groups, index, axis) for axis in (0, 1)]
    current_score = sum(_axis_score(group, axis, group.rect[axis], refs[axis]) for axis in (0, 1))
    neighbours = [g for i, g in enumerate(groups) if i != index]
    choices = [_choices(group, axis, refs[axis], neighbours, width) for axis in (0, 1)]
    def rank(position):
        x, y = position
        score = _axis_score(group, 0, x, refs[0]) + _axis_score(group, 1, y, refs[1])
        return (-score, abs(x-group.x)+abs(y-group.y), y, x)
    ranked = sorted(product(*choices), key=rank)
    gain = -rank(ranked[0])[0]-current_score if ranked else 0
    return ranked[:MAX_CANDIDATES], gain


def alignment_score(groups):
    return sum(_axis_score(group, axis, group.rect[axis], _references(groups, index, axis))
               for index, group in enumerate(groups) for axis in (0, 1))


def _moved(group, x, y):
    from layout_optimizer import _build_group_contents
    updated = copy(group)
    updated.x, updated.y = x, y
    updated.modules = []
    _build_group_contents(group._group_def, group.modules[0].config, x, y, group.rotated,
                          updated.modules, [], [])
    return updated


def _fits(group, others, site, reserved):
    if not can_place(group.rect, others, site, group._group_def):
        return False
    return not any(rects_violate_spacing(group.rect, rect, (0, 0)) for rect in reserved)


def _pack(groups, active, positions, site, reserved, width, deadline, reverse=False):
    proposed = list(groups)
    placed = [g for i, g in enumerate(groups) if i not in active]
    # Place larger units first. Remove the movable set together so expanding
    # one row's gap does not collide with the next row's *old* position.
    order = sorted(active, key=lambda i: (-groups[i].length_m*groups[i].width_m,
                                         -groups[i].y if reverse else groups[i].y, i))
    states = 0
    solutions = []
    def search(depth):
        nonlocal states
        _check_deadline(deadline)
        if depth == len(order):
            displacement = sum(abs(a.x-b.x)+abs(a.y-b.y) for a,b in zip(groups, proposed))
            solutions.append(((-alignment_score(proposed), displacement), list(proposed)))
            return
        if states >= MAX_SEARCH_STATES:
            return None
        index = order[depth]
        group = groups[index]
        network = RoadNetwork(site, [m for g in placed for m in g.modules], public_width_m=width)
        for x, y in positions[index]:
            _check_deadline(deadline)
            if states >= MAX_SEARCH_STATES:
                break
            rect_group = copy(group)
            rect_group.x, rect_group.y = x, y
            if not _fits(rect_group, placed, site, reserved):
                continue
            updated = _moved(group, x, y)
            states += 1
            if not network.evaluate(updated.modules, include_roads=False).valid:
                continue
            placed.append(updated)
            proposed[index] = updated
            search(depth+1)
            placed.pop()
            if states >= MAX_SEARCH_STATES or len(solutions) >= 12:
                break
        proposed[index] = group
        return None
    search(0)
    return [proposal for _, proposal in sorted(solutions, key=lambda item: item[0])[:3]]


def tidy_layout(original, *, fallback_on_error=True):
    try:
        return _tidy_layout(original)
    except TimeoutError as error:
        # Finishing is optional; an exhausted request budget must not discard
        # the already verified feasible layout.
        if not fallback_on_error:
            raise TidyingUnavailable('Tidying budget exhausted') from error
        return original
    except Exception as error:
        # Errors in this optional finishing stage must not discard a verified
        # layout. Retain diagnostics instead of turning it into a failed cart.
        logger.exception('Final tidying failed; retaining verified layout')
        if not fallback_on_error:
            raise TidyingUnavailable('Tidying failed') from error
        return original


def _tidy_layout(original):
    """Return an independently audited improvement or the original layout.

    Called for the final result only; recommendation capacity probes keep their
    fast feasibility path. Does not alter selection, module design or 1.2m limit.
    """
    if not original.success or original.unplaced or len(original.groups) < 2:
        return original
    deadline = time.monotonic() + MAX_TIDY_SECONDS
    groups = original.groups
    width = original.metrics['public_road_width_m']
    positions, gains = {}, {}
    # Keep one reference unit stationary to avoid an arbitrary whole-plan shift.
    anchor = max(range(len(groups)), key=lambda i: groups[i].length_m*groups[i].width_m)
    for index in range(len(groups)):
        _check_deadline(deadline)
        if index == anchor:
            continue
        positions[index], gains[index] = _positions(groups, index, width)
    active = set(sorted((i for i in gains if gains[i] > 0),
                        key=lambda i: (-gains[i], i))[:MAX_MOVING_GROUPS])
    if not active:
        return original
    site = original.site_polygon
    reserved = [tuple(c[k] for k in ('x', 'y', 'width', 'height'))
                for c in original.metrics.get('main_corridors', [])]
    before = alignment_score(groups)
    proposals = _pack(groups, active, positions, site, reserved, width, deadline)
    if not proposals:
        proposals = _pack(groups, active, positions, site, reserved, width, deadline, reverse=True)
    for proposed in proposals:
        _check_deadline(deadline)
        if alignment_score(proposed) <= before:
            continue
        modules = [m for group in proposed for m in group.modules]
        network = RoadNetwork(site, modules, public_width_m=width)
        checked = network.evaluate()
        if not checked.valid:
            continue
        paths = audit_bed_routes(network)
        _check_deadline(deadline)
        if not paths['route_access_valid']:
            continue
        from layout_optimizer import _build_group_contents, _compute_metrics
        beds = []
        for group in proposed:
            _build_group_contents(group._group_def, group.modules[0].config,
                                  group.x, group.y, group.rotated, [], beds, [])
        result = copy(original)
        result.groups, result.beds = proposed, beds
        result.roads = checked.roads + [road for road in original.roads if road.source == 'main']
        result.metrics = {**original.metrics, **_compute_metrics(proposed, beds, site, result.roads),
                          **paths, 'road_area_m2': round(checked.reachable_area, 3),
                          'unusable_open_area_m2': round(checked.unusable_area, 6),
                          'road_component_count': checked.component_count,
                          'alignment_score_before': before,
                          'alignment_score_after': alignment_score(proposed),
                          'alignment_moved_groups': sum(abs(a.x-b.x)+abs(a.y-b.y) > EPS
                                                        for a, b in zip(groups, proposed))}
        return result
    return original
