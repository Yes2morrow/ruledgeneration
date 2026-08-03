# -*- coding: utf-8 -*-
"""
灵活间距管理器
用于在空间不足时动态调整模块间距
创建时间: 2025-08-18
版本: v1.0
"""

import builtins
import os
from typing import Dict, List

from module_spacing_manager import (
    get_adaptive_base_spacing,
    get_minimum_required_spacing,
)


VERBOSE_LAYOUT = os.environ.get("LAYOUT_VERBOSE", "0") == "1"


def print(*args, **kwargs):
    if VERBOSE_LAYOUT:
        builtins.print(*args, **kwargs)

def calculate_adaptive_spacing(modules_selection: Dict[str, int], 
                             field_area: float, 
                             required_area: float,
                             base_spacing: float = None) -> float:
    """
    根据空间利用率动态调整模块间距
    
    :param modules_selection: 模块选择字典
    :param field_area: 场地总面积
    :param required_area: 模块所需面积
    :param base_spacing: 基础间距
    :return: 调整后的间距
    """
    if base_spacing is None:
        base_spacing = get_adaptive_base_spacing()

    utilization_rate = (required_area / field_area) * 100
    
    print(f"\n=== 自适应间距计算 ===")
    print(f"空间利用率: {utilization_rate:.1f}%")
    print(f"基础间距: {base_spacing}m")
    
    # 根据空间利用率调整间距
    if utilization_rate > 80:
        # 空间紧张，大幅减少间距
        adjusted_spacing = max(1.0, base_spacing * 0.3)
        print(f"空间紧张，间距调整为: {adjusted_spacing}m")
    elif utilization_rate > 70:
        # 空间较紧，适度减少间距
        adjusted_spacing = max(1.5, base_spacing * 0.5)
        print(f"空间较紧，间距调整为: {adjusted_spacing}m")
    elif utilization_rate > 60:
        # 空间正常，轻微减少间距
        adjusted_spacing = max(2.0, base_spacing * 0.7)
        print(f"空间正常，间距调整为: {adjusted_spacing}m")
    else:
        # 空间充足，保持原间距
        adjusted_spacing = base_spacing
        print(f"空间充足，保持原间距: {adjusted_spacing}m")
    
    return adjusted_spacing

def get_progressive_spacing_strategy(current_group_index: int, 
                                   total_groups: int, 
                                   base_spacing: float) -> float:
    """
    获取渐进式间距策略
    随着群组数量增加，逐渐减少间距
    
    :param current_group_index: 当前群组索引
    :param total_groups: 总群组数
    :param base_spacing: 基础间距
    :return: 当前群组的间距
    """
    # 计算进度比例
    progress = current_group_index / total_groups
    
    # 随着进度增加，间距逐渐减少
    if progress < 0.5:
        # 前半部分，保持较大间距
        spacing_factor = 1.0
    elif progress < 0.8:
        # 中间部分，适度减少间距
        spacing_factor = 0.7
    else:
        # 后半部分，大幅减少间距
        spacing_factor = 0.4
    
    adjusted_spacing = max(1.0, base_spacing * spacing_factor)
    
    if current_group_index % 5 == 0:  # 每5个群组打印一次
        print(f"群组 {current_group_index+1}/{total_groups}: 渐进间距 {adjusted_spacing:.1f}m")
    
    return adjusted_spacing

def optimize_spacing_for_layout_failure(failed_module_type: str, 
                                       current_spacing: float,
                                       attempt_count: int) -> float:
    """
    在布局失败时优化间距
    
    :param failed_module_type: 失败的模块类型
    :param current_spacing: 当前间距
    :param attempt_count: 尝试次数
    :return: 优化后的间距
    """
    min_spacing = get_minimum_required_spacing(failed_module_type)
    
    # 根据尝试次数逐步减少间距
    reduction_factor = 0.8 ** attempt_count  # 每次尝试减少20%
    new_spacing = max(min_spacing, current_spacing * reduction_factor)
    
    print(f"\n=== 间距优化 (尝试 {attempt_count}) ===")
    print(f"模块类型: {failed_module_type}")
    print(f"原间距: {current_spacing:.1f}m")
    print(f"新间距: {new_spacing:.1f}m")
    print(f"最小间距: {min_spacing:.1f}m")
    
    return new_spacing

def create_emergency_compact_strategy(modules_selection: Dict[str, int]) -> Dict[str, float]:
    """
    创建紧急紧凑策略
    为每种模块类型设置最小间距
    
    :param modules_selection: 模块选择字典
    :return: 各模块类型的紧急间距配置
    """
    emergency_spacing = {}
    
    for module_name in modules_selection.keys():
        emergency_spacing[module_name] = get_minimum_required_spacing(module_name)
    
    print(f"\n=== 紧急紧凑策略 ===")
    for module_name, spacing in emergency_spacing.items():
        print(f"模块{module_name}: {spacing}m")
    
    return emergency_spacing

def suggest_layout_optimization(utilization_rate: float, 
                              failed_module_type: str,
                              remaining_modules: int) -> List[str]:
    """
    提供布局优化建议
    
    :param utilization_rate: 空间利用率
    :param failed_module_type: 失败的模块类型
    :param remaining_modules: 剩余模块数量
    :return: 优化建议列表
    """
    suggestions = []
    
    if utilization_rate < 60:
        suggestions.append("空间充足，问题可能在于间距配置过大")
        suggestions.append("建议启用自适应间距策略")
        suggestions.append("考虑使用渐进式间距减少")
    
    if remaining_modules > 5:
        suggestions.append(f"剩余{remaining_modules}个模块，建议使用紧急紧凑策略")
        suggestions.append("考虑将相同类型模块聚集放置")
    
    if failed_module_type == 'C':
        suggestions.append("C模块可以使用更紧密的布局")
        suggestions.append("建议C模块间距减少到0.8m以下")
    
    return suggestions
