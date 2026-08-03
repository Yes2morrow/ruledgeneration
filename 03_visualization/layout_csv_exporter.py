import csv
import os
from datetime import datetime


def _read_env_flag(name, default="1"):
    value = os.environ.get(name, default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class LayoutCSVExporter:
    """布局CSV导出器类"""
    
    def __init__(self, export_subdir=None, write_analysis_report=None):
        self.module_data = []
        self.export_subdir = export_subdir or os.environ.get("LAYOUT_EXPORT_SUBDIR", "layout_analysis_exports")
        self.write_analysis_report = (
            _read_env_flag("LAYOUT_EXPORT_ANALYSIS_REPORT", "1")
            if write_analysis_report is None
            else write_analysis_report
        )
        
    def add_module_group(self, group_id, module_type, x, y, width, height, 
                        is_rotated=False, module_count=1, rows=1, cols=1):
        """
        添加模块群组信息
        
        Args:
            group_id: 群组ID
            module_type: 模块类型 (A, B, C, D, E)
            x: X坐标 (m)
            y: Y坐标 (m)
            width: 群组宽度 (m)
            height: 群组高度 (m)
            is_rotated: 是否旋转
            module_count: 模块数量
            rows: 行数
            cols: 列数
        """
        self.module_data.append({
            'group_id': group_id,
            'module_type': module_type,
            'x_position': round(x, 2),
            'y_position': round(y, 2),
            'width': round(width, 2),
            'height': round(height, 2),
            'x_end': round(x + width, 2),
            'y_end': round(y + height, 2),
            'is_rotated': is_rotated,
            'module_count': module_count,
            'rows': rows,
            'cols': cols,
            'area': round(width * height, 2)
        })
        
    def check_overlaps(self):
        """
        检查模块重叠情况
        
        Returns:
            list: 重叠的模块对列表
        """
        overlaps = []
        
        for i in range(len(self.module_data)):
            for j in range(i + 1, len(self.module_data)):
                module1 = self.module_data[i]
                module2 = self.module_data[j]
                
                # 检查是否重叠
                if (module1['x_position'] < module2['x_end'] and 
                    module1['x_end'] > module2['x_position'] and
                    module1['y_position'] < module2['y_end'] and 
                    module1['y_end'] > module2['y_position']):
                    
                    overlaps.append({
                        'group1': module1['group_id'],
                        'type1': module1['module_type'],
                        'group2': module2['group_id'],
                        'type2': module2['module_type'],
                        'overlap_area': self._calculate_overlap_area(module1, module2)
                    })
                    
        return overlaps
    
    def _calculate_overlap_area(self, module1, module2):
        """
        计算两个模块的重叠面积
        """
        x_overlap = max(0, min(module1['x_end'], module2['x_end']) - 
                           max(module1['x_position'], module2['x_position']))
        y_overlap = max(0, min(module1['y_end'], module2['y_end']) - 
                           max(module1['y_position'], module2['y_position']))
        return round(x_overlap * y_overlap, 2)
    
    def check_boundary_violations(self, site_width, site_height):
        """
        检查边界溢出情况
        
        Args:
            site_width: 场地宽度 (m)
            site_height: 场地高度 (m)
            
        Returns:
            list: 溢出边界的模块列表
        """
        violations = []
        
        for module in self.module_data:
            violation_info = {
                'group_id': module['group_id'],
                'module_type': module['module_type'],
                'violations': []
            }
            
            if module['x_position'] < 0:
                violation_info['violations'].append('左边界溢出')
            if module['y_position'] < 0:
                violation_info['violations'].append('下边界溢出')
            if module['x_end'] > site_width:
                violation_info['violations'].append(f'右边界溢出 ({module["x_end"]}m > {site_width}m)')
            if module['y_end'] > site_height:
                violation_info['violations'].append(f'上边界溢出 ({module["y_end"]}m > {site_height}m)')
                
            if violation_info['violations']:
                violations.append(violation_info)
                
        return violations
    
    def export_to_csv(self, filename=None, site_width=None, site_height=None):
        """
        导出模块信息到CSV文件
        
        Args:
            filename: 文件名，如果为None则自动生成
            site_width: 场地宽度，用于边界检查
            site_height: 场地高度，用于边界检查
            
        Returns:
            str: 导出的文件路径
        """
        current_dir = os.path.dirname(os.path.abspath(__file__))

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_dir = os.path.join(current_dir, self.export_subdir)
            os.makedirs(export_dir, exist_ok=True)
            filename = os.path.join(export_dir, f"layout_analysis_{timestamp}.csv")
            
        # 确保文件路径是绝对路径
        if not os.path.isabs(filename):
            filename = os.path.join(current_dir, filename)

        os.makedirs(os.path.dirname(filename), exist_ok=True)
            
        # 导出主要模块数据
        with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
            fieldnames = ['group_id', 'module_type', 'x_position', 'y_position', 
                         'width', 'height', 'x_end', 'y_end', 'is_rotated', 
                         'module_count', 'rows', 'cols', 'area']
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for module in self.module_data:
                writer.writerow(module)

        if self.write_analysis_report:
            analysis_filename = filename.replace('.csv', '_analysis.txt')
            with open(analysis_filename, 'w', encoding='utf-8') as f:
                f.write("=== 布局分析报告 ===\n")
                f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"总模块群组数: {len(self.module_data)}\n\n")
                
                # 重叠检查
                overlaps = self.check_overlaps()
                f.write(f"=== 重叠检查 ===\n")
                if overlaps:
                    f.write(f"发现 {len(overlaps)} 处重叠:\n")
                    for overlap in overlaps:
                        f.write(f"  群组{overlap['group1']}({overlap['type1']}) 与 "
                               f"群组{overlap['group2']}({overlap['type2']}) 重叠，"
                               f"重叠面积: {overlap['overlap_area']} m^2\n")
                else:
                    f.write("未发现重叠\n")
                f.write("\n")
                
                # 边界检查
                if site_width and site_height:
                    violations = self.check_boundary_violations(site_width, site_height)
                    f.write(f"=== 边界检查 (场地: {site_width}m x {site_height}m) ===\n")
                    if violations:
                        f.write(f"发现 {len(violations)} 个边界违规:\n")
                        for violation in violations:
                            f.write(f"  群组{violation['group_id']}({violation['module_type']}): "
                                   f"{', '.join(violation['violations'])}\n")
                    else:
                        f.write("所有模块都在边界内\n")
                else:
                    f.write("=== 边界检查 ===\n")
                    f.write("未提供场地尺寸，跳过边界检查\n")
                
        print(f"布局数据已导出到: {filename}")
        if self.write_analysis_report:
            print(f"分析报告已生成: {analysis_filename}")
        
        return filename
    
    def clear_data(self):
        """清空数据"""
        self.module_data.clear()
        
    def get_summary(self):
        """
        获取布局摘要信息
        
        Returns:
            dict: 摘要信息
        """
        if not self.module_data:
            return {"total_groups": 0}
            
        # 按模块类型统计
        type_count = {}
        total_area = 0
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        
        for module in self.module_data:
            module_type = module['module_type']
            type_count[module_type] = type_count.get(module_type, 0) + 1
            total_area += module['area']
            
            min_x = min(min_x, module['x_position'])
            min_y = min(min_y, module['y_position'])
            max_x = max(max_x, module['x_end'])
            max_y = max(max_y, module['y_end'])
            
        return {
            'total_groups': len(self.module_data),
            'type_distribution': type_count,
            'total_area': round(total_area, 2),
            'layout_bounds': {
                'min_x': round(min_x, 2),
                'min_y': round(min_y, 2),
                'max_x': round(max_x, 2),
                'max_y': round(max_y, 2),
                'used_width': round(max_x - min_x, 2),
                'used_height': round(max_y - min_y, 2)
            }
        }

# 使用示例
if __name__ == "__main__":
    # 创建导出器实例
    exporter = LayoutCSVExporter()
    
    # 添加示例数据
    exporter.add_module_group(1, 'A', 0, 0, 8, 6, False, 4, 2, 2)
    exporter.add_module_group(2, 'B', 10, 0, 4, 4, False, 2, 2, 1)
    exporter.add_module_group(3, 'C', 0, 8, 12, 5, False, 8, 2, 4)
    
    # 导出数据
    exporter.export_to_csv(site_width=50, site_height=50)
    
    # 打印摘要
    summary = exporter.get_summary()
    print("\n=== 布局摘要 ===")
    print(f"总群组数: {summary['total_groups']}")
    print(f"模块类型分布: {summary['type_distribution']}")
    print(f"总占用面积: {summary['total_area']} m^2")
    print(f"布局范围: {summary['layout_bounds']['used_width']}m x {summary['layout_bounds']['used_height']}m")
