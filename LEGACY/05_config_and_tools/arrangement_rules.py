import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '01_pre_selection'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'intra_module_rules'))

from core_calculations import modules
from module_c_organizer import organize_module_c
from module_a_organizer import organize_module_a
from module_b_organizer import organize_module_b
from module_d_organizer import organize_module_d

def generate_group_arrangement(module_type, quantity):
    """
    生成模块的群组排列规则
    :param module_type: 模块类型(A-G)
    :param quantity: 需要排列的模块数量
    :return: 一个包含群组配置字典的列表
    """
    # 对于模块C，使用新的、独立的组织逻辑
    if module_type == 'C':
        return organize_module_c(quantity)

    # 对于模块A，使用新的、独立的组织逻辑
    if module_type == 'A':
        return organize_module_a(quantity)
    
    # 对于模块B，使用新的、独立的组织逻辑
    if module_type == 'B':
        return organize_module_b(quantity)
    
    # 对于模块D，使用新的、独立的组织逻辑
    if module_type == 'D':
        return organize_module_d(quantity)

    # --- 保持其他模块的旧有简单规则 ---
    config = {
        'rows': 1,
        'columns': 1,
    }

    
    if module_type == 'D':
        n = quantity // 2
        if n > 0:
            if n <= 4:
                config.update({'rows': 2, 'columns': n})
            elif 4 < n <= 8:
                config.update({'rows': 4, 'columns': n // 2})
            else: # 超过8个组合单元（16个模块）时
                config.update({'rows': 4, 'columns': 4})

    elif module_type == 'E':
        if quantity > 0:
            if quantity <= 8:
                config['columns'] = quantity
            else: # 超过8个
                config.update({'rows': 2, 'columns': (quantity + 1) // 2})

    elif module_type == 'F':
        n = quantity // 2
        if n > 0:
            if n <= 4:
                config.update({'rows': 1, 'columns': 2 * n})
            else: # 超过4个组合单元（8个模块）
                config.update({'rows': 2, 'columns': n})

    elif module_type == 'G':
        if quantity > 0:
            if quantity <= 4:
                config['rows'] = quantity
            elif 4 < quantity <= 8:
                config.update({'columns': 2, 'rows': (quantity + 1) // 2})
            else: # 超过8个
                config.update({'columns': 3, 'rows': (quantity + 2) // 3})

    # 为保证返回类型统一，将单个群组配置封装在列表中
    # 注意：对于数量过多的情况，旧逻辑可能仍会生成超大群组
    if quantity > 0:
        num_groups = 1
        # 一个简化的分页逻辑，避免生成过于庞大的单个群组
        if module_type in ['A', 'B', 'D', 'E', 'F'] and config['columns'] * config['rows'] > 16:
             # 如果一个群组的模块数大于16，就拆分
            total_modules_per_group = config['rows'] * config['columns']
            num_groups = (quantity + total_modules_per_group - 1) // total_modules_per_group
            
        final_groups = []
        for _ in range(num_groups):
            final_groups.append({
                'module': modules[module_type],
                'rows': config['rows'],
                'cols': config['columns'],
                'count': 1 # 每个字典代表一个独立的群组
            })
        
        # 处理不能均分时的最后一个群组的数量
        if quantity % (config['rows'] * config['columns']) != 0:
            # 此处简化处理，暂不精确计算最后一个组的行列数
            pass

        return final_groups
    else:
        return []


def calculate_aisle_width(space_type):
    """ 根据空间类型返回过道宽度 """
    return {
        '经济型': 1.2, # 根据PPT，模块C的过道是1200
        '均衡型': 1.8,
        '舒适型': 2.0
    }[space_type]

def get_module_spacing_config(module_type, space_type='均衡型'):
    """
    根据模块类型和空间类型获取间距配置
    
    Args:
        module_type (str): 模块类型（A, B, C, D等）
        space_type (str): 空间类型（'经济型', '均衡型', '舒适型'）
    
    Returns:
        dict: 间距配置字典，包含vertical_gap和horizontal_gap
    """
    # 基础间距配置
    base_spacing = calculate_aisle_width(space_type)
    
    if module_type == 'A':
        return {'vertical_gap': 0, 'horizontal_gap': 0}
    elif module_type == 'B':
        return {'vertical_gap': 0, 'horizontal_gap': 0}
    elif module_type == 'C':
        return {'vertical_gap': 0, 'horizontal_gap': 0}
    elif module_type == 'D':
        return {'vertical_gap': 0, 'horizontal_gap': 0}
    else:
        return {'vertical_gap': 0, 'horizontal_gap': 0}
