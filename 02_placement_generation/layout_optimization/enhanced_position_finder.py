"""
功能：
1. 修复候选位置生成逻辑，避免边界溢出
2. 增强旋转尝试机制
3. 改进空间利用率
"""

import math
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '05_config_and_tools'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'inter_module_rules'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'intra_module_rules'))

from arrangement_rules import calculate_aisle_width, get_module_spacing_config
from module_spacing_manager import determine_inter_module_spacing, should_apply_inter_module_spacing

def calculate_group_dimensions_enhanced(group, rotated=False, aisle=2.0):
    """
    计算群组的实际尺寸（增强版）
    
    :param group: 群组配置字典
    :param rotated: 是否旋转90度
    :param aisle: 过道宽度（米）
    :return: (group_width, group_height)
    """
    mod = group['module']
    
    # 统一使用length和width属性
    # length对应x轴（绘图中的长度），width对应y轴（绘图中的宽度）
    module_length = mod['length'] / 1000  # x轴尺寸，转换为米
    module_width = mod['width'] / 1000    # y轴尺寸，转换为米
    
    rows = group['rows']
    cols = group['cols']
    
    # 获取该群组的垂直间距，优先使用群组配置，否则使用模块类型的默认配置
    if 'vertical_gap' in group and 'horizontal_gap' in group:
        # 如果群组已经配置了间距，直接使用
        vertical_gap = group['vertical_gap']
        horizontal_gap = group['horizontal_gap']
    else:
        # 否则根据模块类型获取默认间距配置
        spacing_config = get_module_spacing_config(mod['name'])
        vertical_gap = group.get('vertical_gap', spacing_config['vertical_gap'])
        horizontal_gap = group.get('horizontal_gap', spacing_config['horizontal_gap'])
    
    if rotated:
        # 旋转90度：交换长宽和行列配置
        module_length, module_width = module_width, module_length
        rows, cols = cols, rows  # 交换行列配置
        # 对于模块C和D，旋转时不交换间隔，保持原有的垂直无间隔、水平有间隔的特性
        if mod['name'] not in ['C', 'D']:
            # 其他模块旋转时交换间隔
            vertical_gap, horizontal_gap = horizontal_gap, vertical_gap
    
    # 计算群组的实际尺寸
    group_width = (module_length + horizontal_gap) * cols - horizontal_gap
    group_height = (module_width + vertical_gap) * rows - vertical_gap
    
    return group_width, group_height

def generate_enhanced_candidate_positions(current_positions, all_length, all_width, group_spacing, group_width, group_height):
    """
    生成增强的候选放置位置（考虑群组实际尺寸）
    
    :param current_positions: 已放置群组的位置列表
    :param all_length: 场地总长度（X轴）
    :param all_width: 场地总宽度（Y轴）
    :param group_spacing: 群组间距
    :param group_width: 待放置群组的宽度
    :param group_height: 待放置群组的高度
    :return: 候选位置列表 [(x, y), ...]
    """
    candidates = []
    
    # 起始位置（左上角）
    if group_width <= all_length and group_height <= all_width:
        candidates.append((0, 0))
    
    # 基于已放置群组生成新的候选位置
    for pos_info in current_positions:
        if isinstance(pos_info, dict):
            x, y, length, width = pos_info['x'], pos_info['y'], pos_info['length'], pos_info['width']
        else:
            x, y, length, width = pos_info
        
        # 右侧位置（紧贴或有间距）
        right_x = x + length + group_spacing
        if right_x + group_width <= all_length and y + group_height <= all_width:
            candidates.append((right_x, y))
        
        # 下方位置（紧贴或有间距）
        bottom_y = y + width + group_spacing
        if x + group_width <= all_length and bottom_y + group_height <= all_width:
            candidates.append((x, bottom_y))
        
        # 右下角位置
        if right_x + group_width <= all_length and bottom_y + group_height <= all_width:
            candidates.append((right_x, bottom_y))
        
        # 对于模块C（group_spacing=0），添加更多紧凑的候选位置
        if group_spacing == 0:
            # 在已放置群组的右侧，尝试不同的y坐标
            for other_pos_info in current_positions:
                if isinstance(other_pos_info, dict):
                    other_x, other_y, other_length, other_width = other_pos_info['x'], other_pos_info['y'], other_pos_info['length'], other_pos_info['width']
                else:
                    other_x, other_y, other_length, other_width = other_pos_info
                    
                if other_x != x or other_y != y:  # 不是同一个群组
                    # 在其他群组的y坐标位置尝试放置
                    tight_right_x = x + length
                    tight_bottom_x = other_x + other_length
                    
                    if tight_right_x + group_width <= all_length and other_y + group_height <= all_width:
                        candidates.append((tight_right_x, other_y))
                    if tight_bottom_x + group_width <= all_length and y + group_height <= all_width:
                        candidates.append((tight_bottom_x, y))
    
    # 添加网格搜索候选位置（用于填补空隙）
    grid_step = min(2.0, group_width / 2, group_height / 2)  # 网格步长
    x_positions = [i * grid_step for i in range(int(all_length / grid_step) + 1)]
    y_positions = [i * grid_step for i in range(int(all_width / grid_step) + 1)]
    
    for x in x_positions:
        for y in y_positions:
            if x + group_width <= all_length and y + group_height <= all_width:
                candidates.append((x, y))
    
    # 去重
    unique_candidates = list(set(candidates))
    
    print(f"生成增强候选位置: {len(unique_candidates)}个")
    return sorted(unique_candidates, key=lambda pos: (pos[1], pos[0]))  # 按y，然后x排序

