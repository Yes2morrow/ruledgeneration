"""
功能：
1. 支持群组旋转90度以优化空间利用
2. 多方向空间检测和布局策略
3. 智能换行和空间填充算法
"""

import builtins
import math
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '05_config_and_tools'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'inter_module_rules'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'intra_module_rules'))

from arrangement_rules import calculate_aisle_width, get_module_spacing_config
from module_spacing_manager import (
    build_axis_search_candidates,
    determine_inter_module_spacing,
    get_pair_spacing_requirement,
    should_apply_inter_module_spacing,
)
from module_b_spacing_handler import find_module_b_position
from advanced_space_optimizer import enhanced_space_check, analyze_space_utilization
from flexible_spacing_manager import calculate_adaptive_spacing, optimize_spacing_for_layout_failure, suggest_layout_optimization
from orientation_spacing import get_orientation_spacing_requirement, violates_spacing_rule, calculate_rotation_penalty


VERBOSE_LAYOUT = os.environ.get("LAYOUT_VERBOSE", "0") == "1"


def print(*args, **kwargs):
    if VERBOSE_LAYOUT:
        builtins.print(*args, **kwargs)


def enhanced_boundary_check(x, y, group_width, group_height, all_length, all_width, group_info=None):
    """
    增强的边界检查函数
    
    :param x, y: 放置位置
    :param group_width, group_height: 群组尺寸
    :param all_length, all_width: 场地尺寸
    :param group_info: 群组信息（用于调试）
    :return: (is_valid, error_messages)
    """
    errors = []
    
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
    
    return is_valid, errors

