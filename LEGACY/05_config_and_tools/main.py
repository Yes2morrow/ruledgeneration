import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '01_pre_selection'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '03_visualization'))

from core_calculations import validate_inputs, build_recommendation_profile
from arrangement_rules import calculate_aisle_width
from visualization import draw_layout
from interactive_module_selector import interactive_module_selection

if __name__ == '__main__':
    try:
        # 用户输入
        N = int(input('避难人数：'))
        all_length = float(input('体育馆长度（米）：'))
        all_width = float(input('体育馆宽度（米）：'))
        S = all_length * all_width
        days = int(input('安置时长（天）：'))
        
        # 参数校验
        s0 = validate_inputs(N, S, days)
        
        # 计算推荐画像、空间类型和过道宽度
        recommendation_profile = build_recommendation_profile(N, S, days)
        space_type = recommendation_profile['space_type']
        aisle = calculate_aisle_width(space_type)
        print(f'推荐空间类型：{space_type}，过道宽度：{aisle}米，人均面积：{s0:.2f} m^2/人')
        print(
            f"推荐依据：人数优先={recommendation_profile['people_priority']}，"
            f"时长判断={recommendation_profile['time_label']}，"
            f"模块偏好={recommendation_profile['module_preferences']}"
        )

        # 交互式选择模块并获取布局方案
        layout_plan = interactive_module_selection(
            space_type,
            N,
            all_length,
            all_width,
            module_preferences=recommendation_profile['module_preferences'],
            recommendation_profile=recommendation_profile,
            days=days
        )

        # 渲染最终布局
        if layout_plan:
            print("\n布局方案详情：")
            print(f"总床位数：{layout_plan['total_beds']} 个")
            print(f"总成本：{layout_plan['total_cost']:.2f} 元")
            print("正在生成布局图...")
            # 生成带标签的布局图
            print("生成带标签的布局图...")
            # 设置输出目录
            output_dir = os.path.join(os.path.dirname(__file__), '..', '06_output_results')
            os.makedirs(output_dir, exist_ok=True)
            
            draw_layout(layout_plan['groups'], aisle, all_length, all_width, show_labels=True, 
                       output_filename=os.path.join(output_dir, 'layout_with_labels.png'))
            
            # 生成纯图像纹理布局图
            print("生成纯图像纹理布局图...")
            draw_layout(layout_plan['groups'], aisle, all_length, all_width, show_labels=False, 
                       output_filename=os.path.join(output_dir, 'layout_texture_only.png'))
        else:
            print("\n未能生成有效的布局方案。")
            print("建议：\n1. 减少所需床位数\n2. 增大场地尺寸\n3. 缩短安置时长\n4. 选择更紧凑的模块类型")
            # 设置输出目录
            output_dir = os.path.join(os.path.dirname(__file__), '..', '06_output_results')
            os.makedirs(output_dir, exist_ok=True)
            
            # 生成空的场地图像（带标签版本）
            draw_layout([], aisle, all_length, all_width, show_labels=True, 
                       output_filename=os.path.join(output_dir, 'layout_with_labels.png'))
            # 生成空的场地图像（纯纹理版本）
            draw_layout([], aisle, all_length, all_width, show_labels=False, 
                       output_filename=os.path.join(output_dir, 'layout_texture_only.png'))
        
    except ValueError as e:
        print(f'输入错误：{e}')
    except Exception as e:
        print(f'发生未知错误：{e}')
        raise  # 在开发阶段，重新抛出异常以便查看完整的错误信息
