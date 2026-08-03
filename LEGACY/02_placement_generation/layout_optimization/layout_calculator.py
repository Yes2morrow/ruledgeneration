"""
布局计算器模块
负责所有与布局相关的数学计算，而不涉及任何绘图操作。
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from smart_layout_optimizer import calculate_smart_layout

def calculate_layout(groups_config: list, aisle: float, all_width: float, all_length: float, use_smart_layout=True, modules_selection=None):
    """
    布局计算函数，支持传统布局和智能布局两种模式
    
    :param groups_config: 群组配置列表
    :param aisle: 过道宽度
    :param all_width: 场地总宽度（Y轴）
    :param all_length: 场地总长度（X轴）
    :param use_smart_layout: 是否使用智能布局（支持旋转和多方向检测）
    :return: (fits, positions) 或 (fits, positions, rotations)
    """
    if use_smart_layout:
        # 使用智能布局算法
        fits, positions, rotations = calculate_smart_layout(groups_config, aisle, all_width, all_length, modules_selection)
        # 为了保持兼容性，将旋转信息添加到群组配置中
        for i, (group, rotated) in enumerate(zip(groups_config, rotations)):
            group['rotated'] = rotated
        return fits, positions
    else:
        # 使用传统布局算法
        return calculate_layout_traditional(groups_config, aisle, all_width, all_length)

def calculate_layout_traditional(groups_config: list, aisle: float, all_width: float, all_length: float):
    """
    计算给定模块群组在指定场地内的布局位置。

    改进的布局算法：
    1. 修复换行逻辑，确保所有群组都能正确换行
    2. 优化群组间距，减少不必要的空白
    3. 改进行高计算，确保垂直方向紧凑排列
    4. 添加调试信息，便于问题诊断

    :param groups_config: 一个列表，其中每个元素是描述一个模块群组的字典。
                          每个字典需要包含 'module', 'rows', 'cols'。
    :param aisle: 过道宽度（米）。
    :param all_width: 场地的总宽度（Y轴）（米）。
    :param all_length: 场地的总长度（X轴）（米）。
    :return: 一个元组 (fits, positions)。
             - fits (bool): 如果布局可以容纳在场地内，则为 True，否则为 False。
             - positions (list): 一个列表，包含每个群组的左下角 (x, y) 坐标。
                               如果 fits 为 False，则返回一个空列表。
    """
    if not groups_config:
        return True, []
    
    positions = []
    x_offset = 0
    y_offset = 0
    max_row_height = 0
    # 群组间距：模块A群组之间无间距，其他模块使用标准间距
    default_group_spacing = 1.0  # 建筑业标准群组间距 
    
    print(f"=== 布局计算开始 ===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"群组数量: {len(groups_config)}")
    print(f"过道宽度: {aisle}m")
    print(f"默认群组间距: {default_group_spacing}m")
    
    for i, group in enumerate(groups_config):
        mod = group['module']
        width = mod['width'] / 1000  # 转换为米
        height = mod['height'] / 1000  # 转换为米
        rows = group['rows']
        cols = group['cols']
        
        # 获取该群组的垂直和水平间距，若未指定则使用默认过道宽度
        vertical_gap = group.get('vertical_gap', aisle)
        horizontal_gap = group.get('horizontal_gap', aisle)
        
        # 根据模块类型决定群组间距：模块A群组之间无间距，其他模块使用标准间距
        if mod['name'] == 'A':
            current_group_spacing = 0.0  # 模块A群组之间无间距
        else:
            current_group_spacing = default_group_spacing  # 其他模块使用标准间距
        
        # 计算群组的实际尺寸
        group_width = (width + horizontal_gap) * cols - horizontal_gap
        group_height = (height + vertical_gap) * rows - vertical_gap
        
        print(f"\n群组 {i+1}: {mod['name']}模块")
        print(f"  模块尺寸: {width:.2f}m x {height:.2f}m")
        print(f"  群组配置: {rows}行 x {cols}列")
        print(f"  群组尺寸: {group_width:.2f}m x {group_height:.2f}m")
        print(f"  当前位置: x={x_offset:.2f}m, y={y_offset:.2f}m")
        
        # 检查是否需要换行
        if x_offset + group_width > all_length:
            print(f"  群组{i+1}需要换行")
            x_offset = 0
            y_offset += max_row_height + current_group_spacing
            max_row_height = 0
            print(f"  换行到: x={x_offset:.2f}m, y={y_offset:.2f}m")
        
        # 检查新位置是否会超出场地总高度
        if y_offset + group_height > all_width:
            print(f"  错误：群组超出场地高度 ({y_offset + group_height:.2f}m > {all_width}m)")
            return False, []  # 布局溢出
        
        # 记录当前群组的位置
        positions.append((x_offset, y_offset))
        print(f"  最终位置: x={x_offset:.2f}m, y={y_offset:.2f}m")
        
        # 更新下一群组的起始x坐标和当前行的最大高度
        x_offset += group_width + current_group_spacing
        max_row_height = max(max_row_height, group_height)
        
        print(f"  下一个x位置: {x_offset:.2f}m")
        print(f"  当前行最大高度: {max_row_height:.2f}m")
    
    # 计算实际使用的场地尺寸
    if positions:
        max_x = 0
        max_y = 0
        for i, (x, y) in enumerate(positions):
            group = groups_config[i]
            mod = group['module']
            width = mod['width'] / 1000
            height = mod['height'] / 1000
            rows = group['rows']
            cols = group['cols']
            vertical_gap = group.get('vertical_gap', aisle)
            horizontal_gap = group.get('horizontal_gap', aisle)
            
            group_width = (width + horizontal_gap) * cols - horizontal_gap
            group_height = (height + vertical_gap) * rows - vertical_gap
            
            max_x = max(max_x, x + group_width)
            max_y = max(max_y, y + group_height)
        
        print(f"\n=== 布局计算完成 ===")
        print(f"实际使用尺寸: {max_x:.2f}m x {max_y:.2f}m")
        print(f"场地利用率: {(max_x/all_length)*100:.1f}% x {(max_y/all_width)*100:.1f}%")
        
        # 如果利用率过低，给出建议
        if max_x / all_length < 0.6:
            print(f"警告：长度利用率较低 ({(max_x/all_length)*100:.1f}%)，可能存在布局优化空间")
        if max_y / all_width < 0.6:
            print(f"警告：宽度利用率较低 ({(max_y/all_width)*100:.1f}%)，可能存在布局优化空间")
    
    return True, positions