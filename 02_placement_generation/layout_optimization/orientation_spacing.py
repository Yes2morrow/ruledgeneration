MIXED_ORIENTATION_SPACING = 1.5

# 空间利用率阈值：低于此值时强惩罚旋转，高于此值时不惩罚
_ROTATION_PENALTY_UTILIZATION_THRESHOLD = 0.6


def _axis_gap(start_a, size_a, start_b, size_b):
    end_a = start_a + size_a
    end_b = start_b + size_b
    if end_a <= start_b:
        return start_b - end_a
    if end_b <= start_a:
        return start_a - end_b
    return 0.0


def _is_true_overlap(start_a, size_a, start_b, size_b):
    """检查两个区间是否真正重叠（边界接触不算重叠）"""
    end_a = start_a + size_a
    end_b = start_b + size_b
    return start_a < end_b - 1e-6 and start_b < end_a - 1e-6


def get_orientation_spacing_requirement(new_rotated, existing_rotated, base_spacing):
    """
    旋转与未旋转群组混排时，强制保留固定 1.5m 间距。
    """
    required_spacing = max(0.0, base_spacing)
    if bool(new_rotated) != bool(existing_rotated):
        required_spacing = max(required_spacing, MIXED_ORIENTATION_SPACING)
    return required_spacing


def violates_spacing_rule(
    x,
    y,
    group_width,
    group_height,
    existing_x,
    existing_y,
    existing_width,
    existing_height,
    required_spacing,
    *,
    allow_zero_vertical_spacing=False
):
    horizontal_gap = _axis_gap(x, group_width, existing_x, existing_width)
    vertical_gap = _axis_gap(y, group_height, existing_y, existing_height)
    # 使用真正的重叠检测：边界接触不算重叠
    horizontal_overlap = _is_true_overlap(x, group_width, existing_x, existing_width)
    vertical_overlap = _is_true_overlap(y, group_height, existing_y, existing_height)

    if horizontal_overlap and vertical_overlap:
        return True

    if allow_zero_vertical_spacing:
        # 纵向允许零间距：边界接触不算违规，只在真正纵向重叠时检查横向间距
        if vertical_overlap and horizontal_gap + 1e-6 < required_spacing:
            return True
        return False

    return horizontal_gap + 1e-6 < required_spacing and vertical_gap + 1e-6 < required_spacing


def calculate_rotation_penalty(rotated, current_positions, all_length, all_width):
    """
    根据当前空间利用率计算旋转惩罚权重。

    策略：
    - 空间利用率低（<阈值）：强惩罚旋转，避免空间充足时的不必要旋转
    - 空间利用率高（>=阈值）：不惩罚旋转，允许资源紧张时旋转以容纳更多模块

    :param rotated: 当前候选是否旋转
    :param current_positions: 已放置群组位置列表
    :param all_length: 场地长度
    :param all_width: 场地宽度
    :return: 旋转惩罚值（0 表示不惩罚，1 表示惩罚）
    """
    if not rotated:
        return 0
    if not current_positions:
        return 1
    total_area = all_length * all_width
    if total_area <= 0:
        return 0
    occupied = 0.0
    for pos in current_positions:
        if isinstance(pos, dict):
            occupied += pos.get('length', 0) * pos.get('width', 0)
        else:
            occupied += pos[2] * pos[3]
    utilization = occupied / total_area
    if utilization < _ROTATION_PENALTY_UTILIZATION_THRESHOLD:
        return 1
    return 0
