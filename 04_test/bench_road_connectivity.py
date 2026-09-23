"""Local CPU benchmark; no cloud requests. Run with --repeats 3 for medians."""
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '05_config_and_tools'))
import service_adapter  # Sets up project import paths.
from config_loader import load_module_config
from layout_optimizer import calculate_layout
from renderer import render_layout, get_texture_handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', default=str(ROOT / '06_output_results' / 'road_benchmark'))
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    get_texture_handler()  # Report warm texture-cache costs separately from process startup.
    cases = [
        ('blocked_64', {'D':2,'G':12,'C':4}, 20, 30),
        ('mixed_100', {'A':26,'B':4,'C':2,'D':4}, 30, 45),
        ('B_300', {'B':150}, 80, 80),
        ('G_300', {'G':75}, 80, 80),
    ]
    rows = []
    for name, selection, w, h in cases:
        row = {'case':name,'requested_beds':sum(load_module_config(c)['beds']*q for c,q in selection.items())}
        for checked in [False, True]:
            durations = []
            for _ in range(args.repeats):
                start = time.perf_counter()
                result = calculate_layout(selection, [(0,0),(w,0),(w,h),(0,h)], road_check=checked)
                durations.append(time.perf_counter()-start)
            row['checked_s' if checked else 'without_candidate_checks_s'] = round(statistics.median(durations), 4)
        start = time.perf_counter()
        render_layout(result, out / f'{name}.png', show_structure=False)
        row.update(render_s=round(time.perf_counter()-start,4), actual_beds=len(result.beds),
                   blocked=result.metrics['beds_without_road_access_count'],
                   opening_errors=result.metrics['road_opening_errors_count'],
                   public_width_m=result.metrics['public_road_width_m'],
                   success=result.success,
                   checked_candidates=result.metrics['connectivity_candidates_checked'])
        rows.append(row)
        print(json.dumps(row), flush=True)
    report = {'python':platform.python_version(), 'platform':platform.platform(),
              'processor':platform.processor(), 'repeats':args.repeats, 'cases':rows}
    (out/'benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    main()
