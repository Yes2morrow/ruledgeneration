"""测试模块C新群组类型（C_quad + C_pair）布局图片生成"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '01_pre_selection'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'intra_module_rules'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'layout_optimization'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '03_visualization'))

from service_adapter import generate_plan_payload, _selection_list_from_map, _expand_group_configs, _finalize_layout
from core_calculations import modules

# ===== 1. 检查群组展开 =====
print("=== 检查模块C群组展开 (30个C模块) ===")
selected_map = {"C": 30}
selection_list = _selection_list_from_map(selected_map)
group_configs = _expand_group_configs(selection_list)
print(f"展开后群组数量: {len(group_configs)}")
for i, g in enumerate(group_configs):
    gt = g.get('group_type', 'N/A')
    print(f"  群组{i+1}: rows={g['rows']}, cols={g['cols']}, group_type={gt}")

# 统计群组类型
quad_count = sum(1 for g in group_configs if g.get('group_type') == 'C_quad')
pair_count = sum(1 for g in group_configs if g.get('group_type') == 'C_pair')
print(f"\n  C_quad (4x2=8模块): {quad_count}个, 共{quad_count*8}模块")
print(f"  C_pair (2x1=2模块): {pair_count}个, 共{pair_count*2}模块")
print(f"  合计: {quad_count*8 + pair_count*2}模块")

# ===== 2. 生成布局图片 =====
print("\n=== 生成布局图片 ===")
result = generate_plan_payload(
    evacuees=90,
    length=30,
    width=20,
    days=3,
    selected_modules={"C": 30},
    quiet=False,
)

if result:
    print("\n=== 布局图片生成成功 ===")
    print(f"  纹理图: {result['outputFiles']['latestTextureOnly']}")
    print(f"  标签图: {result['outputFiles']['latestWithLabels']}")
    print(f"  总床位: {result['layout']['totalBeds']}")
    print(f"  群组数: {result['layout']['groupCount']}")

    # ===== 3. 验证间距 =====
    print("\n=== 验证群组间距 ===")
    layout_result = _finalize_layout(_selection_list_from_map({"C": 30}), "经济型", 30.0, 20.0, quiet=True)
    if layout_result:
        module_c = modules['C']
        single_w = module_c['length'] / 1000  # 单个C模块宽度
        for i, g in enumerate(layout_result['groups']):
            x, y = g['position']
            gt = g.get('group_type', 'C_pair')
            rotated = g.get('rotated', False)
            # 计算群组实际宽度
            if gt == 'C_quad':
                gw = single_w * 2  # 2列
            else:
                gw = single_w     # 1列
            print(f"  群组{i+1}: x={x:.2f}, y={y:.2f}, type={gt}, width={gw:.2f}m")

        # 检查 C_quad 之间的间距
        print("\n  --- C_quad 群组间距检查 ---")
        quad_groups = [(i, g) for i, g in enumerate(layout_result['groups']) if g.get('group_type') == 'C_quad']
        for idx in range(len(quad_groups)):
            for jdx in range(idx + 1, len(quad_groups)):
                i, gi = quad_groups[idx]
                j, gj = quad_groups[jdx]
                xi, yi = gi['position']
                xj, yj = gj['position']
                gi_rotated = gi.get('rotated', False)
                gj_rotated = gj.get('rotated', False)
                # 计算群组实际尺寸
                from smart_layout_optimizer import calculate_group_dimensions
                wi, hi = calculate_group_dimensions(gi, rotated=gi_rotated)
                wj, hj = calculate_group_dimensions(gj, rotated=gj_rotated)
                
                # 水平间距：x方向相邻
                if abs(yi - yj) < 0.5:  # 大致同行
                    if xi < xj:
                        gap_x = xj - (xi + wi)
                        print(f"  C_quad {i+1}({xi:.2f},{yi:.2f},w={wi:.2f}) -> C_quad {j+1}({xj:.2f},{yj:.2f}): 水平间距={gap_x:.2f}m")
                # 垂直间距：y方向相邻
                if abs(xi - xj) < 0.5:  # 大致同列
                    if yi < yj:
                        gap_y = yj - (yi + hi)
                        print(f"  C_quad {i+1}({xi:.2f},{yi:.2f},h={hi:.2f}) -> C_quad {j+1}({xj:.2f},{yj:.2f}): 垂直间距={gap_y:.2f}m")
                
                # 通用：检查两群组间的最小间距
                x_gap = max(0, xj - (xi + wi)) if xi < xj else max(0, xi - (xj + wj))
                y_gap = max(0, yj - (yi + hi)) if yi < yj else max(0, yi - (yj + hj))
                if x_gap > 0 or y_gap > 0:
                    min_gap = min(x_gap, y_gap) if x_gap > 0 and y_gap > 0 else max(x_gap, y_gap)
                    print(f"  C_quad {i+1} -> C_quad {j+1}: 水平间隔={x_gap:.2f}m, 垂直间隔={y_gap:.2f}m")
else:
    print("布局生成失败")
