"""Mock order data — 5 orders covering all status states.

Used by the Commerce Agent's order_service tool.
"""
from __future__ import annotations

ORDERS: list[dict] = [
    {
        "order_id": "ORD-20260320-001",
        "user_id": "demo_user",
        "product_id": "prod_005",
        "quantity": 1,
        "unit_price": 128.0,
        "total_price": 128.0,
        "status": "delivered",
        "logistics_no": "SF1234567890",
        "logistics_co": "SF顺丰速运",
        "created_at": "2026-03-20T10:30:00",
        "shipped_at": "2026-03-21T09:15:00",
        "estimated_delivery": "2026-03-23",
        "address": {
            "city": "上海市",
            "district": "静安区",
            "street": "南京西路1234号",
            "zip": "200040",
        },
    },
    {
        "order_id": "ORD-20260328-002",
        "user_id": "demo_user",
        "product_id": "prod_009",
        "quantity": 2,
        "unit_price": 89.0,
        "total_price": 178.0,
        "status": "shipped",
        "logistics_no": "JD7654321098",
        "logistics_co": "京东物流",
        "created_at": "2026-03-28T14:22:00",
        "shipped_at": "2026-03-29T11:00:00",
        "estimated_delivery": "2026-04-02",
        "address": {
            "city": "北京市",
            "district": "朝阳区",
            "street": "三里屯路20号",
            "zip": "100027",
        },
    },
    {
        "order_id": "ORD-20260331-003",
        "user_id": "demo_user",
        "product_id": "prod_005",
        "quantity": 1,
        "unit_price": 128.0,
        "total_price": 128.0,
        "status": "paid",
        "logistics_no": None,
        "logistics_co": None,
        "created_at": "2026-03-31T16:45:00",
        "shipped_at": None,
        "estimated_delivery": "2026-04-04",
        "address": {
            "city": "广州市",
            "district": "天河区",
            "street": "天河路385号",
            "zip": "510620",
        },
    },
    {
        "order_id": "ORD-20260401-004",
        "user_id": "demo_user",
        "product_id": "prod_009",
        "quantity": 1,
        "unit_price": 89.0,
        "total_price": 89.0,
        "status": "pending",
        "logistics_no": None,
        "logistics_co": None,
        "created_at": "2026-04-01T09:10:00",
        "shipped_at": None,
        "estimated_delivery": None,
        "address": {
            "city": "深圳市",
            "district": "南山区",
            "street": "科技园路18号",
            "zip": "518057",
        },
    },
    {
        "order_id": "ORD-20260315-005",
        "user_id": "demo_user",
        "product_id": "prod_005",
        "quantity": 1,
        "unit_price": 128.0,
        "total_price": 128.0,
        "status": "cancelled",
        "logistics_no": None,
        "logistics_co": None,
        "created_at": "2026-03-15T08:00:00",
        "shipped_at": None,
        "estimated_delivery": None,
        "address": {
            "city": "成都市",
            "district": "武侯区",
            "street": "人民南路四段11号",
            "zip": "610041",
        },
    },
]

# Own-brand product catalog (for Commerce Agent browse action)
OWN_BRAND_PRODUCTS = ["prod_005", "prod_009"]

STATUS_LABELS: dict[str, str] = {
    "pending": "待付款",
    "paid": "已付款，备货中",
    "shipped": "已发货，运输中",
    "delivered": "已签收",
    "cancelled": "已取消",
}
