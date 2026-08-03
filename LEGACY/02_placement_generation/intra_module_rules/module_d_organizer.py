import math
from core_calculations import modules

def organize_module_d(quantity: int):
    """
    根据模块D的特定数学规则生成布局群组。

    规则摘要:
    - 基本单位是"组合单元"，由2个D模块垂直镜像构成（3.6m*3.6m）。
    - D模块总数为 Q，可以是奇数或偶数。
    - 如果Q为偶数，n = Q/2个"组合单元"。
    - 如果Q为奇数，n = (Q-1)/2个"组合单元" + 1个单独的D模块。
    - 如果 n <= 4，则所有"组合单元"排成一行。
    - 如果 4 < n <= 8，则分为上下两排。
    - 如果 n > 8，则扩展为多行，每行最多4个"组合单元"。
    - 群组间垂直无间隔，水平有间隔。

    Args:
        quantity (int): 模块D的总数量。

    Returns:
        list: 一个字典列表，每个字典代表一个群组，供 visualization.py 使用。
    """
    if quantity <= 0:
        return []

    module_d_info = modules['D']
    groups = []
    
    # 为模块D的群组添加配置，实现垂直无间隔，水平有间隔
    d_group_config = {
        'vertical_gap': 0,      # 垂直方向无间隔
        'horizontal_gap': 1.2   # 水平方向间隔（可根据空间类型调整）
    }

    # 计算组合单元数量和剩余单个模块
    n = quantity // 2  # 组合单元数量
    single_modules = quantity % 2  # 剩余单个模块数量
    
    # "组合单元"在绘图逻辑中被视为一个2行1列的群组
    combined_unit_rows = 2
    combined_unit_cols = 1

    # 处理组合单元的布局
    if n > 0:
        if n <= 4:
            # 规则1: n <= 4，创建1个大群组，代表一行n个"组合单元"
            groups.append({
                'module': module_d_info,
                'rows': combined_unit_rows,
                'cols': n,
                'count': 1,
                'module_type': 'D',
                **d_group_config
            })
        elif 4 < n <= 8:
            # 规则2: 4 < n <= 8，创建2个大群组，代表上下两排
            # 第一排（上）
            num_cols_top = math.ceil(n / 2)
            groups.append({
                'module': module_d_info,
                'rows': combined_unit_rows,
                'cols': num_cols_top,
                'count': 1,
                'module_type': 'D',
                **d_group_config
            })
            # 第二排（下）
            num_cols_bottom = n - num_cols_top
            if num_cols_bottom > 0:
                groups.append({
                    'module': module_d_info,
                    'rows': combined_unit_rows,
                    'cols': num_cols_bottom,
                    'count': 1,
                    'module_type': 'D',
                    **d_group_config
                })
        else:  # n > 8
            # 规则扩展: n > 8，创建多个大群组，每行最多4个"组合单元"
            num_full_rows = n // 4
            for _ in range(num_full_rows):
                groups.append({
                    'module': module_d_info,
                    'rows': combined_unit_rows,
                    'cols': 4,
                    'count': 1,
                    'module_type': 'D',
                    **d_group_config
                })
            
            remaining_cols = n % 4
            if remaining_cols > 0:
                groups.append({
                    'module': module_d_info,
                    'rows': combined_unit_rows,
                    'cols': remaining_cols,
                    'count': 1,
                    'module_type': 'D',
                    **d_group_config
                })
    
    # 处理剩余的单个模块D
    if single_modules > 0:
        groups.append({
            'module': module_d_info,
            'rows': 1,
            'cols': 1,
            'count': 1,
            'module_type': 'D',
            'is_single': True,  # 标记为单个模块
            **d_group_config
        })
            
    return groups

def get_module_d_spacing_config(space_type='均衡型'):
    """
    根据空间类型获取模块D的间距配置
    
    Args:
        space_type (str): 空间类型（'经济型', '均衡型', '舒适型'）
    
    Returns:
        dict: 间距配置字典
    """
    spacing_configs = {
        '经济型': {'horizontal_gap': 1.0, 'vertical_gap': 0},
        '均衡型': {'horizontal_gap': 1.2, 'vertical_gap': 0},
        '舒适型': {'horizontal_gap': 1.5, 'vertical_gap': 0}
    }
    
    return spacing_configs.get(space_type, spacing_configs['均衡型'])