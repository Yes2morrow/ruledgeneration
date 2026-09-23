"""YAML配置文件加载器 - 从configs/目录加载模块、群组和建筑配置"""
from pathlib import Path
from typing import Dict, List, Optional
import yaml
from functools import lru_cache
from copy import deepcopy

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


@lru_cache(maxsize=64)
def _load_yaml_version(filepath, modified, size):
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_yaml(filepath: Path) -> dict:
    """Cache parsed YAML; file edits invalidate the cache and callers own copies."""
    filepath = Path(filepath)
    stat = filepath.stat()
    return deepcopy(_load_yaml_version(str(filepath.resolve()), stat.st_mtime_ns, stat.st_size))


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


def load_building_config(building_id: str) -> dict:
    """加载建筑配置"""
    filepath = _resolve_case_insensitive(CONFIG_ROOT / "buildings", f"{building_id}.yaml")
    if not filepath.exists():
        raise FileNotFoundError(f"建筑配置文件不存在: {filepath}")
    return load_yaml(filepath)


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


def get_decompose_to(module_id: str, group_type: str) -> Optional[str]:
    """取群组的降级目标 group_type, 无则返回 None。"""
    g = get_group_def_by_type(module_id, group_type)
    if not g:
        return None
    dt = g.get('decompose_to')
    if dt in (None, 'null', 'None', ''):
        return None
    return dt


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
