from typing import Dict, Iterable, Tuple

# 统一的模块类型映射与间距参数入口，后续若要调整默认间距或搜索粒度，只需要改这里。
MODULE_TYPE_MAP = {
    'A': '舒适型', 'B': '舒适型',
    'C': '经济型', 'D': '经济型',
    'E': '均衡型', 'F': '均衡型', 'G': '均衡型'
}

DEFAULT_INTER_MODULE_SPACING = 0.0
DEFAULT_GROUP_SPACING = 0.0
DEFAULT_SEARCH_GRID_STEP = 0.5
DEFAULT_SMART_Y_OFFSETS = (0, 1, 2, 3, 4, 5, 6, 8, 10)
DEFAULT_ADAPTIVE_BASE_SPACING = 6.0

MINIMUM_SPACING_BY_MODULE = {
    'A': 1.5,
    'B': 1.2,
    'C': 0.8,
    'D': 1.0,
    'E': 1.0,
    'F': 1.0,
    'G': 1.0,
}

def calculate_module_type_ratio(modules_selection: Dict[str, int]) -> Dict[str, float]:
    """
    计算各模块类型的占比
    
    :param modules_selection: 模块选择字典 {模块名: 数量}
    :return: 各类型占比字典 {'舒适型': 比例, '经济型': 比例, '均衡型': 比例}
    """
    # 统计各类型数量
    type_counts = {'舒适型': 0, '经济型': 0, '均衡型': 0}
    total_modules = 0
    
    for module_name, quantity in modules_selection.items():
        if module_name in MODULE_TYPE_MAP:
            module_type = MODULE_TYPE_MAP[module_name]
            type_counts[module_type] += quantity
            total_modules += quantity
    
    # 计算占比
    if total_modules == 0:
        return {'舒适型': 0.0, '经济型': 0.0, '均衡型': 0.0}
    
    type_ratios = {}
    for type_name, count in type_counts.items():
        type_ratios[type_name] = count / total_modules
    
    return type_ratios

def determine_inter_module_spacing(modules_selection: Dict[str, int]) -> float:
    """
    当前统一采用紧密排布，不同模块类型之间默认不留额外间隔。
    
    :param modules_selection: 模块选择字典
    :return: 间隔距离（米）
    """
    return DEFAULT_INTER_MODULE_SPACING

def should_apply_inter_module_spacing(group1_module_name: str, group2_module_name: str) -> bool:
    """
    判断两个群组之间是否需要应用模块间间隔
    
    :param group1_module_name: 第一个群组的模块名称
    :param group2_module_name: 第二个群组的模块名称
    :return: 是否需要间隔
    """
    # 当前默认不同模块间距为0时，不启用额外间距逻辑。
    return group1_module_name != group2_module_name and DEFAULT_INTER_MODULE_SPACING > 0


def get_search_grid_step() -> float:
    """返回统一的网格搜索步长（米）。"""
    return DEFAULT_SEARCH_GRID_STEP


def get_smart_y_offsets() -> Tuple[float, ...]:
    """返回智能候选位置的默认Y偏移列表。"""
    return DEFAULT_SMART_Y_OFFSETS


def get_minimum_required_spacing(module_type: str) -> float:
    """返回模块类型的最小推荐间距。"""
    return MINIMUM_SPACING_BY_MODULE.get(module_type, 1.0)


def get_adaptive_base_spacing() -> float:
    """返回自适应间距策略的基础间距。"""
    return DEFAULT_ADAPTIVE_BASE_SPACING