def validate_layout_before_placement(groups_config, all_length, all_width):
    """
    在布局放置前验证所有群组是否可能放置在场地内
    
    :param groups_config: 群组配置列表
    :param all_length, all_width: 场地尺寸
    :return: (is_feasible, error_report)
    """
    print(f"\n=== 布局可行性预检查 ===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"群组数量: {len(groups_config)}")
    
    total_area_needed = 0
    oversized_groups = []
    error_report = []
    
    for i, group in enumerate(groups_config):
        # 计算群组尺寸（正常方向）
        normal_width, normal_height = calculate_group_dimensions(group, rotated=False)
        
        # 计算群组尺寸（旋转方向）
        rotated_width, rotated_height = calculate_group_dimensions(group, rotated=True)
        
        # 检查是否至少有一个方向可以放置
        normal_fits = (normal_width <= all_length and normal_height <= all_width)
        rotated_fits = (rotated_width <= all_length and rotated_height <= all_width)
        
        group_area = min(normal_width * normal_height, rotated_width * rotated_height)
        total_area_needed += group_area
        
        module_name = group['module']['name']
        
        if not normal_fits and not rotated_fits:
            error_msg = f"群组{i+1}({module_name}) 无法放置在场地内"
            error_msg += f" - 正常: {normal_width:.2f}x{normal_height:.2f}m"
            error_msg += f" - 旋转: {rotated_width:.2f}x{rotated_height:.2f}m"
            error_msg += f" - 场地: {all_length}x{all_width}m"
            
            oversized_groups.append({
                'group_id': i+1,
                'module_type': module_name,
                'normal_size': (normal_width, normal_height),
                'rotated_size': (rotated_width, rotated_height),
                'error': error_msg
            })
            error_report.append(error_msg)
            print(f"[失败] {error_msg}")
        else:
            fit_info = []
            if normal_fits:
                fit_info.append(f"正常({normal_width:.2f}x{normal_height:.2f}m)")
            if rotated_fits:
                fit_info.append(f"旋转({rotated_width:.2f}x{rotated_height:.2f}m)")
            print(f"[可放置] 群组{i+1}({module_name}): {', '.join(fit_info)}")
    
    site_area = all_length * all_width
    area_utilization = (total_area_needed / site_area) * 100
    
    print(f"\n总需求面积: {total_area_needed:.2f} m^2")
    print(f"场地面积: {site_area:.2f} m^2")
    print(f"理论利用率: {area_utilization:.1f}%")
    
    if area_utilization > 90:
        warning_msg = f"[警告] 场地利用率过高 ({area_utilization:.1f}%)，可能导致布局困难"
        error_report.append(warning_msg)
        print(warning_msg)
    
    is_feasible = len(oversized_groups) == 0
    
    if is_feasible:
        print(f"[通过] 布局可行性检查通过")
    else:
        print(f"[失败] 发现 {len(oversized_groups)} 个无法放置的群组")
    
    return is_feasible, {
        'oversized_groups': oversized_groups,
        'total_area_needed': total_area_needed,
        'site_area': site_area,
        'area_utilization': area_utilization,
        'errors': error_report
    }


def calculate_group_dimensions(group, rotated=False, aisle=2.0):
    """
    计算群组的实际尺寸
    
    :param group: 群组配置字典
    :param rotated: 是否旋转90度
    :param aisle: 过道宽度（米）
    :return: (group_width, group_height)
    """
    mod = group['module']

    # 自定义子组团坐标：用于表达模块B这类“先抽象组团，再套贴图”的特殊排布。
    if group.get('subgroups'):
        total_length = group.get('total_length')
        total_width = group.get('total_width')

        if total_length is None or total_width is None:
            total_length = max(item['x'] + item['length'] for item in group['subgroups'])
            total_width = max(item['y'] + item['width'] for item in group['subgroups'])

        if rotated:
            return total_width, total_length
        return total_length, total_width

    # 自定义单元坐标组团：用于表达模块B这类“局部紧贴 + 局部分组间距”的特殊排布。
    if group.get('unit_positions'):
        total_length = group.get('total_length')
        total_width = group.get('total_width')

        if total_length is None or total_width is None:
            module_length = mod['length'] / 1000
            module_width = mod['width'] / 1000
            total_length = max(pos['x'] for pos in group['unit_positions']) + module_length
            total_width = max(pos['y'] for pos in group['unit_positions']) + module_width

        if rotated:
            return total_width, total_length
        return total_length, total_width
    
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

def find_best_position(group, current_positions, all_length, all_width, group_spacing=1.0, module_type=None):
    """
    为群组寻找最佳放置位置，考虑旋转和多方向布局
    
    :param group: 群组配置
    :param current_positions: 已放置群组的位置列表 [(x, y, width, height), ...]
    :param all_width: 场地总宽度
    :param all_width: 场地总宽度（Y轴）
    :param group_spacing: 群组间距
    :return: (best_x, best_y, rotated, fits)
    """
    print(f"\n=== 寻找群组最佳位置 ===")
    print(f"群组类型: {group.get('module_type', 'Unknown')}")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"已放置群组数量: {len(current_positions)}")
    
    # 尝试正常方向
    normal_width, normal_height = calculate_group_dimensions(group, rotated=False, aisle=group_spacing)
    print(f"正常方向尺寸: {normal_width}m x {normal_height}m")
    
    # 尝试旋转90度
    rotated_width, rotated_height = calculate_group_dimensions(group, rotated=True, aisle=group_spacing)
    print(f"旋转方向尺寸: {rotated_width}m x {rotated_height}m")
    
    # 候选位置列表：(x, y, rotated, width, height)
    candidates = []
    
    # 为正常方向生成候选位置
    normal_positions = generate_candidate_positions(current_positions, all_length, all_width, group_spacing, normal_width, normal_height)
    print(f"正常方向候选位置数量: {len(normal_positions)}")
    
    for i, (x, y) in enumerate(normal_positions):
        normal_fits = can_place_group(
            x,
            y,
            normal_width,
            normal_height,
            current_positions,
            all_length,
            all_width,
            group_spacing,
            rotated=False,
            module_type=module_type,
        )
        if normal_fits:
            candidates.append((x, y, False, normal_width, normal_height))
            print(f"  正常方向位置 {i+1}: ({x:.2f}, {y:.2f}) [可用]")
        else:
            print(f"  正常方向位置 {i+1}: ({x:.2f}, {y:.2f}) [不可用]")
    
    # 为旋转方向生成候选位置
    rotated_positions = generate_candidate_positions(current_positions, all_length, all_width, group_spacing, rotated_width, rotated_height)
    print(f"旋转方向候选位置数量: {len(rotated_positions)}")
    
    for i, (x, y) in enumerate(rotated_positions):
        rotated_fits = can_place_group(
            x,
            y,
            rotated_width,
            rotated_height,
            current_positions,
            all_length,
            all_width,
            group_spacing,
            rotated=True,
            module_type=module_type,
        )
        if rotated_fits:
            candidates.append((x, y, True, rotated_width, rotated_height))
            print(f"  旋转方向位置 {i+1}: ({x:.2f}, {y:.2f}) [可用]")
        else:
            print(f"  旋转方向位置 {i+1}: ({x:.2f}, {y:.2f}) [不可用]")
    
    print(f"\n总候选方案数量: {len(candidates)}")
    
    if not candidates:
        print("无法找到合适的放置位置！")
        return None, None, False, False
    
    # 选择最佳位置（优化策略：优先选择能够紧凑排列的位置）
    # 计算每个候选位置的紧凑度得分，优先选择能够填补空隙的位置
    def calculate_compactness_score(candidate):
        x, y, rotated, width, height = candidate
        rotated_penalty = calculate_rotation_penalty(rotated, current_positions, all_length, all_width)
        if not current_positions:
            return (rotated_penalty, 0, 0, 0, 0, 0, 0, 0)
        
        position_score = (y, x)
        gap_fill_score = 0
        footprint_width = width
        footprint_height = height
        mixed_orientation_contacts = 0
        
        left_adjacent = False
        for pos_info in current_positions:
            if isinstance(pos_info, dict):
                px, py, pw, ph = pos_info['x'], pos_info['y'], pos_info['length'], pos_info['width']
            else:
                px, py, pw, ph = pos_info
            footprint_width = max(footprint_width, x + width, px + pw)
            footprint_height = max(footprint_height, y + height, py + ph)
            if abs(px + pw - x) < 0.1 and not (y + height <= py or y >= py + ph):
                left_adjacent = True
                if bool(pos_info.get('rotated', False)) != rotated:
                    mixed_orientation_contacts += 1
                break
        
        top_adjacent = False
        for pos_info in current_positions:
            if isinstance(pos_info, dict):
                px, py, pw, ph = pos_info['x'], pos_info['y'], pos_info['length'], pos_info['width']
            else:
                px, py, pw, ph = pos_info
            if abs(py + ph - y) < 0.1 and not (x + width <= px or x >= px + pw):
                top_adjacent = True
                if bool(pos_info.get('rotated', False)) != rotated:
                    mixed_orientation_contacts += 1
                break
        
        if left_adjacent and top_adjacent:
            gap_fill_score = 0
        elif left_adjacent or top_adjacent:
            gap_fill_score = 1
        else:
            gap_fill_score = 2
        
        footprint_area = footprint_width * footprint_height
        length_utilization = footprint_width / max(all_length, 1e-6)
        width_utilization = footprint_height / max(all_width, 1e-6)
        spread_score = min(length_utilization, width_utilization)
        balance_penalty = abs(length_utilization - width_utilization)
        # rotated_penalty 提到最前面：空间充足时避免不必要旋转
        return (
            rotated_penalty,
            gap_fill_score,
            mixed_orientation_contacts,
            -spread_score,
            -footprint_area,
            balance_penalty,
            position_score[0],
            position_score[1],
        )
    
    # 按紧凑度排序，然后按左上角优先
    # 打印所有候选位置的紧凑度得分
    print("\n候选位置紧凑度分析:")
    for candidate in candidates:
        score = calculate_compactness_score(candidate)
        print(f"  位置({candidate[0]}, {candidate[1]}) 旋转:{candidate[2]} 紧凑度得分:{score}")
    
    best_candidate = min(candidates, key=lambda c: calculate_compactness_score(c))
    print(f"选择最佳位置: ({best_candidate[0]}, {best_candidate[1]}), 旋转: {best_candidate[2]}")
    
    return best_candidate[0], best_candidate[1], best_candidate[2], True

