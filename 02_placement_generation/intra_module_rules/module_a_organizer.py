import math

# 模块A的基本信息（避免循环导入）
module_a_info = {
    'type': '舒适型', 
    'beds': 3, 
    'cost': 4273, 
    'priority': 1, 
    'length': 4600,
    'width': 5600,
    'name': 'A'
}


def _build_a_group(rows: int, cols: int, group_type: str, layout_priority: str):
    """创建标准化的 A 群组配置。"""
    return {
        'module': module_a_info,
        'rows': rows,
        'cols': cols,
        'count': 1,
        'group_type': group_type,
        'layout_priority': layout_priority,
        'vertical_gap': 0.0,
        'horizontal_gap': 0.0,
        'module_count': rows * cols
    }

def organize_module_a(quantity: int):
    """
    模块A重置后的组团规则。

    规则说明：
    1. 单个A模块尺寸为 4.6m(x) x 5.6m(y)。
    2. A2 = 2x2 组团，用于主体填充。
    3. A1 = A2 的纵向一半（2x1）。
    4. A3 = A2 的横向一半（1x2）。
    5. A 组团外部间距为：横向 2m、纵向 0m，由位置寻找器统一控制。

    :param quantity: 模块A的数量（必须为偶数）
    :return: 群组配置列表
    """
    
    if quantity <= 0:
        return []
    
    # 注意: 模块A数量的奇偶校验应在调用前处理
    # 这里假设传入的 quantity 始终为偶数
    
    groups = []
    
    # 优先使用 A2（2x2）主体组团，剩余 2 个模块时用 A1 作为初始次级组团。
    max_group_two_count = quantity // 4
    remaining_modules = quantity % 4
    
    group_one_count = remaining_modules // 2
    
    if max_group_two_count > 0:
        group_two = _build_a_group(2, 2, 'A_group_two', 'interior')
        group_two['count'] = max_group_two_count
        groups.append(group_two)
    
    if group_one_count > 0:
        group_one = _build_a_group(2, 1, 'A_group_one', 'flexible')
        group_one['count'] = group_one_count
        groups.append(group_one)
    
    return groups


def decompose_module_a_group(group: dict):
    """
    当 A 组团在剩余空间放不下时，逐级降级为更小或更扁的组团继续补空。
    """
    group_type = group.get('group_type', 'A_group_one')

    if group_type == 'A_group_two':
        return [
            _build_a_group(2, 1, 'A_group_one', 'flexible'),
            _build_a_group(2, 1, 'A_group_one', 'flexible')
        ]

    if group_type == 'A_group_one':
        return [
            _build_a_group(1, 2, 'A_group_three', 'flexible')
        ]

    return []


def validate_module_a_quantity(quantity: int) -> bool:
    """
    验证模块A数量是否符合规则（必须为偶数）
    
    :param quantity: 模块A的数量
    :return: 是否符合规则
    """
    return quantity > 0 and quantity % 2 == 0


def get_module_a_layout_info(quantity: int) -> dict:
    """
    获取模块A布局的详细信息
    
    :param quantity: 模块A的数量
    :return: 布局信息字典
    """
    if not validate_module_a_quantity(quantity):
        return {
            'valid': False,
            'error': '模块A数量必须为偶数',
            'groups': []
        }
    
    groups = organize_module_a(quantity)
    
    # 统计群组信息
    group_two_count = 0
    group_one_count = 0
    group_three_count = 0
    
    for group in groups:
        if group.get('group_type') == 'A_group_two':
            group_two_count = group['count']
        elif group.get('group_type') == 'A_group_one':
            group_one_count = group['count']
        elif group.get('group_type') == 'A_group_three':
            group_three_count = group['count']
    
    return {
        'valid': True,
        'total_modules': quantity,
        'group_one_count': group_one_count,
        'group_two_count': group_two_count,
        'group_three_count': group_three_count,
        'groups': groups,
        'layout_strategy': {
            'edge_groups': group_one_count,
            'interior_groups': group_two_count,
            'total_groups': group_one_count + group_two_count + group_three_count
        }
    }
