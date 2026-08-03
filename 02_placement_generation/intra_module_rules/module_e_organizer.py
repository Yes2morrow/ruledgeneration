import math


E_HORIZONTAL_GAP = 0.0
E_VERTICAL_GAP = 1.5
MAX_E_MODULES_PER_GROUP = 16
MAX_E_MODULES_PER_ROW = 8
MODULE_E_INFO = {
    'type': '均衡型',
    'beds': 3,
    'cost': 2133,
    'priority': 1,
    'length': 3000,
    'width': 5500,
    'name': 'E',
    'visual_ready': True
}


def _build_e_row_subgroups(module_e_info: dict, row_quantity: int, y_offset: float):
    """
    按“优先双模块镜像组团，其次单模块”的规则生成一行 E 子组团。
    """
    module_length = module_e_info['length'] / 1000.0
    module_width = module_e_info['width'] / 1000.0

    subgroups = []
    x_offset = 0.0
    remaining = row_quantity

    while remaining >= 2:
        subgroups.append({
            'x': x_offset,
            'y': y_offset,
            'length': module_length * 2,
            'width': module_width,
            'group_type': 'E_pair',
            'module_count': 2
        })
        x_offset += module_length * 2
        remaining -= 2

    if remaining == 1:
        subgroups.append({
            'x': x_offset,
            'y': y_offset,
            'length': module_length,
            'width': module_width,
            'group_type': 'E_single',
            'module_count': 1
        })
        x_offset += module_length

    return subgroups, x_offset


def organize_module_e(quantity: int):
    """
    生成模块 E 的群组规则。

    规则说明：
    1. 优先使用 2 个 E 横向紧贴镜像后的组团，对应 `moduleE1.png`
    2. 奇数余量使用单个 E 单元，对应 `moduleEsingle.png`
    3. 所有 E 排布默认横向间距为 0，纵向行间距为 1.5m
    4. 单个大群组最多承载 16 个 E，超过时拆分为多个分页群组
    """
    if quantity <= 0:
        return []

    module_e_info = MODULE_E_INFO
    groups = []
    remaining_quantity = quantity

    while remaining_quantity > 0:
        current_group_quantity = min(remaining_quantity, MAX_E_MODULES_PER_GROUP)

        if current_group_quantity <= MAX_E_MODULES_PER_ROW:
            row_quantities = [current_group_quantity]
        else:
            row_count = math.ceil(current_group_quantity / MAX_E_MODULES_PER_ROW)
            row_quantities = []
            remaining_in_group = current_group_quantity
            for _ in range(row_count):
                row_quantity = min(MAX_E_MODULES_PER_ROW, remaining_in_group)
                row_quantities.append(row_quantity)
                remaining_in_group -= row_quantity

        subgroups = []
        total_length = 0.0
        total_width = 0.0
        current_y = 0.0

        for row_index, row_quantity in enumerate(row_quantities):
            row_subgroups, row_length = _build_e_row_subgroups(module_e_info, row_quantity, current_y)
            subgroups.extend(row_subgroups)
            total_length = max(total_length, row_length)
            total_width = current_y + module_e_info['width'] / 1000.0

            if row_index < len(row_quantities) - 1:
                current_y += module_e_info['width'] / 1000.0 + E_VERTICAL_GAP

        groups.append({
            'module': module_e_info,
            'rows': len(row_quantities),
            'cols': 1,
            'count': 1,
            'group_type': 'E_group',
            'layout_priority': 'preferred_pair',
            'vertical_gap': E_VERTICAL_GAP,
            'horizontal_gap': E_HORIZONTAL_GAP,
            'module_count': current_group_quantity,
            'subgroups': subgroups,
            'total_length': total_length,
            'total_width': total_width
        })

        remaining_quantity -= current_group_quantity

    return groups
