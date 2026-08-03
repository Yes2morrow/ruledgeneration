# -*- coding: utf-8 -*-
"""
排布系统批量诊断脚本

用途：
1. 验证模块组团规则是否符合预期
2. 验证手工指定模块组合能否完成落位
3. 验证自动推荐链路在多种场景下的表现
4. 输出布局图片、CSV、分析文本与总摘要

标注时间：2026-06-10
"""

from __future__ import annotations

import json
import sys
import traceback
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "07_layout_tests" / "outputs"


def _append_sys_path(path: Path):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.append(path_str)


_append_sys_path(ROOT_DIR / "01_pre_selection")
_append_sys_path(ROOT_DIR / "05_config_and_tools")
_append_sys_path(ROOT_DIR / "02_placement_generation" / "layout_optimization")
_append_sys_path(ROOT_DIR / "03_visualization")

from core_calculations import build_recommendation_profile, modules, select_modules
from arrangement_rules import calculate_aisle_width, generate_group_arrangement
from service_adapter import generate_plan_payload, generate_recommendation_payload
from auto_retry_layout import calculate_smart_layout_with_retry
from smart_layout_optimizer import calculate_group_dimensions
from visualization import draw_layout
from layout_csv_exporter import LayoutCSVExporter


GROUP_GENERATION_CASES = [
    {"name": "gen_e_5", "module_name": "E", "quantity": 5},
    {"name": "gen_f_5", "module_name": "F", "quantity": 5},
    {"name": "gen_f_8", "module_name": "F", "quantity": 8},
    {"name": "gen_g_6", "module_name": "G", "quantity": 6},
]

MANUAL_LAYOUT_CASES = [
    {"name": "manual_f_5", "selection": {"F": 5}, "all_length": 20.0, "all_width": 18.0, "space_type": "均衡型"},
    {"name": "manual_f_8", "selection": {"F": 8}, "all_length": 26.0, "all_width": 18.0, "space_type": "均衡型"},
    {"name": "manual_g_6", "selection": {"G": 6}, "all_length": 24.0, "all_width": 20.0, "space_type": "均衡型"},
    {"name": "manual_f4_g4_mix", "selection": {"F": 4, "G": 4}, "all_length": 28.0, "all_width": 20.0, "space_type": "均衡型"},
    {"name": "manual_f_4_narrow", "selection": {"F": 4}, "all_length": 8.5, "all_width": 12.0, "space_type": "均衡型"},
]

AUTO_CASES = [
    {"name": "auto_low_24_18x16_7d", "N": 24, "all_length": 18.0, "all_width": 16.0, "days": 7},
    {"name": "auto_low_36_20x18_14d", "N": 36, "all_length": 20.0, "all_width": 18.0, "days": 14},
    {"name": "auto_low_60_26x22_30d", "N": 60, "all_length": 26.0, "all_width": 22.0, "days": 30},
    {"name": "auto_low_100_50x30_3d", "N": 100, "all_length": 50.0, "all_width": 30.0, "days": 3},
    {"name": "auto_medium_60_22x18_7d", "N": 60, "all_length": 22.0, "all_width": 18.0, "days": 7},
    {"name": "auto_pressure_90_28x22_3d", "N": 90, "all_length": 28.0, "all_width": 22.0, "days": 3},
    {"name": "auto_pressure_200_50x30_3d", "N": 200, "all_length": 50.0, "all_width": 30.0, "days": 3},
    {"name": "auto_capacity_110_22x18_3d", "N": 110, "all_length": 22.0, "all_width": 18.0, "days": 3},
]


def ensure_case_dir(case_name: str) -> Path:
    case_dir = OUTPUT_DIR / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir


def normalize_manual_selection(selection: dict) -> list:
    normalized = []
    for module_name, quantity in selection.items():
        normalized.append({
            "module": deepcopy(modules[module_name]),
            "quantity": quantity
        })
    return normalized


