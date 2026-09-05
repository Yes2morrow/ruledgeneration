"""测试床位布局配置"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '01_pre_selection'))

from config_loader import get_module_beds_layout, get_module_road_areas

for module_id in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
    beds = get_module_beds_layout(module_id)
    roads = get_module_road_areas(module_id)
    print(f"模块{module_id}: {len(beds)}个床位, {len(roads)}个通道区域")
    for b in beds:
        print(f"  床{b['bed_id']}: 朝向{b['head_direction']}, 线{b['head_position_mm']}mm, 多边形{b['polygon']}")

print("\n=== 床位布局配置加载成功! ===")