def enhanced_boundary_check_with_details(x, y, group_width, group_height, all_length, all_width, group_info=None):
    """
    增强的边界检查函数（带详细信息）
    
    :param x, y: 放置位置
    :param group_width, group_height: 群组尺寸
    :param all_length, all_width: 场地尺寸
    :param group_info: 群组信息（用于调试）
    :return: (is_valid, error_messages, boundary_info)
    """
    errors = []
    boundary_info = {
        'left_edge': x,
        'right_edge': x + group_width,
        'top_edge': y,
        'bottom_edge': y + group_height,
        'site_length': all_length,
        'site_width': all_width
    }
    
    # 检查起始位置是否在场地内
    if x < 0:
        errors.append(f"X坐标超出左边界: {x} < 0")
    if y < 0:
        errors.append(f"Y坐标超出下边界: {y} < 0")
    
    # 检查结束位置是否在场地内
    right_edge = x + group_width
    bottom_edge = y + group_height
    
    if right_edge > all_length:
        errors.append(f"群组右边界超出场地: {right_edge:.2f}m > {all_length}m (超出 {right_edge - all_length:.2f}m)")
    if bottom_edge > all_width:
        errors.append(f"群组下边界超出场地: {bottom_edge:.2f}m > {all_width}m (超出 {bottom_edge - all_width:.2f}m)")
    
    # 检查群组尺寸是否合理
    if group_width <= 0:
        errors.append(f"群组宽度无效: {group_width}")
    if group_height <= 0:
        errors.append(f"群组高度无效: {group_height}")
    
    # 检查群组是否过大
    if group_width > all_length:
        errors.append(f"群组宽度超过场地宽度: {group_width:.2f}m > {all_length}m")
    if group_height > all_width:
        errors.append(f"群组高度超过场地高度: {group_height:.2f}m > {all_width}m")
    
    is_valid = len(errors) == 0
    
    if not is_valid and group_info:
        print(f"[失败] 边界检查失败 - 群组信息: {group_info}")
        for error in errors:
            print(f"  - {error}")
        print(f"  边界详情: 左={boundary_info['left_edge']:.2f}, 右={boundary_info['right_edge']:.2f}, 上={boundary_info['top_edge']:.2f}, 下={boundary_info['bottom_edge']:.2f}")
        print(f"  场地尺寸: 长={boundary_info['site_length']:.2f}, 宽={boundary_info['site_width']:.2f}")
    
    return is_valid, errors, boundary_info

