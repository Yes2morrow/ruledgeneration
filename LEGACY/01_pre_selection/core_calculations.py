def validate_inputs(N: int, S: float, days: int):
    if not isinstance(N, int) or N <=0:
        raise ValueError('避难人数必须是正整数')

    try:
        s0 = S / N  # 人均空间
    except ZeroDivisionError:
        raise ValueError('避难人数不能为0')
    
    # 检查最低要求：人均空间3平米
    if s0 < 3:
        raise ValueError(f'  人均空间不足！当前：{s0:.2f} m^2/人，最低要求：3 m^2/人\n'
                        f'   场馆面积：{S} m^2，避难人数：{N}人\n'
                        f'   建议：减少避难人数至{int(S/3)}人以下，或增大场馆面积至{N*3} m^2以上')
    if days < 1:
        raise ValueError('安置时长不能小于1天')
    
    return round(s0, 2)


def _shift_space_type(base_type: str, shift: int):
    """在经济型-均衡型-舒适型之间做有限位移。"""
    type_order = ['经济型', '均衡型', '舒适型']
    current_index = type_order.index(base_type)
    target_index = max(0, min(len(type_order) - 1, current_index + shift))
    return type_order[target_index]


def build_recommendation_profile(N: int, S: float, days: int):
    """
    构建推荐画像。

    规则说明：
    1. 人数压力优先级最高，主要由人均面积决定，人数极大时进一步偏向高密度模块。
    2. 安置时长作为二级修正，时长长则向更舒适方向偏移，时长短则允许更紧凑。
    """
    s0 = validate_inputs(N, S, days)

    # 人数优先：优先根据人均面积和总人数判定安置压力。
    if s0 <= 3.3 or N >= 240:
        people_priority = '经济型'
        people_locked = True
    elif s0 <= 4.6 or N >= 120:
        people_priority = '均衡型'
        people_locked = False
    else:
        people_priority = '舒适型'
        people_locked = False

    # 时间次之：仅在人数压力不是极端时，对舒适度做单级修正。
    if days <= 3:
        time_shift = -1
        time_label = '短期安置'
    elif days >= 30:
        time_shift = 1
        time_label = '长期安置'
    else:
        time_shift = 0
        time_label = '中期安置'

    if people_priority == '舒适型':
        # 宽松场地 + 低人数时，以舒适度优先，短时安置不再强制降档。
        final_type = '舒适型'
    elif people_locked and time_shift > 0:
        final_type = people_priority
    else:
        final_type = _shift_space_type(people_priority, time_shift)

    preference_map = {
        '舒适型': ['舒适型', '均衡型', '经济型'],
        '均衡型': ['均衡型', '经济型', '舒适型'],
        '经济型': ['经济型', '均衡型', '舒适型'],
    }

    return {
        'space_type': final_type,
        'module_preferences': preference_map[final_type],
        'people_priority': people_priority,
        'people_locked': people_locked,
        'time_label': time_label,
        'time_shift': time_shift,
        'per_capita_area': s0,
    }


def calculate_space_type(N, S, days):
    profile = build_recommendation_profile(N, S, days)
    return profile['space_type']


# 模块定义字典
modules = {
    # 注意：length对应x轴（绘图中的长度），width对应y轴（绘图中的宽度）
    'A': {'type':'舒适型', 'beds':3, 'cost':3842, 'priority':1, 'length':5600, 'width':5600, 'name':'A', 'visual_ready': True},
    'B': {'type':'舒适型', 'beds':2, 'cost':2298, 'priority':2, 'length':4000, 'width':2000, 'name':'B', 'visual_ready': True},
    'C': {'type':'经济型', 'beds':3, 'cost':1035, 'priority':1, 'length':4500, 'width':2500, 'name':'C', 'visual_ready': True},
    'D': {'type':'经济型', 'beds':2, 'cost':690, 'priority':2, 'length':3600, 'width':1800, 'name':'D', 'visual_ready': True},
    'E': {'type':'均衡型', 'beds':3, 'cost':2133, 'priority':1, 'length':3000, 'width':3800, 'name':'E', 'visual_ready': False},
    'F': {'type':'均衡型', 'beds':3, 'cost':3373, 'priority':2, 'length':3000, 'width':5500, 'name':'F', 'visual_ready': False},
    'G': {'type':'均衡型', 'beds':4, 'cost':3384, 'priority':3, 'length':3200, 'width':4000, 'name':'G', 'visual_ready': False},
}

import logging
import sys
import os
# 添加solution_optimizer所在目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'layout_optimization'))

from solution_optimizer import find_best_layout_solution

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def select_modules(module_preferences, N, all_length, all_width):
    """
    根据用户偏好、人数和场地尺寸，选择最优的模块组合和布局。

    此函数现在是新一代优化器 `solution_optimizer` 的入口点。
    所有复杂的计算逻辑都已移交，这里只负责调用和返回结果。
    """
    logging.info("接收到布局请求，调用新一代解决方案优化器...")
    
    try:
        # 直接调用重构后的核心算法
        result = find_best_layout_solution(
            module_preferences=module_preferences,
            N=N,
            all_length=all_length,
            all_width=all_width
        )
        
        if result:
            logging.info("优化器成功返回最佳布局方案。")
        else:
            # find_best_layout_solution 内部会抛出 ValueError，但为了健壮性我们还是处理空返回值
            logging.warning("优化器未能找到任何有效方案。")
            
        return result

    except ValueError as e:
        # 捕获并记录在优化过程中发生的、可预见的错误（如无解）
        logging.error(f"优化器在寻找解决方案时遇到问题: {e}")
        return None
    except Exception as e:
        # 捕_捕获任何意外错误
        logging.error(f"调用优化器时发生意外错误: {e}", exc_info=True)
        return None
