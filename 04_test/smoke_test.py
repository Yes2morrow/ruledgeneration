"""冒烟测试: 验证核心排布链路能跑通。"""
import sys
import os
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

_PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJ / "01_pre_selection"))
sys.path.insert(0, str(_PROJ / "02_placement_generation" / "layout_optimization"))

from layout_optimizer import calculate_layout, layout_result_to_dict
from config_loader import get_site_polygon, load_all_module_configs


def main():
    site = get_site_polygon(length_m=48.0, width_m=14.0)
    print(f"场地多边形: {site}")

    # 测试1: A模块4个 + C模块8个
    print("\n=== 测试1: A=4, C=8 ===")
    r = calculate_layout({"A": 4, "C": 8}, site)
    print(f"success={r.success}, message={r.message}")
    print(f"metrics={r.metrics}")
    print(f"unplaced={r.unplaced}")
    print(f"groups={len(r.groups)}, beds={len(r.beds)}, roads={len(r.roads)}")
    for g in r.groups:
        print(f"  组 {g.module_id}/{g.group_type} @({g.x:.2f},{g.y:.2f}) "
              f"尺寸{g.length_m:.2f}x{g.width_m:.2f} rot={g.rotated} mods={len(g.modules)}")

    # 测试2: 全模块各2个
    print("\n=== 测试2: 各模块=2 ===")
    r2 = calculate_layout({"A": 2, "B": 2, "C": 2, "D": 2, "E": 2, "F": 2, "G": 2}, site)
    print(f"success={r2.success}, message={r2.message}")
    print(f"metrics={r2.metrics}")
    print(f"unplaced={r2.unplaced}")

    # 测试3: 建筑多边形场地
    print("\n=== 测试3: building=slab_residential_18f, C=4 ===")
    site3 = get_site_polygon(building_id="slab_residential_18f")
    print(f"建筑场地: {site3}")
    r3 = calculate_layout({"C": 4}, site3)
    print(f"success={r3.success}, metrics={r3.metrics}")


if __name__ == "__main__":
    main()
