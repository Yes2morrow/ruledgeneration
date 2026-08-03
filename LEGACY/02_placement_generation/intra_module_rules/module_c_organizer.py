import math
from core_calculations import modules

def organize_module_c(quantity: int):
    """
    根据用户为模块C定义的特定数学规则生成布局群组。

    规则摘要:
    - 基本单位是"组合单元"，由2个C模块垂直镜像构成（2行*1列）。
    - 每个"组合单元"作为一个独立的群组。
    - C模块总数为 Q = 2n，n是"组合单元"的数量。
    - 每个群组都是2行*1列的垂直镜像配置。

    Args:
        quantity (int): 模块C的总数量。

    Returns:
        list: 一个字典列表，每个字典代表一个群组，供 visualization.py 使用。
    """
    if quantity <= 0:
        return []

    # 注意: 模块C数量的奇偶校验已在 core_calculations.py 和 interactive_module_selector.py 中处理。
    # 这里假设传入的 quantity 始终为偶数。

    n = quantity // 2  # "组合单元"的数量
    module_c_info = modules['C']
    
    groups = []
    # 为模块C的群组添加间距配置：垂直无间距，水平无间距（群组内）
    c_group_config = {
        'vertical_gap': 0,    # 垂直无间距，实现紧贴镜像
        'horizontal_gap': 0   # 水平无间距（群组内不需要间距）
    }

    # 为每个"组合单元"创建一个独立的群组（2行*1列）
    for i in range(n):
        groups.append({
            'module': module_c_info,
            'rows': 2,    # 2行：上下垂直镜像
            'cols': 1,    # 1列：每个群组只有1列
            'count': 1,   # 每个群组包含1个"组合单元"
            **c_group_config
        })
            
    return groups