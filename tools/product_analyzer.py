"""product_analyzer tool — merged product detail + ingredient safety analysis.

Used by: Analyst Agent

Combines two previously separate tools into one to reduce LLM round-trips:
  - Product detail lookup (name, brand, price, full ingredient list, ratings)
  - Ingredient safety analysis (EWG scores, irritation risk, allergy warnings)
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
        "name": "product_analyzer",
        "description": (
            "查询产品详细信息并分析成分安全性。"
            "返回产品完整信息（成分表、价格、评分）+ 成分EWG评级、刺激风险、过敏警告。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_query": {
                    "type": "string",
                    "description": "产品名称或product_id（如'珂润面霜'或'prod_001'）",
                },
                "user_allergies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "用户已知过敏成分INCI名称列表（可选，用于交叉检查）",
                },
            },
            "required": ["product_query"],
        },
    },
}


# ── Tool implementation ─────────────────────────────────────────────────────

async def product_analyzer(
    db: Database,
    product_query: str,
    user_allergies: list[str] | None = None,
) -> str:
    """Lookup product + analyze all ingredients, return JSON string."""
    user_allergies = user_allergies or []

    # Stage 1: Find product (by ID or fuzzy name match)
    product: dict | None = None
    if product_query.startswith("prod_"):
        products = await db.get_products_by_ids([product_query])
        product = products[0] if products else None
    else:
        # Fuzzy match by name (simple substring search)
        all_products = await db.get_all_products()
        query_lower = product_query.lower()
        for p in all_products:
            if query_lower in p["name_cn"].lower() or query_lower in p.get("name_en", "").lower():
                product = p
                break

    if not product:
        return json.dumps(
            {"error": f"未找到产品：{product_query}"},
            ensure_ascii=False,
        )

    # Stage 2: Analyze all ingredients
    ingredient_names = product["ingredients_full"]
    ingredients_data = await db.get_ingredients_by_names(ingredient_names)

    # Build ingredient analysis list
    ingredient_analysis: list[dict] = []
    allergy_warnings: list[str] = []

    for ing_name in ingredient_names:
        # Find ingredient data (case-insensitive match)
        ing_data = next(
            (i for i in ingredients_data if i["inci_name"].lower() == ing_name.lower()),
            None,
        )

        if ing_data:
            analysis = {
                "inci_name": ing_data["inci_name"],
                "name_cn": ing_data["name_cn"],
                "ewg_score": ing_data["ewg_score"],
                "irritation_risk": ing_data["irritation_risk"],
                "functions": ing_data["functions"],
                "mechanism": ing_data["mechanism"][:80] + "..." if len(ing_data["mechanism"]) > 80 else ing_data["mechanism"],
            }

            # Check allergy cross-reference
            if user_allergies:
                for allergen in user_allergies:
                    if allergen.lower() == ing_name.lower():
                        allergy_warnings.append(
                            f"⚠️ 含有你的过敏成分：{ing_data['name_cn']}（{ing_data['inci_name']}）"
                        )
                        analysis["allergy_warning"] = True

            ingredient_analysis.append(analysis)
        else:
            # Ingredient not in our database
            ingredient_analysis.append({
                "inci_name": ing_name,
                "name_cn": "（数据库中暂无此成分信息）",
                "ewg_score": None,
                "irritation_risk": "unknown",
            })

    # Stage 3: Compute safety summary
    ewg_scores = [i["ewg_score"] for i in ingredient_analysis if i.get("ewg_score") is not None]
    avg_ewg = sum(ewg_scores) / len(ewg_scores) if ewg_scores else None
    high_risk_count = sum(1 for s in ewg_scores if s >= 7)

    safety_summary = {
        "average_ewg_score": round(avg_ewg, 1) if avg_ewg else None,
        "high_risk_ingredients_count": high_risk_count,
        "allergy_warnings": allergy_warnings,
    }

    # Stage 4: Format result
    result = {
        "product": {
            "product_id": product["product_id"],
            "name_cn": product["name_cn"],
            "brand": product["brand"],
            "category": product["category"],
            "price": product["retail_price"],
            "rating": f"{product['rating_avg']}/5.0 ({product['rating_count']}条)",
            "alcohol_free": product["alcohol_free"],
            "fragrance_free": product["fragrance_free"],
            "description": product["description"],
        },
        "ingredients_analysis": ingredient_analysis,
        "safety_summary": safety_summary,
    }

    logger.info(
        "product_analyzer: product=%s, ingredients=%d, avg_ewg=%.1f",
        product["name_cn"], len(ingredient_analysis), avg_ewg or 0,
    )

    return json.dumps(result, ensure_ascii=False, indent=2)
