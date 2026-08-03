import math
from copy import deepcopy
from arrangement_rules import generate_group_arrangement, calculate_aisle_width
from layout_calculator import calculate_layout
from auto_retry_layout import calculate_smart_layout_with_retry

# 模块定义字典 (为保持独立性，从 core_calculations 复制过来)
modules = {
    # 注意：length对应x轴（绘图中的长度），width对应y轴（绘图中的宽度）
    'A': {'type':'舒适型', 'beds':3, 'cost':4273, 'priority':1, 'length':5600, 'width':5600, 'name':'A', 'visual_ready': True},
    'B': {'type':'舒适型', 'beds':2, 'cost':2298, 'priority':2, 'length':4000, 'width':2000, 'name':'B', 'visual_ready': True},
    'C': {'type':'经济型', 'beds':3, 'cost':1035, 'priority':1, 'length':4500, 'width':2500, 'name':'C', 'visual_ready': True},
    'D': {'type':'经济型', 'beds':2, 'cost':690, 'priority':2, 'length':3600, 'width':1800, 'name':'D', 'visual_ready': True},
    'E': {'type':'均衡型', 'beds':3, 'cost':2133, 'priority':1, 'length':3000, 'width':3800, 'name':'E', 'visual_ready': False},
    'F': {'type':'均衡型', 'beds':3, 'cost':3373, 'priority':2, 'length':3000, 'width':5500, 'name':'F', 'visual_ready': False},
    'G': {'type':'均衡型', 'beds':4, 'cost':3384, 'priority':3, 'length':3200, 'width':4000, 'name':'G', 'visual_ready': False},
}

COMBINATION_LIMIT = 8000  # 安全阀：最多找8千种组合，避免主程序长时间卡在理论组合搜索
MAX_LAYOUT_VALIDATIONS_PER_POOL = 24  # 每个候选池最多验证24个物理布局，降低卡顿
AUTO_FILL_GROUP_LIMIT = 12  # 布局成功后最多追加12个补空群组，避免二次补空拖慢主流程


def _build_runtime_positions(groups, aisle):
    """把已放置群组转换为运行时碰撞检测所需的坐标信息。"""
    from smart_layout_optimizer import calculate_group_dimensions

    current_positions = []
    for group in groups:
        if 'position' not in group:
            continue
        final_width, final_height = calculate_group_dimensions(
            group,
            rotated=group.get('rotated', False),
            aisle=aisle
        )
        current_positions.append({
            'x': group['position'][0],
            'y': group['position'][1],
            'length': final_width,
            'width': final_height,
            'height': final_height,
            'module_type': group['module']['name'],
            'group_type': group.get('group_type')
        })
    return current_positions


def _increment_module_count(combo_modules, module_name, add_count):
    """把自动补空追加的模块数量同步回最终方案。"""
    module_info, current_count = combo_modules.get(module_name, (modules[module_name], 0))
    combo_modules[module_name] = (module_info, current_count + add_count)


