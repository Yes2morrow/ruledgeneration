# 模块B的基本信息（避免循环导入）
module_b_info = {
    'type': '舒适型', 
    'beds': 2, 
    'cost': 2298, 
    'priority': 2, 
    'length': 4000,  # length对应x轴
    'width': 2000,   # width对应y轴
    'name': 'B'
}


def _build_b_group(rows: int, cols: int, group_type: str):
    """创建标准化的 B 群组配置。"""
    return {
        'module': module_b_info,
        'rows': rows,
        'cols': cols,
        'count': 1,
        'group_type': group_type,
        'layout_priority': 'standard',
        'vertical_gap': 0.0,
        'horizontal_gap': 0.0,
        'module_count': rows * cols
    }

def organize_module_b(quantity: int):
    """
    模块B的详细规则制定与修正
    
    规则说明：
    1. 新增两类稳定小组团，不再把很多B封成一个超级长块
    2. B1：2x2，共4个B模块，对应 moduleB1.png
    3. B2：1x2，共2个B模块，对应 moduleB2.png
    4. B1/B2 这类大组团之间由位置寻找器统一控制四周 2000mm 外部间距
    5. B_single 作为补空模块，只在剩余空间中补位，但仍需保留至少 1200mm 外部间距
    
    :param quantity: 模块B的数量
    :return: 群组配置列表
    """
    
    if quantity <= 0:
        return []
    
    # 使用本地定义的模块B信息
    groups = []
    
    quad_group_count = quantity // 4
    remaining = quantity % 4

    if quad_group_count > 0:
        quad_group = _build_b_group(2, 2, 'B_quad_cluster')
        quad_group['count'] = quad_group_count
        groups.append(quad_group)

    if remaining >= 2:
        groups.append(_build_b_group(1, 2, 'B_row_pair'))
        remaining -= 2

    if remaining == 1:
        groups.append(_build_b_group(1, 1, 'B_single'))

    return groups


def decompose_module_b_group(group: dict):
    """
    当大组团在局部空间放不下时，逐级拆分成更小的 B 组团用于补空。
    """
    group_type = group.get('group_type', 'B_single')

    if group_type == 'B_quad_cluster':
        return [
            _build_b_group(1, 2, 'B_row_pair'),
            _build_b_group(1, 2, 'B_row_pair')
        ]

    if group_type == 'B_row_pair':
        return [
            _build_b_group(1, 1, 'B_single'),
            _build_b_group(1, 1, 'B_single')
        ]

    return []


def validate_module_b_quantity(quantity: int) -> bool:
    """
    验证模块B数量是否符合规则
    
    :param quantity: 模块B的数量
    :return: 是否有效
    """
    return quantity > 0  # 现在接受任何正数数量，包括奇数


def get_module_b_layout_info(quantity: int) -> dict:
    """
    获取模块B布局的详细信息
    
    :param quantity: 模块B的数量
    :return: 布局信息字典
    """
    if not validate_module_b_quantity(quantity):
        return {
            'valid': False,
            'error': '模块B数量必须为正数',
            'groups': []
        }
    
    groups = organize_module_b(quantity)
    
    # 统计群组信息
    group_count = quantity // 2
    
    return {
        'valid': True,
        'total_modules': quantity,
        'group_count': group_count,  # 垂直镜像群组数量（1行x2列）
        'groups': groups,
        'layout_strategy': {
            'group_type': 'vertical_mirror',  # 垂直镜像
            'spacing_rule': 'fully_compact',  # 群组间紧密贴合
            'total_groups': group_count
        },
        'spacing_info': {
            'vertical_gap': 0.0,    # 垂直间距（米）
            'horizontal_gap': 0,    # 水平间距（米）
            'description': '垂直方向和水平方向都不留额外间距'
        }
    }


def get_module_b_dimensions():
    """
    获取模块B的尺寸信息
    
    :return: 尺寸信息字典
    """
    return {
        'length': module_b_info['length'],  # x轴尺寸（毫米）
        'width': module_b_info['width'],    # y轴尺寸（毫米）
        'length_m': module_b_info['length'] / 1000,  # x轴尺寸（米）
        'width_m': module_b_info['width'] / 1000,    # y轴尺寸（米）
        'area_sqm': (module_b_info['length'] * module_b_info['width']) / 1000000  # 面积（平方米）
    }


def print_module_b_rules():
    """
    打印模块B的详细规则说明
    """
    print("\n=== 模块B布局规则 ===")
    print("1. 数量限制：模块B数量必须为正数")
    print("2. 群组形式：B1=2x2、B2=1x2、B_single=1x1")
    print("3. 间距规则：")
    print("   - B1/B2 组团之间：水平和垂直都保留 2.0 米")
    print("   - B_single：作为补空模块，只禁止重叠")
    print("4. 组团标识：B_quad_cluster / B_row_pair / B_single")
    print("6. 布局优先级：标准优先级")
    
    # 显示尺寸信息
    dims = get_module_b_dimensions()
    print(f"\n模块B尺寸：{dims['length']}mm x {dims['width']}mm")
    print(f"模块B面积：{dims['area_sqm']:.2f}平方米")
    print(f"床位数：{module_b_info['beds']}个")
    print(f"成本：{module_b_info['cost']}元")


# 测试代码已移除，保持文件简洁
