"""product_search tool — hybrid retrieval with structured filters.

Used by: Recommendation Agent
"""
from __future__ import annotations

import json
import logging

from retrieval.hybrid_search import HybridSearch
from storage.database import Database

logger = logging.getLogger(__name__)

# ── Tool schema for Claude ──────────────────────────────────────────────────

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "product_search",
        "description": (
            "搜索产品目录，支持语义检索和结构化过滤。"
            "返回最相关的产品列表（含名称、品牌、价格、成分、评分）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或自然语言描述，如'补水精华'、'适合敏感肌的面霜'",
                },
                "skin_type": {
                    "type": "string",
                    "enum": ["dry", "oily", "combination", "sensitive", "normal"],
                    "description": "肤质过滤（可选）",
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "moisturizer", "serum", "cleanser", "toner",
                        "sunscreen", "eye_cream", "mask",
                    ],
                    "description": "产品类别过滤（可选）",
                },
                "price_min": {
                    "type": "number",
                    "description": "最低价格（元，可选）",
                },
                "price_max": {
                    "type": "number",
                    "description": "最高价格（元，可选）",
                },
                "exclude_ingredients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要排除的成分INCI名称列表（如用户过敏成分），可选",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量上限，默认5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}


# ── Tool implementation ─────────────────────────────────────────────────────

async def product_search(
    hybrid: HybridSearch,
    db: Database,
    query: str,
    skin_type: str | None = None,
    category: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    exclude_ingredients: list[str] | None = None,
    limit: int = 5,
) -> str:
    """Execute hybrid search + structured filters, return JSON string."""
    # Stage 1: Hybrid retrieval (semantic + keyword)
    candidate_ids = await hybrid.search(query, final_top_k=limit * 3)

    # Stage 2: Load full product records
    products = await db.get_products_by_ids(candidate_ids)

    # Stage 3: Apply structured filters
    filtered: list[dict] = []
    for p in products:
        # Skin type filter
        if skin_type and skin_type not in p["suitable_skin_types"]:
            continue

        # Category filter
        if category and p["category"] != category:
            continue

        # Price range filter
        if price_min is not None and p["retail_price"] < price_min:
            continue
        if price_max is not None and p["retail_price"] > price_max:
            continue

        # Exclude ingredients filter (check if any excluded ingredient is in product)
        if exclude_ingredients:
            ingredients_lower = [ing.lower() for ing in p["ingredients_full"]]
            if any(excl.lower() in ingredients_lower for excl in exclude_ingredients):
                logger.debug("Excluded %s due to ingredient filter", p["name_cn"])
                continue

        filtered.append(p)

    # Stage 4: Take top N and format for agent
    results = filtered[:limit]
    formatted = [
        {
            "product_id": p["product_id"],
            "name_cn": p["name_cn"],
            "brand": p["brand"],
            "category": p["category"],
            "price": p["retail_price"],
            "suitable_skin_types": p["suitable_skin_types"],
            "skin_concerns": p["skin_concerns"],
            "key_ingredients": p["key_ingredients"],
            "alcohol_free": p["alcohol_free"],
            "fragrance_free": p["fragrance_free"],
            "rating": f"{p['rating_avg']}/5.0 ({p['rating_count']}条评价)",
            "description": p["description"][:100] + "..." if len(p["description"]) > 100 else p["description"],
        }
        for p in results
    ]

    logger.info(
        "product_search: query='%s', candidates=%d, filtered=%d, returned=%d",
        query, len(candidate_ids), len(filtered), len(formatted),
    )

    return json.dumps({"results": formatted, "total_found": len(filtered)}, ensure_ascii=False, indent=2)