def _try_auto_fill_remaining_space(best_combo, all_groups, all_length, all_width, aisle, site_area_m2, fill_mode):
    """
    在主布局成功后，继续尝试用小群组补剩余空间。
    目标不是全局最优，而是把明显能补上的空洞尽量补掉。
    """
    if not fill_mode or not all_groups:
        return 0

    from smart_layout_optimizer import calculate_group_dimensions
    from module_a_layout_handler import find_module_a_position_with_priority
    from module_b_spacing_handler import find_module_b_position

    filler_templates = [
        {
            'module': modules['A'],
            'rows': 2,
            'cols': 1,
            'group_type': 'A_group_one',
            'layout_priority': 'flexible',
            'vertical_gap': 0.0,
            'horizontal_gap': 0.0,
            'module_count': 2,
        },
        {
            'module': modules['B'],
            'rows': 1,
            'cols': 2,
            'group_type': 'B_row_pair',
            'layout_priority': 'gap_fill',
            'vertical_gap': 0.0,
            'horizontal_gap': 0.0,
            'module_count': 2,
        },
        {
            'module': modules['B'],
            'rows': 1,
            'cols': 1,
            'group_type': 'B_single',
            'layout_priority': 'gap_fill',
            'vertical_gap': 0.0,
            'horizontal_gap': 0.0,
            'module_count': 1,
        },
    ]

    added_groups = 0
    for _ in range(AUTO_FILL_GROUP_LIMIT):
        current_positions = _build_runtime_positions(all_groups, aisle)
        best_option = None

        for template in filler_templates:
            candidate_group = deepcopy(template)
            module_name = candidate_group['module']['name']

            if module_name == 'A':
                best_x, best_y, rotated, fits = find_module_a_position_with_priority(
                    candidate_group, current_positions, all_length, all_width, 0.0
                )
            elif module_name == 'B':
                best_x, best_y, rotated, fits = find_module_b_position(
                    candidate_group, current_positions, all_length, all_width, 2.0
                )
            else:
                continue

            if not fits:
                continue

            final_width, final_height = calculate_group_dimensions(
                candidate_group, rotated=rotated, aisle=aisle
            )
            candidate_score = (
                final_width * final_height,
                -best_y,
                -best_x,
            )

            if best_option is None or candidate_score > best_option['score']:
                best_option = {
                    'group': candidate_group,
                    'x': best_x,
                    'y': best_y,
                    'rotated': rotated,
                    'score': candidate_score,
                    'area_m2': final_width * final_height,
                }

        if best_option is None:
            break

        group_to_add = best_option['group']
        group_to_add['position'] = (best_option['x'], best_option['y'])
        group_to_add['rotated'] = best_option['rotated']
        all_groups.append(group_to_add)

        module_name = group_to_add['module']['name']
        added_units = group_to_add.get('module_count', group_to_add.get('rows', 1) * group_to_add.get('cols', 1))
        _increment_module_count(best_combo['modules'], module_name, added_units)
        best_combo['total_beds'] += group_to_add['module']['beds'] * added_units
        best_combo['total_cost'] += group_to_add['module']['cost'] * added_units
        best_combo['total_area_m2'] = best_combo.get('total_area_m2', 0.0) + best_option['area_m2']
        added_groups += 1

    if added_groups > 0 and site_area_m2 > 0:
        best_combo['fill_ratio'] = min(1.0, best_combo.get('total_area_m2', 0.0) / site_area_m2)

    return added_groups

def _calculate_module_metrics(all_modules):
    """为每个模块计算人均指标"""
    for name, mod in all_modules.items():
        # 兼容新旧属性名称
        if 'length' in mod and 'width' in mod:
            # 新格式：使用length和width
            area = mod['width'] * mod['length']
        else:
            # 旧格式：使用width和height
            area = mod['width'] * mod.get('height', mod['width'])
        
        beds = mod['beds']
        if beds > 0:
            mod['cost_per_person'] = mod['cost'] / beds
            mod['space_per_person'] = area / beds
        else:
            mod['cost_per_person'] = float('inf')
            mod['space_per_person'] = float('inf')
    return all_modules

def _filter_and_sort_candidates(all_modules, module_preferences):
    """
    根据空间类型偏好对模块进行排序。
    """
    pruned_candidates = [module for module in all_modules.values() if module.get('visual_ready', True)]
    if not pruned_candidates:
        pruned_candidates = list(all_modules.values())
    if not pruned_candidates:
        raise ValueError("当前模块库为空，无法生成候选模块。")

    def get_sort_key(module):
        preference_rank = module_preferences.index(module['type']) if module['type'] in module_preferences else 99
        # 在同一空间类型偏好下，优先更高床位和更紧凑的模块，减少后续组合与落位压力。
        return (
            preference_rank,
            module['priority'],
            -module['beds'],
            module['space_per_person'],
            module['length'] * module['width']
        )

    pruned_candidates.sort(key=get_sort_key)
    
    print("--- 模块偏好排序完成 ---")
    print(f"可用模块: {[m['name'] for m in pruned_candidates]}")
    return pruned_candidates


def _groups_fit_field_individually(selection_modules, all_length, all_width):
    """
    预检查每个群组是否至少能以某个方向放入场地。
    这一步比完整布局便宜，用来提前跳过明显无解的大候选。
    """
    from smart_layout_optimizer import calculate_group_dimensions

    for _, (module, count) in selection_modules.items():
        groups = generate_group_arrangement(module['name'], count)
        for group in groups:
            group_count = group.get('count', 1)
            for _ in range(group_count):
                group_copy = {k: v for k, v in group.items() if k != 'count'}
                normal_length, normal_width = calculate_group_dimensions(group_copy, rotated=False)
                rotated_length, rotated_width = calculate_group_dimensions(group_copy, rotated=True)
                normal_fits = normal_length <= all_length and normal_width <= all_width
                rotated_fits = rotated_length <= all_length and rotated_width <= all_width
                if not normal_fits and not rotated_fits:
                    return False

    return True


