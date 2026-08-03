import matplotlib.pyplot as plt
from typing import Dict
import sys
import os
sys.path.append(os.path.dirname(__file__))

from enhanced_image_texture_handler import EnhancedImageTextureHandler

plt.rcParams['font.sans-serif'] = ['SimHei']  # 设置字体为黑体
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


def draw_layout(groups_config: list, aisle: float, all_length: float, all_width: float, show_labels=True, output_filename='layout.png'):
    """
    根据预先计算好的布局信息绘制平面图。
    该函数直接使用 group_configs 中提供的精确坐标进行绘制，不再进行任何布局计算。

    :param groups_config: 包含精确坐标和模块信息的群组配置列表
    :param aisle: 过道宽度，用于模块组内的间距
    :param all_length: 场地总长度（X轴）
    :param all_width: 场地总宽度（Y轴）
    """
    # 计算图像尺寸，保持场地比例的同时确保图像大小合理
    aspect_ratio = all_length / all_width  # 场地的长宽比
    
    # 设置基准尺寸（英寸），确保图像不会过大或过小
    base_size = 12  # 基准尺寸（英寸）
    
    if aspect_ratio >= 1:  # 宽度大于等于高度
        fig_width_in = base_size
        fig_height_in = base_size / aspect_ratio
    else:  # 高度大于宽度
        fig_height_in = base_size
        fig_width_in = base_size * aspect_ratio
    
    # 确保最小尺寸不小于6英寸，最大尺寸不超过16英寸
    min_size, max_size = 6, 16
    if fig_width_in < min_size:
        scale = min_size / fig_width_in
        fig_width_in *= scale
        fig_height_in *= scale
    elif fig_width_in > max_size:
        scale = max_size / fig_width_in
        fig_width_in *= scale
        fig_height_in *= scale
        
    if fig_height_in < min_size:
        scale = min_size / fig_height_in
        fig_width_in *= scale
        fig_height_in *= scale
    elif fig_height_in > max_size:
        scale = max_size / fig_height_in
        fig_width_in *= scale
        fig_height_in *= scale

    fig, ax = plt.subplots(figsize=(fig_width_in, fig_height_in))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    colors = {'舒适型': '#8B0000', '经济型': '#006400', '均衡型': '#00008B'}
    aisle_width = aisle
    
    # 初始化增强版图像纹理处理器
    texture_handler = EnhancedImageTextureHandler()
    print(f"图像加载状态: {texture_handler.get_available_images()}")
    
    # 用于跟踪模块A的群组索引
    module_a_group_count = 0

    # 绘制场地边界，确保布局从(0,0)开始
    ax.add_patch(plt.Rectangle((0, 0), all_length, all_width,
                               edgecolor='black', facecolor='none',
                               linewidth=1, linestyle='-', label='场地边界'))

    if not groups_config:
        print("警告：未能生成有效的布局方案，无法绘制布局图。")
        # 仍然生成一个空的场地图像
        ax.set_aspect('equal', adjustable='box')
        ax.set_xlim(0, all_length)
        ax.set_ylim(0, all_width)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        
        # 优化布局，避免元素重叠
        try:
            plt.tight_layout(pad=0.1)
        except:
            # 如果tight_layout失败，手动调整边距
            plt.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)
        
        plt.savefig(output_filename, dpi=200, bbox_inches='tight', pad_inches=0.1,
                    facecolor='white', edgecolor='none')
        print(f'已生成空的场地布局图：{output_filename}')
        print(f'图像尺寸：{fig_width_in:.1f}" x {fig_height_in:.1f}" (宽 x 高)')
        print(f'场地比例：{all_length:.1f}m x {all_width:.1f}m (长 x 宽)')
        return

    # 直接使用预计算的坐标进行绘制
    for group in groups_config:
        mod = group['module']
        
        # 确定当前群组的模块索引（用于图像纹理选择）
        current_group_index = 0
        if mod['name'] == 'A':
            current_group_index = module_a_group_count
            module_a_group_count += 1
        elif mod['name'] == 'B':
            current_group_index = 0  # 模块B只有一种图像
        elif mod['name'] == 'C':
            current_group_index = 0  # 模块C只有一种图像
        mod_type = mod['type']
        # 统一使用length和width属性
        # length对应x轴（绘图中的长度），width对应y轴（绘图中的宽度）
        original_length = mod['length'] / 1000  # x轴尺寸
        original_width = mod['width'] / 1000     # y轴尺寸

        rows = group['rows']
        cols = group['cols']
        
        # 检查是否旋转了90度
        rotated = group.get('rotated', False)
        
        if rotated:
            # 旋转90度后，单模块长宽和群组行列都要同步交换，才能和布局计算保持一致
            width, height = original_width, original_length
            draw_rows, draw_cols = cols, rows
        else:
            width, height = original_length, original_width
            draw_rows, draw_cols = rows, cols

        # 从 position 元组中解包 x 和 y
        x_offset, y_offset = group['position']

        # 绘图应优先忠实复现布局计算结果，未显式提供时默认不额外补画过道。
        vertical_gap = group.get('vertical_gap', 0.0)
        horizontal_gap = group.get('horizontal_gap', 0.0)
        draw_vertical_gap = vertical_gap
        draw_horizontal_gap = horizontal_gap

        if rotated and mod['name'] not in ['C', 'D']:
            draw_vertical_gap, draw_horizontal_gap = horizontal_gap, vertical_gap

        group_type = group.get('group_type', None)

        if group.get('subgroups'):
            total_length = group.get('total_length', 0.0)
            total_width = group.get('total_width', 0.0)

            for subgroup_index, subgroup in enumerate(group['subgroups']):
                sub_length = subgroup['length']
                sub_width = subgroup['width']

                if rotated:
                    sub_x = total_width - (subgroup['y'] + sub_width)
                    sub_y = subgroup['x']
                    draw_width = sub_width
                    draw_height = sub_length
                else:
                    sub_x = subgroup['x']
                    sub_y = subgroup['y']
                    draw_width = sub_length
                    draw_height = sub_width

                texture_handler.create_enhanced_textured_rectangle(
                    ax,
                    x_offset + sub_x,
                    y_offset + sub_y,
                    draw_width,
                    draw_height,
                    mod['name'],
                    subgroup_index,
                    subgroup.get('group_type', 'B_single'),
                    rotated=rotated,
                    facecolor=colors[mod_type],
                    edgecolor='none',
                    linewidth=0.0,
                    alpha=1.0,
                    add_shadow=False,
                    add_label=False
                )

            if show_labels:
                label_width = total_width if rotated else total_length
                label_height = total_length if rotated else total_width
                text_x = x_offset + label_width / 2
                text_y = y_offset + label_height / 2
                font_size = min(label_width, label_height) * 0.5
                font_size = max(6, min(font_size, 12))
                ax.text(
                    text_x,
                    text_y,
                    f"B{group.get('module_count', 0)}",
                    horizontalalignment='center',
                    verticalalignment='center',
                    fontsize=font_size,
                    color='white',
                    weight='bold',
                    bbox=dict(boxstyle="round,pad=0.2", facecolor='black', alpha=0.7)
                )
            continue

        if group.get('unit_positions'):
            unit_length = mod['length'] / 1000
            unit_width = mod['width'] / 1000
            total_length = group.get('total_length', unit_length)
            total_width = group.get('total_width', unit_width)

            for unit_index, unit_pos in enumerate(group['unit_positions']):
                if rotated:
                    unit_x = total_width - (unit_pos['y'] + unit_width)
                    unit_y = unit_pos['x']
                    draw_width = unit_width
                    draw_height = unit_length
                else:
                    unit_x = unit_pos['x']
                    unit_y = unit_pos['y']
                    draw_width = unit_length
                    draw_height = unit_width

                texture_handler.create_enhanced_textured_rectangle(
                    ax,
                    x_offset + unit_x,
                    y_offset + unit_y,
                    draw_width,
                    draw_height,
                    mod['name'],
                    unit_index,
                    unit_pos.get('group_type', 'B_single'),
                    rotated=rotated,
                    facecolor=colors[mod_type],
                    edgecolor='none',
                    linewidth=0.0,
                    alpha=1.0,
                    add_shadow=False,
                    add_label=False
                )

            if show_labels:
                label_width = total_width if rotated else total_length
                label_height = total_length if rotated else total_width
                text_x = x_offset + label_width / 2
                text_y = y_offset + label_height / 2
                font_size = min(label_width, label_height) * 0.5
                font_size = max(6, min(font_size, 12))
                ax.text(
                    text_x,
                    text_y,
                    f"B{group.get('module_count', len(group['unit_positions']))}",
                    horizontalalignment='center',
                    verticalalignment='center',
                    fontsize=font_size,
                    color='white',
                    weight='bold',
                    bbox=dict(boxstyle="round,pad=0.2", facecolor='black', alpha=0.7)
                )
            continue

        # A/B 的组合贴图代表整组模块，必须按整组尺寸绘制，不能塞进单个模块单元格。
        if (
            mod['name'] == 'A' and group_type in ['A_group_one', 'A_group_two']
        ) or (
            mod['name'] == 'B' and group_type in ['B_vertical_mirror', 'B_single', 'B_quad_cluster', 'B_row_pair']
        ):
            group_width = (width + draw_horizontal_gap) * draw_cols - draw_horizontal_gap
            group_height = (height + draw_vertical_gap) * draw_rows - draw_vertical_gap

            texture_handler.create_enhanced_textured_rectangle(
                ax, x_offset, y_offset, group_width, group_height,
                mod['name'], current_group_index, group_type,
                rotated=rotated,
                facecolor=colors[mod_type],
                edgecolor='none',
                linewidth=0.0,
                alpha=1.0,
                add_shadow=False,
                add_label=False
            )

            if show_labels:
                text_x = x_offset + group_width / 2
                text_y = y_offset + group_height / 2
                font_size = min(group_width, group_height) * 0.8
                font_size = max(6, min(font_size, 12))
                if group_type == 'A_group_one':
                    label_text = 'A1'
                elif group_type == 'A_group_two':
                    label_text = 'A2'
                else:
                    label_text = 'B'
                ax.text(text_x, text_y, label_text,
                        horizontalalignment='center',
                        verticalalignment='center',
                        fontsize=font_size,
                        color='white',
                        weight='bold',
                        bbox=dict(boxstyle="round,pad=0.2",
                                 facecolor='black', alpha=0.7))
            continue

        # 绘制群组内的单个模块单元
        for r in range(draw_rows):
            for c in range(draw_cols):
                # 计算模块在群组内的相对位置
                if mod['name'] == 'A':
                    # 模块A群组内部无间隔
                    x = x_offset + c * width
                    y = y_offset + r * height
                elif mod['name'] == 'C':
                    # 模块C垂直无间隔，水平有1.2m间隔
                    x = x_offset + c * width + (c * draw_horizontal_gap if c > 0 else 0)
                    y = y_offset + r * height  # 垂直方向无间隔
                else:
                    # 其他模块保持原有间隔逻辑
                    x = x_offset + c * width + (c * draw_horizontal_gap if c > 0 else 0)
                    y = y_offset + r * height + (r * draw_vertical_gap if r > 0 else 0)

                module_name = mod['name']
                
                # 使用增强版图像纹理绘制模块
                texture_handler.create_enhanced_textured_rectangle(
                    ax, x, y, width, height, 
                    module_name, current_group_index, group_type,
                    rotated=rotated,
                    facecolor=colors[mod_type], 
                    edgecolor='none',
                    linewidth=0.0, 
                    alpha=1.0,
                    add_shadow=False, 
                    add_label=False  # 我们将单独添加标签
                )
                
                # 添加模块名称文本（使用增强样式）
                text_x = x + width / 2
                text_y = y + height / 2
                font_size = min(width, height) * 1.2
                font_size = max(6, min(font_size, 12))  # 限制字体大小范围
                
                # 创建标签文本
                if module_name == 'A':
                    label_text = f'{module_name}{current_group_index + 1}'
                else:
                    label_text = module_name
                
                # 根据show_labels参数决定是否添加文本标签
                if show_labels:
                    # 添加带背景的文本
                    ax.text(text_x, text_y, label_text,
                            horizontalalignment='center',
                            verticalalignment='center',
                            fontsize=font_size,
                            color='white',
                            weight='bold',
                            bbox=dict(boxstyle="round,pad=0.2", 
                                     facecolor='black', alpha=0.7))

    ax.set_aspect('equal', adjustable='box')
    ax.set_xlim(0, all_length)
    ax.set_ylim(0, all_width)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    # 优化布局，避免元素重叠
    try:
        plt.tight_layout(pad=0.1)
    except:
        # 如果tight_layout失败，手动调整边距
        plt.subplots_adjust(left=0.02, right=0.98, top=0.98, bottom=0.02)
    
    # 保存图像，使用更好的设置
    plt.savefig(output_filename, dpi=200, bbox_inches='tight', pad_inches=0.1, 
                facecolor='white', edgecolor='none')
    print(f'布局图已生成：{output_filename}')
    print(f'图像尺寸：{fig_width_in:.1f}" x {fig_height_in:.1f}" (宽 x 高)')
    print(f'场地比例：{all_length:.1f}m x {all_width:.1f}m (长 x 宽)')