def expand_groups_from_selection(modules_selection: list) -> list:
    groups = []
    for item in modules_selection:
        module_name = item["module"]["name"]
        quantity = item["quantity"]
        arrangements = generate_group_arrangement(module_name, quantity)
        for group in arrangements:
            group_count = group.get("count", 1)
            for _ in range(group_count):
                groups.append({k: deepcopy(v) for k, v in group.items() if k != "count"})
    return groups


def attach_layout_positions(groups: list, positions: list, rotations: list):
    for index, group in enumerate(groups):
        group["position"] = positions[index]
        if index < len(rotations):
            group["rotated"] = rotations[index]


def export_group_analysis(case_dir: Path, groups: list, all_length: float, all_width: float):
    exporter = LayoutCSVExporter()
    for index, group in enumerate(groups, start=1):
        group_width, group_height = calculate_group_dimensions(
            group,
            rotated=group.get("rotated", False)
        )
        x_pos, y_pos = group.get("position", (0.0, 0.0))
        exporter.add_module_group(
            group_id=index,
            module_type=group["module"]["name"],
            x=x_pos,
            y=y_pos,
            width=group_width,
            height=group_height,
            is_rotated=group.get("rotated", False),
            module_count=group.get("module_count", group.get("rows", 1) * group.get("cols", 1)),
            rows=group.get("rows", 1),
            cols=group.get("cols", 1),
        )

    csv_path = case_dir / "layout_analysis.csv"
    exporter.export_to_csv(
        filename=str(csv_path),
        site_width=all_length,
        site_height=all_width
    )
    overlaps = exporter.check_overlaps()
    violations = exporter.check_boundary_violations(all_length, all_width)
    summary = exporter.get_summary()
    return overlaps, violations, summary


def build_group_notes(groups: list) -> list:
    notes = []
    group_type_counter = Counter(group.get("group_type", "未标记") for group in groups)
    if any(group["module"]["name"] == "F" for group in groups):
        has_f_quad = any(group.get("group_type") == "F1" for group in groups)
        if not has_f_quad and sum(group.get("module_count", 1) for group in groups if group["module"]["name"] == "F") >= 4:
            notes.append("F 数量已达到 4 个以上，但未形成 F1 四联组。")
    if any(group["module"]["name"] == "G" for group in groups):
        non_single_g = [group.get("group_type") for group in groups if group["module"]["name"] == "G" and group.get("group_type") != "G_single"]
        if non_single_g:
            notes.append(f"G 出现了非单体群组: {non_single_g}")
    notes.append(f"group_type 分布: {dict(group_type_counter)}")
    return notes


