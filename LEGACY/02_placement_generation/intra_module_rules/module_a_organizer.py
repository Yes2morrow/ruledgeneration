import math

# 模块A的基本信息（避免循环导入）
module_a_info = {
    'type': '舒适型', 
    'beds': 3, 
    'cost': 4273, 
    'priority': 1, 
    'length': 5600, 
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
    模块A的详细规则制定与修正
    
    规则说明：
    1. 模块A的个数只能是偶数
    2. 群组一（普遍组合）：两个模块A垂直组合，用于水平边缘（左右横向）
    3. 群组二：四个模块A组成2x2正方形，用于场地内部（非边缘）
    4. 群组之间无间隔（vertical_gap: 0, horizontal_gap: 0）
    5. 不同群组有区分标识，便于后续贴图设置
    
    :param quantity: 模块A的数量（必须为偶数）
    :return: 群组配置列表
    """
    
    if quantity <= 0:
        return []
    
    # 注意: 模块A数量的奇偶校验应在调用前处理
    # 这里假设传入的 quantity 始终为偶数
    
    groups = []
    
    # 计算可以组成多少个2x2群组（群组二）
    # 优先使用群组二（内部布局），剩余的使用群组一（边缘布局）
    max_group_two_count = quantity // 4  # 每个群组二需要4个模块
    remaining_modules = quantity % 4
    
    # 如果剩余模块数为2，可以组成1个群组一
    # 如果剩余模块数为0，全部使用群组二
    group_one_count = remaining_modules // 2
    
    # 创建群组二（2x2正方形群组）- 用于内部
    if max_group_two_count > 0:
        group_two = _build_a_group(2, 2, 'A_group_two', 'interior')
        group_two['count'] = max_group_two_count
        groups.append(group_two)
    
    # 创建群组一（2x1垂直组合群组）- 灵活布局
    if group_one_count > 0:
        group_one = _build_a_group(2, 1, 'A_group_one', 'flexible')
        group_one['count'] = group_one_count
        groups.append(group_one)
    
    return groups


def decompose_module_a_group(group: dict):
    """
    当 A 大组团在剩余空间放不下时，拆成更小的 A_group_one 继续补空。
    """
    group_type = group.get('group_type', 'A_group_one')

    if group_type == 'A_group_two':
        return [
            _build_a_group(2, 1, 'A_group_one', 'flexible'),
            _build_a_group(2, 1, 'A_group_one', 'flexible')
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
    
    for group in groups:
        if group.get('group_type') == 'A_group_two':
            group_two_count = group['count']
        elif group.get('group_type') == 'A_group_one':
            group_one_count = group['count']
    
    return {
        'valid': True,
        'total_modules': quantity,
        'group_one_count': group_one_count,  # 群组一数量（2x1）
        'group_two_count': group_two_count,  # 群组二数量（2x2）
        'groups': groups,
        'layout_strategy': {
            'edge_groups': group_one_count,
            'interior_groups': group_two_count,
            'total_groups': group_one_count + group_two_count
        }
    }
