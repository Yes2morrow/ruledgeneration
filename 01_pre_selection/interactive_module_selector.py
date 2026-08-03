import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '05_config_and_tools'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '02_placement_generation', 'layout_optimization'))

from core_calculations import modules, select_modules, build_recommendation_profile
from arrangement_rules import generate_group_arrangement, calculate_aisle_width
from auto_retry_layout import calculate_smart_layout_with_retry
import copy

def display_modules():
    """显示所有可用模块"""
    print("\n可用模块列表：")
    print("{:<5} {:<8} {:<6} {:<8} {:<10}".format("模块", "类型", "床位数", "成本", "优先级"))
    print("-" * 45)
    for name, info in modules.items():
        print("{:<5} {:<8} {:<6} {:<8} {:<10}".format(
            name, info['type'], info['beds'], info['cost'], info['priority']))

def display_current_selection(selected_modules):
    """显示当前选择的模块"""
    print("\n当前选择的模块方案：")
    if not selected_modules:
        print("  暂无选择")
        return
    
    print("{:<5} {:<10}".format("模块", "数量"))
    print("-" * 15)
    for item in selected_modules:
        print("{:<5} {:<10}".format(item['module']['name'], item['quantity']))

def calculate_total(selected_modules):
    """计算总床位数和总成本"""
    total_beds = sum(item['module']['beds'] * item['quantity'] for item in selected_modules)
    total_cost = sum(item['module']['cost'] * item['quantity'] for item in selected_modules)
    return total_beds, total_cost


def _expand_group_configs(module_selection):
    """展开群组配置，确保预校验与最终布局使用同一份群组展开规则。"""
    group_configs = []
    for item in module_selection:
        arrangement = generate_group_arrangement(item['module']['name'], item['quantity'])
        for group in arrangement:
            count = group.get('count', 1)
            for _ in range(count):
                group_copy = {k: v for k, v in group.items() if k != 'count'}
                group_configs.append(group_copy)
    return group_configs

def check_layout_feasibility(module_selection, aisle_width, all_length, all_width):
    """检查当前模块选择的布局是否可行"""
    if not module_selection:
        return True # 空白方案总是可行的

    group_configs = _expand_group_configs(module_selection)
    fits, _, _ = calculate_smart_layout_with_retry(
        group_configs,
        aisle_width,
        all_width,
        all_length,
        modules_selection=module_selection,
        max_retries=3,
    )
    return bool(fits)

