"""order_service tool — e-commerce operations for own-brand products.

Used by: Commerce Agent

Single tool with action dispatch:
  - browse:  List all own-brand products in stock
  - place:   Create a new order
  - query:   Check order status
  - track:   Get logistics tracking info
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from data.orders import STATUS_LABELS
from storage.database import Database

logger = logging.getLogger(__name__)

# ── Tool schema ─────────────────────────────────────────────────────────────

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "order_service",
        "description": (
            "自有品牌电商服务：浏览产品、下单、查询订单状态、追踪物流。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["browse", "place_order", "query_order", "track_logistics"],
                    "description": (
                        "操作类型：browse=浏览自有品牌产品，place_order=下单，"
                        "query_order=查询订单，track_logistics=追踪物流"
                    ),
                },
                "user_id": {
                    "type": "string",
                    "description": "用户ID（所有操作必需）",
                },
                "product_id": {
                    "type": "string",
                    "description": "产品ID（place_order时必需）",
                },
                "quantity": {
                    "type": "integer",
                    "description": "购买数量（place_order时可选，默认1）",
                    "default": 1,
                },
                "order_id": {
                    "type": "string",
                    "description": "订单ID（query_order和track_logistics时必需）",
                },
            },
            "required": ["action", "user_id"],
        },
    },
}


# ── Tool implementation ─────────────────────────────────────────────────────

async def order_service(
    db: Database,
    action: str,
    user_id: str,
    product_id: str | None = None,
    quantity: int = 1,
    order_id: str | None = None,
) -> str:
    """Dispatch to appropriate e-commerce operation, return JSON string."""

    if action == "browse":
        return await _browse_own_brand(db)

    elif action == "place_order":
        if not product_id:
            return json.dumps({"error": "缺少product_id参数"}, ensure_ascii=False)
        return await _place_order(db, user_id, product_id, quantity)

    elif action == "query_order":
        if not order_id:
            return json.dumps({"error": "缺少order_id参数"}, ensure_ascii=False)
        return await _query_order(db, order_id)

    elif action == "track_logistics":
        if not order_id:
            return json.dumps({"error": "缺少order_id参数"}, ensure_ascii=False)
        return await _track_logistics(db, order_id)

    else:
        return json.dumps({"error": f"未知操作：{action}"}, ensure_ascii=False)


# ── Action handlers ─────────────────────────────────────────────────────────

async def _browse_own_brand(db: Database) -> str:
    """List all own-brand products currently in stock."""
    products = await db.get_own_brand_products()
    formatted = [
        {
            "product_id": p["product_id"],
            "name_cn": p["name_cn"],
            "category": p["category"],
            "price": p["retail_price"],
            "suitable_skin_types": p["suitable_skin_types"],
            "key_ingredients": p["key_ingredients"],
            "rating": f"{p['rating_avg']}/5.0",
            "description": p["description"][:80] + "..." if len(p["description"]) > 80 else p["description"],
        }
        for p in products
    ]
    logger.info("browse_own_brand: %d products", len(formatted))
    return json.dumps({"products": formatted, "total": len(formatted)}, ensure_ascii=False, indent=2)


async def _place_order(db: Database, user_id: str, product_id: str, quantity: int) -> str:
    """Create a new order (mock — always succeeds)."""
    # Verify product exists and is own-brand
    products = await db.get_products_by_ids([product_id])
    if not products:
        return json.dumps({"error": f"产品不存在：{product_id}"}, ensure_ascii=False)

    product = products[0]
    if not product["is_own_brand"]:
        return json.dumps({"error": "该产品不是自有品牌，无法通过此渠道购买"}, ensure_ascii=False)

    # Generate order
    now = datetime.utcnow()
    order_id = f"ORD-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"
    total_price = product["retail_price"] * quantity

    order = {
        "order_id": order_id,
        "user_id": user_id,
        "product_id": product_id,
        "quantity": quantity,
        "unit_price": product["retail_price"],
        "total_price": total_price,
        "status": "pending",
        "logistics_no": None,
        "logistics_co": None,
        "created_at": now.isoformat(),
        "shipped_at": None,
        "estimated_delivery": (now + timedelta(days=3)).strftime("%Y-%m-%d"),
        "address": {
            "city": "上海市",
            "district": "静安区",
            "street": "南京西路1234号",
            "zip": "200040",
        },
    }

    await db.create_order(order)

    result = {
        "success": True,
        "order_id": order_id,
        "product_name": product["name_cn"],
        "quantity": quantity,
        "total_price": total_price,
        "status": "待付款",
        "estimated_delivery": order["estimated_delivery"],
        "message": f"订单创建成功！订单号：{order_id}，请尽快完成付款。",
    }

    logger.info("place_order: user=%s, product=%s, order=%s", user_id, product_id, order_id)
    return json.dumps(result, ensure_ascii=False, indent=2)


async def _query_order(db: Database, order_id: str) -> str:
    """Query order status."""
    order = await db.get_order(order_id)
    if not order:
        return json.dumps({"error": f"订单不存在：{order_id}"}, ensure_ascii=False)

    # Get product name
    products = await db.get_products_by_ids([order["product_id"]])
    product_name = products[0]["name_cn"] if products else "（产品信息缺失）"

    result = {
        "order_id": order["order_id"],
        "product_name": product_name,
        "quantity": order["quantity"],
        "total_price": order["total_price"],
        "status": order["status"],
        "status_label": STATUS_LABELS.get(order["status"], order["status"]),
        "created_at": order["created_at"][:10],
        "estimated_delivery": order.get("estimated_delivery"),
    }

    if order["status"] in ("shipped", "delivered"):
        result["logistics_no"] = order.get("logistics_no")
        result["logistics_co"] = order.get("logistics_co")

    logger.info("query_order: order=%s, status=%s", order_id, order["status"])
    return json.dumps(result, ensure_ascii=False, indent=2)


async def _track_logistics(db: Database, order_id: str) -> str:
    """Get logistics tracking info (mock data)."""
    order = await db.get_order(order_id)
    if not order:
        return json.dumps({"error": f"订单不存在：{order_id}"}, ensure_ascii=False)

    if order["status"] not in ("shipped", "delivered"):
        return json.dumps(
            {"error": f"订单尚未发货，当前状态：{STATUS_LABELS.get(order['status'])}"},
            ensure_ascii=False,
        )

    # Mock tracking timeline
    tracking = {
        "order_id": order["order_id"],
        "logistics_no": order["logistics_no"],
        "logistics_co": order["logistics_co"],
        "current_status": "运输中" if order["status"] == "shipped" else "已签收",
        "estimated_delivery": order.get("estimated_delivery"),
        "timeline": [
            {"time": order["created_at"][:16], "status": "订单已创建"},
            {"time": order.get("shipped_at", "")[:16], "status": "商品已发货"},
        ],
    }

    if order["status"] == "shipped":
        tracking["timeline"].append({
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "status": "运输中 - 包裹已到达中转站",
        })
    else:
        tracking["timeline"].append({
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "status": "已签收 - 感谢购买",
        })

    logger.info("track_logistics: order=%s, status=%s", order_id, order["status"])
    return json.dumps(tracking, ensure_ascii=False, indent=2)
