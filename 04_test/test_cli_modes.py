"""端到端测试: 验证 generate / recommend 两种模式 + 渲染输出。"""
import tempfile
import sys
from pathlib import Path

_PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJ / "01_pre_selection"))
sys.path.insert(0, str(_PROJ / "05_config_and_tools"))

from service_adapter import generate_plan_payload, generate_recommendation_payload


def _print_summary(name: str, payload: dict):
    s = payload["summary"]
    lay = payload["layout"]
    out = lay.get("outputFiles", {})
    print(f"\n=== {name} ===")
    print(f"  runId={payload['runId']}")
    print(f"  mode={payload['mode']} spaceType={payload['spaceType']}")
    print(f"  selectedModules={payload['selectedModules']}")
    print(f"  summary: {s}")
    print(f"  layout: success={lay['success']} groups={len(lay['groups'])} "
          f"beds={len(lay['beds'])} roads={len(lay['roads'])}")
    print(f"  metrics={lay['metrics']}")
    print(f"  unplaced={lay['unplaced']}")
    if out:
        print(f"  png={out.get('layoutPng')}")
        print(f"  json={out.get('layoutJson')}")


def main():
    with tempfile.TemporaryDirectory(prefix="layout-e2e-") as out_dir:

        # 1. generate 模式: A=4, C=8 (36 床, 场地 48x14)
        p1 = generate_plan_payload(
            evacuees=36,
            length=48.0,
            width=14.0,
            days=3,
            selected_modules={"A": 4, "C": 8},
            output_dir=out_dir,
            run_id="gen_a4_c8",
        )
        _print_summary("generate | A=4,C=8 | 48x14", p1)

        # 校验: 床周边道路
        m1 = p1["layout"]["metrics"]
        assert m1.get("beds_without_road_access_count", 0) == 0, "generate 模式有床缺道路!"
        assert p1["layout"]["success"], "generate 模式排布失败!"

        # 2. recommend 模式: 60 人, 48x14, 7 天, balanced
        p2 = generate_recommendation_payload(
            evacuees=60,
            length=48.0,
            width=14.0,
            days=7,
            strategy_key="balanced",
            output_dir=out_dir,
            run_id="rec_60p_balanced",
        )
        _print_summary("recommend | 60人 | 48x14 | balanced", p2)
        assert p2["summary"]["totalBeds"] >= 60, "recommend 床位不足 60!"
        m2 = p2["layout"]["metrics"]
        assert m2.get("beds_without_road_access_count", 0) == 0, "recommend 模式有床缺道路!"
        assert p2["layout"]["success"], "recommend 模式排布失败!"

        # 3. recommend 模式: 经济型小场地 24 人, 18x16, 3 天
        p3 = generate_recommendation_payload(
            evacuees=24,
            length=18.0,
            width=16.0,
            days=3,
            strategy_key="economy",
            output_dir=out_dir,
            run_id="rec_24p_economy",
        )
        _print_summary("recommend | 24人 | 18x16 | economy", p3)
        assert p3["summary"]["totalBeds"] >= 24, "recommend(小场地) 床位不足 24!"

        for payload in [p1, p2, p3]:
            metrics = payload["layout"]["metrics"]
            assert metrics["road_model"] == "explicit_aisles_and_public_clearance"
            assert metrics["road_connected"] and metrics["road_opening_errors_count"] == 0

        print("\n所有端到端测试通过!")
        return 0

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
