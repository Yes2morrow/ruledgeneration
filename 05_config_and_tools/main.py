import argparse
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "01_pre_selection"))

from core_calculations import build_recommendation_profile, validate_inputs
from interactive_module_selector import interactive_module_selection
from service_adapter import generate_plan_payload, generate_recommendation_payload


def build_parser():
    parser = argparse.ArgumentParser(description="规则系统命令行入口")
    parser.add_argument(
        "--mode",
        choices=["recommend", "generate", "interactive"],
        default="interactive",
        help="运行模式：recommend 返回推荐结果，generate 直接生成布局图，interactive 为本地交互调试",
    )
    parser.add_argument("--evacuees", type=int, help="避难人数")
    parser.add_argument("--length", type=float, help="场地长度（米）")
    parser.add_argument("--width", type=float, help="场地宽度（米）")
    parser.add_argument("--days", type=int, help="安置时长（天）")
    parser.add_argument(
        "--strategy",
        choices=["comfort", "economy", "balanced"],
        help="前端策略选择，对应舒适型、经济型、平衡型",
    )
    parser.add_argument(
        "--modules-json",
        help="手动指定模块数量，示例：{\"A\": 2, \"E\": 6}",
    )
    parser.add_argument(
        "--output-dir",
        help="布局图输出目录，默认写入 06_output_results",
    )
    parser.add_argument(
        "--run-id",
        help="外部指定本次生成任务 ID，便于和小程序任务号对齐",
    )
    parser.add_argument(
        "--time-limit-seconds",
        type=float,
        default=20.0,
        help="自动推荐搜索的时间上限（秒），超时后返回当前最佳方案",
    )
    parser.add_argument(
        "--recommendation-mode",
        choices=["fill", "match_input"],
        default="match_input",
        help="推荐模式：match_input 为严格按输入人数推荐，fill 为铺满优先",
    )
    return parser


def require_common_args(args):
    missing_args = []
    for field in ("evacuees", "length", "width", "days"):
        if getattr(args, field) is None:
            missing_args.append(field)
    if missing_args:
        raise ValueError(f"缺少必要参数：{', '.join(missing_args)}")


def run_interactive_mode():
    evacuees = int(input("避难人数："))
    all_length = float(input("体育馆长度（米）："))
    all_width = float(input("体育馆宽度（米）："))
    days = int(input("安置时长（天）："))
    area = all_length * all_width

    per_capita_area = validate_inputs(evacuees, area, days)
    recommendation_profile = build_recommendation_profile(evacuees, area, days)
    print(
        f"推荐空间类型：{recommendation_profile['space_type']}，"
        f"人均面积：{per_capita_area:.2f} m^2/人"
    )
    print(
        f"推荐依据：人数优先={recommendation_profile['people_priority']}，"
        f"时长判断={recommendation_profile['time_label']}，"
        f"模块偏好={recommendation_profile['module_preferences']}"
    )

    layout_plan = interactive_module_selection(
        recommendation_profile["space_type"],
        evacuees,
        all_length,
        all_width,
        module_preferences=recommendation_profile["module_preferences"],
        recommendation_profile=recommendation_profile,
        days=days,
        recommendation_mode="match_input",
        time_limit_seconds=20.0,
    )
    if not layout_plan:
        print("未能生成有效的布局方案。")
        return 1

    payload = generate_plan_payload(
        evacuees=evacuees,
        length=all_length,
        width=all_width,
        days=days,
        selected_modules=layout_plan["modules"],
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.mode == "interactive":
            return run_interactive_mode()

        require_common_args(args)
        selected_modules = json.loads(args.modules_json) if args.modules_json else None

        if args.mode == "recommend":
            payload = generate_recommendation_payload(
                evacuees=args.evacuees,
                length=args.length,
                width=args.width,
                days=args.days,
                strategy_key=args.strategy,
                recommendation_mode=args.recommendation_mode,
                time_limit_seconds=args.time_limit_seconds,
            )
        else:
            payload = generate_plan_payload(
                evacuees=args.evacuees,
                length=args.length,
                width=args.width,
                days=args.days,
                strategy_key=args.strategy,
                recommendation_mode=args.recommendation_mode,
                selected_modules=selected_modules,
                output_dir=args.output_dir,
                run_id=args.run_id,
                time_limit_seconds=args.time_limit_seconds,
            )

        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        print(f"输入错误：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"发生未知错误：{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
