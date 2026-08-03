import builtins
import os

from module_spacing_manager import (
    build_axis_search_candidates,
    calculate_group_dimensions_for_search,
    get_pair_spacing_requirement,
    get_search_grid_step,
    get_smart_y_offsets,
)
from orientation_spacing import get_orientation_spacing_requirement, violates_spacing_rule, calculate_rotation_penalty


VERBOSE_LAYOUT = os.environ.get("LAYOUT_VERBOSE", "0") == "1"


def print(*args, **kwargs):
    if VERBOSE_LAYOUT:
        builtins.print(*args, **kwargs)


def find_position_with_smart_spacing(group, current_positions, all_length, all_width, 
                                    inter_module_spacing=6.0, group_spacing=1.0, module_type='A'):
    """
    为任意模块群组寻找最佳放置位置，优先考虑智能间距
    
    :param group: 群组配置
    :param current_positions: 已放置群组的位置列表
    :param all_length: 场地总长度
    :param all_width: 场地总宽度
    :param inter_module_spacing: 不同模块类型间的智能间距
    :param group_spacing: 同类型群组间距
    :param module_type: 当前模块类型
    :return: (best_x, best_y, rotated, fits)
    """
    print(f"\n=== {module_type}模块智能位置寻找 ===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"智能间隔: {inter_module_spacing}m")
    print(f"群组间距: {group_spacing}m")
    
    # 计算群组尺寸（正常和旋转）
    normal_width, normal_height = calculate_group_dimensions_for_search(group, rotated=False)
    rotated_width, rotated_height = calculate_group_dimensions_for_search(group, rotated=True)
    
    print(f"正常方向尺寸: {normal_width}m x {normal_height}m")
    print(f"旋转方向尺寸: {rotated_width}m x {rotated_height}m")
    
    # 检查是否存在不同类型的已放置模块
    different_module_types = set()
    for pos_info in current_positions:
        existing_module_type = pos_info.get('module_type', 'A')
        if existing_module_type != module_type:
            different_module_types.add(existing_module_type)
    
    candidates = []
    
    # 如果存在不同类型模块，优先尝试智能间距位置
    if different_module_types:
        print(f"检测到不同模块类型: {different_module_types}，优先尝试智能间距位置")
        
        # 找到所有不同类型模块的右边界
        for pos_info in current_positions:
            existing_module_type = pos_info.get('module_type', 'A')
            if existing_module_type != module_type:
                # 计算智能间距位置（使用length作为水平尺寸）
                smart_x = pos_info['x'] + pos_info['length'] + inter_module_spacing
                
                # 尝试多个y位置（从顶部开始）
                for y_offset in get_smart_y_offsets():
                    smart_y = y_offset
                    
                    # 尝试正常方向
                    if (smart_x + normal_width <= all_length and 
                        smart_y + normal_height <= all_width and
                        can_place_group_universal(smart_x, smart_y, normal_width, normal_height, 
                                                current_positions, module_type, group_spacing, rotated=False)):
                        candidates.append((smart_x, smart_y, False, normal_width, normal_height, 'smart'))
                        print(f"找到智能间距位置（正常）: ({smart_x}, {smart_y})")
                    
                    # 尝试旋转方向
                    if (smart_x + rotated_width <= all_length and 
                        smart_y + rotated_height <= all_width and
                        can_place_group_universal(smart_x, smart_y, rotated_width, rotated_height, 
                                                current_positions, module_type, group_spacing, rotated=True)):
                        candidates.append((smart_x, smart_y, True, rotated_width, rotated_height, 'smart'))
                        print(f"找到智能间距位置（旋转）: ({smart_x}, {smart_y})")
    
    # 如果智能间距位置不可行，使用网格搜索
    if not candidates:
        print("智能间距位置不可行，使用网格搜索")
        
        x_candidates = build_axis_search_candidates(
            all_length, min(normal_width, rotated_width), current_positions, 'x', spacing=group_spacing
        )
        y_candidates = build_axis_search_candidates(
            all_width, min(normal_height, rotated_height), current_positions, 'y', spacing=group_spacing
        )

        for y in y_candidates:
            for x in x_candidates:
                # 尝试正常方向
                if (x + normal_width <= all_length and 
                    y + normal_height <= all_width and
                    can_place_group_universal(x, y, normal_width, normal_height, 
                                            current_positions, module_type, group_spacing, rotated=False)):
                    candidates.append((x, y, False, normal_width, normal_height, 'grid'))
                
                # 尝试旋转方向
                if (x + rotated_width <= all_length and 
                    y + rotated_height <= all_width and
                    can_place_group_universal(x, y, rotated_width, rotated_height, 
                                            current_positions, module_type, group_spacing, rotated=True)):
                    candidates.append((x, y, True, rotated_width, rotated_height, 'grid'))
    
    if not candidates:
        print("无法找到合适的群组位置！")
        return None, None, False, False
    
    # 选择最佳位置：空间利用率低时惩罚旋转，空间紧张时允许旋转
    def position_priority(candidate):
        x, y, rotated, width, height, method = candidate
        rotated_penalty = calculate_rotation_penalty(rotated, current_positions, all_length, all_width)
        if method == 'smart':
            return (rotated_penalty, 0, y, x)
        else:
            return (rotated_penalty, 1, y, x)
    
    best_candidate = min(candidates, key=position_priority)
    best_x, best_y, rotated, width, height, method = best_candidate
    
    print(f"选择位置: ({best_x}, {best_y}), 旋转: {rotated}, 方法: {method}")
    
    # 验证与其他模块的距离
    if method == 'smart' and different_module_types:
        for pos_info in current_positions:
            existing_module_type = pos_info.get('module_type', 'A')
            if existing_module_type != module_type:
                distance = best_x - (pos_info['x'] + pos_info['length'])
                print(f"与{existing_module_type}模块的水平距离: {distance:.1f}m (期望: {inter_module_spacing}m)")
    
    return best_x, best_y, rotated, True

def can_place_group_universal(x, y, width, height, current_positions, module_type, group_spacing, rotated=False):
    """
    通用的群组放置检查函数，支持异类型 1.5m 和异朝向 1.5m 的统一约束。
    
    :param x: 群组x坐标
    :param y: 群组y坐标
    :param width: 群组宽度
    :param height: 群组高度
    :param current_positions: 已放置群组的位置列表
    :param module_type: 当前模块类型
    :param group_spacing: 群组间距
    :return: 是否可以放置
    """
    for pos_info in current_positions:
        existing_x = pos_info['x']
        existing_y = pos_info['y']
        existing_width = pos_info['length']
        existing_height = pos_info['width']
        existing_module_type = pos_info.get('module_type', 'A')
        existing_rotated = pos_info.get('rotated', False)
        mixed_orientation = bool(rotated) != bool(existing_rotated)
        base_spacing = get_pair_spacing_requirement(module_type, existing_module_type, group_spacing)
        required_spacing = get_orientation_spacing_requirement(
            rotated,
            existing_rotated,
            base_spacing
        )

        if module_type != existing_module_type:
            if violates_spacing_rule(
                x, y, width, height,
                existing_x, existing_y, existing_width, existing_height,
                required_spacing
            ):
                return False
            continue
        
        # 根据模块类型应用不同的间距规则
        if module_type == 'A' and existing_module_type == 'A':
            # 模块A之间的特殊间距规则：群组内和群组间都无间距，可以紧贴排列
            # 只检查是否有重叠，不考虑间距
            if violates_spacing_rule(
                x, y, width, height,
                existing_x, existing_y, existing_width, existing_height,
                required_spacing
            ):
                return False
        elif module_type == 'B' and existing_module_type == 'B':
            # 模块B之间允许紧密贴合，只禁止真实重叠
            from module_b_spacing_handler import calculate_module_b_group_spacing
            if not calculate_module_b_group_spacing(current_positions, x, y, width, height, 0.0, rotated=rotated):
                return False
        elif module_type == 'C' and existing_module_type == 'C':
            if mixed_orientation:
                if violates_spacing_rule(
                    x, y, width, height,
                    existing_x, existing_y, existing_width, existing_height,
                    required_spacing
                ):
                    return False
            elif violates_spacing_rule(
                x, y, width, height,
                existing_x, existing_y, existing_width, existing_height,
                required_spacing,
                allow_zero_vertical_spacing=True
            ):
                return False  # 水平方向没有足够间距，不能放置
        elif module_type == 'D' and existing_module_type == 'D':
            if mixed_orientation:
                if violates_spacing_rule(
                    x, y, width, height,
                    existing_x, existing_y, existing_width, existing_height,
                    required_spacing
                ):
                    return False
            elif violates_spacing_rule(
                x, y, width, height,
                existing_x, existing_y, existing_width, existing_height,
                required_spacing,
                allow_zero_vertical_spacing=True
            ):
                return False  # 水平方向没有足够间距，不能放置
        else:
            if violates_spacing_rule(
                x, y, width, height,
                existing_x, existing_y, existing_width, existing_height,
                required_spacing
            ):
                return False
    
    return True


def find_best_position_universal(group, current_positions, all_length, all_width, group_spacing=1.0, module_type='C'):
    """
    为模块C等特殊模块寻找最佳放置位置，支持特定的间距规则
    模块C：水平有间距，垂直无间距
    
    :param group: 群组配置
    :param current_positions: 已放置群组的位置列表
    :param all_length: 场地总长度
    :param all_width: 场地总宽度
    :param group_spacing: 群组间距（仅用于水平方向）
    :param module_type: 模块类型
    :return: (best_x, best_y, rotated, fits)
    """
    print(f"\n=== {module_type}模块专用位置寻找 ===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"水平间距: {group_spacing}m，垂直无间距")
    print(f"已放置群组数量: {len(current_positions)}")
    
    # 计算群组尺寸（正常和旋转）
    normal_width, normal_height = calculate_group_dimensions_for_search(group, rotated=False)
    rotated_width, rotated_height = calculate_group_dimensions_for_search(group, rotated=True)
    
    print(f"正常方向尺寸: {normal_width}m x {normal_height}m")
    print(f"旋转方向尺寸: {rotated_width}m x {rotated_height}m")
    
    # 候选位置列表：(x, y, rotated, width, height)
    candidates = []
    
    # 生成候选位置的网格
    x_candidates = build_axis_search_candidates(
        all_length, min(normal_width, rotated_width), current_positions, 'x', spacing=group_spacing
    )
    y_candidates = build_axis_search_candidates(
        all_width, min(normal_height, rotated_height), current_positions, 'y', spacing=group_spacing
    )

    # 为正常方向生成候选位置
    for x in x_candidates:
        for y in y_candidates:
            # 检查边界
            if x + normal_width <= all_length and y + normal_height <= all_width:
                # 使用模块C专用的间距检查
                if can_place_group_universal(x, y, normal_width, normal_height, current_positions, module_type, group_spacing, rotated=False):
                    candidates.append((x, y, False, normal_width, normal_height))
    
    # 为旋转方向生成候选位置
    for x in x_candidates:
        for y in y_candidates:
            # 检查边界
            if x + rotated_width <= all_length and y + rotated_height <= all_width:
                # 使用模块C专用的间距检查
                if can_place_group_universal(x, y, rotated_width, rotated_height, current_positions, module_type, group_spacing, rotated=True):
                    candidates.append((x, y, True, rotated_width, rotated_height))
    
    print(f"找到 {len(candidates)} 个可行位置")
    
    if not candidates:
        print("无法找到合适的放置位置！")
        return None, None, False, False
    
    # 选择最佳位置（模块C专用：优先垂直紧贴，然后左上角）
    def position_score_for_module_c(candidate):
        x, y, rotated, width, height = candidate
        
        # 检查是否垂直紧贴已有的模块C群组
        is_vertically_adjacent = False
        for pos in current_positions:
            if pos.get('module_type') == module_type:  # 只考虑同类型模块
                existing_x = pos['x']
                existing_y = pos['y']
                existing_width = pos['width']
                existing_height = pos['height']
                
                # 检查水平方向是否有重叠或相邻
                horizontal_overlap_or_adjacent = not (
                    x >= existing_x + existing_width + group_spacing or
                    x + width + group_spacing <= existing_x
                )
                
                # 检查垂直方向是否紧贴
                vertically_adjacent = (
                    abs(y - (existing_y + existing_height)) < 0.1 or  # 紧贴在下方
                    abs((y + height) - existing_y) < 0.1  # 紧贴在上方
                )
                
                if horizontal_overlap_or_adjacent and vertically_adjacent:
                    is_vertically_adjacent = True
                    break
        
        # 评分：空间利用率低时惩罚旋转，空间紧张时允许旋转；垂直紧贴次之，然后按左上角排序
        rotated_penalty = calculate_rotation_penalty(rotated, current_positions, all_length, all_width)
        if is_vertically_adjacent:
            return (rotated_penalty, 0, y, x)
        else:
            return (rotated_penalty, 1, y, x)
    
    best_candidate = min(candidates, key=position_score_for_module_c)
    best_x, best_y, rotated, width, height = best_candidate
    
    print(f"选择最佳位置: ({best_x:.2f}, {best_y:.2f}), 旋转: {rotated}")
    
    return best_x, best_y, rotated, True