def find_enhanced_position(group, current_positions, all_length, all_width, group_spacing=1.0):
    """
    增强的位置搜索函数，修复边界溢出问题
    
    :param group: 群组配置
    :param current_positions: 已放置群组的位置列表 [(x, y, width, height), ...]
    :param all_length: 场地总长度（X轴）
    :param all_width: 场地总宽度（Y轴）
    :param group_spacing: 群组间距
    :return: (best_x, best_y, rotated, fits)
    """
    print(f"\n=== 增强位置搜索 ===")
    print(f"群组类型: {group.get('module_type', group['module']['name'])}")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"已放置群组数量: {len(current_positions)}")
    
    # 尝试正常方向
    normal_width, normal_height = calculate_group_dimensions_enhanced(group, rotated=False)
    print(f"正常方向尺寸: {normal_width:.2f}m x {normal_height:.2f}m")
    
    # 尝试旋转90度
    rotated_width, rotated_height = calculate_group_dimensions_enhanced(group, rotated=True)
    print(f"旋转方向尺寸: {rotated_width:.2f}m x {rotated_height:.2f}m")
    
    # 候选位置列表：(x, y, rotated, width, height, score)
    candidates = []
    
    # 为正常方向生成候选位置
    normal_positions = generate_enhanced_candidate_positions(
        current_positions, all_length, all_width, group_spacing, normal_width, normal_height
    )
    
    for x, y in normal_positions:
        if can_place_group_enhanced(x, y, normal_width, normal_height, current_positions, all_length, all_width, group_spacing):
            score = calculate_position_score(x, y, normal_width, normal_height, current_positions)
            candidates.append((x, y, False, normal_width, normal_height, score))
    
    # 为旋转方向生成候选位置
    rotated_positions = generate_enhanced_candidate_positions(
        current_positions, all_length, all_width, group_spacing, rotated_width, rotated_height
    )
    
    for x, y in rotated_positions:
        if can_place_group_enhanced(x, y, rotated_width, rotated_height, current_positions, all_length, all_width, group_spacing):
            score = calculate_position_score(x, y, rotated_width, rotated_height, current_positions)
            candidates.append((x, y, True, rotated_width, rotated_height, score))
    
    print(f"总候选方案数量: {len(candidates)}")
    
    if not candidates:
        print("[失败] 无法找到合适的放置位置！")
        return None, None, False, False
    
    # 选择最佳位置（按得分排序）
    best_candidate = min(candidates, key=lambda c: c[5])  # 按score排序
    print(f"[成功] 选择最佳位置: ({best_candidate[0]:.2f}, {best_candidate[1]:.2f}), 旋转: {best_candidate[2]}, 得分: {best_candidate[5]}")
    
    return best_candidate[0], best_candidate[1], best_candidate[2], True

def can_place_group_enhanced(x, y, group_width, group_height, current_positions, all_length, all_width, group_spacing):
    """
    增强的群组放置检查函数
    
    :param x, y: 放置位置
    :param group_width, group_height: 群组尺寸
    :param current_positions: 已放置群组的位置列表
    :param all_length, all_width: 场地尺寸
    :param group_spacing: 群组间距
    :return: 是否可以放置
    """
    # 使用增强的边界检查
    is_valid, errors, boundary_info = enhanced_boundary_check_with_details(
        x, y, group_width, group_height, all_length, all_width,
        group_info=f"位置({x:.2f}, {y:.2f}) 尺寸({group_width:.2f}x{group_height:.2f}m)"
    )
    
    if not is_valid:
        return False
    
    # 检查是否与已放置的群组重叠（考虑群组间距）
    for i, pos_info in enumerate(current_positions):
        if isinstance(pos_info, dict):
            existing_x, existing_y, existing_width, existing_height = pos_info['x'], pos_info['y'], pos_info['length'], pos_info['width']
        else:
            existing_x, existing_y, existing_width, existing_height = pos_info
        
        # 检查矩形重叠（考虑群组间距）
        # 新群组需要与已放置群组保持group_spacing的距离
        overlap = not (x >= existing_x + existing_width + group_spacing or
                      x + group_width + group_spacing <= existing_x or
                      y >= existing_y + existing_height + group_spacing or
                      y + group_height + group_spacing <= existing_y)
        if overlap:
            return False
    
    return True

def calculate_position_score(x, y, width, height, current_positions):
    """
    计算位置得分（越小越好）
    
    :param x, y: 位置坐标
    :param width, height: 群组尺寸
    :param current_positions: 已放置群组的位置列表
    :return: 位置得分
    """
    # 基础得分：优先左上角
    base_score = x * 0.1 + y * 0.1
    
    # 紧凑度得分：优先紧贴已有群组
    compactness_score = 0
    if current_positions:
        min_distance = float('inf')
        for pos_info in current_positions:
            if isinstance(pos_info, dict):
                px, py, pw, ph = pos_info['x'], pos_info['y'], pos_info['length'], pos_info['width']
            else:
                px, py, pw, ph = pos_info
            
            # 计算到已有群组的最小距离
            dx = max(0, max(x - (px + pw), px - (x + width)))
            dy = max(0, max(y - (py + ph), py - (y + height)))
            distance = math.sqrt(dx*dx + dy*dy)
            min_distance = min(min_distance, distance)
        
        compactness_score = min_distance * 0.5
    
    return base_score + compactness_score
