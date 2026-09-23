"""Geometry preflight shared by the form, cart and generation service.

Limits are verified capacities of the current greedy packing rules, not proofs of
the global optimum. Never use area / beds as a claim that a mixed cart will fit.
"""
from copy import deepcopy
from functools import lru_cache
import math
import threading

from config_loader import get_site_polygon, load_all_module_configs
from layout_optimizer import calculate_layout
from module_selector import fit_addition, select_modules, build_recommendation_profile


_layout_locks = [threading.Lock() for _ in range(16)]


@lru_cache(maxsize=32)
def _layout(selection, site):
    return calculate_layout(dict(selection), site, allow_decompose=True, road_check=True)


@lru_cache(maxsize=16)
def _final_layout(selection, site):
    from layout_alignment import tidy_layout
    # lru_cache does not store exceptions: a later request may retry finishing
    # with a fresh budget rather than permanently reusing a timed-out fallback.
    return tidy_layout(_layout(selection, site), fallback_on_error=False)


def checked_layout(selection, site, finalize=False, **kwargs):
    # The cart serializes A..G; use the same order for recommendation and generation.
    key = (tuple(sorted(selection.items())), tuple(tuple(p) for p in site))
    if sum(selection.values()) > 256:
        result = calculate_layout(dict(key[0]), key[1], allow_decompose=True, road_check=True)
        if finalize:
            from layout_alignment import tidy_layout
            return tidy_layout(result)
        return result
    # lru_cache alone permits simultaneous misses to calculate the same layout.
    with _layout_locks[hash(key) % len(_layout_locks)]:
        if not finalize:
            return deepcopy(_layout(*key))
        from layout_alignment import TidyingUnavailable
        try:
            result = _final_layout(*key)
        except TidyingUnavailable:
            result = _layout(*key)
        return deepcopy(result)


def validate_dimensions(length, width):
    if not all(math.isfinite(float(v)) and 0 < float(v) <= 2000 for v in (length, width)):
        raise ValueError('场地长宽必须大于 0 且不超过 2000 米')


@lru_cache(maxsize=24)
def site_capacity(length, width):
    """Largest verified bed count among homogeneous layouts under current rules."""
    validate_dimensions(length, width)
    site = get_site_polygon(length_m=length, width_m=width)
    area = length * width
    configs = load_all_module_configs()
    options = []
    for code, cfg in configs.items():
        dimensions = cfg['dimensions']
        module_area = dimensions['length_mm'] * dimensions['width_mm'] / 1e6
        upper = int(min(area / module_area, area / 3 / cfg['beds'], 2000 / cfg['beds']))
        selected = fit_addition({}, code, upper, site, checked_layout)
        options.append((sum(selected.values()) * cfg['beds'], selected))
    beds, selected = max(options, key=lambda option: option[0])
    return {'maxEvacuees': beds, 'capacitySelection': selected,
            'capacityBasis': '当前排布规则已验证容量（非全局最优值）'}


def check_cart(length, width, selected, changed_module=None):
    validate_dimensions(length, width)
    site = get_site_polygon(length_m=length, width_m=width)
    result = checked_layout(selected, site)
    if result.success and not result.unplaced:
        return {'isValid': True, 'totalQuantity': sum(selected.values())}
    if changed_module and changed_module in selected:
        base = {code: qty for code, qty in selected.items() if code != changed_module}
        base_result = checked_layout(base, site)
        if base_result.success and not base_result.unplaced:
            fitted = fit_addition(base, changed_module, selected[changed_module], site, checked_layout)
        else:
            fitted = None
    else:
        fitted = None
    if fitted is None:
        fitted = {}
        for code, qty in selected.items():
            fitted = fit_addition(fitted, code, qty, site, checked_layout)
    maximum = sum(fitted.values())
    qualifier = f'保留其他模块、调整模块{changed_module}时' if changed_module else '按当前模块组合试排'
    return {'isValid': False, 'maxModules': maximum, 'fittingSelection': fitted,
            'message': f'当前场地尺寸最大模块数量为 {maximum}（{qualifier}，按当前排布规则）。请减少模块或增大场地。'}


def preflight(evacuees, length, width, days, strategy_key=None, selected_modules=None,
              changed_module=None):
    from service_adapter import normalize_selected_modules, validate_selection_rules, _STRATEGY_PREF
    validate_dimensions(length, width)
    if selected_modules is not None:
        selected = normalize_selected_modules(selected_modules)
        issues = validate_selection_rules(selected)
        if issues:
            raise ValueError('; '.join(issues))
        return check_cart(length, width, selected, changed_module)
    # Handle population overflow before profile's area-per-person exception.
    if evacuees > length * width / 3:
        capacity = site_capacity(length, width)
        return dict(capacity, isValid=False,
                    message=f'当前场地按现有排布规则最大可设定人数为 {capacity["maxEvacuees"]} 人，请减少人数或增大场地。')
    profile = build_recommendation_profile(evacuees, length * width, days)
    if strategy_key in _STRATEGY_PREF:
        profile['module_preferences'] = _STRATEGY_PREF[strategy_key]
    site = get_site_polygon(length_m=length, width_m=width)
    selected = select_modules(evacuees, site, profile, layout_runner=checked_layout)
    configs = load_all_module_configs()
    beds = sum(configs[code]['beds'] * qty for code, qty in selected.items())
    if beds >= evacuees:
        return {'isValid': True, 'selectedModules': selected, 'totalBeds': beds,
                'message': f'场地试排通过，可安排 {beds} 床。'}
    capacity = dict(site_capacity(length, width))
    # A verified mixed layout can exceed any of the homogeneous trials.
    if beds > capacity['maxEvacuees']:
        capacity.update(maxEvacuees=beds, capacitySelection=selected)
    # If a denser type fits, the input is valid; strategy remains a preference.
    if capacity['maxEvacuees'] >= evacuees:
        return dict(capacity, isValid=True, message='场地可容纳目标人数，推荐时需调整模块组合。')
    return dict(capacity, isValid=False,
                message=f'当前场地按现有排布规则最大可设定人数为 {capacity["maxEvacuees"]} 人，请减少人数或增大场地。')
