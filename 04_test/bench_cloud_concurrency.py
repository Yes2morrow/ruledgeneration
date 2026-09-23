"""本地并发性能与渲染隔离检查，不请求云端服务。

用途:
  1. 测量单请求(排布 + 2 次渲染)耗时, 判断能否放进小程序 15s 超时窗口。
  2. 并发渲染时校验输出 PNG 是否出现「串图」(A 任务的图被 B 任务覆盖),
     用于验证 matplotlib pyplot 全局状态在多线程下的问题。

运行:
  python 04_test/bench_cloud_concurrency.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RULE_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = RULE_ROOT / "06_output_results" / "_bench"

for sub in (
    RULE_ROOT / "01_pre_selection",
    RULE_ROOT / "02_placement_generation" / "layout_optimization",
    RULE_ROOT / "03_visualization",
    RULE_ROOT / "05_config_and_tools",
):
    if str(sub) not in sys.path:
        sys.path.insert(0, str(sub))


def fingerprint(png_path: Path) -> int:
    """对 PNG 字节流做哈希, 用于识别并发串图。"""
    import hashlib

    return int(hashlib.md5(png_path.read_bytes()).hexdigest()[:12], 16)


def one_run(idx: int, evacuees: int, length: float, width: float) -> dict:
    from service_adapter import generate_recommendation_payload

    run_id = f"bench_{idx}_{int(time.time() * 1000)}"
    t0 = time.perf_counter()
    payload = generate_recommendation_payload(
        evacuees=evacuees,
        length=length,
        width=width,
        days=3,
        strategy_key="balanced",
        recommendation_mode="match_input",
        output_dir=str(OUT_DIR),
        run_id=run_id,
    )
    cost = time.perf_counter() - t0
    files = payload["layout"]["outputFiles"]
    return {
        "idx": idx,
        "runId": run_id,
        "cost": cost,
        "layoutPng": Path(files["layoutPng"]).name,
        "structurePng": Path(files["structurePng"]).name,
        "beds": len(payload["layout"].get("beds", [])),
        "groups": len(payload["layout"].get("groups", [])),
    }


def bench_serial(n: int = 3) -> None:
    print(f"\n=== 串行 {n} 次 ===")
    for i in range(n):
        r = one_run(i, 60, 48.0, 14.0)
        print(f"  #{i} 耗时 {r['cost']:.2f}s  床位 {r['beds']}  群组 {r['groups']}")


def bench_concurrent(n: int = 4) -> None:
    print(f"\n=== 并发 {n} 路(不同人数/场地, 便于识别串图) ===")
    # 每个任务用不同的场地尺寸, 渲染出的图片必然不同
    cases = [(20 + i * 10, 30.0 + i * 6, 12.0) for i in range(n)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [
            pool.submit(one_run, i, ev, ln, wd)
            for i, (ev, ln, wd) in enumerate(cases)
        ]
        results = [f.result() for f in futures]
    total = time.perf_counter() - t0

    for r in results:
        print(f"  #{r['idx']} runId={r['runId']} 耗时 {r['cost']:.2f}s")

    print(f"  并发总耗时 {total:.2f}s (串行预计 {sum(r['cost'] for r in results):.2f}s)")

    print("\n=== 串图检测(同一份布局结果, 8 路并发渲染, 对比字节流) ===")
    from config_loader import get_site_polygon
    from layout_optimizer import calculate_layout
    from renderer import render_layout

    site = get_site_polygon(length_m=48.0, width_m=14.0)
    result = calculate_layout({"A": 4, "C": 8}, site, allow_decompose=True, road_check=True)

    def _render(tag: str) -> int:
        p = OUT_DIR / f"race_{tag}.png"
        render_layout(result, str(p), show_structure=False)
        return fingerprint(p)

    with ThreadPoolExecutor(max_workers=8) as pool:
        fps = list(pool.map(_render, [f"t{i}" for i in range(8)]))

    uniq = set(fps)
    print(f"  8 路并发渲染同一布局, 得到 {len(uniq)} 种不同字节流")
    if len(uniq) == 1:
        print("  [OK] 未出现串图")
    else:
        print("  [RISK] 出现串图: pyplot 全局 figure 在线程间互相覆盖")
    return None


if __name__ == "__main__":
    bench_serial(3)
    bench_concurrent(4)
