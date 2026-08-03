F_HORIZONTAL_GAP = 1.5
F_VERTICAL_GAP = 0.0
MODULE_F_INFO = {
    'type': '均衡型',
    'beds': 3,
    'cost': 3373,
    'priority': 2,
    'length': 3000,
    'width': 3800,
    'name': 'F',
    'visual_ready': True
}


def _build_f_quad_group(module_f_info: dict):
    """
    构建 4 个 F 上下左右对称排布的大组团。
    """
    module_length = module_f_info['length'] / 1000.0
    module_width = module_f_info['width'] / 1000.0
    total_length = module_length * 2 + F_HORIZONTAL_GAP
    total_width = module_width * 2 + F_VERTICAL_GAP

    return {
        'module': module_f_info,
        'rows': 2,
        'cols': 2,
        'count': 1,
        'group_type': 'F1',
        'layout_priority': 'preferred_quad',
        'vertical_gap': F_VERTICAL_GAP,
        'horizontal_gap': F_HORIZONTAL_GAP,
        'module_count': 4,
        # 使用整组贴图绘制 2x2 组团，避免被拆成 4 个单独贴图。
        'subgroups': [
            {
                'x': 0.0,
                'y': 0.0,
                'length': total_length,
                'width': total_width,
                'group_type': 'F1',
                'module_count': 4
            }
        ],
        'total_length': total_length,
        'total_width': total_width
    }


def _build_f_single_group(module_f_info: dict):
    """
    构建单个 F 模块。
    """
    return {
        'module': module_f_info,
        'rows': 1,
        'cols': 1,
        'count': 1,
        'group_type': 'F_single',
        'layout_priority': 'single_fill',
        'vertical_gap': 0.0,
        'horizontal_gap': 0.0,
        'module_count': 1
    }


def organize_module_f(quantity: int):
    """
    生成模块 F 的群组规则。

    规则说明：
    1. 优先按 4 个 F 组成 `F1` 大组团，对应 `moduleF1.png`
    2. `F1` 组团内部为 2x2 排布，纵向无间距，横向间距 1.5m
    3. 无法组成完整四联组的余量，使用单模块 `F_single`
    """
    if quantity <= 0:
        return []

    module_f_info = MODULE_F_INFO
    groups = []

    quad_group_count = quantity // 4
    single_count = quantity % 4

    for _ in range(quad_group_count):
        groups.append(_build_f_quad_group(module_f_info))

    for _ in range(single_count):
        groups.append(_build_f_single_group(module_f_info))

    return groups