def generate_candidate_positions(current_positions, all_length, all_width, group_spacing, group_width=None, group_height=None):
    """
    生成候选放置位置（修复版：考虑群组实际尺寸）
    
    :param current_positions: 已放置群组的位置列表
    :param all_length: 场地总长度（X轴）
    :param all_width: 场地总宽度（Y轴）
    :param group_spacing: 群组间距
    :param group_width: 待放置群组的宽度（用于边界检查）
    :param group_height: 待放置群组的高度（用于边界检查）
    :return: 候选位置列表 [(x, y), ...]
    """
    candidates = []
    
    # 起始位置（左上角）- 只有在群组能放下时才添加
    if group_width is None or group_height is None or (group_width <= all_length and group_height <= all_width):
        candidates.append((0, 0))
    
    # 基于已放置群组生成新的候选位置
    for pos_info in current_positions:
        if isinstance(pos_info, dict):
            x, y, length, width = pos_info['x'], pos_info['y'], pos_info['length'], pos_info['width']
        else:
            x, y, length, width = pos_info
        
        # 右侧位置（紧贴或有间距）
        right_x = x + length + group_spacing
        if group_width is None or right_x + group_width <= all_length:
            if group_height is None or y + group_height <= all_width:
                candidates.append((right_x, y))
        
        # 下方位置（紧贴或有间距）
        bottom_y = y + width + group_spacing
        if group_width is None or x + group_width <= all_length:
            if group_height is None or bottom_y + group_height <= all_width:
                candidates.append((x, bottom_y))
        
        # 右下角位置
        if group_width is None or right_x + group_width <= all_length:
            if group_height is None or bottom_y + group_height <= all_width:
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
                    
                    if group_width is None or tight_right_x + group_width <= all_length:
                        if group_height is None or other_y + group_height <= all_width:
                            candidates.append((tight_right_x, other_y))
                    if group_width is None or tight_bottom_x + group_width <= all_length:
                        if group_height is None or y + group_height <= all_width:
                            candidates.append((tight_bottom_x, y))
    
    # 添加网格搜索候选位置（用于填补空隙）
    if group_width and group_height:
        x_positions = build_axis_search_candidates(
            all_length, group_width, current_positions, 'x', spacing=group_spacing
        )
        y_positions = build_axis_search_candidates(
            all_width, group_height, current_positions, 'y', spacing=group_spacing
        )

        for x in x_positions:
            for y in y_positions:
                if x + group_width <= all_length and y + group_height <= all_width:
                    candidates.append((x, y))
    
    # 去重
    unique_candidates = list(set(candidates))
    
    print(f"生成候选位置: {len(unique_candidates)}个（考虑群组尺寸 {group_width}x{group_height}）")
    return sorted(unique_candidates, key=lambda pos: (pos[1], pos[0]))  # 按y，然后x排序


