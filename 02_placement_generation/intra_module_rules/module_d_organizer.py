MODULE_D_INFO = {
    'type': '经济型',
    'beds': 2,
    'cost': 690,
    'priority': 2,
    'length': 3600,
    'width': 1800,
    'name': 'D',
    'visual_ready': True
}

D_HORIZONTAL_GAP = 1.5
D_VERTICAL_GAP = 0.0
MAX_D_SUBGROUPS_PER_ROW = 4
MAX_D_ROWS_PER_GROUP = 2


def _build_d_templates(quantity: int):
    """
    优先生成 D1 四模块大组团，其次退化为 D0，再处理单个 D。
    """
    templates = []
    remaining = quantity

    while remaining >= 4:
        templates.append({
            'length': 7.2,
            'width': 3.6,
            'group_type': 'D1',
            'module_count': 4
        })
        remaining -= 4

    if remaining >= 2:
        templates.append({
            'length': 3.6,
            'width': 3.6,
            'group_type': 'D0',
            'module_count': 2
        })
        remaining -= 2

    if remaining == 1:
        templates.append({
            'length': 3.6,
            'width': 1.8,
            'group_type': 'D_single',
            'module_count': 1
        })

    return templates


def _build_d_group_from_templates(templates: list):
    """
    把 D1/D0/D_single 模板拼成一个可直接落位的群组。
    """
    subgroups = []
    total_length = 0.0
    total_width = 0.0
    module_count = 0
    template_index = 0
    current_y = 0.0
    row_count = 0

    while template_index < len(templates) and row_count < MAX_D_ROWS_PER_GROUP:
        row_templates = templates[template_index: template_index + MAX_D_SUBGROUPS_PER_ROW]
        template_index += len(row_templates)

        x_offset = 0.0
        row_height = 0.0
        for subgroup in row_templates:
            subgroups.append({
                'x': x_offset,
                'y': current_y,
                'length': subgroup['length'],
                'width': subgroup['width'],
                'group_type': subgroup['group_type'],
                'module_count': subgroup['module_count']
            })
            x_offset += subgroup['length'] + D_HORIZONTAL_GAP
            row_height = max(row_height, subgroup['width'])
            module_count += subgroup['module_count']

        total_length = max(total_length, x_offset - D_HORIZONTAL_GAP if row_templates else 0.0)
        total_width = current_y + row_height
        current_y += row_height + D_VERTICAL_GAP
        row_count += 1

    return {
        'module': MODULE_D_INFO,
        'rows': row_count,
        'cols': min(MAX_D_SUBGROUPS_PER_ROW, len(subgroups)) if subgroups else 0,
        'count': 1,
        'group_type': 'D_group',
        'layout_priority': 'preferred_cluster',
        'vertical_gap': D_VERTICAL_GAP,
        'horizontal_gap': D_HORIZONTAL_GAP,
        'module_count': module_count,
        'subgroups': subgroups,
        'total_length': total_length,
        'total_width': total_width
    }, templates[template_index:]


def organize_module_d(quantity: int):
    """
    根据新的 D 组团规则生成布局群组。

    规则说明：
    1. `D1` 为 2x2 的四模块镜像大组团，对应 `moduleD1.png`
    2. `D0` 为原有 2x1 的上下紧密镜像组团，对应 `moduleD.png`
    3. `D_single` 为单个 D 模块，对应 `moduleDsingle.png`
    4. D 组团优先使用 `D1`，横向间距 1.5m，纵向无间距
    """
    if quantity <= 0:
        return []

    templates = _build_d_templates(quantity)
    groups = []

    while templates:
        group, templates = _build_d_group_from_templates(templates)
        groups.append(group)

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
        '经济型': {'horizontal_gap': 1.5, 'vertical_gap': 0},
        '均衡型': {'horizontal_gap': 1.5, 'vertical_gap': 0},
        '舒适型': {'horizontal_gap': 1.5, 'vertical_gap': 0}
    }
    
    return spacing_configs.get(space_type, spacing_configs['均衡型'])
