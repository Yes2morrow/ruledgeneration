from module_spacing_manager import build_axis_search_candidates


def _is_large_b_group(group_type):
    """判断是否为需要四周保留 2m 的 B 大组团。"""
    return group_type in {'B_quad_cluster', 'B_row_pair'}


def _get_b_spacing_requirement(group_type):
    """返回不同 B 群组的最小外部间距。"""
    if _is_large_b_group(group_type):
        return 2.0
    return 1.2


def calculate_module_b_group_spacing(
    current_positions,
    new_group_x,
    new_group_y,
    new_group_length,
    new_group_width,
    new_group_type='B_single',
    large_group_spacing=2.0,
):
    """
    计算模块B群组的特殊间距。

    规则：
    1. B1/B2 大组团之间，横向和纵向都保留 2m。
    2. B_single 或小 B 组团，至少保留 1.2m。
    3. B 与其他模块之间仍只禁止真实重叠。
    
    :param current_positions: 已放置群组的位置列表
    :param new_group_x: 新群组的x坐标
    :param new_group_y: 新群组的y坐标
    :param new_group_length: 新群组的长度（x轴尺寸）
    :param new_group_width: 新群组的宽度（y轴尺寸）
    :param new_group_type: 新群组类型
    :param large_group_spacing: 大组团之间的最小外部间距
    :return: 是否可以放置
    """
    tolerance = 1e-6
    for pos_info in current_positions:
        existing_x = pos_info['x']
        existing_y = pos_info['y']
        existing_width = pos_info['length']
        existing_height = pos_info['width']
        module_type = pos_info.get('module_type', 'A')
        
        if module_type == 'B':
            existing_group_type = pos_info.get('group_type', 'B_single')
            vertical_overlap = not (
                new_group_y >= existing_y + existing_height or
                new_group_y + new_group_width <= existing_y
            )
            horizontal_overlap = not (
                new_group_x >= existing_x + existing_width or
                new_group_x + new_group_length <= existing_x
            )

            # 先排除真实重叠。
            if horizontal_overlap and vertical_overlap:
                return False

            required_spacing = (
                2.0
                if _is_large_b_group(new_group_type) and _is_large_b_group(existing_group_type)
                else min(_get_b_spacing_requirement(new_group_type), _get_b_spacing_requirement(existing_group_type))
            )
            if required_spacing > 0:
                horizontal_gap = min(
                    abs(new_group_x - (existing_x + existing_width)),
                    abs((new_group_x + new_group_length) - existing_x)
                )
                vertical_gap = min(
                    abs(new_group_y - (existing_y + existing_height)),
                    abs((new_group_y + new_group_width) - existing_y)
                )
                if vertical_overlap and horizontal_gap + tolerance < required_spacing:
                    return False
                if horizontal_overlap and vertical_gap + tolerance < required_spacing:
                    return False
        else:
            # 与其他类型模块（A、C等）不能有任何重叠
            horizontal_overlap = not (
                new_group_x >= existing_x + existing_width or
                new_group_x + new_group_length <= existing_x
            )
            
            vertical_overlap = not (
                new_group_y >= existing_y + existing_height or
                new_group_y + new_group_width <= existing_y
            )
            
            # 如果有任何重叠，则不能放置
            if horizontal_overlap and vertical_overlap:
                return False
    
    return True

