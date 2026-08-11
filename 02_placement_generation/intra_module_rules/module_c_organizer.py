from core_calculations import modules


def _build_c_group(rows: int, cols: int, group_type: str) -> dict:
    """构建模块C群组配置的辅助函数"""
    module_c_info = modules['C']
    return {
        'module': module_c_info,
        'rows': rows,
        'cols': cols,
        'count': 1,
        'group_type': group_type,
        'module_count': rows * cols,
        'vertical_gap': 0,     # 群组内垂直无间距，实现紧贴镜像
        'horizontal_gap': 0,   # 群组内水平无间距
    }


def organize_module_c(quantity: int):
    """
    根据模块C定义的规则生成布局群组，优先使用大面积群组。

    群组层级（面积从大到小）:
    1. C_quad:  4行*2列 = 8个模块，群组间间距1.5m（x轴和y轴）
    2. C_pair:  2行*1列 = 2个模块，群组间间距0m

    布局策略：优先以大面积群组计算，次第尝试小面积群组。

    Args:
        quantity (int): 模块C的总数量（必须为偶数）。

    Returns:
        list: 群组配置字典列表，大面积群组在前。
    """
    if quantity <= 0:
        return []

    groups = []

    # 第一优先级：C_quad（4行*2列 = 8模块）
    n_quad = quantity // 8
    remaining = quantity - n_quad * 8

    for _ in range(n_quad):
        groups.append(_build_c_group(4, 2, 'C_quad'))

    # 第二优先级：C_pair（2行*1列 = 2模块）
    n_pair = remaining // 2

    for _ in range(n_pair):
        groups.append(_build_c_group(2, 1, 'C_pair'))

    return groups


def decompose_module_c_group(group: dict):
    """
    当 C 大组团在剩余空间放不下时，逐级拆分为更小的 C 组团用于补空。

    分解链: C_quad(4x2) -> 4 x C_pair(2x1)
    """
    group_type = group.get('group_type', 'C_pair')

    if group_type == 'C_quad':
        return [
            _build_c_group(2, 1, 'C_pair'),
            _build_c_group(2, 1, 'C_pair'),
            _build_c_group(2, 1, 'C_pair'),
            _build_c_group(2, 1, 'C_pair'),
        ]

    # C_pair 已是最小组合单元，无法继续拆分
    return []
