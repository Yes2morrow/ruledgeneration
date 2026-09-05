"""YAML配置文件加载器 - 从configs/目录加载模块、群组和建筑配置"""
import os
from pathlib import Path
from typing import Dict, List, Optional
import yaml

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = PROJECT_ROOT / "configs"


def _resolve_case_insensitive(directory: Path, filename: str) -> Path:
    """在大小写敏感文件系统中按不区分大小写方式解析文件名。"""
    exact = directory / filename
    if exact.exists():
        return exact
    target = filename.lower()
    for candidate in directory.iterdir():
        if candidate.name.lower() == target:
            return candidate
    return exact


def load_yaml(filepath: Path) -> dict:
    """加载单个YAML文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_module_config(module_id: str) -> dict:
    """加载指定模块的配置"""
    filepath = _resolve_case_insensitive(CONFIG_ROOT / "modules", f"module_{module_id.lower()}.yaml")
    if not filepath.exists():
        raise FileNotFoundError(f"模块配置文件不存在: {filepath}")
    return load_yaml(filepath)


def load_all_module_configs() -> Dict[str, dict]:
    """加载所有模块配置"""
    modules = {}
    module_dir = CONFIG_ROOT / "modules"
    for filepath in sorted(module_dir.glob("module_*.yaml")):
        config = load_yaml(filepath)
        modules[config['module_id']] = config
    return modules


def load_group_config(module_id: str) -> dict:
    """加载指定模块的群组配置"""
    filepath = _resolve_case_insensitive(CONFIG_ROOT / "groups", f"group_{module_id.lower()}.yaml")
    if not filepath.exists():
        raise FileNotFoundError(f"群组配置文件不存在: {filepath}")
    return load_yaml(filepath)


def load_all_group_configs() -> Dict[str, dict]:
    """加载所有群组配置"""
    groups = {}
    group_dir = CONFIG_ROOT / "groups"
    for filepath in sorted(group_dir.glob("group_*.yaml")):
        config = load_yaml(filepath)
        groups[config['module_id']] = config
    return groups


def load_building_config(building_id: str) -> dict:
    """加载建筑配置"""
    filepath = _resolve_case_insensitive(CONFIG_ROOT / "buildings", f"{building_id}.yaml")
    if not filepath.exists():
        raise FileNotFoundError(f"建筑配置文件不存在: {filepath}")
    return load_yaml(filepath)


def load_all_building_configs() -> Dict[str, dict]:
    """加载所有建筑配置"""
    buildings = {}
    building_dir = CONFIG_ROOT / "buildings"
    for filepath in sorted(building_dir.glob("*.yaml")):
        config = load_yaml(filepath)
        buildings[config['id']] = config
    return buildings


def get_module_catalog() -> List[dict]:
    """获取模块目录(用于API返回)。统一字段与 service_adapter 一致。"""
    configs = load_all_module_configs()
    catalog = []
    for module_id, config in sorted(configs.items()):
        step = module_step(module_id)
        catalog.append({
            'id': module_id,
            'code': module_id,
            'name': config['name'],
            'type': config['type'],
            'bedsPerUnit': int(config['beds']),
            'costPerUnit': int(config['cost']),
            'length_mm': int(config['dimensions']['length_mm']),
            'width_mm': int(config['dimensions']['width_mm']),
            'step': step,
            'ruleText': f"需按 {step} 的倍数增减" if step > 1 else "可按单个模块增减",
            'color': (config.get('visual') or {}).get('color', '#444444'),
        })
    return catalog


def get_module_beds_layout(module_id: str) -> List[dict]:
    """获取模块的床位布局"""
    config = load_module_config(module_id)
    return config.get('beds_layout', [])


def get_module_road_areas(module_id: str) -> List[dict]:
    """获取模块的通道区域"""
    config = load_module_config(module_id)
    return config.get('road_areas', [])


# --------------------------------------------------------------------------- #
# 群组配置查询
# --------------------------------------------------------------------------- #
_STEP_CACHE: Dict[str, int] = {}


def module_step(module_id: str) -> int:
    """模块最小增减步长(从 group 配置推导), 供后端全局使用。"""
    if module_id in _STEP_CACHE:
        return _STEP_CACHE[module_id]
    groups = get_group_defs(module_id)
    counts = [int(g.get("module_count", 1)) for g in groups] or [1]
    step = min(counts)
    _STEP_CACHE[module_id] = step
    return step


def get_group_defs(module_id: str) -> List[dict]:
    """获取某模块的所有群组定义列表。"""
    config = load_group_config(module_id)
    return config.get('groups', [])


def get_group_def_by_type(module_id: str, group_type: str) -> Optional[dict]:
    """按 group_type 查找群组定义。"""
    for g in get_group_defs(module_id):
        if g.get('group_type') == group_type:
            return g
    return None


def get_group_types(module_id: str) -> List[str]:
    """列出某模块的所有 group_type。"""
    return [g['group_type'] for g in get_group_defs(module_id)]


def get_decompose_to(module_id: str, group_type: str) -> Optional[str]:
    """取群组的降级目标 group_type, 无则返回 None。"""
    g = get_group_def_by_type(module_id, group_type)
    if not g:
        return None
    dt = g.get('decompose_to')
    if dt in (None, 'null', 'None', ''):
        return None
    return dt


def get_decompose_chain(module_id: str, group_type: str) -> List[str]:
    """获取完整降级链: [group_type, decompose_to, ...] 直到 None。"""
    chain = [group_type]
    seen = {group_type}
    current = group_type
    while True:
        nxt = get_decompose_to(module_id, current)
        if nxt is None or nxt in seen:
            break
        chain.append(nxt)
        seen.add(nxt)
        current = nxt
    return chain


def get_sub_groups(module_id: str, group_type: str) -> List[str]:
    """取群组声明的 sub_groups 备选列表(E 模块用)。"""
    g = get_group_def_by_type(module_id, group_type)
    if not g:
        return []
    return list(g.get('sub_groups', []) or [])


# --------------------------------------------------------------------------- #
# 建筑场地
# --------------------------------------------------------------------------- #
def rect_to_site_polygon(length_m: float, width_m: float) -> list:
    """由 length/width 构造矩形场地多边形(左下角为原点)。"""
    return [[0.0, 0.0], [float(length_m), 0.0], [float(length_m), float(width_m)], [0.0, float(width_m)]]


def building_to_site_polygon(building_id: str) -> list:
    """建筑 footprint(中心原点)平移到左下角原点, 返回场地多边形(米)。

    要求 footprint.points 已按顺序给出闭合多边形顶点。
    """
    config = load_building_config(building_id)
    pts = config.get('footprint', {}).get('points', [])
    if not pts:
        raise ValueError(f"建筑 {building_id} 无 footprint.points")
    pts = [list(p) for p in pts]
    minx = min(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    # 平移使最小 x,y 落到 0
    return [[p[0] - minx, p[1] - miny] for p in pts]


def get_site_polygon(building_id: Optional[str] = None, length_m: Optional[float] = None,
                     width_m: Optional[float] = None) -> list:
    """统一获取场地多边形: 优先 building_id, 否则用 length/width 构造矩形。"""
    if building_id:
        return building_to_site_polygon(building_id)
    if length_m is not None and width_m is not None:
        return rect_to_site_polygon(length_m, width_m)
    raise ValueError("需提供 building_id 或 (length_m, width_m)")
