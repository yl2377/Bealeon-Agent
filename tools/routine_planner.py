"""routine_planner tool — merged compatibility check + routine step generation.

Used by: Collocation Agent

Combines two previously separate tools:
  - Compatibility check: detect ingredient conflicts (e.g. Retinol + AHA)
  - Routine builder: generate morning/evening skincare steps with wait times
"""
from __future__ import annotations

import json
import logging

from storage.database import Database

logger = logging.getLogger(__name__)

# ── Tool schema ─────────────────────────────────────────────────────────────

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "routine_planner",
        "description": (
            "分析多个产品的成分配伍关系，检测冲突并生成早晚护肤步骤。"
            "返回配伍冲突警告 + 推荐的使用顺序和等待时间。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "products": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "产品名称或product_id列表（如['prod_001', '珂润面霜']）",
                },
                "action": {
                    "type": "string",
                    "enum": ["check_compatibility", "build_routine"],
                    "description": (
                        "操作类型：check_compatibility=仅检测冲突，"
                        "build_routine=生成完整早晚步骤（默认）"
                    ),
                    "default": "build_routine",
                },
            },
            "required": ["products"],
        },
    },
}


# ── Tool implementation ─────────────────────────────────────────────────────

async def routine_planner(
    db: Database,
    products: list[str],
    action: str = "build_routine",
) -> str:
    """Check compatibility + optionally build routine, return JSON string."""
    if not products:
        return json.dumps({"error": "未提供产品列表"}, ensure_ascii=False)

    # Stage 1: Resolve product names/IDs to full product records
    resolved: list[dict] = []
    for query in products:
        if query.startswith("prod_"):
            prods = await db.get_products_by_ids([query])
            if prods:
                resolved.append(prods[0])
        else:
            # Fuzzy match by name
            all_prods = await db.get_all_products()
            query_lower = query.lower()
            for p in all_prods:
                if query_lower in p["name_cn"].lower():
                    resolved.append(p)
                    break

    if not resolved:
        return json.dumps({"error": "未找到任何匹配的产品"}, ensure_ascii=False)

    # Stage 2: Extract all unique ingredients across products
    all_ingredients: set[str] = set()
    product_ingredients: dict[str, list[str]] = {}
    for p in resolved:
        ings = p["key_ingredients"]  # Use key ingredients for conflict detection
        product_ingredients[p["product_id"]] = ings
        all_ingredients.update(ings)

    # Stage 3: Check pairwise compatibility rules
    conflicts: list[dict] = []
    for i, ing_a in enumerate(sorted(all_ingredients)):
        for ing_b in sorted(all_ingredients)[i + 1 :]:
            rules = await db.get_compatibility_rules(ing_a, ing_b)
            for rule in rules:
                if rule["relationship"] == "conflict":
                    # Find which products contain these conflicting ingredients
                    products_with_a = [
                        p["name_cn"] for p in resolved
                        if ing_a in product_ingredients[p["product_id"]]
                    ]
                    products_with_b = [
                        p["name_cn"] for p in resolved
                        if ing_b in product_ingredients[p["product_id"]]
                    ]
                    conflicts.append({
                        "ingredient_a": rule["ingredient_a"],
                        "ingredient_b": rule["ingredient_b"],
                        "severity": rule["severity"],
                        "reason": rule["reason"],
                        "recommendation": rule["recommendation"],
                        "affected_products": {
                            "with_a": products_with_a,
                            "with_b": products_with_b,
                        },
                    })

    # If only checking compatibility, return conflicts
    if action == "check_compatibility":
        result = {
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "products_analyzed": [p["name_cn"] for p in resolved],
        }
        logger.info("routine_planner (check): %d conflicts found", len(conflicts))
        return json.dumps(result, ensure_ascii=False, indent=2)

    # Stage 4: Build routine steps (simplified heuristic)
    # Category order: cleanser → toner → serum → eye_cream → moisturizer → sunscreen
    category_order = ["cleanser", "toner", "serum", "eye_cream", "moisturizer", "sunscreen"]
    sorted_products = sorted(
        resolved,
        key=lambda p: category_order.index(p["category"]) if p["category"] in category_order else 99,
    )

    morning_steps: list[dict] = []
    evening_steps: list[dict] = []

    for idx, p in enumerate(sorted_products, 1):
        step = {
            "step": idx,
            "product": p["name_cn"],
            "category": p["category"],
            "amount": "适量" if p["category"] != "sunscreen" else "一元硬币大小",
            "wait_seconds": 30 if p["category"] in ("serum", "toner") else 60,
        }

        # Sunscreen only in morning
        if p["category"] == "sunscreen":
            morning_steps.append(step)
        # Retinol products only in evening (check key ingredients)
        elif any("retinol" in ing.lower() for ing in p.get("key_ingredients", [])):
            evening_steps.append({**step, "note": "含视黄醇，仅夜间使用"})
        else:
            morning_steps.append(step)
            evening_steps.append(step)

    result = {
        "morning_routine": morning_steps,
        "evening_routine": evening_steps,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "products_analyzed": [p["name_cn"] for p in resolved],
    }

    logger.info(
        "routine_planner (build): morning=%d steps, evening=%d steps, conflicts=%d",
        len(morning_steps), len(evening_steps), len(conflicts),
    )

    return json.dumps(result, ensure_ascii=False, indent=2)
