from module_spacing_manager import build_axis_search_candidates, get_search_grid_step
from module_spacing_manager import get_pair_spacing_requirement
from orientation_spacing import get_orientation_spacing_requirement, violates_spacing_rule, calculate_rotation_penalty


def find_module_a_position_with_priority(group, current_positions, all_length, all_width, group_spacing=0.0):
    """
    为模块A群组寻找最佳放置位置，考虑布局优先级
    
    :param group: 群组配置
    :param current_positions: 已放置群组的位置列表
    :param all_length: 场地总长度
    :param all_width: 场地总宽度
    :param group_spacing: 群组间距（模块A默认为0）
    :return: (best_x, best_y, rotated, fits)
    """
    from smart_layout_optimizer import calculate_group_dimensions
    horizontal_spacing = group_spacing
    vertical_spacing = 0.0
    
    print(f"\n=== 模块A群组位置寻找（优先级处理）===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"横向最小间距: {horizontal_spacing}m")
    print(f"纵向最小间距: {vertical_spacing}m")
    
    # 获取群组的布局优先级
    layout_priority = group.get('layout_priority', 'interior')  # 默认为内部
    group_type = group.get('group_type', 'A_group_two')  # 默认为群组二
    allow_rotation = group_type == 'A_group_two'
    
    print(f"群组类型: {group_type}")
    print(f"布局优先级: {layout_priority}")
    
    # 计算群组尺寸（正常和旋转）
    normal_length, normal_width = calculate_group_dimensions(group, rotated=False)
    rotated_length, rotated_width = calculate_group_dimensions(group, rotated=True)
    if not allow_rotation:
        rotated_length, rotated_width = normal_length, normal_width
    
    print(f"正常方向尺寸: {normal_length}m x {normal_width}m")
    if allow_rotation:
        print(f"旋转方向尺寸: {rotated_length}m x {rotated_width}m")
    else:
        print("旋转方向尺寸: 已禁用 A_group_one 旋转尝试")
    
    # 生成候选位置
    candidates = []
    
    def build_candidates(include_grid):
        local_candidates = []
        if layout_priority == 'edge':
            # 边缘布局优先：优先考虑场地边缘位置
            local_candidates.extend(generate_edge_positions(
                normal_length, normal_width, rotated_length, rotated_width,
                all_length, all_width, current_positions, group_spacing,
                include_grid=include_grid, allow_rotation=allow_rotation,
                horizontal_spacing=horizontal_spacing, vertical_spacing=vertical_spacing
            ))
        elif layout_priority == 'flexible':
            # 灵活布局：先贴边贴缝，再补充内部候选
            edge_candidates = generate_edge_positions(
                normal_length, normal_width, rotated_length, rotated_width,
                all_length, all_width, current_positions, group_spacing,
                include_grid=include_grid, allow_rotation=allow_rotation,
                horizontal_spacing=horizontal_spacing, vertical_spacing=vertical_spacing
            )
            interior_candidates = generate_interior_positions(
                normal_length, normal_width, rotated_length, rotated_width,
                all_length, all_width, current_positions, group_spacing,
                include_grid=include_grid, allow_rotation=allow_rotation,
                horizontal_spacing=horizontal_spacing, vertical_spacing=vertical_spacing
            )
            local_candidates.extend(edge_candidates)
            local_candidates.extend(interior_candidates)
        else:
            # 内部布局优先：优先考虑场地内部位置
            local_candidates.extend(generate_interior_positions(
                normal_length, normal_width, rotated_length, rotated_width,
                all_length, all_width, current_positions, group_spacing,
                include_grid=include_grid, allow_rotation=allow_rotation,
                horizontal_spacing=horizontal_spacing, vertical_spacing=vertical_spacing
            ))
        return local_candidates

    # 先尝试“贴边/贴已有群组”的精确候选，找不到再回退到完整网格，既更快也更容易补细缝。
    candidates = build_candidates(include_grid=False)
    if not candidates:
        candidates = build_candidates(include_grid=True)
    
    if not candidates:
        print("无法找到合适的模块A群组位置！")
        return None, None, False, False
    
    # 选择最佳位置
    if layout_priority == 'edge':
        # 边缘布局：优先选择靠近边缘的位置
        best_candidate = select_best_edge_position(candidates, all_length, all_width, current_positions)
    elif layout_priority == 'flexible':
        # 灵活布局：优先选择紧凑排列的位置，同时考虑边缘优势
        best_candidate = select_best_flexible_position(candidates, all_length, all_width, current_positions)
    else:
        # 内部布局：优先选择紧凑排列的位置
        best_candidate = select_best_interior_position(candidates, all_length, all_width, current_positions)
    
    best_x, best_y, rotated, length, width = best_candidate
    if not allow_rotation:
        rotated = False
    print(f"选择位置: ({best_x}, {best_y}), 旋转: {rotated}")
    
    return best_x, best_y, rotated, True


def generate_edge_positions(normal_length, normal_width, rotated_length, rotated_width, 
                          all_length, all_width, current_positions, group_spacing,
                          include_grid=True, allow_rotation=True,
                          horizontal_spacing=0.0, vertical_spacing=0.0):
    """
    生成边缘位置候选列表，优先考虑水平边缘
    """
    candidates = []
    step_size = get_search_grid_step()
    y_candidates = build_axis_search_candidates(
        all_width, min(normal_width, rotated_width), current_positions, 'y',
        spacing=vertical_spacing, include_grid=include_grid
    )
    x_candidates = build_axis_search_candidates(
        all_length, min(normal_length, rotated_length), current_positions, 'x',
        spacing=horizontal_spacing, include_grid=include_grid
    )
    
    print("生成边缘位置候选...")
    
    # 1. 优先考虑右侧边缘（水平边缘）- 完全贴墙
    # 寻找右侧可用的垂直空间
    for y in y_candidates:
        # 正常方向：完全贴右墙
        x = all_length - normal_length
        if (x >= 0 and y + normal_width <= all_width and 
            can_place_module_a_group(
                x, y, normal_length, normal_width, current_positions,
                horizontal_spacing, vertical_spacing
            )):
            candidates.append((x, y, False, normal_length, normal_width))
            print(f"  右侧边缘候选: ({x:.2f}, {y:.2f}) 正常方向 [贴墙]")
        
        # 旋转方向：完全贴右墙
        if allow_rotation:
            x = all_length - rotated_length
            if (x >= 0 and y + rotated_width <= all_width and 
                can_place_module_a_group(
                    x, y, rotated_length, rotated_width, current_positions,
                    horizontal_spacing, vertical_spacing
                )):
                candidates.append((x, y, True, rotated_length, rotated_width))
                print(f"  右侧边缘候选: ({x:.2f}, {y:.2f}) 旋转方向 [贴墙]")
        
        # 如果贴墙位置不可用，尝试稍微偏移的位置
        for x_offset in [step_size, step_size * 2]:  # 从右边缘开始尝试偏移
            # 正常方向：尝试放置在右侧
            x = all_length - normal_length - x_offset
            if (x >= 0 and y + normal_width <= all_width and 
                can_place_module_a_group(
                    x, y, normal_length, normal_width, current_positions,
                    horizontal_spacing, vertical_spacing, rotated=False
                )):
                candidates.append((x, y, False, normal_length, normal_width))
                print(f"  右侧边缘候选: ({x:.2f}, {y:.2f}) 正常方向 [偏移{x_offset}m]")
            
            # 旋转方向：尝试放置在右侧
            if allow_rotation:
                x = all_length - rotated_length - x_offset
                if (x >= 0 and y + rotated_width <= all_width and 
                    can_place_module_a_group(
                        x, y, rotated_length, rotated_width, current_positions,
                        horizontal_spacing, vertical_spacing, rotated=True
                    )):
                    candidates.append((x, y, True, rotated_length, rotated_width))
                    print(f"  右侧边缘候选: ({x:.2f}, {y:.2f}) 旋转方向 [偏移{x_offset}m]")
    
    # 2. 考虑底部边缘（水平边缘）- 完全贴底
    for x in x_candidates:
        # 正常方向：完全贴底墙
        y = all_width - normal_width
        if (y >= 0 and x + normal_length <= all_length and 
            can_place_module_a_group(
                x, y, normal_length, normal_width, current_positions,
                horizontal_spacing, vertical_spacing
            )):
            candidates.append((x, y, False, normal_length, normal_width))
            print(f"  底部边缘候选: ({x:.2f}, {y:.2f}) 正常方向 [贴墙]")
        
        # 旋转方向：完全贴底墙
        if allow_rotation:
            y = all_width - rotated_width
            if (y >= 0 and x + rotated_length <= all_length and 
                can_place_module_a_group(
                    x, y, rotated_length, rotated_width, current_positions,
                    horizontal_spacing, vertical_spacing
                )):
                candidates.append((x, y, True, rotated_length, rotated_width))
                print(f"  底部边缘候选: ({x:.2f}, {y:.2f}) 旋转方向 [贴墙]")
        
        # 如果贴墙位置不可用，尝试稍微偏移的位置
        for y_offset in [step_size, step_size * 2]:  # 从底边缘开始尝试偏移
            # 正常方向：尝试放置在底部
            y = all_width - normal_width - y_offset
            if (y >= 0 and x + normal_length <= all_length and 
                can_place_module_a_group(
                    x, y, normal_length, normal_width, current_positions,
                    horizontal_spacing, vertical_spacing, rotated=False
                )):
                candidates.append((x, y, False, normal_length, normal_width))
                print(f"  底部边缘候选: ({x:.2f}, {y:.2f}) 正常方向 [偏移{y_offset}m]")
            
            # 旋转方向：尝试放置在底部
            if allow_rotation:
                y = all_width - rotated_width - y_offset
                if (y >= 0 and x + rotated_length <= all_length and 
                    can_place_module_a_group(
                        x, y, rotated_length, rotated_width, current_positions,
                        horizontal_spacing, vertical_spacing, rotated=True
                    )):
                    candidates.append((x, y, True, rotated_length, rotated_width))
                    print(f"  底部边缘候选: ({x:.2f}, {y:.2f}) 旋转方向 [偏移{y_offset}m]")
    
    # 3. 如果边缘位置不够，考虑其他位置
    if len(candidates) < 3:
        candidates.extend(generate_interior_positions(normal_length, normal_width, rotated_length, rotated_width, 
                                                    all_length, all_width, current_positions, group_spacing,
                                                    include_grid=include_grid, allow_rotation=allow_rotation,
                                                    horizontal_spacing=horizontal_spacing,
                                                    vertical_spacing=vertical_spacing))
    
    return candidates


def generate_interior_positions(normal_length, normal_width, rotated_length, rotated_width, 
                              all_length, all_width, current_positions, group_spacing,
                              include_grid=True, allow_rotation=True,
                              horizontal_spacing=0.0, vertical_spacing=0.0):
    """
    生成内部位置候选列表，优先考虑紧凑排列
    """
    candidates = []
    x_candidates = build_axis_search_candidates(
        all_length, min(normal_length, rotated_length), current_positions, 'x',
        spacing=horizontal_spacing, include_grid=include_grid
    )
    y_candidates = build_axis_search_candidates(
        all_width, min(normal_width, rotated_width), current_positions, 'y',
        spacing=vertical_spacing, include_grid=include_grid
    )
    
    print("生成内部位置候选...")
    
    # 从左上角开始的网格搜索
    for y in y_candidates:
        for x in x_candidates:
            # 尝试正常方向
            if (x + normal_length <= all_length and 
                y + normal_width <= all_width and
                can_place_module_a_group(
                    x, y, normal_length, normal_width, current_positions,
                    horizontal_spacing, vertical_spacing, rotated=False
                )):
                candidates.append((x, y, False, normal_length, normal_width))
            
            # 尝试旋转方向
            if (allow_rotation and
                x + rotated_length <= all_length and 
                y + rotated_width <= all_width and
                can_place_module_a_group(
                    x, y, rotated_length, rotated_width, current_positions,
                    horizontal_spacing, vertical_spacing, rotated=True
                )):
                candidates.append((x, y, True, rotated_length, rotated_width))
    
    return candidates


def can_place_module_a_group(
    x, y, width, height, current_positions,
    horizontal_spacing=0.0, vertical_spacing=0.0, rotated=False
):
    """
    检查模块A群组是否可以放置在指定位置
    A 组团规则：
    1. A 与 A 在横向相邻时需要最小 2m 外间距。
    2. A 与 A 在纵向堆叠时不需要额外间距，只禁止真实重叠。
    3. A 与其他类型模块之间，统一至少保留 1.5m。
    4. 任意 A 群组若与异朝向群组相邻，也至少保留 1.5m。
    """
    tolerance = 1e-6
    for pos_info in current_positions:
        existing_x = pos_info['x']
        existing_y = pos_info['y']
        existing_width = pos_info['length']
        existing_height = pos_info['width']
        existing_module_type = pos_info.get('module_type', 'A')
        existing_rotated = pos_info.get('rotated', False)
        mixed_orientation = bool(rotated) != bool(existing_rotated)
        base_spacing = (
            horizontal_spacing
            if existing_module_type == 'A'
            else get_pair_spacing_requirement('A', existing_module_type, 0.0)
        )
        required_spacing = get_orientation_spacing_requirement(
            rotated,
            existing_rotated,
            base_spacing
        )
        
        if existing_module_type == 'A':
            if violates_spacing_rule(
                x, y, width, height,
                existing_x, existing_y, existing_width, existing_height,
                required_spacing,
                allow_zero_vertical_spacing=(vertical_spacing <= tolerance and not mixed_orientation)
            ):
                return False
        else:
            if violates_spacing_rule(
                x, y, width, height,
                existing_x, existing_y, existing_width, existing_height,
                required_spacing
            ):
                return False
    
    return True


def select_best_edge_position(candidates, all_length, all_width, current_positions=None):
    """
    选择最佳边缘位置：优先选择靠近右侧或底部边缘的位置
    空间利用率低时惩罚旋转，空间紧张时允许旋转
    """
    def edge_priority(candidate):
        x, y, rotated, width, height = candidate
        
        right_distance = all_length - (x + width)
        bottom_distance = all_width - (y + height)
        rotated_penalty = calculate_rotation_penalty(rotated, current_positions or [], all_length, all_width)
        
        return (rotated_penalty, min(right_distance, bottom_distance), right_distance, y, x)
    
    return min(candidates, key=edge_priority)


def select_best_interior_position(candidates, all_length=0, all_width=0, current_positions=None):
    """
    选择最佳内部位置：优先选择左上角位置
    空间利用率低时惩罚旋转，空间紧张时允许旋转
    """
    def interior_priority(candidate):
        x, y, rotated, width, height = candidate
        rotated_penalty = calculate_rotation_penalty(rotated, current_positions or [], all_length, all_width)
        return (rotated_penalty, y, x)
    
    return min(candidates, key=interior_priority)


def select_best_flexible_position(candidates, all_length, all_width, current_positions=None):
    """
    选择最佳灵活位置：优先选择紧凑排列的位置，同时考虑边缘优势
    空间利用率低时惩罚旋转，空间紧张时允许旋转
    """
    def flexible_priority(candidate):
        x, y, rotated, width, height = candidate
        
        right_distance = all_length - (x + width)
        bottom_distance = all_width - (y + height)
        left_distance = x
        top_distance = y
        min_edge_distance = min(right_distance, bottom_distance, left_distance, top_distance)
        rotated_penalty = calculate_rotation_penalty(rotated, current_positions or [], all_length, all_width)
        
        return (rotated_penalty, y, x, min_edge_distance)
    
    return min(candidates, key=flexible_priority)