def _build_candidate_pools(candidates, module_preferences):
    """
    按排序后的候选模块逐级放开。
    先尝试最高优先级模块，再逐步加入同类型次优模块和次一级类型模块。
    """
    pools = []
    seen_signatures = set()

    for prefix_count in range(1, len(candidates) + 1):
        pool = candidates[:prefix_count]
        signature = tuple(module['name'] for module in pool)
        if signature in seen_signatures:
            continue

        pools.append({
            'allowed_types': tuple(sorted({module['type'] for module in pool})),
            'modules': pool
        })
        seen_signatures.add(signature)

    return pools

def _find_combinations_with_limit(candidates, N, site_area_m2, fill_mode=True):
    """基于场地面积约束的回溯搜索。自动推荐默认持续搜索到尽量铺满平面。"""
    valid_combinations = []
    allowed_over_provision = max(
        max((module['beds'] for module in candidates), default=0),
        math.ceil(N * 0.15)
    )
    near_full_ratio = 0.985
    candidate_areas_m2 = []
    for module in candidates:
        if 'length' in module and 'width' in module:
            candidate_areas_m2.append(module['width'] * module['length'] / 1000000)
        else:
            candidate_areas_m2.append(module['width'] * module.get('height', module['width']) / 1000000)
    
    # 预计算未来最小面积需求，用于启发式剪枝
    min_area_per_bed = [0] * len(candidates)
    if len(candidates) > 0:
        min_area_per_bed[-1] = candidates[-1]['space_per_person'] / 1000000
        for i in range(len(candidates) - 2, -1, -1):
            min_area_per_bed[i] = min(candidates[i]['space_per_person'] / 1000000, min_area_per_bed[i+1])

    def backtrack(start_index, current_cost, current_beds, current_area, current_combination):
        # 安全阀
        if len(valid_combinations) >= COMBINATION_LIMIT:
            return

        # 场地面积剪枝
        if current_area > site_area_m2:
            return

        # 手动非铺满模式时，仍保留超配剪枝；自动铺满模式下允许继续扩展到接近场地上限。
        if not fill_mode and current_beds > N + allowed_over_provision:
            return

        # 启发式剪枝：预估未来最小面积
        if start_index < len(candidates) and current_beds < N:
            beds_needed = N - current_beds
            min_future_area = beds_needed * min_area_per_bed[start_index]
            if current_area + min_future_area > site_area_m2:
                return

        # 找到可行解
        if current_beds >= N:
            valid_combinations.append({
                'modules': current_combination.copy(),
                'total_cost': current_cost,
                'total_beds': current_beds,
                'total_area_m2': current_area,
            })

            if len(valid_combinations) >= COMBINATION_LIMIT:
                return

            # 自动铺满模式下继续搜索更高填充率的组合，直到接近场地上限。
            if not fill_mode or current_area >= site_area_m2 * near_full_ratio:
                return

        # 递归终止
        if start_index == len(candidates):
            return

        module = candidates[start_index]
        
        # 通过床位需求和场地面积共同控制搜索上限。
        beds_needed = max(0, N - current_beds)
        beds_limit = int((beds_needed + allowed_over_provision + module['beds'] - 1) // module['beds'])

        module_area = candidate_areas_m2[start_index]
        remaining_area = max(0, site_area_m2 - current_area)
        area_limit = int(remaining_area // module_area) if module_area > 0 else 0

        if fill_mode:
            max_count = max(0, min(area_limit, 200))
        else:
            max_count = max(0, min(beds_limit, area_limit, 200))
        
        print(f"模块{module['name']}: 床位限制={beds_limit}, 面积限制={area_limit}, 最终上限={max_count}")

        for count in range(max_count, -1, -1):
            # 检查模块C和模块A的数量限制
            if module['name'] == 'C' and count % 2 != 0:
                continue
            if module['name'] == 'A' and count % 2 != 0:
                continue

            if count > 0:
                current_combination[module['name']] = (module, count)
            
            backtrack(
                start_index + 1,
                current_cost + count * module['cost'],
                current_beds + count * module['beds'],
                current_area + count * module_area,
                current_combination
            )
            
            if len(valid_combinations) >= COMBINATION_LIMIT: # 提前退出
                return

            if count > 0:
                del current_combination[module['name']]

    print(f"--- 开始回溯搜索 (上限: {COMBINATION_LIMIT} 组合) ---")
    backtrack(0, 0, 0, 0, {})
    print(f"--- 回溯搜索结束, 共找到 {len(valid_combinations)} 个理论可行组合 ---")
    return valid_combinations


def _build_layout_result(best_combo, all_groups, solution_level='target'):
    """统一构造最终返回结果，便于保底方案复用。"""
    final_selection = []
    for mod_name, (mod, count) in best_combo['modules'].items():
        final_selection.append({'module': mod, 'quantity': count})

    return {
        'modules': final_selection,
        'total_cost': best_combo['total_cost'],
        'total_beds': best_combo['total_beds'],
        'groups': all_groups,
        'fill_ratio': best_combo.get('fill_ratio', 0.0),
        'final_score': best_combo.get('final_score', 0.0),
        'solution_level': solution_level,
    }


def _is_better_fallback(candidate_combo, best_combo, N):
    """比较两个可落地保底方案，优先更高填充率。"""
    if best_combo is None:
        return True

    candidate_key = (
        candidate_combo.get('fill_ratio', 0.0),
        candidate_combo.get('final_score', 0.0),
        -max(0, candidate_combo.get('total_beds', 0) - N),
    )
    best_key = (
        best_combo.get('fill_ratio', 0.0),
        best_combo.get('final_score', 0.0),
        -max(0, best_combo.get('total_beds', 0) - N),
    )
    return candidate_key > best_key

def _rank_combinations(combinations, N, module_preferences, site_area_m2):
    """对组合进行排序，核心目标为尽量填满平面，其次满足人数，再匹配模块舒适度。"""
    if not combinations:
        return []

    # 为避免除零错误，过滤掉床位数为0的无效组合
    valid_combinations = [c for c in combinations if c['total_beds'] > 0]
    if not valid_combinations:
        return []

    for combo in valid_combinations:
        # 1. 平面填充率：当前版本的主目标是尽量把平面填满。
        total_area = combo.get('total_area_m2', 0)
        fill_ratio = min(1.0, total_area / site_area_m2) if site_area_m2 > 0 else 0

        # 2. 床位匹配度：仍需要控制超配，但优先级低于填充率。
        extra_beds = max(0, combo['total_beds'] - N)
        bed_match_score = 1 / (1 + extra_beds)

        # 3. 类型匹配度：人数优先、时间次之生成的模块偏好在此体现。
        preference_score_sum = 0
        preference_weight_sum = 0
        for item in combo['modules'].values():
            module = item[0]
            count = item[1]
            preference_rank = module_preferences.index(module['type']) if module['type'] in module_preferences else len(module_preferences)
            module_preference_score = max(0.0, 1 - preference_rank / max(1, len(module_preferences)))
            preference_score_sum += module_preference_score * module['beds'] * count
            preference_weight_sum += module['beds'] * count

        preference_match_score = (
            preference_score_sum / preference_weight_sum if preference_weight_sum > 0 else 0
        )

        final_score = (
            0.75 * fill_ratio +
            0.15 * preference_match_score +
            0.10 * bed_match_score
        )

        combo['fill_ratio'] = fill_ratio
        combo['preference_match_score'] = preference_match_score
        combo['bed_match_score'] = bed_match_score
        combo['final_score'] = final_score

    ranked = sorted(
        valid_combinations,
        key=lambda combo: (
            combo['final_score'],
            combo['fill_ratio'],
            -max(0, combo['total_beds'] - N),
            combo['preference_match_score']
        ),
        reverse=True
    )
    print(f"--- 加权评分完成, 已按优先级完成排序 ---")
    return ranked


def _search_candidate_pools(candidate_pools, module_preferences, N, site_area_m2,
                           all_length, all_width, aisle, fill_mode=True,
                           minimum_fill_to_stop=0.90):
    """
    遍历候选池并尝试返回第一个可落地方案。
    fill_mode=True 时优先铺满；False 时优先找到稳定可落地的方案。
    """
    best_feasible_result = None
    best_feasible_combo = None

    for pool_index, pool_info in enumerate(candidate_pools, start=1):
        pool_candidates = pool_info['modules']
        print(f"--- 开始尝试候选池 {pool_index}: {pool_info['allowed_types']} ---")
        print(f"候选模块: {[module['name'] for module in pool_candidates]}")

        valid_combinations = _find_combinations_with_limit(
            pool_candidates, N, site_area_m2, fill_mode=fill_mode
        )
        if not valid_combinations:
            print("当前候选池未找到满足人数的理论组合，继续放开下一层偏好。")
            continue

        ranked_combinations = _rank_combinations(valid_combinations, N, module_preferences, site_area_m2)
        if not ranked_combinations:
            continue

        print("--- 候选方案排序前5名 ---")
        for idx, combo in enumerate(ranked_combinations[:5], start=1):
            print(
                f"候选{idx}: 填充率={combo['fill_ratio']:.3f}, "
                f"总床位={combo['total_beds']}, "
                f"偏好匹配={combo['preference_match_score']:.3f}, "
                f"总分={combo['final_score']:.3f}"
            )

        for candidate_index, best_combo in enumerate(ranked_combinations[:MAX_LAYOUT_VALIDATIONS_PER_POOL], start=1):
            print(f"--- 正在验证候选方案 {candidate_index} ---")
            print(
                f"总床位: {best_combo['total_beds']}, 总成本: {best_combo['total_cost']:.2f}元, "
                f"填充率: {best_combo['fill_ratio']:.3f}"
            )
            for mod_name, (mod, count) in best_combo['modules'].items():
                print(f"模块{mod_name}: {count}个 (每个{mod['beds']}床位, 成本{mod['cost']}元)")

            if not _groups_fit_field_individually(best_combo['modules'], all_length, all_width):
                print("候选方案跳过：至少有一个群组在任何方向下都无法放入场地。")
                continue

            all_groups = []
            for mod_name, (mod, count) in best_combo['modules'].items():
                groups = generate_group_arrangement(mod['name'], count)
                for group in groups:
                    group_count = group.get('count', 1)
                    for _ in range(group_count):
                        group_copy = {k: v for k, v in group.items() if k != 'count'}
                        all_groups.append(group_copy)

            if not all_groups:
                continue

            layout_result = calculate_smart_layout_with_retry(
                all_groups, aisle, all_width, all_length,
                modules_selection=best_combo['modules'], max_retries=2
            )

            if len(layout_result) == 2:
                fits, positions = layout_result
                rotations = [False] * len(all_groups)
            elif len(layout_result) == 3:
                fits, positions, rotations = layout_result
            else:
                raise ValueError(f"calculate_layout返回了意外的值数量: {len(layout_result)}")

            if not fits:
                continue

            for i, group in enumerate(all_groups):
                group['position'] = positions[i]
                if i < len(rotations):
                    group['rotated'] = rotations[i]

            auto_filled_groups = _try_auto_fill_remaining_space(
                best_combo,
                all_groups,
                all_length,
                all_width,
                aisle,
                site_area_m2,
                fill_mode
            )
            if auto_filled_groups:
                print(f"布局成功后追加补空群组: {auto_filled_groups}个")

            if fill_mode and best_combo.get('fill_ratio', 0.0) < minimum_fill_to_stop and pool_index < len(candidate_pools):
                if _is_better_fallback(best_combo, best_feasible_combo, N):
                    best_feasible_combo = best_combo
                    best_feasible_result = _build_layout_result(best_combo, all_groups, solution_level='fallback')
                print(
                    f"当前候选池填充率 {best_combo['fill_ratio']:.3f} 仍偏低，继续尝试更宽的模块池。"
                )
                break

            print("--- 布局成功！返回最终方案 ---")
            print(f"最终方案: 总床位{best_combo['total_beds']}, 总成本{best_combo['total_cost']:.2f}元")
            for item in _build_layout_result(best_combo, all_groups)['modules']:
                print(f"  模块{item['module']['name']}: {item['quantity']}个")

            return _build_layout_result(best_combo, all_groups)

    if best_feasible_result is not None:
        print("--- 未达到铺满阈值，返回当前最高填充率的可落地保底方案 ---")
        return best_feasible_result

    return None


def find_best_layout_solution(module_preferences, N, all_length, all_width):
    """
    总调度函数，整合了候选排序、组合搜索、加权评分和最终验证的全过程。
    """
    print(f"=== 开始寻找最佳布局方案 ===")
    print(f"需求: {N}人, 场地: {all_length}m x {all_width}m")
    site_area_m2 = all_length * all_width
    
    # 1. 准备模块数据
    all_modules_with_metrics = _calculate_module_metrics(deepcopy(modules))

    # 2. 按空间类型偏好进行排序
    candidates = _filter_and_sort_candidates(all_modules_with_metrics, module_preferences)
    candidate_pools = _build_candidate_pools(candidates, module_preferences)
    if not candidate_pools:
        raise ValueError("未能构建候选模块池。")

    primary_space_type = module_preferences[0]
    aisle = calculate_aisle_width(primary_space_type)
    print("--- 搜索模式: 铺满优先 ---")
    result = _search_candidate_pools(
        candidate_pools, module_preferences, N, site_area_m2,
        all_length, all_width, aisle, fill_mode=True, minimum_fill_to_stop=0.90
    )
    if result:
        return result

    print("--- 铺满优先未找到可落地方案，切换到可落地优先 ---")
    result = _search_candidate_pools(
        candidate_pools, module_preferences, N, site_area_m2,
        all_length, all_width, aisle, fill_mode=False, minimum_fill_to_stop=0.0
    )
    if result:
        return result

    raise ValueError(
        f"当前场地 {all_length}m x {all_width}m 下，已搜索到的候选组合都无法完成物理落位。"
    )
