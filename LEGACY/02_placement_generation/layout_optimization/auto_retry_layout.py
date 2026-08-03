import sys
import os

# 添加路径以导入其他模块
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '05_config_and_tools'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'inter_module_rules'))

from advanced_space_optimizer import analyze_space_utilization
from flexible_spacing_manager import (
    calculate_adaptive_spacing, 
    optimize_spacing_for_layout_failure,
    create_emergency_compact_strategy
)
from module_spacing_manager import determine_inter_module_spacing


def _normalize_modules_selection(modules_selection):
    """统一模块选择格式，便于读取当前基础间距设置。"""
    normalized = {}
    if not modules_selection:
        return normalized

    if isinstance(modules_selection, dict):
        for module_name, value in modules_selection.items():
            if isinstance(value, tuple):
                normalized[module_name] = value[1]
            else:
                normalized[module_name] = value
        return normalized

    if isinstance(modules_selection, list):
        for item in modules_selection:
            module_info = item.get('module')
            module_name = module_info['name'] if isinstance(module_info, dict) else module_info
            normalized[module_name] = item.get('quantity', 0)

    return normalized

def calculate_smart_layout_with_retry(groups_config, aisle, all_width, all_length, 
                                    modules_selection=None, max_retries=3):
    """
    带重试机制的智能布局计算
    
    :param groups_config: 群组配置列表
    :param aisle: 过道宽度
    :param all_width: 场地总宽度
    :param all_length: 场地总长度
    :param modules_selection: 模块选择信息
    :param max_retries: 最大重试次数
    :return: (fits, positions, rotations)
    """
    from smart_layout_optimizer import calculate_smart_layout
    
    print(f"\n=== 启动自动重试布局系统 ===")
    print(f"最大重试次数: {max_retries}")
    
    # 保存原始配置
    original_groups_config = [group.copy() for group in groups_config]
    
    # 第一次尝试：使用原始配置
    print(f"\n第1次尝试：使用原始配置")
    fits, positions, rotations = calculate_smart_layout(
        groups_config, aisle, all_width, all_length, modules_selection
    )
    
    if fits:
        print(f"第1次尝试成功！")
        return fits, positions, rotations
    
    # 分析失败原因
    analysis = analyze_space_utilization(groups_config, all_length, all_width, aisle)
    print(f"\n失败分析: 空间利用率 {analysis['utilization_rate']:.1f}%")

    normalized_modules_selection = _normalize_modules_selection(modules_selection)
    base_spacing = determine_inter_module_spacing(normalized_modules_selection)
    if base_spacing <= 0:
        print("当前基础模块间距已为0m，重试不再注入额外间距，直接返回失败结果。")
        return False, [], []
    
    # 重试循环
    for retry_count in range(1, max_retries + 1):
        print(f"\n第{retry_count + 1}次尝试：优化间距策略")
        
        # 重置为原始配置
        groups_config = [group.copy() for group in original_groups_config]
        
        # 根据重试次数选择不同的优化策略
        if retry_count == 1:
            # 第一次重试：自适应间距
            strategy = "自适应间距"
            suggested_spacing = calculate_adaptive_spacing(
                modules_selection or {}, 
                analysis['total_field_area'], 
                analysis['required_area']
            )
            optimized_spacing = min(base_spacing, suggested_spacing)
        elif retry_count == 2:
            # 第二次重试：渐进式减少间距
            strategy = "渐进式减少间距"
            optimized_spacing = max(0.0, base_spacing * (0.5 ** retry_count))
        else:
            # 最后一次重试：紧急紧凑策略
            strategy = "紧急紧凑策略"
            optimized_spacing = 0.0

        if optimized_spacing >= base_spacing:
            print(f"策略 {strategy} 无法进一步压缩当前间距 {base_spacing:.1f}m，跳过后续重试。")
            break
        
        print(f"策略: {strategy}，间距: {optimized_spacing:.1f}m")
        
        # 应用优化策略（这里需要修改布局算法以接受动态间距）
        # 由于当前架构限制，我们通过环境变量传递优化参数
        os.environ['ADAPTIVE_SPACING'] = str(optimized_spacing)
        os.environ['RETRY_COUNT'] = str(retry_count)
        
        # 重新尝试布局
        fits, positions, rotations = calculate_smart_layout(
            groups_config, aisle, all_width, all_length, modules_selection
        )
        
        if fits:
            print(f"第{retry_count + 1}次尝试成功！使用策略: {strategy}")
            # 清理环境变量
            os.environ.pop('ADAPTIVE_SPACING', None)
            os.environ.pop('RETRY_COUNT', None)
            return fits, positions, rotations
        else:
            print(f"第{retry_count + 1}次尝试失败")
    
    # 所有重试都失败
    print(f"\n所有重试尝试都失败了")
    print(f"建议:")
    print(f"1. 减少模块数量")
    print(f"2. 增加场地尺寸")
    print(f"3. 调整模块配置")
    
    # 清理环境变量
    os.environ.pop('ADAPTIVE_SPACING', None)
    os.environ.pop('RETRY_COUNT', None)
    
    return False, [], []

def get_adaptive_spacing_from_env(default_spacing=6.0):
    """
    从环境变量获取自适应间距
    
    :param default_spacing: 默认间距
    :return: 间距值
    """
    try:
        adaptive_spacing = float(os.environ.get('ADAPTIVE_SPACING', default_spacing))
        retry_count = int(os.environ.get('RETRY_COUNT', 0))
        
        if retry_count > 0:
            print(f"使用自适应间距: {adaptive_spacing:.1f}m (重试第{retry_count}次)")
        
        return adaptive_spacing
    except (ValueError, TypeError):
        return default_spacing

def should_use_compact_strategy():
    """
    检查是否应该使用紧凑策略
    
    :return: 是否使用紧凑策略
    """
    retry_count = int(os.environ.get('RETRY_COUNT', 0))
    return retry_count >= 2

def get_progressive_spacing_reduction(base_spacing, group_index, total_groups):
    """
    获取渐进式间距减少值
    
    :param base_spacing: 基础间距
    :param group_index: 当前群组索引
    :param total_groups: 总群组数
    :return: 调整后的间距
    """
    retry_count = int(os.environ.get('RETRY_COUNT', 0))
    
    if retry_count == 0:
        return base_spacing
    
    # 根据重试次数和群组进度调整间距
    progress = group_index / max(1, total_groups - 1)
    reduction_factor = 1.0 - (retry_count * 0.3) - (progress * 0.2)
    
    adjusted_spacing = max(0.5, base_spacing * reduction_factor)
    
    return adjusted_spacing

def create_retry_report(retry_attempts, final_result):
    """
    创建重试报告
    
    :param retry_attempts: 重试尝试列表
    :param final_result: 最终结果
    :return: 报告字符串
    """
    report = ["\n=== 自动重试布局报告 ==="]
    
    for i, attempt in enumerate(retry_attempts):
        status = "成功" if attempt['success'] else "失败"
        report.append(f"第{i+1}次尝试: {attempt['strategy']} - {status}")
        if 'spacing' in attempt:
            report.append(f"  使用间距: {attempt['spacing']:.1f}m")
    
    if final_result:
        report.append("\n最终结果: 布局成功")
    else:
        report.append("\n最终结果: 布局失败")
        report.append("建议手动调整配置")
    
    return "\n".join(report)
