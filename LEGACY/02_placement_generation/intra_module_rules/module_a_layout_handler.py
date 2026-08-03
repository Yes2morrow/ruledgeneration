from module_spacing_manager import build_axis_search_candidates, get_search_grid_step


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
    
    print(f"\n=== 模块A群组位置寻找（优先级处理）===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"群组间距: {group_spacing}m")
    
    # 获取群组的布局优先级
    layout_priority = group.get('layout_priority', 'interior')  # 默认为内部
    group_type = group.get('group_type', 'A_group_two')  # 默认为群组二
    allow_rotation = group_type != 'A_group_one'
    
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
                include_grid=include_grid, allow_rotation=allow_rotation
            ))
        elif layout_priority == 'flexible':
            # 灵活布局：先贴边贴缝，再补充内部候选
            edge_candidates = generate_edge_positions(
                normal_length, normal_width, rotated_length, rotated_width,
                all_length, all_width, current_positions, group_spacing,
                include_grid=include_grid, allow_rotation=allow_rotation
            )
            interior_candidates = generate_interior_positions(
                normal_length, normal_width, rotated_length, rotated_width,
                all_length, all_width, current_positions, group_spacing,
                include_grid=include_grid, allow_rotation=allow_rotation
            )
            local_candidates.extend(edge_candidates)
            local_candidates.extend(interior_candidates)
        else:
            # 内部布局优先：优先考虑场地内部位置
            local_candidates.extend(generate_interior_positions(
                normal_length, normal_width, rotated_length, rotated_width,
                all_length, all_width, current_positions, group_spacing,
                include_grid=include_grid, allow_rotation=allow_rotation
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
        best_candidate = select_best_edge_position(candidates, all_length, all_width)
    elif layout_priority == 'flexible':
        # 灵活布局：优先选择紧凑排列的位置，同时考虑边缘优势
        best_candidate = select_best_flexible_position(candidates, all_length, all_width)
    else:
        # 内部布局：优先选择紧凑排列的位置
        best_candidate = select_best_interior_position(candidates)
    
    best_x, best_y, rotated, length, width = best_candidate
    if not allow_rotation:
        rotated = False
    print(f"选择位置: ({best_x}, {best_y}), 旋转: {rotated}")
    
    return best_x, best_y, rotated, True


def generate_edge_positions(normal_length, normal_width, rotated_length, rotated_width, 
                          all_length, all_width, current_positions, group_spacing,
                          include_grid=True, allow_rotation=True):
    """
    生成边缘位置候选列表，优先考虑水平边缘
    """
    candidates = []
    step_size = get_search_grid_step()
    y_candidates = build_axis_search_candidates(
        all_width, min(normal_width, rotated_width), current_positions, 'y',
        spacing=group_spacing, include_grid=include_grid
    )
    x_candidates = build_axis_search_candidates(
        all_length, min(normal_length, rotated_length), current_positions, 'x',
        spacing=group_spacing, include_grid=include_grid
    )
    
    print("生成边缘位置候选...")
    
    # 1. 优先考虑右侧边缘（水平边缘）- 完全贴墙
    # 寻找右侧可用的垂直空间
    for y in y_candidates:
        # 正常方向：完全贴右墙
        x = all_length - normal_length
        if (x >= 0 and y + normal_width <= all_width and 
            can_place_module_a_group(x, y, normal_length, normal_width, current_positions, group_spacing)):
            candidates.append((x, y, False, normal_length, normal_width))
            print(f"  右侧边缘候选: ({x:.2f}, {y:.2f}) 正常方向 [贴墙]")
        
        # 旋转方向：完全贴右墙
        if allow_rotation:
            x = all_length - rotated_length
            if (x >= 0 and y + rotated_width <= all_width and 
                can_place_module_a_group(x, y, rotated_length, rotated_width, current_positions, group_spacing)):
                candidates.append((x, y, True, rotated_length, rotated_width))
                print(f"  右侧边缘候选: ({x:.2f}, {y:.2f}) 旋转方向 [贴墙]")
        
        # 如果贴墙位置不可用，尝试稍微偏移的位置
        for x_offset in [step_size, step_size * 2]:  # 从右边缘开始尝试偏移
            # 正常方向：尝试放置在右侧
            x = all_length - normal_length - x_offset
            if (x >= 0 and y + normal_width <= all_width and 
                can_place_module_a_group(x, y, normal_length, normal_width, current_positions, group_spacing)):
                candidates.append((x, y, False, normal_length, normal_width))
                print(f"  右侧边缘候选: ({x:.2f}, {y:.2f}) 正常方向 [偏移{x_offset}m]")
            
            # 旋转方向：尝试放置在右侧
            if allow_rotation:
                x = all_length - rotated_length - x_offset
                if (x >= 0 and y + rotated_width <= all_width and 
                    can_place_module_a_group(x, y, rotated_length, rotated_width, current_positions, group_spacing)):
                    candidates.append((x, y, True, rotated_length, rotated_width))
                    print(f"  右侧边缘候选: ({x:.2f}, {y:.2f}) 旋转方向 [偏移{x_offset}m]")
    
    # 2. 考虑底部边缘（水平边缘）- 完全贴底
    for x in x_candidates:
        # 正常方向：完全贴底墙
        y = all_width - normal_width
        if (y >= 0 and x + normal_length <= all_length and 
            can_place_module_a_group(x, y, normal_length, normal_width, current_positions, group_spacing)):
            candidates.append((x, y, False, normal_length, normal_width))
            print(f"  底部边缘候选: ({x:.2f}, {y:.2f}) 正常方向 [贴墙]")
        
        # 旋转方向：完全贴底墙
        if allow_rotation:
            y = all_width - rotated_width
            if (y >= 0 and x + rotated_length <= all_length and 
                can_place_module_a_group(x, y, rotated_length, rotated_width, current_positions, group_spacing)):
                candidates.append((x, y, True, rotated_length, rotated_width))
                print(f"  底部边缘候选: ({x:.2f}, {y:.2f}) 旋转方向 [贴墙]")
        
        # 如果贴墙位置不可用，尝试稍微偏移的位置
        for y_offset in [step_size, step_size * 2]:  # 从底边缘开始尝试偏移
            # 正常方向：尝试放置在底部
            y = all_width - normal_width - y_offset
            if (y >= 0 and x + normal_length <= all_length and 
                can_place_module_a_group(x, y, normal_length, normal_width, current_positions, group_spacing)):
                candidates.append((x, y, False, normal_length, normal_width))
                print(f"  底部边缘候选: ({x:.2f}, {y:.2f}) 正常方向 [偏移{y_offset}m]")
            
            # 旋转方向：尝试放置在底部
            if allow_rotation:
                y = all_width - rotated_width - y_offset
                if (y >= 0 and x + rotated_length <= all_length and 
                    can_place_module_a_group(x, y, rotated_length, rotated_width, current_positions, group_spacing)):
                    candidates.append((x, y, True, rotated_length, rotated_width))
                    print(f"  底部边缘候选: ({x:.2f}, {y:.2f}) 旋转方向 [偏移{y_offset}m]")
    
    # 3. 如果边缘位置不够，考虑其他位置
    if len(candidates) < 3:
        candidates.extend(generate_interior_positions(normal_length, normal_width, rotated_length, rotated_width, 
                                                    all_length, all_width, current_positions, group_spacing,
                                                    include_grid=include_grid, allow_rotation=allow_rotation))
    
    return candidates


def generate_interior_positions(normal_length, normal_width, rotated_length, rotated_width, 
                              all_length, all_width, current_positions, group_spacing,
                              include_grid=True, allow_rotation=True):
    """
    生成内部位置候选列表，优先考虑紧凑排列
    """
    candidates = []
    x_candidates = build_axis_search_candidates(
        all_length, min(normal_length, rotated_length), current_positions, 'x',
        spacing=group_spacing, include_grid=include_grid
    )
    y_candidates = build_axis_search_candidates(
        all_width, min(normal_width, rotated_width), current_positions, 'y',
        spacing=group_spacing, include_grid=include_grid
    )
    
    print("生成内部位置候选...")
    
    # 从左上角开始的网格搜索
    for y in y_candidates:
        for x in x_candidates:
            # 尝试正常方向
            if (x + normal_length <= all_length and 
                y + normal_width <= all_width and
                can_place_module_a_group(x, y, normal_length, normal_width, current_positions, group_spacing)):
                candidates.append((x, y, False, normal_length, normal_width))
            
            # 尝试旋转方向
            if (allow_rotation and
                x + rotated_length <= all_length and 
                y + rotated_width <= all_width and
                can_place_module_a_group(x, y, rotated_length, rotated_width, current_positions, group_spacing)):
                candidates.append((x, y, True, rotated_length, rotated_width))
    
    return candidates


def can_place_module_a_group(x, y, width, height, current_positions, group_spacing):
    """
    检查模块A群组是否可以放置在指定位置
    模块A群组之间无间距，只检查重叠
    """
    for pos_info in current_positions:
        existing_x = pos_info['x']
        existing_y = pos_info['y']
        existing_width = pos_info['length']
        existing_height = pos_info['width']
        existing_module_type = pos_info.get('module_type', 'A')
        
        if existing_module_type == 'A':
            # 模块A之间只检查重叠，不考虑间距
            horizontal_overlap = not (
                x >= existing_x + existing_width or
                x + width <= existing_x
            )
            
            vertical_overlap = not (
                y >= existing_y + existing_height or
                y + height <= existing_y
            )
            
            # 如果有重叠，则不能放置
            if horizontal_overlap and vertical_overlap:
                return False
        else:
            # 与其他类型模块需要保持标准间距
            horizontal_no_overlap = (
                x >= existing_x + existing_width + group_spacing or
                x + width + group_spacing <= existing_x
            )
            
            vertical_no_overlap = (
                y >= existing_y + existing_height + group_spacing or
                y + height + group_spacing <= existing_y
            )
            
            if not (horizontal_no_overlap or vertical_no_overlap):
                return False
    
    return True


def select_best_edge_position(candidates, all_length, all_width):
    """
    选择最佳边缘位置：优先选择靠近右侧或底部边缘的位置
    """
    def edge_priority(candidate):
        x, y, rotated, width, height = candidate
        
        # 计算到右边缘和底边缘的距离
        right_distance = all_length - (x + width)
        bottom_distance = all_width - (y + height)
        
        # 优先选择靠近边缘的位置（距离越小越好）
        # 右边缘优先级高于底边缘
        return (min(right_distance, bottom_distance), right_distance, y, x)
    
    return min(candidates, key=edge_priority)


def select_best_interior_position(candidates):
    """
    选择最佳内部位置：优先选择左上角位置
    """
    def interior_priority(candidate):
        x, y, rotated, width, height = candidate
        # 优先选择左上角位置
        return (y, x)
    
    return min(candidates, key=interior_priority)


def select_best_flexible_position(candidates, all_length, all_width):
    """
    选择最佳灵活位置：优先选择紧凑排列的位置，同时考虑边缘优势
    策略：优先选择能够贴合已有群组的位置，其次考虑边缘位置
    """
    def flexible_priority(candidate):
        x, y, rotated, width, height = candidate
        
        # 计算到边缘的距离
        right_distance = all_length - (x + width)
        bottom_distance = all_width - (y + height)
        left_distance = x
        top_distance = y
        
        # 计算最小边缘距离（是否靠近边缘）
        min_edge_distance = min(right_distance, bottom_distance, left_distance, top_distance)
        
        # 优先级策略：
        # 1. 优先选择左上角位置（紧凑排列）
        # 2. 其次考虑靠近边缘的位置
        # 3. 最后考虑x坐标（从左到右）
        return (y, x, min_edge_distance)
    
    return min(candidates, key=flexible_priority)
