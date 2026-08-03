"""
用于处理大量模块的空间布局优化问题
"""
import math
import sys
import os

# 添加路径以导入其他模块
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '05_config_and_tools'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'inter_module_rules'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'intra_module_rules'))

from arrangement_rules import calculate_aisle_width, get_module_spacing_config
from module_spacing_manager import determine_inter_module_spacing, should_apply_inter_module_spacing

def calculate_total_area_required(groups_config, aisle=2.0):
    """
    计算所有群组所需的总面积
    
    :param groups_config: 群组配置列表
    :param aisle: 通道宽度
    :return: 总面积（平方米）
    """
    total_area = 0
    
    for group in groups_config:
        if not group or 'module' not in group:
            continue
            
        module_info = group['module']
        rows = group.get('rows', 1)
        cols = group.get('cols', 1)
        
        # 获取单个模块的尺寸（转换为米）
        module_length = module_info.get('length', 0.0) / 1000.0
        module_width = module_info.get('width', 0.0) / 1000.0
        
        # 计算群组面积
        group_area = (module_length * cols) * (module_width * rows)
        total_area += group_area
    
    return total_area

def analyze_space_utilization(groups_config, all_length, all_width, aisle=2.0):
    """
    分析空间利用率
    
    :param groups_config: 群组配置列表
    :param all_length: 场地长度
    :param all_width: 场地宽度
    :param aisle: 通道宽度
    :return: 空间利用率分析结果
    """
    total_field_area = all_length * all_width
    required_area = calculate_total_area_required(groups_config, aisle)
    
    utilization_rate = (required_area / total_field_area) * 100
    
    analysis = {
        'total_field_area': total_field_area,
        'required_area': required_area,
        'utilization_rate': utilization_rate,
        'available_space': total_field_area - required_area,
        'is_feasible': utilization_rate <= 85  # 预留15%的空间用于间距和通道
    }
    
    print(f"\n=== 空间利用率分析 ===")
    print(f"场地总面积: {total_field_area:.2f}平方米")
    print(f"模块所需面积: {required_area:.2f}平方米")
    print(f"空间利用率: {utilization_rate:.1f}%")
    print(f"剩余可用空间: {analysis['available_space']:.2f}平方米")
    print(f"布局可行性: {'可行' if analysis['is_feasible'] else '不可行'}")
    
    return analysis

def optimize_module_arrangement(groups_config, all_length, all_width):
    """
    优化模块排列，提高空间利用率
    
    :param groups_config: 群组配置列表
    :param all_length: 场地长度
    :param all_width: 场地宽度
    :return: 优化后的群组配置
    """
    print(f"\n=== 开始空间优化 ===")
    
    # 首先分析当前空间利用率
    analysis = analyze_space_utilization(groups_config, all_length, all_width)
    
    if not analysis['is_feasible']:
        print("警告: 当前模块配置可能无法在给定场地内完成布局")
        return suggest_optimization_strategies(groups_config, analysis)
    
    # 按模块类型分组
    module_groups = {}
    for i, group in enumerate(groups_config):
        if group and 'module' in group:
            module_type = group['module']['name']
            if module_type not in module_groups:
                module_groups[module_type] = []
            module_groups[module_type].append((i, group))
    
    print(f"检测到模块类型: {list(module_groups.keys())}")
    
    # 优化建议
    optimized_config = groups_config.copy()
    
    return optimized_config

def suggest_optimization_strategies(groups_config, analysis):
    """
    提供优化策略建议
    
    :param groups_config: 群组配置列表
    :param analysis: 空间分析结果
    :return: 优化建议
    """
    suggestions = []
    
    if analysis['utilization_rate'] > 90:
        suggestions.append("建议减少模块数量或增加场地面积")
    
    if analysis['utilization_rate'] > 85:
        suggestions.append("建议优化群组配置，减少间距要求")
        suggestions.append("考虑使用更紧凑的布局策略")
    
    # 分析模块类型分布
    module_counts = {}
    for group in groups_config:
        if group and 'module' in group:
            module_type = group['module']['name']
            module_counts[module_type] = module_counts.get(module_type, 0) + 1
    
    print(f"\n=== 优化建议 ===")
    print(f"当前模块分布: {module_counts}")
    
    for suggestion in suggestions:
        print(f"- {suggestion}")
    
    return groups_config

def create_compact_layout_strategy(groups_config, all_length, all_width):
    """
    创建紧凑布局策略
    
    :param groups_config: 群组配置列表
    :param all_length: 场地长度
    :param all_width: 场地宽度
    :return: 紧凑布局配置
    """
    print(f"\n=== 创建紧凑布局策略 ===")
    
    # 计算最优的行列配置
    total_groups = len(groups_config)
    
    # 尝试不同的行列组合
    best_config = None
    min_waste = float('inf')
    
    for rows in range(1, int(math.sqrt(total_groups)) + 3):
        cols = math.ceil(total_groups / rows)
        
        # 估算所需空间
        estimated_width = cols * 6  # 假设每个群组平均宽度6米
        estimated_height = rows * 6  # 假设每个群组平均高度6米
        
        if estimated_width <= all_length and estimated_height <= all_width:
            waste = (all_length * all_width) - (estimated_width * estimated_height)
            if waste < min_waste:
                min_waste = waste
                best_config = (rows, cols)
    
    if best_config:
        print(f"推荐布局配置: {best_config[0]}行 x {best_config[1]}列")
        print(f"预计空间浪费: {min_waste:.2f}平方米")
    else:
        print("无法找到合适的紧凑布局配置")
    
    return best_config

def enhanced_space_check(groups_config, all_length, all_width, aisle=2.0):
    """
    增强的空间检查功能
    
    :param groups_config: 群组配置列表
    :param all_length: 场地长度
    :param all_width: 场地宽度
    :param aisle: 通道宽度
    :return: 检查结果和建议
    """
    print(f"\n=== 增强空间检查 ===")
    print(f"场地尺寸: {all_length}m x {all_width}m")
    print(f"群组数量: {len(groups_config)}")
    
    # 执行空间分析
    analysis = analyze_space_utilization(groups_config, all_length, all_width, aisle)
    
    # 创建紧凑布局策略
    compact_config = create_compact_layout_strategy(groups_config, all_length, all_width)
    
    # 提供优化建议
    if not analysis['is_feasible']:
        optimized_config = suggest_optimization_strategies(groups_config, analysis)
        return False, optimized_config, analysis
    
    return True, groups_config, analysis