def build_axis_search_candidates(
    limit: float,
    group_size: float,
    current_positions: Iterable,
    axis: str,
    spacing: float = 0.0,
    include_grid: bool = True,
) -> Tuple[float, ...]:
    """
    为单轴搜索构建候选坐标。

    设计目标：
    1. 优先加入与已有群组边界精确贴齐的坐标，避免 0.5m 网格带来的意外缝隙。
    2. 保留少量网格点作为兜底，兼顾兼容性。
    """
    if group_size <= 0 or limit < group_size:
        return tuple()

    max_start = round(limit - group_size, 4)
    values = {0.0, max_start}
    step_size = get_search_grid_step() if include_grid else 0.0

    for pos_info in current_positions or []:
        if isinstance(pos_info, dict):
            start = pos_info['x'] if axis == 'x' else pos_info['y']
            size = pos_info['length'] if axis == 'x' else pos_info['width']
        else:
            start = pos_info[0] if axis == 'x' else pos_info[1]
            size = pos_info[2] if axis == 'x' else pos_info[3]

        end = start + size
        candidate_values = (
            start - group_size - spacing,
            start - group_size,
            start,
            end - group_size,
            end,
            end + spacing,
        )
        for value in candidate_values:
            values.add(round(value, 4))

    if include_grid and step_size > 0:
        grid_count = int(max_start / step_size) + 1
        for index in range(grid_count + 1):
            values.add(round(index * step_size, 4))

    valid_values = sorted(
        value for value in values
        if -1e-9 <= value <= max_start + 1e-9
    )
    return tuple(valid_values)


def calculate_group_dimensions_for_search(group: Dict, rotated: bool = False) -> Tuple[float, float]:
    """
    为位置搜索与间距判断提供统一的群组尺寸计算，避免多处重复实现。
    """
    if not group or 'module' not in group:
        return 0.0, 0.0

    module_info = group['module']
    rows = group.get('rows', 1)
    cols = group.get('cols', 1)
    vertical_gap = group.get('vertical_gap', 0.0)
    horizontal_gap = group.get('horizontal_gap', 0.0)

    if rotated:
        module_length = module_info.get('width', 0.0) / 1000.0
        module_width = module_info.get('length', 0.0) / 1000.0
        rows, cols = cols, rows
        if module_info.get('name') not in ['C', 'D']:
            vertical_gap, horizontal_gap = horizontal_gap, vertical_gap
    else:
        module_length = module_info.get('length', 0.0) / 1000.0
        module_width = module_info.get('width', 0.0) / 1000.0

    total_length = (module_length + horizontal_gap) * cols - horizontal_gap if cols > 0 else 0.0
    total_width = (module_width + vertical_gap) * rows - vertical_gap if rows > 0 else 0.0

    return total_length, total_width

def get_spacing_info(modules_selection: Dict[str, int]) -> Dict:
    """
    获取间距设置的详细信息
    
    :param modules_selection: 模块选择字典
    :return: 间距信息字典
    """
    type_ratios = calculate_module_type_ratio(modules_selection)
    inter_spacing = determine_inter_module_spacing(modules_selection)
    
    return {
        'type_ratios': type_ratios,
        'inter_module_spacing': inter_spacing,
        'spacing_rule': f"当前采用紧密排布，模块间间隔{inter_spacing}米",
        'description': _get_spacing_description(type_ratios, inter_spacing)
    }

def _get_spacing_description(type_ratios: Dict[str, float], spacing: float) -> str:
    """
    生成间距规则的描述文本
    
    :param type_ratios: 类型占比字典
    :param spacing: 间距值
    :return: 描述文本
    """
    return f"当前为紧密贴合排布，不同模块间留{spacing}米间隔"

def print_spacing_analysis(modules_selection: Dict[str, int]):
    """
    打印间距分析结果
    
    :param modules_selection: 模块选择字典
    """
    info = get_spacing_info(modules_selection)
    
    print("\n=== 模块间距分析 ===")
    print(f"模块类型占比:")
    for type_name, ratio in info['type_ratios'].items():
        print(f"  {type_name}: {ratio*100:.1f}%")
    
    print(f"\n间距规则: {info['description']}")
    print(f"不同模块类型间间隔: {info['inter_module_spacing']}米")

# 测试代码已移除，保持文件简洁
