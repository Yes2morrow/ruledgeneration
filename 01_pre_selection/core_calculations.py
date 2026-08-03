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


def _classify_density_level(per_capita_area: float, evacuees: int, days: int) -> str:
    """按人均面积、人数规模和安置时长划分场景密度。"""
    if per_capita_area <= 4.2:
        return '高密度/高压'
    if evacuees >= 180 and per_capita_area <= 9.0:
        return '高密度/高压'
    if per_capita_area <= 7.2:
        return '中密度'
    if evacuees >= 120 and per_capita_area <= 10.5:
        return '中密度'
    if days >= 30 and per_capita_area <= 8.8:
        return '中密度'
    return '低密度'


def build_recommendation_profile(N: int, S: float, days: int):
    """
    构建推荐画像。

    规则说明：
    1. 人数压力优先级最高，主要由人均面积决定，人数极大时进一步偏向高密度模块。
    2. 安置时长作为二级修正，时长长则向更舒适方向偏移，时长短则允许更紧凑。
    """
    s0 = validate_inputs(N, S, days)

    density_level = _classify_density_level(s0, N, days)

    # 人数压力优先：先判断高压/中压/低压，再映射到空间类型。
    if density_level == '高密度/高压':
        people_priority = '经济型'
        people_locked = s0 <= 3.8 or N >= 240
    elif density_level == '中密度':
        people_priority = '均衡型'
        people_locked = False
    else:
        people_priority = '舒适型'
        people_locked = False

    # 时间次之：短期安置在中高压场景下允许再压紧一档；长期安置在非高压场景下向舒适侧偏移。
    if days <= 3:
        if density_level == '中密度' and s0 < 7.8:
            time_shift = -1
        else:
            time_shift = 0
        time_label = '短期安置'
    elif days >= 30:
        time_shift = 0 if density_level == '高密度/高压' else 1
        time_label = '长期安置'
    else:
        time_shift = 0
        time_label = '中期安置'

    if people_locked and time_shift > 0:
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
        'density_level': density_level,
        'per_capita_area': s0,
    }


def calculate_space_type(N, S, days):
    profile = build_recommendation_profile(N, S, days)
    return profile['space_type']


# 模块定义字典
modules = {
    # 注意：length对应x轴（绘图中的长度），width对应y轴（绘图中的宽度）
    'A': {'type':'舒适型', 'beds':3, 'cost':3842, 'priority':1, 'length':4600, 'width':5600, 'name':'A', 'visual_ready': True},
    'B': {'type':'舒适型', 'beds':2, 'cost':2298, 'priority':2, 'length':4000, 'width':2000, 'name':'B', 'visual_ready': True},
    'C': {'type':'经济型', 'beds':3, 'cost':1035, 'priority':2, 'length':4500, 'width':2500, 'name':'C', 'visual_ready': True},
    'D': {'type':'经济型', 'beds':2, 'cost':690, 'priority':1, 'length':3600, 'width':1800, 'name':'D', 'visual_ready': True},
    'E': {'type':'均衡型', 'beds':3, 'cost':2133, 'priority':1, 'length':3000, 'width':5500, 'name':'E', 'visual_ready': True},
    'F': {'type':'均衡型', 'beds':3, 'cost':3373, 'priority':2, 'length':3000, 'width':3800, 'name':'F', 'visual_ready': True},
    'G': {'type':'均衡型', 'beds':4, 'cost':3384, 'priority':3, 'length':2800, 'width':4100, 'name':'G', 'visual_ready': True},
}

import logging
import sys
import os
# 添加solution_optimizer所在目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'layout_optimization'))

from solution_optimizer import find_best_layout_solution

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def select_modules(
    module_preferences,
    N,
    all_length,
    all_width,
    time_limit_seconds=None,
    recommendation_mode='fill',
):
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
            all_width=all_width,
            time_limit_seconds=time_limit_seconds,
            recommendation_mode=recommendation_mode,
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