def interactive_module_selection(space_type, N, all_length, all_width, auto_select=False,
                                 module_preferences=None, recommendation_profile=None, days=None,
                                 recommendation_mode='match_input', time_limit_seconds=20.0):
    """具备实时布局验证的交互式模块选择器
    :param space_type: 空间类型
    :param N: 需要的床位数
    :param all_width: 场地总宽度
    :param all_height: 场地总高度
    :param auto_select: 是否自动选择推荐方案
    """
    print(f"\n开始交互式模块选择 (空间类型: {space_type}, 需要床位: {N})")
    print(f"场地尺寸: {all_length}米 x {all_width}米")
    aisle = calculate_aisle_width(space_type)

    # 生成经过布局验证的初始推荐方案
    try:
        # 若上游未显式传入推荐画像，则按当前输入即时生成。
        if recommendation_profile is None:
            recommendation_profile = build_recommendation_profile(
                N, all_length * all_width, days if days is not None else 7
            )

        if module_preferences is None:
            module_preferences = recommendation_profile.get(
                'module_preferences',
                ['均衡型', '经济型', '舒适型']
            )

        print(
            f"自动推荐逻辑：人数优先={recommendation_profile.get('people_priority', space_type)}，"
            f"时长判断={recommendation_profile.get('time_label', '未提供')}，"
            f"模块偏好顺序={module_preferences}"
        )
        print("自动推荐目标：优先尽量填满平面，其次满足人数，再匹配模块舒适度。")

        # 交互式入口默认优先严格匹配输入人数，避免先推荐超配方案再在最终确认时失败。
        recommended_layout = select_modules(
            module_preferences,
            N,
            all_length,
            all_width,
            time_limit_seconds=time_limit_seconds,
            recommendation_mode=recommendation_mode,
        )
        
        if recommended_layout:
            print("\n系统推荐方案：")
            display_current_selection(recommended_layout['modules'])
            total_beds, total_cost = calculate_total(recommended_layout['modules'])
            print(f"\n推荐方案总计：{total_beds} 个床位, {total_cost:.2f} 元")
            selected_modules = recommended_layout['modules']
        else:
            print("\n无法生成满足所有约束的推荐方案。请尝试手动配置。")
            recommended_layout = None
            selected_modules = []

    except ValueError as e:
        print(f"\n无法生成推荐方案：{e}")
        recommended_layout = None
        selected_modules = []

    if auto_select:
        print("\n自动选择推荐方案。")
        return recommended_layout

    # 用户自定义调整
    while True:
        print("\n请选择操作：")
        print("1. 查看可用模块")
        print("2. 查看当前选择")
        print("3. 添加模块")
        print("4. 移除模块")
        print("5. 确认最终方案")
        print("6. 恢复系统推荐")
        
        try:
            choice = input("请输入选项 (1-6): ").strip()
        except EOFError:
            # 处理管道输入或自动化测试时的EOF错误
            if recommended_layout:
                print("检测到自动化输入，直接返回系统推荐方案。")
                return recommended_layout
            print("检测到自动化输入，但当前没有可用推荐方案。")
            return None
        
        if choice == '1':
            display_modules()
        
        elif choice == '2':
            display_current_selection(selected_modules)
            if selected_modules:
                total_beds, total_cost = calculate_total(selected_modules)
                print(f"\n当前方案总计：{total_beds} 个床位, 估算成本 {total_cost:.2f} 元")
                if total_beds >= N: print(f"[满足] 床位需求 ({total_beds} >= {N})")
                else: print(f"[不足] 床位不足 (需要 {N} 个，当前 {total_beds} 个)")
        
        elif choice == '3' or choice == '4': #合并添加和移除逻辑
            action = 'add' if choice == '3' else 'remove'
            prompt_action = "添加" if action == 'add' else "移除"
            module_name = input(f"请输入要{prompt_action}的模块名称: ").strip().upper()
            if module_name not in modules:
                print(f"错误：模块 '{module_name}' 不存在。")
                continue
            try:
                quantity = int(input(f"请输入要{prompt_action}的数量: "))
                if quantity <= 0: print("数量必须大于0"); continue
                # 检查模块C和模块A的数量限制
                if modules[module_name]['name'] == 'C' and quantity % 2 != 0:
                    print("错误：模块C的数量必须是2的倍数。")
                    continue
                if modules[module_name]['name'] == 'A' and quantity % 2 != 0:
                    print("错误：模块A的数量必须是2的倍数（偶数）。")
                    continue
                temp_selection = copy.deepcopy(selected_modules)
                
                # 更新临时选择
                found = False
                for item in temp_selection:
                    if item['module']['name'] == module_name:
                        if action == 'add': item['quantity'] += quantity
                        else: item['quantity'] -= quantity
                        found = True
                        break
                if not found and action == 'add':
                    temp_selection.append({'module': modules[module_name], 'quantity': quantity})
                elif not found and action == 'remove':
                    print(f"错误：模块 '{module_name}' 不在当前选择中。")
                    continue
                
                # 清理数量小于等于0的模块
                temp_selection = [item for item in temp_selection if item['quantity'] > 0]

                # 验证布局可行性
                if check_layout_feasibility(temp_selection, aisle, all_length, all_width):
                    selected_modules = temp_selection
                    print(f"已{prompt_action} {quantity} 个模块 {module_name}")
                else:
                    print(f"操作无效：此更改将导致布局超出场地范围({all_length}x{all_width}米)，操作已取消。")

            except ValueError: print("请输入有效的数字")

        elif choice == '5':
            if not selected_modules: print("当前没有选择任何模块。") ; continue
            total_beds, total_cost = calculate_total(selected_modules)
            if total_beds < N: print(f"床位不足(需要{N}个)，请添加模块。") ; continue
            
            print("\n正在进行最终布局计算...")
            group_configs = _expand_group_configs(selected_modules)

            print("\n启动自动重试布局系统...")
            fits, positions, rotations = calculate_smart_layout_with_retry(
                group_configs, aisle, all_width, all_length, 
                modules_selection=selected_modules, max_retries=3
            )
            
            # 兼容原有代码格式
            final_layout_result = (fits, positions, rotations)

            # 处理calculate_layout的返回值（可能是2个或3个值）
            if len(final_layout_result) == 2:
                fits, positions = final_layout_result
                rotations = [False] * len(group_configs)  # 默认不旋转
            elif len(final_layout_result) == 3:
                fits, positions, rotations = final_layout_result
            else:
                raise ValueError(f"calculate_layout返回了意外的值数量: {len(final_layout_result)}")

            # 将旋转信息也整合到群组数据中
            for i, group in enumerate(group_configs):
                if i < len(rotations):
                    group['rotated'] = rotations[i]

            if fits:
                print("最终方案确认成功！")
                # 将位置信息整合回群组列表
                for i, group in enumerate(group_configs):
                    group['position'] = positions[i]

                final_plan = {
                    'modules': selected_modules,
                    'total_cost': total_cost,
                    'total_beds': total_beds,
                    'groups': group_configs # 返回带有位置信息的群组列表
                }
                return final_plan
            else:
                print("错误：最终方案无法在场地内成功布局，请重新调整。")
        
        elif choice == '6':
            if recommended_layout:
                selected_modules = recommended_layout['modules']
                print("已恢复为系统最初的推荐方案。")
            else:
                print("没有可用的系统推荐方案。")
        
        else:
            print("无效选项，请重新选择。")
