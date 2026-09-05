"""测试config_loader能否正确加载所有YAML配置"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '01_pre_selection'))

from config_loader import load_all_module_configs, load_all_group_configs, load_all_building_configs

m = load_all_module_configs()
g = load_all_group_configs()
b = load_all_building_configs()

print(f"模块: {len(m)}个 - {list(m.keys())}")
print(f"群组: {len(g)}个 - {list(g.keys())}")
print(f"建筑: {len(b)}个 - {list(b.keys())}")

print()
c = m['C']
print(f"模块C: {c['name']}, 床位:{c['beds']}, 尺寸:{c['dimensions']['length_mm']}x{c['dimensions']['width_mm']}mm")
print(f"  床头朝向: {c['bed_orientation']['head_direction']}")
print(f"  通道区域: {len(c['road_areas'])}个")

gc = g['C']
print(f"\n群组C: {len(gc['groups'])}种")
for gt in gc['groups']:
    arr_len = len(gt['arrangement'])
    ext = gt.get('external_spacing') or {}
    print(f"  {gt['group_type']}: {gt['rows']}x{gt['cols']}={gt['module_count']}模块, 外间距H{ext.get('horizontal_gap_m','-')}m/V{ext.get('vertical_gap_m','-')}m, arrangement:{arr_len}项")

print("\n=== 所有配置加载成功! ===")