def can_place_group(
    x,
    y,
    group_width,
    group_height,
    current_positions,
    all_length,
    all_width,
    group_spacing,
    rotated=False,
    module_type=None,
):
    """
    检查是否可以在指定位置放置群组（增强版边界检查）
    
    :param x, y: 放置位置
    :param group_width, group_height: 群组尺寸
    :param current_positions: 已放置群组的位置列表
    :param all_length, all_width: 场地尺寸
    :param group_spacing: 群组间距
    :return: 是否可以放置
    """
    # 使用增强的边界检查
    is_valid, errors = enhanced_boundary_check(
        x, y, group_width, group_height, all_length, all_width,
        group_info=f"位置({x:.2f}, {y:.2f}) 尺寸({group_width:.2f}x{group_height:.2f}m)"
    )
    
    if not is_valid:
        print(f"    边界检查失败: {'; '.join(errors)}")
        return False
    
    # 检查是否与已放置的群组重叠（考虑群组间距）
    for i, pos_info in enumerate(current_positions):
        if isinstance(pos_info, dict):
            existing_x, existing_y, existing_width, existing_height = pos_info['x'], pos_info['y'], pos_info['length'], pos_info['width']
            existing_module_type = pos_info.get('module_type')
            existing_rotated = pos_info.get('rotated', False)
        else:
            existing_x, existing_y, existing_width, existing_height = pos_info
            existing_module_type = None
            existing_rotated = False
        
        # 检查矩形重叠（考虑群组间距）
        base_spacing = get_pair_spacing_requirement(module_type, existing_module_type, group_spacing)
        required_spacing = get_orientation_spacing_requirement(
            rotated,
            existing_rotated,
            base_spacing
        )
        overlap = violates_spacing_rule(
            x,
            y,
            group_width,
            group_height,
            existing_x,
            existing_y,
            existing_width,
            existing_height,
            required_spacing
        )
        
        if overlap:
            if required_spacing > 0:
                print(f"    间距检查失败: 新群组({x:.2f}, {y:.2f}, {group_width:.2f}, {group_height:.2f}) 与已放置群组{i+1}({existing_x:.2f}, {existing_y:.2f}, {existing_width:.2f}, {existing_height:.2f}) 间距不足{required_spacing}m")
            else:
                print(f"    重叠检查失败: 新群组({x:.2f}, {y:.2f}, {group_width:.2f}, {group_height:.2f}) 与已放置群组{i+1}({existing_x:.2f}, {existing_y:.2f}, {existing_width:.2f}, {existing_height:.2f}) 发生重叠")
            return False
    
    return True

