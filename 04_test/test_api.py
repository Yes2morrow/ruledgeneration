"""测试 WebUI /api/layout 接口。"""
import json
import os
import sys
import urllib.request

# 禁用代理
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:3001"


def call_api(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    # 1. 模块目录
    print("=== GET /api/modules/catalog ===")
    with urllib.request.urlopen(BASE + "/api/modules/catalog", timeout=30) as resp:
        catalog = json.loads(resp.read().decode("utf-8"))
    print(f"模块数: {len(catalog)}")
    for m in catalog[:3]:
        print(f"  {m['code']} type={m['type']} beds={m['bedsPerUnit']} step={m['step']}")

    # 2. generate 模式
    print("\n=== POST /api/layout (generate, A=4 C=8) ===")
    r = call_api("/api/layout", {
        "mode": "generate",
        "evacuees": 36,
        "length": 48.0,
        "width": 14.0,
        "days": 3,
        "selectedModules": {"A": 4, "C": 8},
    })
    lay = r["layout"]
    print(f"success={lay['success']} groups={len(lay['groups'])} beds={len(lay['beds'])} roads={len(lay['roads'])}")
    print(f"metrics={lay['metrics']}")
    print(f"pngUrl={lay.get('pngUrl')}")

    # 3. recommend 模式
    print("\n=== POST /api/layout (recommend, 60人 balanced) ===")
    r2 = call_api("/api/layout", {
        "mode": "recommend",
        "evacuees": 60,
        "length": 48.0,
        "width": 14.0,
        "days": 7,
        "strategy": "balanced",
    })
    lay2 = r2["layout"]
    print(f"success={lay2['success']} groups={len(lay2['groups'])} beds={len(lay2['beds'])}")
    print(f"selectedModules={r2['selectedModules']}")
    print(f"metrics={lay2['metrics']}")
    print(f"pngUrl={lay2.get('pngUrl')}")

    print("\nAPI 测试通过!")


if __name__ == "__main__":
    main()