def find_module_b_position(group, current_positions, all_length, all_width, group_spacing=2.0):
    """
    为模块B群组寻找最佳放置位置
    
    :param group: 群组配置
    :param current_positions: 已放置群组的位置列表
    :param all_length: 场地总长度
    :param all_width: 场地总宽度
    :param group_spacing: 兼容上层调用，实际由 group_type 决定是否应用
    :return: (best_x, best_y, rotated, fits)
    """
    from smart_layout_optimizer import calculate_group_dimensions

    group_type = group.get('group_type', 'B_single')
    active_spacing = _get_b_spacing_requirement(group_type)
    
    print(f"\n=== 模块B群组位置寻找 ===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"B群组类型: {group_type}")
    print(f"B群组最小外间距: {active_spacing}m")
    print("B_single / 小B补空策略: 仍需保留至少 1.2m 间距")
    print(f"B组团内部间距: 0m（由B1/B2组团定义控制）")
    
    # 计算群组尺寸（正常和旋转）
    normal_length, normal_width = calculate_group_dimensions(group, rotated=False)
    rotated_length, rotated_width = calculate_group_dimensions(group, rotated=True)
    
    print(f"正常方向尺寸: {normal_length}m x {normal_width}m")
    print(f"旋转方向尺寸: {rotated_length}m x {rotated_width}m")
    
    # 生成候选位置
    candidates = []

    def add_candidates(group_length, group_width, rotated, include_grid):
        x_candidates = build_axis_search_candidates(
            all_length, group_length, current_positions, 'x',
            spacing=active_spacing, include_grid=include_grid
        )
        y_candidates = build_axis_search_candidates(
            all_width, group_width, current_positions, 'y',
            spacing=active_spacing, include_grid=include_grid
        )

        for y in y_candidates:
            for x in x_candidates:
                if (x + group_length <= all_length and
                    y + group_width <= all_width and
                    calculate_module_b_group_spacing(
                        current_positions,
                        x,
                        y,
                        group_length,
                        group_width,
                        new_group_type=group_type,
                        large_group_spacing=active_spacing
                    )):
                    candidates.append((x, y, rotated, group_length, group_width))

    # 先用精确贴边候选尝试补空，必要时再退回网格搜索。
    add_candidates(normal_length, normal_width, False, include_grid=False)
    add_candidates(rotated_length, rotated_width, True, include_grid=False)
    if not candidates:
        add_candidates(normal_length, normal_width, False, include_grid=True)
        add_candidates(rotated_length, rotated_width, True, include_grid=True)
    
    if not candidates:
        print("无法找到合适的模块B群组位置！")
        return None, None, False, False
    
    # 选择最佳位置：优先紧密贴合已有B群组或场地边界，尽量消除不必要空隙
    def candidate_score(candidate):
        x, y, rotated, length, width = candidate
        touch_count = 0
        min_gap = float('inf')
        epsilon = 0.11

        # 贴场地边界也视为紧凑排列
        if abs(x) < epsilon:
            touch_count += 1
            min_gap = min(min_gap, 0.0)
        if abs(y) < epsilon:
            touch_count += 1
            min_gap = min(min_gap, 0.0)

        for pos_info in current_positions:
            existing_x = pos_info['x']
            existing_y = pos_info['y']
            existing_length = pos_info['length']
            existing_width = pos_info['width']

            horizontal_overlap = not (
                x >= existing_x + existing_length or
                x + length <= existing_x
            )
            vertical_overlap = not (
                y >= existing_y + existing_width or
                y + width <= existing_y
            )

            horizontal_gap = min(
                abs(x - (existing_x + existing_length)),
                abs((x + length) - existing_x)
            )
            vertical_gap = min(
                abs(y - (existing_y + existing_width)),
                abs((y + width) - existing_y)
            )

            if horizontal_overlap:
                min_gap = min(min_gap, vertical_gap)
                if vertical_gap < epsilon:
                    touch_count += 1

            if vertical_overlap:
                min_gap = min(min_gap, horizontal_gap)
                if horizontal_gap < epsilon:
                    touch_count += 1

        if min_gap == float('inf'):
            min_gap = max(x, y)

        return (-touch_count, min_gap, y, x)

    best_candidate = min(candidates, key=candidate_score)
    
    best_x, best_y, rotated, length, width = best_candidate
    print(f"选择位置: ({best_x}, {best_y}), 旋转: {rotated}")
    
    return best_x, best_y, rotated, True