def calculate_smart_layout(groups_config, aisle, all_width, all_length, modules_selection=None):
    """
    智能布局计算函数，支持群组旋转和多方向布局
    
    :param groups_config: 群组配置列表
    :param aisle: 过道宽度
    :param all_width: 场地总宽度（Y轴）
    :param all_length: 场地总长度（X轴）
    :return: (fits, positions, rotations)
    """
    # 导入CSV导出器
    try:
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '03_visualization'))
        from layout_csv_exporter import LayoutCSVExporter
        csv_export_available = True
    except ImportError:
        print("警告: 无法导入CSV导出器，跳过CSV导出功能")
        csv_export_available = False
        # 布局可行性预检查
    is_feasible, feasibility_report = validate_layout_before_placement(groups_config, all_length, all_width)
    if not is_feasible:
        print(f"[失败] 布局可行性检查失败，无法继续")
        for error in feasibility_report['errors']:
            print(f"  - {error}")
        return False, [], []
    
    # 空间优化预检查
    print(f"\n=== 空间优化预检查 ===")
    try:
        space_feasible, optimized_config, space_analysis = enhanced_space_check(groups_config, all_length, all_width, aisle)
        if not space_feasible:
            print(f"[警告] 空间利用率偏高: {space_analysis['utilization_rate']:.1f}%")
            print(f"建议在布局过程中采用更紧凑的策略")
    except Exception as e:
        print(f"空间预检查失败: {e}，继续使用标准布局")
    
    if not groups_config:
        return True, [], []
    
    positions = []  # 存储位置 (x, y)
    rotations = []  # 存储是否旋转
    current_positions = []  # 存储已放置群组的完整信息 (x, y, width, height)
    
    # 检查是否有自适应间距设置（来自重试机制）
    adaptive_spacing = None
    try:
        if 'ADAPTIVE_SPACING' in os.environ:
            adaptive_spacing = float(os.environ.get('ADAPTIVE_SPACING'))
            retry_count = int(os.environ.get('RETRY_COUNT', 0))
            print(f"检测到自适应间距设置: {adaptive_spacing:.1f}m (重试第{retry_count}次)")
    except (ValueError, TypeError):
        adaptive_spacing = None
    
    # 计算模块间间距
    if modules_selection:
        # 处理不同的 modules_selection 格式
        modules_dict = {}
        
        if isinstance(modules_selection, dict):
            # 格式1: {module_name: (module, count), ...} - 来自solution_optimizer
            for module_name, (module, count) in modules_selection.items():
                modules_dict[module_name] = count
        elif isinstance(modules_selection, list):
            # 格式2: [{'module': mod, 'quantity': count}, ...] - 来自其他地方
            for item in modules_selection:
                if isinstance(item['module'], dict):
                    module_name = item['module']['name']
                else:
                    module_name = item['module']  # 如果module直接是字符串
                quantity = item['quantity']
                modules_dict[module_name] = quantity
        else:
            print(f"警告: 未知的modules_selection格式: {type(modules_selection)}")
            modules_dict = {}
        
        inter_module_spacing = determine_inter_module_spacing(modules_dict)
    else:
        inter_module_spacing = adaptive_spacing if adaptive_spacing is not None else 0.0  # 默认采用紧密贴合
    
    # 检查是否所有群组都是模块A
    all_module_a = all(group['module']['name'] == 'A' for group in groups_config)
    default_spacing = 0.0  # 默认群组间不留额外间距
    
    print(f"\n=== 智能布局计算开始 ===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"群组数量: {len(groups_config)}")
    print(f"过道宽度: {aisle}m")
    print(f"默认群组间距: {default_spacing}m")
    print(f"不同模块类型间距: {inter_module_spacing}m")
    print(f"支持功能: 群组旋转90度, 多方向空间检测")
    
    i = 0
    while i < len(groups_config):
        group = groups_config[i]
        mod = group['module']
        
        # 检查是否需要与不同模块类型保持智能间距
        needs_inter_module_spacing = False
        if current_positions and modules_selection and inter_module_spacing > 0:
            for pos_info in current_positions:
                if 'module_type' in pos_info and pos_info['module_type'] != mod['name']:
                    needs_inter_module_spacing = True
                    break
        
        # 根据模块类型和智能间距规则设置群组间距
        if needs_inter_module_spacing:
            # 不同模块类型之间使用智能间距规则
            current_group_spacing = inter_module_spacing
            print(f"应用智能间距规则: {inter_module_spacing}m（不同模块类型间）")
        elif mod['name'] == 'A':
            current_group_spacing = 2.0  # 模块A组团横向最小间距 2m，纵向由专用逻辑控制为 0m
        elif mod['name'] == 'B':
            current_group_spacing = 2.0  # B 同类组团横向相邻时保留 2m，纵向堆叠由专用逻辑决定
        elif mod['name'] == 'C':
            current_group_spacing = 1.5  # 模块C所有群组之间横纵间距 1.5m
        elif mod['name'] == 'F':
            current_group_spacing = 1.5  # 模块F横向组团与同类群组外间距按 1.5m 控制
        elif mod['name'] == 'G':
            current_group_spacing = 1.5  # 模块G为单体布局，横纵外间距统一保持 1.5m
        else:
            current_group_spacing = default_spacing
        
        # 根据模块类型和是否需要智能间距选择合适的位置寻找方法
        if mod['name'] == 'A':
            # 模块A使用专门的布局处理器，考虑layout_priority
            from module_a_layout_handler import find_module_a_position_with_priority
            print(f"使用模块A专用逻辑寻找位置，考虑布局优先级")
            best_x, best_y, rotated, fits = find_module_a_position_with_priority(
                group, current_positions, all_length, all_width, current_group_spacing
            )
        elif mod['name'] == 'B':
            # 模块B使用专用的位置寻找逻辑
            from module_b_spacing_handler import find_module_b_position
            print(f"使用模块B专用逻辑寻找位置")
            best_x, best_y, rotated, fits = find_module_b_position(
                group, current_positions, all_length, all_width, current_group_spacing
            )
        elif needs_inter_module_spacing:
            # 不同模块类型间仅在确实启用额外间距时，才使用智能间距逻辑
            from universal_smart_position_finder import find_position_with_smart_spacing
            print(f"使用智能间距逻辑寻找{mod['name']}模块位置")
            best_x, best_y, rotated, fits = find_position_with_smart_spacing(
                group, current_positions, all_length, all_width, 
                inter_module_spacing, current_group_spacing, mod['name']
            )
        elif mod['name'] == 'C':
            # 模块C所有群组间横纵均1.5m间距，统一使用标准位置寻找逻辑
            print(f"使用标准逻辑寻找模块C位置，间距{current_group_spacing}m")
            best_x, best_y, rotated, fits = find_best_position(
                group, current_positions, all_length, all_width, current_group_spacing, mod['name']
            )
        else:
            # 其他模块使用标准的位置寻找逻辑
            print(f"使用标准逻辑寻找{mod['name']}模块位置")
            best_x, best_y, rotated, fits = find_best_position(
                group, current_positions, all_length, all_width, current_group_spacing, mod['name']
            )
        
        if not fits:
            if mod['name'] == 'A':
                from module_a_organizer import decompose_module_a_group

                fallback_groups = decompose_module_a_group(group)
                if fallback_groups:
                    print(
                        f"\n群组 {i+1}: A模块 {group.get('group_type')} 放置失败，"
                        f"尝试拆分为更小的A组团继续补空"
                    )
                    groups_config[i:i+1] = fallback_groups
                    continue

            if mod['name'] == 'B':
                from module_b_organizer import decompose_module_b_group

                fallback_groups = decompose_module_b_group(group)
                if fallback_groups:
                    print(
                        f"\n群组 {i+1}: B模块 {group.get('group_type')} 放置失败，"
                        f"尝试拆分为更小的B组团继续补空"
                    )
                    groups_config[i:i+1] = fallback_groups
                    continue

            if mod['name'] == 'C':
                from module_c_organizer import decompose_module_c_group

                fallback_groups = decompose_module_c_group(group)
                if fallback_groups:
                    print(
                        f"\n群组 {i+1}: C模块 {group.get('group_type')} 放置失败，"
                        f"尝试拆分为更小的C组团继续补空"
                    )
                    groups_config[i:i+1] = fallback_groups
                    continue

            print(f"\n群组 {i+1}: {mod['name']}模块 - 无法放置，布局失败")
            
            # 调用空间优化器进行分析
            print(f"\n=== 启动空间优化分析 ===")
            try:
                analysis = analyze_space_utilization(groups_config, all_length, all_width, aisle)
                remaining_modules = len(groups_config) - i
                
                # 获取优化建议
                suggestions = suggest_layout_optimization(
                    analysis['utilization_rate'], 
                    mod['name'], 
                    remaining_modules
                )
                
                if analysis['utilization_rate'] > 85:
                    print(f"\n优化建议:")
                    print(f"- 当前空间利用率过高 ({analysis['utilization_rate']:.1f}%)")
                    print(f"- 建议减少模块数量或调整群组配置")
                    print(f"- 考虑增加场地尺寸以容纳更多模块")
                else:
                    print(f"\n布局问题分析:")
                    print(f"- 空间利用率正常 ({analysis['utilization_rate']:.1f}%)")
                    print(f"- 问题可能在于模块间距或位置算法")
                    
                    # 尝试自适应间距优化
                    if analysis['utilization_rate'] < 70:
                        print(f"\n尝试自适应间距优化...")
                        adaptive_spacing = calculate_adaptive_spacing(
                            {mod['name']: remaining_modules}, 
                            analysis['total_field_area'], 
                            analysis['required_area']
                        )
                        print(f"建议将间距调整为: {adaptive_spacing:.1f}m")
                
                # 显示所有优化建议
                print(f"\n详细优化建议:")
                for suggestion in suggestions:
                    print(f"- {suggestion}")
                     
            except Exception as e:
                print(f"空间分析失败: {e}")
            
            return False, [], []
        
        # 计算最终尺寸
        final_width, final_height = calculate_group_dimensions(group, rotated=rotated, aisle=aisle)
        
        # 记录位置和旋转状态
        positions.append((best_x, best_y))
        rotations.append(rotated)
        current_positions.append({
            'x': best_x, 
            'y': best_y, 
            'length': final_width,  # x轴尺寸，对应length
            'width': final_height,  # y轴尺寸，对应width
            'height': final_height, # 保持兼容性
            'module_type': mod['name'],
            'group_type': group.get('group_type'),
            'rotated': rotated
        })
        
        # 确保群组配置中包含位置、旋转和群组类型信息
        group['position'] = (best_x, best_y)
        group['rotated'] = rotated
        # 保持原有的group_type信息（如果存在）
        if 'group_type' not in group and hasattr(group, 'group_type'):
            # 从原始群组配置中获取group_type
            pass  # group_type应该已经在原始配置中
        
        # 输出调试信息
        rotation_info = "(旋转90°)" if rotated else "(正常方向)"
        print(f"\n群组 {i+1}: {mod['name']}模块 {rotation_info}")
        
        # 统一使用length和width属性
        module_length = mod['length'] / 1000  # x轴尺寸
        module_width = mod['width'] / 1000    # y轴尺寸
        
        print(f"  模块尺寸: {module_length:.2f}m x {module_width:.2f}m")
        print(f"  群组配置: {group['rows']}行 x {group['cols']}列")
        if mod['name'] == 'A':
            print(f"  群组类型: {group.get('group_type', 'Unknown')}")
            print(f"  布局优先级: {group.get('layout_priority', 'Unknown')}")
        print(f"  最终尺寸: {final_width:.2f}m x {final_height:.2f}m")
        print(f"  放置位置: x={best_x:.2f}m, y={best_y:.2f}m")
        i += 1
    
    # 计算实际使用尺寸和利用率
    if current_positions:
        max_x = max(pos_info['x'] + pos_info['length'] for pos_info in current_positions)
        max_y = max(pos_info['y'] + pos_info['width'] for pos_info in current_positions)
        
        length_utilization = (max_x / all_length) * 100
        width_utilization = (max_y / all_width) * 100
        
        print(f"\n=== 智能布局计算完成 ===")
        print(f"实际使用尺寸: {max_x:.2f}m x {max_y:.2f}m")
        print(f"场地利用率: {length_utilization:.1f}% x {width_utilization:.1f}%")
        
        if length_utilization < 80:
            print(f"提示：长度利用率较低 ({length_utilization:.1f}%)，布局已优化")
        if width_utilization < 80:
            print(f"提示：宽度利用率较低 ({width_utilization:.1f}%)，布局已优化")
    
    # 导出布局数据到CSV文件
    if csv_export_available:
        try:
            csv_exporter = LayoutCSVExporter()
            
            # 添加所有模块群组的位置信息
            for i, (group, position, rotated) in enumerate(zip(groups_config, positions, rotations)):
                mod = group['module']
                x, y = position
                final_width, final_height = calculate_group_dimensions(group, rotated=rotated, aisle=aisle)
                
                csv_exporter.add_module_group(
                    group_id=i+1,
                    module_type=mod['name'],
                    x=x,
                    y=y,
                    width=final_width,
                    height=final_height,
                    rows=group['rows'],
                    cols=group['cols'],
                    is_rotated=rotated,
                    module_count=group.get('module_count', group['rows'] * group['cols'])
                )
            
            # 导出到CSV文件
            csv_filename = csv_exporter.export_to_csv(
                site_width=all_length,
                site_height=all_width
            )
            
            print(f"\n=== CSV导出完成 ===")
            print(f"布局数据已导出到: {csv_filename}")
            
            # 显示分析报告
            overlaps = csv_exporter.check_overlaps()
            violations = csv_exporter.check_boundary_violations(all_length, all_width)
            if overlaps:
                print(f"[警告] 发现 {len(overlaps)} 个重叠问题")
                for overlap in overlaps[:3]:  # 显示前3个
                    print(f"  群组 {overlap['group1']} 与群组 {overlap['group2']} 重叠，面积: {overlap['overlap_area']} m^2")
            if violations:
                print(f"[警告] 发现 {len(violations)} 个边界溢出问题")
                for violation in violations[:3]:  # 显示前3个
                    print(f"  群组 {violation['group_id']} 超出边界: {', '.join(violation['violations'])}")
            if not overlaps and not violations:
                print(f"[通过] 布局检查通过，无重叠和溢出问题")
            
        except Exception as e:
            print(f"CSV导出失败: {e}")
    else:
        print("跳过CSV导出功能（导出器不可用）")
    
    return True, positions, rotations
