import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import Rectangle
import numpy as np
from typing import Dict, Tuple, Optional
import os

class EnhancedImageTextureHandler:
    """
    增强版图像纹理处理器
    提供更好的图像填充效果，支持边框、阴影和更清晰的视觉效果
    """
    
    def __init__(self, image_dir: str = None):
        """
        初始化增强版图像纹理处理器
        
        :param image_dir: 图像文件夹路径
        """
        if image_dir is None:
            # 使用当前文件所在目录下的image文件夹作为默认图像目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.image_dir = os.path.join(current_dir, 'image')
        else:
            self.image_dir = image_dir
        self.images = {}
        self.image_info = {}
        self._load_images()

    def _prepare_image_for_display(self, image):
        """
        将带透明通道的 PNG 预合成到白色背景上，避免透明像素显示成灰色。
        """
        image_array = np.asarray(image).astype(np.float32)
        if image_array.max() > 1.0:
            image_array /= 255.0

        if len(image_array.shape) == 3 and image_array.shape[2] == 4:
            rgb = image_array[..., :3]
            alpha = image_array[..., 3:4]
            white_bg = np.ones_like(rgb)
            return np.clip(rgb * alpha + white_bg * (1.0 - alpha), 0.0, 1.0)

        if len(image_array.shape) == 3 and image_array.shape[2] >= 3:
            return np.clip(image_array[..., :3], 0.0, 1.0)

        return np.clip(image_array, 0.0, 1.0)
    
    def _load_images(self):
        """
        加载所有模块图像并记录详细信息
        """
        # 定义图像文件映射
        image_files = {
            'A1': 'moduleA1.png',
            'A2': 'moduleA2.png',
            'A3': 'moduleA3.png',
            'B': 'moduleB.png',
            'B0': 'moduleB.png',
            'B1': 'moduleB1.png',
            'B2': 'moduleB2.png',
            'B_single': 'moduleBsingle.png',  # 单个模块B专用贴图
            'C': 'moduleC.png',
            'D': 'moduleD.png',
            'D_single': 'moduleDsingle.png'  # 单个模块D专用贴图
        }
        
        for key, filename in image_files.items():
            filepath = os.path.join(self.image_dir, filename)
            if os.path.exists(filepath):
                try:
                    image = mpimg.imread(filepath)
                    self.images[key] = image
                    self.image_info[key] = {
                        'filename': filename,
                        'shape': image.shape,
                        'dtype': image.dtype,
                        'has_alpha': len(image.shape) == 3 and image.shape[2] == 4
                    }
                    print(f"[成功] 加载图像: {filename} - 尺寸: {image.shape}")
                except Exception as e:
                    print(f"[失败] 加载图像失败 {filename}: {e}")
            else:
                print(f"[失败] 图像文件不存在: {filepath}")
    
    def get_module_image_key(self, module_name: str, group_index: int = 0, group_type: str = None,
                             rotated: bool = False) -> str:
        """
        根据模块名称、群组索引和群组类型获取对应的图像键
        
        :param module_name: 模块名称 ('A', 'B', 'C')
        :param group_index: 群组索引（对于模块A，0对应A1，1对应A2）
        :param group_type: 群组类型（用于区分单个模块B）
        :return: 图像键
        """
        if module_name == 'A':
            if group_type == 'A_group_one':
                if rotated and 'A3' in self.images:
                    return 'A3'
                return 'A1'
            if group_type == 'A_group_two':
                return 'A2'
            return 'A1' if group_index == 0 else 'A2'
        elif module_name == 'B':
            if group_type in {'B0', 'B_compact'}:
                return 'B0'
            if group_type == 'B_quad_cluster':
                return 'B1'
            if group_type == 'B_row_pair':
                return 'B2'
            if group_type == 'B_single':
                return 'B_single'
            return 'B'
        elif module_name == 'C':
            return 'C'
        elif module_name == 'D':
            # 如果是单个模块D，使用专用贴图
            if group_type == 'D_single':
                return 'D_single'
            else:
                return 'D'
        else:
            return None
    
    def apply_enhanced_texture(self, ax, x: float, y: float, width: float, height: float, 
                              module_name: str, group_index: int = 0, group_type: str = None,
                              rotated: bool = False,
                              alpha: float = 0.9, add_border: bool = True,
                              border_color: str = 'white', border_width: float = 2.0):
        """
        在指定的矩形区域内应用增强的图像纹理
        
        :param ax: matplotlib轴对象
        :param x: 矩形左下角x坐标
        :param y: 矩形左下角y坐标
        :param width: 矩形宽度
        :param height: 矩形高度
        :param module_name: 模块名称
        :param group_index: 群组索引
        :param group_type: 群组类型（用于区分单个模块B）
        :param rotated: 是否旋转90度
        :param alpha: 图像透明度
        :param add_border: 是否添加边框
        :param border_color: 边框颜色
        :param border_width: 边框宽度
        """
        image_key = self.get_module_image_key(module_name, group_index, group_type, rotated)
        
        if image_key and image_key in self.images:
            image = self._prepare_image_for_display(self.images[image_key])
            if rotated and image_key != 'A3':
                # 贴图需要和模块方向保持一致
                image = np.rot90(image, k=1)
            
            # 添加轻微的阴影效果
            if add_border and border_width > 0:
                shadow_offset = 0.05
                shadow_rect = Rectangle(
                    (x + shadow_offset, y - shadow_offset), width, height,
                    facecolor='gray', alpha=0.3, zorder=1
                )
                ax.add_patch(shadow_rect)
            
            # 使用imshow在指定区域显示图像
            # extent参数定义图像的边界：[left, right, bottom, top]
            im = ax.imshow(image, extent=[x, x + width, y, y + height], 
                          aspect='auto', alpha=1.0, interpolation='nearest',
                          zorder=2)
            
            # 添加边框
            if add_border and border_width > 0:
                border_rect = Rectangle(
                    (x, y), width, height,
                    facecolor='none', edgecolor=border_color,
                    linewidth=border_width, zorder=3
                )
                ax.add_patch(border_rect)
            
            return im
        else:
            print(f"未找到模块 {module_name} 群组 {group_index} 的图像")
            return None
    
    def create_enhanced_textured_rectangle(self, ax, x: float, y: float, width: float, height: float,
                                          module_name: str, group_index: int = 0, group_type: str = None,
                                          rotated: bool = False,
                                          facecolor: str = 'lightgray', edgecolor: str = 'white',
                                          linewidth: float = 2.0, alpha: float = 0.9,
                                          add_shadow: bool = True, add_label: bool = True):
        """
        创建带有增强图像纹理的矩形
        
        :param ax: matplotlib轴对象
        :param x: 矩形左下角x坐标
        :param y: 矩形左下角y坐标
        :param width: 矩形宽度
        :param height: 矩形高度
        :param module_name: 模块名称
        :param group_index: 群组索引
        :param group_type: 群组类型（用于区分单个模块B）
        :param rotated: 是否旋转90度
        :param facecolor: 背景颜色（当没有图像时使用）
        :param edgecolor: 边框颜色
        :param linewidth: 边框宽度
        :param alpha: 图像透明度
        :param add_shadow: 是否添加阴影
        :param add_label: 是否添加标签
        """
        # 检查图像是否可用
        if self.is_image_available(module_name, group_index, group_type, rotated):
            # 应用增强纹理
            im = self.apply_enhanced_texture(
                ax, x, y, width, height, module_name, group_index, group_type, rotated,
                alpha=alpha, add_border=True, border_color=edgecolor, 
                border_width=linewidth
            )
            
            # 添加模块标签
            if add_label:
                self._add_module_label(ax, x, y, width, height, module_name, group_index)
            
            return im
        else:
            # 如果没有图像，绘制中性的占位图形，避免出现整块深色误导。
            placeholder_facecolor = 'white'
            placeholder_edgecolor = 'black'
            if add_shadow:
                shadow_offset = 0.05
                shadow_rect = Rectangle(
                    (x + shadow_offset, y - shadow_offset), width, height,
                    facecolor='gray', alpha=0.3, zorder=1
                )
                ax.add_patch(shadow_rect)
            
            # 绘制主矩形
            rect = Rectangle((x, y), width, height,
                           facecolor=placeholder_facecolor,
                           edgecolor=placeholder_edgecolor,
                           linewidth=max(1.0, linewidth),
                           hatch='///', zorder=2)
            ax.add_patch(rect)
            
            # 添加"无图像"标签
            if add_label:
                ax.text(x + width/2, y + height/2, f'{module_name}\n(无贴图)', 
                       ha='center', va='center', fontsize=8, 
                       color='black', weight='bold', zorder=3)
            
            return rect
    
    def _add_module_label(self, ax, x: float, y: float, width: float, height: float,
                         module_name: str, group_index: int):
        """
        添加模块标签
        
        :param ax: matplotlib轴对象
        :param x: 矩形左下角x坐标
        :param y: 矩形左下角y坐标
        :param width: 矩形宽度
        :param height: 矩形高度
        :param module_name: 模块名称
        :param group_index: 群组索引
        """
        # 计算标签位置
        label_x = x + width / 2
        label_y = y + height / 2
        
        # 根据矩形大小调整字体大小
        font_size = min(width, height) * 1.2
        font_size = max(6, min(font_size, 14))  # 限制字体大小范围
        
        # 创建标签文本
        if module_name == 'A':
            label_text = f'{module_name}{group_index + 1}'
        else:
            label_text = module_name
        
        # 添加半透明背景
        bbox_props = dict(boxstyle="round,pad=0.3", facecolor='black', alpha=0.6)
        
        # 添加文本
        ax.text(label_x, label_y, label_text,
               horizontalalignment='center',
               verticalalignment='center',
               fontsize=font_size,
               color='white',
               weight='bold',
               bbox=bbox_props,
               zorder=4)
    
    def is_image_available(self, module_name: str, group_index: int = 0,
                           group_type: str = None, rotated: bool = False) -> bool:
        """
        检查指定模块的图像是否可用
        
        :param module_name: 模块名称
        :param group_index: 群组索引
        :param group_type: 群组类型（用于区分单个模块B）
        :param rotated: 是否旋转90度
        :return: 图像是否可用
        """
        image_key = self.get_module_image_key(module_name, group_index, group_type, rotated)
        return image_key and image_key in self.images
    
    def get_available_images(self) -> Dict[str, bool]:
        """
        获取所有可用图像的状态
        
        :return: 图像可用性字典
        """
        return {
            'moduleA1': 'A1' in self.images,
            'moduleA2': 'A2' in self.images,
            'moduleA3': 'A3' in self.images,
            'moduleB': 'B' in self.images,
            'moduleBsingle': 'B_single' in self.images,
            'moduleC': 'C' in self.images,
            'moduleD': 'D' in self.images,
            'moduleDsingle': 'D_single' in self.images
        }
    
    def get_image_info(self) -> Dict[str, dict]:
        """
        获取图像详细信息
        
        :return: 图像信息字典
        """
        return self.image_info.copy()
    
    def create_texture_preview(self, output_file: str = 'texture_preview.png'):
        """
        创建纹理预览图
        
        :param output_file: 输出文件名
        """
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle('增强版图像纹理预览', fontsize=16, weight='bold')
        
        # 测试配置
        test_configs = [
            {'ax': axes[0, 0], 'module': 'A', 'group': 0, 'title': '模块A1'},
            {'ax': axes[0, 1], 'module': 'A', 'group': 1, 'title': '模块A2'},
            {'ax': axes[1, 0], 'module': 'B', 'group': 0, 'title': '模块B'},
            {'ax': axes[1, 1], 'module': 'C', 'group': 0, 'title': '模块C'},
        ]
        
        for config in test_configs:
            ax = config['ax']
            module_name = config['module']
            group_index = config['group']
            title = config['title']
            
            ax.set_title(title, fontsize=14, weight='bold')
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 8)
            ax.set_aspect('equal')
            ax.grid(True, alpha=0.3)
            
            # 创建增强纹理矩形
            self.create_enhanced_textured_rectangle(
                ax, 1, 1, 8, 6,  # x, y, width, height
                module_name, group_index,
                facecolor='lightblue', edgecolor='navy',
                linewidth=2.0, alpha=0.9,
                add_shadow=True, add_label=True
            )
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=200, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        print(f"[成功] 纹理预览图已保存: {output_file}")
        plt.close()
