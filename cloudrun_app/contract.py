"""v2 内部结果 → 小程序端 API 契约 的适配层。

小程序 WechatMiniprogram 是按规则系统 v1 的返回结构实现的:
  - pages/cart/cart.js 依赖 recommendation.cartItems / summary / spaceType / strategy.label
  - pages/plan/plan.js 依赖 outputFiles.textureOnly || outputFiles.withLabels,
    以及 layout.groupCount / textSummary / layout.layoutMetrics

规则系统 2.0 的 service_adapter 输出结构与 v1 不同(缺 cartItems、textSummary,
layout 里是 metrics 而不是 layoutMetrics, outputFiles 键名也不同)。
与其改小程序端, 统一在这里做适配, 对外复刻 v1 契约。

另一条硬约束: 对外**绝不回传容器绝对路径**, 只给可访问 URL。
"""
from __future__ import annotations

from typing import Dict, List


def build_cart_items(selected_modules: Dict[str, int], catalog: List[dict]) -> List[dict]:
    """把 {模块编码: 数量} 组装成小程序购物车需要的 cartItems。

    小程序 normalizeDynamicCartItems 会读取 code / quantity / step / bedsPerUnit。
    """
    meta = {m.get("code"): m for m in catalog}
    items: List[dict] = []
    for code, qty in (selected_modules or {}).items():
        m = meta.get(code)
        if not m:
            continue
        qty = int(qty)
        beds_per_unit = int(m.get("bedsPerUnit", 0))
        cost_per_unit = int(m.get("costPerUnit", 0))
        items.append({
            "code": code,
            "name": m.get("name", code),
            "quantity": qty,
            "step": int(m.get("step", 1)),
            "bedsPerUnit": beds_per_unit,
            "beds": beds_per_unit * qty,
            "cost": cost_per_unit * qty,
            "type": m.get("type", ""),
            "color": m.get("color", "#444444"),
            "ruleText": m.get("ruleText", ""),
        })
    return items


def build_text_summary(payload: dict) -> str:
    summary = payload.get("summary") or {}
    layout = payload.get("layout") or {}
    metrics = layout.get("metrics") or {}
    strategy = payload.get("strategy") or {}

    used = float(metrics.get("used_area_m2", 0) or 0)
    site = float(metrics.get("site_area_m2", 0) or 0)

    return (
        f"{strategy.get('label') or '自动推荐'} · {payload.get('spaceType') or '未标注'}\n"
        f"目标 {summary.get('targetBeds', 0)} 床，当前 {summary.get('totalBeds', 0)} 床，"
        f"共 {summary.get('totalQuantity', 0)} 个模块、{summary.get('totalTypes', 0)} 类模块。\n"
        f"占地率 {metrics.get('utilization', 0)}%，"
        f"已用 {round(used, 2)} ㎡ / 场地 {round(site, 2)} ㎡。\n"
        f"总成本 {summary.get('totalCost', 0)}。"
    )


def to_v1_contract(payload: dict, catalog: List[dict], public_files: Dict[str, str]) -> dict:
    """把 service_adapter 的输出转成小程序端期望的结构。

    :param public_files: {"layoutPng": "<url>", "structurePng": "<url>", "layoutJson": "<url>"}
    """
    layout = dict(payload.get("layout") or {})
    metrics = layout.get("metrics") or {}
    summary = payload.get("summary") or {}
    selected = payload.get("selectedModules") or {}
    cart_items = build_cart_items(selected, catalog)

    used = float(metrics.get("used_area_m2", 0) or 0)
    site = float(metrics.get("site_area_m2", 0) or 0)

    layout["groupCount"] = len(layout.get("groups", []))
    layout["totalBeds"] = int(metrics.get("total_beds", summary.get("totalBeds", 0)) or 0)
    layout["totalCost"] = int(summary.get("totalCost", 0) or 0) or sum(i["cost"] for i in cart_items)
    layout["layoutMetrics"] = {
        "usageRatio": f"{metrics.get('utilization', 0)}%",
        "remainingArea": round(site - used, 2),
        "usedArea": round(used, 2),
        "siteArea": round(site, 2),
    }

    # 仅暴露可访问地址; 键名沿用 v1 契约
    layout["outputFiles"] = {
        "textureOnly": public_files.get("layoutPng", ""),
        "withLabels": public_files.get("structurePng", ""),
        "layoutJson": public_files.get("layoutJson", ""),
    }

    recommendation = {
        "strategy": payload.get("strategy") or {"key": "", "label": "自动推荐"},
        "spaceType": payload.get("spaceType", ""),
        "recommendationMode": payload.get("recommendationMode", "match_input"),
        "selectedModules": selected,
        "cartItems": cart_items,
        "summary": summary,
        "selectionIssues": payload.get("selectionIssues", []),
    }

    return {
        "runId": payload.get("runId", ""),
        "generatedAt": payload.get("generatedAt", ""),
        "mode": payload.get("mode", ""),
        "site": payload.get("site", {}),
        "recommendation": recommendation,
        "cartItems": cart_items,
        "summary": summary,
        "layout": layout,
        "outputFiles": layout["outputFiles"],
        "textSummary": build_text_summary(payload),
    }