def write_case_report(case_dir: Path, report_data: dict):
    report_path = case_dir / "case_report.json"
    report_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def run_group_generation_case(case: dict) -> dict:
    case_dir = ensure_case_dir(case["name"])
    module_name = case["module_name"]
    quantity = case["quantity"]
    groups = generate_group_arrangement(module_name, quantity)

    expanded_groups = []
    for group in groups:
        for _ in range(group.get("count", 1)):
            expanded_groups.append({k: deepcopy(v) for k, v in group.items() if k != "count"})

    total_modules = sum(group.get("module_count", group.get("rows", 1) * group.get("cols", 1)) for group in expanded_groups)
    group_types = Counter(group.get("group_type", "未标记") for group in expanded_groups)
    issues = []

    if module_name == "F" and quantity >= 4 and "F1" not in group_types:
        issues.append("F 组团规则未产出 F1。")
    if module_name == "G" and any(group_type != "G_single" for group_type in group_types):
        issues.append("G 不是纯单体输出。")
    if total_modules != quantity:
        issues.append(f"组团模块总数异常：期望 {quantity}，实际 {total_modules}")

    report_data = {
        "case_type": "group_generation",
        "module_name": module_name,
        "quantity": quantity,
        "expanded_group_count": len(expanded_groups),
        "group_types": dict(group_types),
        "total_modules": total_modules,
        "issues": issues,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    write_case_report(case_dir, report_data)
    return {
        "name": case["name"],
        "success": len(issues) == 0,
        "issues": issues,
        "summary": report_data,
    }


def run_manual_layout_case(case: dict) -> dict:
    case_dir = ensure_case_dir(case["name"])
    modules_selection = normalize_manual_selection(case["selection"])
    groups = expand_groups_from_selection(modules_selection)
    aisle = calculate_aisle_width(case["space_type"])

    fits, positions, rotations = calculate_smart_layout_with_retry(
        groups,
        aisle,
        case["all_width"],
        case["all_length"],
        modules_selection=modules_selection,
        max_retries=2
    )

    issues = []
    report_data = {
        "case_type": "manual_layout",
        "selection": case["selection"],
        "field": {"length": case["all_length"], "width": case["all_width"]},
        "space_type": case["space_type"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if not fits:
        issues.append("布局失败，未能完成落位。")
        report_data["success"] = False
        report_data["issues"] = issues
        write_case_report(case_dir, report_data)
        return {
            "name": case["name"],
            "success": False,
            "issues": issues,
            "summary": report_data,
        }

    attach_layout_positions(groups, positions, rotations)
    draw_layout(
        groups,
        aisle,
        case["all_length"],
        case["all_width"],
        show_labels=True,
        output_filename=str(case_dir / "layout.png")
    )
    overlaps, violations, csv_summary = export_group_analysis(
        case_dir,
        groups,
        case["all_length"],
        case["all_width"]
    )

    if overlaps:
        issues.append(f"检测到群组重叠 {len(overlaps)} 处。")
    if violations:
        issues.append(f"检测到边界违规 {len(violations)} 处。")

    notes = build_group_notes(groups)
    report_data.update({
        "success": len(issues) == 0,
        "issues": issues,
        "notes": notes,
        "group_count": len(groups),
        "group_types": dict(Counter(group.get("group_type", "未标记") for group in groups)),
        "csv_summary": csv_summary,
    })
    write_case_report(case_dir, report_data)

    return {
        "name": case["name"],
        "success": len(issues) == 0,
        "issues": issues,
        "summary": report_data,
    }


def run_auto_case(case: dict) -> dict:
    case_dir = ensure_case_dir(case["name"])
    recommendation_payload = generate_recommendation_payload(
        evacuees=case["N"],
        length=case["all_length"],
        width=case["all_width"],
        days=case["days"],
        quiet=True,
    )
    recommendation_profile = build_recommendation_profile(
        case["N"],
        case["all_length"] * case["all_width"],
        case["days"]
    )
    space_type = recommendation_profile["space_type"]
    aisle = calculate_aisle_width(space_type)
    layout_plan = select_modules(
        recommendation_profile["module_preferences"],
        case["N"],
        case["all_length"],
        case["all_width"]
    )

    issues = []
    report_data = {
        "case_type": "auto_layout",
        "N": case["N"],
        "field": {"length": case["all_length"], "width": case["all_width"]},
        "days": case["days"],
        "recommendation_profile": recommendation_profile,
        "capacity_estimate": recommendation_payload.get("capacityEstimate"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if recommendation_payload.get("capacityEstimate", {}).get("capacityLimited") and recommendation_payload.get("selectedModules"):
        plan_payload = generate_plan_payload(
            evacuees=case["N"],
            length=case["all_length"],
            width=case["all_width"],
            days=case["days"],
            output_dir=str(case_dir),
            quiet=True,
        )
        report_data.update({
            "success": True,
            "issues": [],
            "notes": [recommendation_payload["capacityEstimate"]["message"]],
            "space_type": recommendation_payload["spaceType"],
            "scenario_space_type": recommendation_payload.get("scenarioSpaceType"),
            "density_level": recommendation_profile.get("density_level"),
            "selected_modules": recommendation_payload["selectedModules"],
            "fill_ratio": recommendation_payload["recommendationMeta"].get("fillRatio"),
            "final_score": recommendation_payload["recommendationMeta"].get("finalScore"),
            "solution_level": recommendation_payload["recommendationMeta"].get("solutionLevel"),
            "plan_replay_success": True,
            "layout_metrics": plan_payload["layout"]["layoutMetrics"],
            "summary": plan_payload["summary"],
        })
        write_case_report(case_dir, report_data)
        return {
            "name": case["name"],
            "success": True,
            "issues": [],
            "summary": report_data,
        }

    if not layout_plan:
        issues.append("自动推荐未返回有效布局方案。")
        report_data["success"] = False
        report_data["issues"] = issues
        write_case_report(case_dir, report_data)
        return {
            "name": case["name"],
            "success": False,
            "issues": issues,
            "summary": report_data,
        }

    groups = deepcopy(layout_plan["groups"])
    draw_layout(
        groups,
        aisle,
        case["all_length"],
        case["all_width"],
        show_labels=True,
        output_filename=str(case_dir / "layout.png")
    )
    overlaps, violations, csv_summary = export_group_analysis(
        case_dir,
        groups,
        case["all_length"],
        case["all_width"]
    )

    if overlaps:
        issues.append(f"检测到群组重叠 {len(overlaps)} 处。")
    if violations:
        issues.append(f"检测到边界违规 {len(violations)} 处。")
    if not layout_plan.get("modules"):
        issues.append("自动推荐返回了空模块列表。")

    selected_module_counter = {
        item["module"]["name"]: item["quantity"]
        for item in layout_plan.get("modules", [])
    }
    notes = build_group_notes(groups)
    if not any(module_name in selected_module_counter for module_name in ("F", "G")):
        notes.append("本案例未选中 F/G，说明当前评分更偏向其他均衡型模块。")

    replay_result = None
    try:
        replay_result = generate_plan_payload(
            evacuees=case["N"],
            length=case["all_length"],
            width=case["all_width"],
            days=case["days"],
            selected_modules=selected_module_counter,
            quiet=True,
        )
    except Exception as exc:
        issues.append(f"推荐结果回放生成失败：{exc}")

    report_data.update({
        "success": len(issues) == 0,
        "issues": issues,
        "notes": notes,
        "space_type": space_type,
        "density_level": recommendation_profile.get("density_level"),
        "selected_modules": selected_module_counter,
        "fill_ratio": layout_plan.get("fill_ratio"),
        "final_score": layout_plan.get("final_score"),
        "solution_level": layout_plan.get("solution_level"),
        "plan_replay_success": replay_result is not None,
        "csv_summary": csv_summary,
    })
    write_case_report(case_dir, report_data)

    return {
        "name": case["name"],
        "success": len(issues) == 0,
        "issues": issues,
        "summary": report_data,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_results = []

    for case in GROUP_GENERATION_CASES:
        try:
            all_results.append(run_group_generation_case(case))
        except Exception as exc:
            all_results.append({
                "name": case["name"],
                "success": False,
                "issues": [f"异常: {exc}"],
                "traceback": traceback.format_exc(),
            })

    for case in MANUAL_LAYOUT_CASES:
        try:
            all_results.append(run_manual_layout_case(case))
        except Exception as exc:
            all_results.append({
                "name": case["name"],
                "success": False,
                "issues": [f"异常: {exc}"],
                "traceback": traceback.format_exc(),
            })

    for case in AUTO_CASES:
        try:
            all_results.append(run_auto_case(case))
        except Exception as exc:
            all_results.append({
                "name": case["name"],
                "success": False,
                "issues": [f"异常: {exc}"],
                "traceback": traceback.format_exc(),
            })

    summary_lines = [
        "# 排布系统诊断摘要",
        "",
        f"- 标注时间：{started_at}",
        f"- 测试总数：{len(all_results)}",
        f"- 成功数：{sum(1 for item in all_results if item.get('success'))}",
        f"- 失败数：{sum(1 for item in all_results if not item.get('success'))}",
        "",
        "## 案例结果",
    ]

    for result in all_results:
        status_text = "通过" if result.get("success") else "失败"
        summary_lines.append(f"- `{result['name']}`：{status_text}")
        issues = result.get("issues") or []
        if issues:
            for issue in issues:
                summary_lines.append(f"  - {issue}")

    summary_path = OUTPUT_DIR / "summary.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    json_path = OUTPUT_DIR / "summary.json"
    json_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"诊断完成，摘要文件：{summary_path}")
    print(f"结构化结果：{json_path}")


if __name__ == "__main__":
    main()
