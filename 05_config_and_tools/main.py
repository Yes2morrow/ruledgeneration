"""命令行入口 - generate / recommend 两种模式。

用法:
  # generate 模式: 用户指定模块
  python main.py --mode generate --evacuees 36 --length 48 --width 14 --days 3 \\
      --modules-json '{"A": 4, "C": 8}'

  # recommend 模式: 按人数自动推荐
  python main.py --mode recommend --evacuees 60 --length 48 --width 14 --days 7 \\
      --strategy balanced

  # 用建筑场地(多边形)替代矩形
  python main.py --mode recommend --evacuees 60 --building slab_residential_18f --days 7
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_CURRENT = Path(__file__).resolve().parent
_RULE_ROOT = _CURRENT.parent
for _sub in (
    _RULE_ROOT / "01_pre_selection",
    _RULE_ROOT / "05_config_and_tools",
):
    if str(_sub) not in sys.path:
        sys.path.insert(0, str(_sub))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="规则系统2.0 - 配置驱动布局生成")
    p.add_argument("--mode", choices=["generate", "recommend"], default="recommend",
                   help="运行模式: recommend 按人数推荐, generate 用指定模块")
    p.add_argument("--evacuees", type=int, required=True, help="避难人数(目标床位)")
    p.add_argument("--length", type=float, help="场地长度(米, 矩形场地)")
    p.add_argument("--width", type=float, help="场地宽度(米, 矩形场地)")
    p.add_argument("--building", type=str, help="建筑配置 id(多边形场地, 优先于 length/width)")
    p.add_argument("--days", type=int, default=3, help="安置时长(天)")
    p.add_argument("--strategy", choices=["comfort", "economy", "balanced"],
                   help="推荐策略(recommend 模式用)")
    p.add_argument("--modules-json", type=str,
                   help='generate 模式的模块选择 JSON, 如 \'{"A": 4, "C": 8}\'')
    p.add_argument("--output-dir", type=str, help="输出目录(默认 06_output_results)")
    p.add_argument("--run-id", type=str, help="任务 id(默认自动生成)")
    p.add_argument("--quiet", action="store_true", help="只输出结果 JSON, 不打印进度")
    return p


def _resolve_site(args):
    """解析场地: building 优先, 否则用 length/width。"""
    from config_loader import get_site_polygon

    if args.building:
        return get_site_polygon(building_id=args.building), ("building", args.building)
    if args.length is not None and args.width is not None:
        return get_site_polygon(length_m=args.length, width_m=args.width), ("rect", (args.length, args.width))
    raise ValueError("必须提供 --building 或 (--length 和 --width)")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.mode == "generate" and not args.modules_json:
            parser.error("generate 模式必须提供 --modules-json")

        site_polygon, site_meta = _resolve_site(args)

        if not args.quiet:
            print(f"[规则系统2.0] 模式={args.mode} 人数={args.evacuees} 场地={site_meta} 时长={args.days}天",
                  file=sys.stderr)

        # 推荐模式直接用矩形 length/width 调 service_adapter
        if args.mode == "recommend":
            if site_meta[0] == "building":
                # recommend 模式暂用矩形参数; 多边形场地走 generate
                # 这里把 building footprint 拟合为外接矩形长度/宽度
                from config_loader import building_to_site_polygon
                pts = building_to_site_polygon(args.building)
                length = max(p[0] for p in pts)
                width = max(p[1] for p in pts)
            else:
                length, width = args.length, args.width

            from service_adapter import generate_recommendation_payload
            payload = generate_recommendation_payload(
                evacuees=args.evacuees,
                length=length,
                width=width,
                days=args.days,
                strategy_key=args.strategy,
                output_dir=args.output_dir,
                run_id=args.run_id,
            )
        else:
            selected = json.loads(args.modules_json)
            if site_meta[0] == "building":
                from config_loader import building_to_site_polygon
                pts = building_to_site_polygon(args.building)
                length = max(p[0] for p in pts)
                width = max(p[1] for p in pts)
            else:
                length, width = args.length, args.width

            from service_adapter import generate_plan_payload
            payload = generate_plan_payload(
                evacuees=args.evacuees,
                length=length,
                width=width,
                days=args.days,
                selected_modules=selected,
                strategy_key=args.strategy,
                output_dir=args.output_dir,
                run_id=args.run_id,
            )

        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    except ValueError as exc:
        print(f"输入错误: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"发生错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
