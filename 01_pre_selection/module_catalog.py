"""模块目录 - 兼容原项目接口, 内部全部委托给 config_loader, 避免重复实现。"""
from config_loader import get_module_catalog, load_all_module_configs


def get_modules() -> dict:
    """获取所有模块定义(兼容原项目接口)"""
    configs = load_all_module_configs()
    modules = {}
    for module_id, config in configs.items():
        modules[module_id] = {
            'type': config['type'],
            'beds': config['beds'],
            'cost': config['cost'],
            'priority': config['priority'],
            'length': config['dimensions']['length_mm'],
            'width': config['dimensions']['width_mm'],
            'name': module_id,
            'visual_ready': True,
        }
    return modules


def get_module_colors() -> dict:
    """获取模块颜色映射"""
    configs = load_all_module_configs()
    return {config['type']: config['visual']['color'] for config in configs.values()}
