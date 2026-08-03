import sys, os, json, builtins

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '01_pre_selection'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'layout_optimization'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'inter_module_rules'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'intra_module_rules'))

os.environ['LAYOUT_VERBOSE'] = '0'

from core_calculations import build_recommendation_profile, validate_inputs, select_modules
from module_spacing_manager import calculate_group_dimensions_for_search

evacuees = 100
all_length = 50.0
all_width = 30.0
days = 3
area = all_length * all_width

validate_inputs(evacuees, area, days)
profile = build_recommendation_profile(evacuees, area, days)

builtins.print(f"推荐画像: space_type={profile['space_type']}, prefs={profile['module_preferences']}")

layout_result = select_modules(
    profile['module_preferences'],
    evacuees,
    all_length,
    all_width,
    time_limit_seconds=20.0,
    recommendation_mode='match_input',
)

if layout_result:
    groups = layout_result['groups']
    builtins.print(f"\n群组总数: {len(groups)}")
    rotated_count = 0
    for i, g in enumerate(groups):
        rot = g.get('rotated', False)
        if rot:
            rotated_count += 1
        gt = g.get('group_type', '?')
        pos = g.get('position', (0, 0))
        mod = g.get('module', {})
        mn = mod.get('name', '?') if isinstance(mod, dict) else '?'
        rows = g.get('rows', '?')
        cols = g.get('cols', '?')
        length_m, width_m = calculate_group_dimensions_for_search(g, rotated=rot)
        builtins.print(
            f"  G{i+1}: {mn} {gt} rows={rows} cols={cols} "
            f"pos=({pos[0]:.1f},{pos[1]:.1f}) size=({length_m:.1f}x{width_m:.1f}) rot={rot}"
        )
    builtins.print(f"\n旋转群组数: {rotated_count}/{len(groups)}")
    builtins.print(f"总床位={layout_result['total_beds']} 填充率={layout_result.get('fill_ratio', 0):.3f}")

    max_x = max(g['position'][0] + calculate_group_dimensions_for_search(g, g.get('rotated', False))[0] for g in groups)
    max_y = max(g['position'][1] + calculate_group_dimensions_for_search(g, g.get('rotated', False))[1] for g in groups)
    builtins.print(f"场地占用: {max_x:.1f}m x {max_y:.1f}m (场地: {all_length}m x {all_width}m)")
    builtins.print(f"剩余空间: {all_length - max_x:.1f}m x {all_width - max_y:.1f}m")
else:
    builtins.print("无布局结果")
