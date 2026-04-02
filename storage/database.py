"""SQLite database layer — all persistence for the beauty agent.

Wraps Python's built-in sqlite3 with asyncio.to_thread() for non-blocking I/O.
Creates and seeds all tables on first run from data/ mock files.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    user_id: str
    skin_type: str                    # dry/oily/combination/sensitive/normal
    skin_concerns: list[str]          # ["acne", "dryness", ...]
    known_allergies: list[str]        # ["Fragrance", "Alcohol Denat."]
    budget_min: int
    budget_max: int
    brand_prefs: list[str]            # ["japanese", "korean", "domestic"]
    age_range: str                    # "18-25" | "26-30" | "31-40" | "40+"
    questionnaire_completed: bool

    def to_prompt_context(self) -> str:
        """Render profile as a system-prompt block for agents."""
        concerns = "、".join(self.skin_concerns) if self.skin_concerns else "暂无"
        allergies = "、".join(self.known_allergies) if self.known_allergies else "无"
        prefs = "、".join(self.brand_prefs) if self.brand_prefs else "无特殊偏好"
        return (
            f"【用户皮肤档案】\n"
            f"- 肤质：{self.skin_type}\n"
            f"- 皮肤问题：{concerns}\n"
            f"- 已知过敏成分：{allergies}\n"
            f"- 预算范围：{self.budget_min}–{self.budget_max} 元\n"
            f"- 品牌偏好：{prefs}\n"
            f"- 年龄段：{self.age_range or '未填写'}"
        )


class Database:
    """Async-friendly SQLite manager. Call await db.init() before use."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Create schema and seed mock data (idempotent)."""
        await asyncio.to_thread(self._sync_init)
        logger.info("Database initialised at %s", self._path)

    def _sync_init(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        self._seed_if_empty()

    def _seed_if_empty(self) -> None:
        """Seed products, ingredients, and orders from mock data on first run."""
        from data.ingredients import COMPATIBILITY_RULES, INGREDIENTS
        from data.orders import ORDERS
        from data.products import PRODUCTS

        with self._conn() as conn:
            if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
                for p in PRODUCTS:
                    conn.execute(
                        """INSERT OR IGNORE INTO products VALUES
                        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            p["product_id"], p["name_cn"], p["name_en"],
                            p["brand"], p["category"],
                            json.dumps(p["suitable_skin_types"], ensure_ascii=False),
                            json.dumps(p["skin_concerns"], ensure_ascii=False),
                            p["retail_price"],
                            json.dumps(p["ingredients_full"], ensure_ascii=False),
                            json.dumps(p["key_ingredients"], ensure_ascii=False),
                            int(p["alcohol_free"]), int(p["fragrance_free"]),
                            p["rating_avg"], p["rating_count"],
                            p["search_text"], p["description"],
                            int(p["in_stock"]), int(p["is_own_brand"]),
                        ),
                    )

            if conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0] == 0:
                for ing in INGREDIENTS:
                    conn.execute(
                        """INSERT OR IGNORE INTO ingredients VALUES
                        (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            ing["inci_name"], ing["name_cn"],
                            json.dumps(ing["aliases"], ensure_ascii=False),
                            json.dumps(ing["functions"], ensure_ascii=False),
                            ing["ewg_score"], ing["irritation_risk"],
                            ing["mechanism"], ing["effective_concentration"],
                            json.dumps(ing["incompatible_with"], ensure_ascii=False),
                            json.dumps(ing["synergistic_with"], ensure_ascii=False),
                            int(ing["photosensitive"]),
                        ),
                    )
                for rule in COMPATIBILITY_RULES:
                    conn.execute(
                        """INSERT OR IGNORE INTO compatibility_rules
                        (ingredient_a, ingredient_b, relationship, severity, reason, recommendation)
                        VALUES (?,?,?,?,?,?)""",
                        (
                            rule["ingredient_a"], rule["ingredient_b"],
                            rule["relationship"], rule["severity"],
                            rule["reason"], rule["recommendation"],
                        ),
                    )

            if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
                for o in ORDERS:
                    conn.execute(
                        """INSERT OR IGNORE INTO orders VALUES
                        (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            o["order_id"], o["user_id"], o["product_id"],
                            o["quantity"], o["unit_price"], o["total_price"],
                            o["status"], o["logistics_no"], o["logistics_co"],
                            o["created_at"], o["shipped_at"], o["estimated_delivery"],
                            json.dumps(o["address"], ensure_ascii=False),
                        ),
                    )
            conn.commit()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    # ── User Profile ────────────────────────────────────────────────────────

    async def get_profile(self, user_id: str) -> UserProfile | None:
        def _query() -> UserProfile | None:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
                ).fetchone()
            if row is None:
                return None
            return UserProfile(
                user_id=row["user_id"],
                skin_type=row["skin_type"] or "normal",
                skin_concerns=json.loads(row["skin_concerns"]),
                known_allergies=json.loads(row["known_allergies"]),
                budget_min=row["budget_min"],
                budget_max=row["budget_max"],
                brand_prefs=json.loads(row["brand_prefs"]),
                age_range=row["age_range"] or "",
                questionnaire_completed=bool(row["questionnaire_completed"]),
            )
        return await asyncio.to_thread(_query)

    async def save_profile(self, profile: UserProfile) -> None:
        now = datetime.utcnow().isoformat()

        def _write() -> None:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO user_profiles
                    (user_id, skin_type, skin_concerns, known_allergies,
                     budget_min, budget_max, brand_prefs, age_range,
                     questionnaire_completed, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        skin_type=excluded.skin_type,
                        skin_concerns=excluded.skin_concerns,
                        known_allergies=excluded.known_allergies,
                        budget_min=excluded.budget_min,
                        budget_max=excluded.budget_max,
                        brand_prefs=excluded.brand_prefs,
                        age_range=excluded.age_range,
                        questionnaire_completed=excluded.questionnaire_completed,
                        updated_at=excluded.updated_at""",
                    (
                        profile.user_id, profile.skin_type,
                        json.dumps(profile.skin_concerns, ensure_ascii=False),
                        json.dumps(profile.known_allergies, ensure_ascii=False),
                        profile.budget_min, profile.budget_max,
                        json.dumps(profile.brand_prefs, ensure_ascii=False),
                        profile.age_range,
                        int(profile.questionnaire_completed),
                        now, now,
                    ),
                )
                conn.commit()
        await asyncio.to_thread(_write)

    # ── Products ────────────────────────────────────────────────────────────

    async def get_all_products(self) -> list[dict]:
        def _query() -> list[dict]:
            with self._conn() as conn:
                rows = conn.execute("SELECT * FROM products").fetchall()
            return [_product_row_to_dict(r) for r in rows]
        return await asyncio.to_thread(_query)

    async def get_products_by_ids(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))

        def _query() -> list[dict]:
            with self._conn() as conn:
                rows = conn.execute(
                    f"SELECT * FROM products WHERE product_id IN ({placeholders})", ids
                ).fetchall()
            return [_product_row_to_dict(r) for r in rows]
        return await asyncio.to_thread(_query)

    async def get_own_brand_products(self) -> list[dict]:
        def _query() -> list[dict]:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM products WHERE is_own_brand = 1 AND in_stock = 1"
                ).fetchall()
            return [_product_row_to_dict(r) for r in rows]
        return await asyncio.to_thread(_query)

    # ── Ingredients ─────────────────────────────────────────────────────────

    async def get_ingredient(self, inci_name: str) -> dict | None:
        def _query() -> dict | None:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM ingredients WHERE inci_name = ? COLLATE NOCASE",
                    (inci_name,),
                ).fetchone()
            if row is None:
                return None
            return _ingredient_row_to_dict(row)
        return await asyncio.to_thread(_query)

    async def get_ingredients_by_names(self, names: list[str]) -> list[dict]:
        if not names:
            return []
        results = []
        for name in names:
            row = await self.get_ingredient(name)
            if row:
                results.append(row)
        return results

    async def get_compatibility_rules(
        self, ingredient_a: str, ingredient_b: str
    ) -> list[dict]:
        def _query() -> list[dict]:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM compatibility_rules WHERE
                    (ingredient_a = ? AND ingredient_b = ?) OR
                    (ingredient_a = ? AND ingredient_b = ?)""",
                    (ingredient_a, ingredient_b, ingredient_b, ingredient_a),
                ).fetchall()
            return [dict(r) for r in rows]
        return await asyncio.to_thread(_query)

    # ── Orders ──────────────────────────────────────────────────────────────

    async def get_orders_by_user(self, user_id: str) -> list[dict]:
        def _query() -> list[dict]:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
            return [_order_row_to_dict(r) for r in rows]
        return await asyncio.to_thread(_query)

    async def get_order(self, order_id: str) -> dict | None:
        def _query() -> dict | None:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM orders WHERE order_id = ?", (order_id,)
                ).fetchone()
            return _order_row_to_dict(row) if row else None
        return await asyncio.to_thread(_query)

    async def create_order(self, order: dict) -> None:
        def _write() -> None:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        order["order_id"], order["user_id"], order["product_id"],
                        order["quantity"], order["unit_price"], order["total_price"],
                        order["status"], order.get("logistics_no"),
                        order.get("logistics_co"), order["created_at"],
                        order.get("shipped_at"), order.get("estimated_delivery"),
                        json.dumps(order.get("address", {}), ensure_ascii=False),
                    ),
                )
                conn.commit()
        await asyncio.to_thread(_write)

    # ── Session Summaries (Episodic Memory) ─────────────────────────────────

    async def save_session_summary(
        self, user_id: str, summary: str, key_facts: dict
    ) -> None:
        now = datetime.utcnow().isoformat()

        def _write() -> None:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO session_summaries (user_id, summary, key_facts, created_at)
                    VALUES (?,?,?,?)""",
                    (user_id, summary, json.dumps(key_facts, ensure_ascii=False), now),
                )
                conn.commit()
        await asyncio.to_thread(_write)

    async def get_recent_summaries(self, user_id: str, limit: int = 3) -> list[dict]:
        def _query() -> list[dict]:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT summary, key_facts, created_at FROM session_summaries
                    WHERE user_id = ? ORDER BY created_at DESC LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            return [
                {
                    "summary": r["summary"],
                    "key_facts": json.loads(r["key_facts"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        return await asyncio.to_thread(_query)

    # ── Product Signals (Long-term Preference Memory) ────────────────────────

    async def save_product_signal(
        self, user_id: str, product_id: str, signal: str, source: str = "explicit"
    ) -> None:
        now = datetime.utcnow().isoformat()

        def _write() -> None:
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO product_signals
                    (user_id, product_id, signal, source, noted_at) VALUES (?,?,?,?,?)""",
                    (user_id, product_id, signal, source, now),
                )
                conn.commit()
        await asyncio.to_thread(_write)

    async def get_product_signals(self, user_id: str) -> list[dict]:
        def _query() -> list[dict]:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM product_signals WHERE user_id = ?", (user_id,)
                ).fetchall()
            return [dict(r) for r in rows]
        return await asyncio.to_thread(_query)


# ── Row → dict helpers ──────────────────────────────────────────────────────

def _product_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("suitable_skin_types", "skin_concerns", "ingredients_full", "key_ingredients"):
        d[key] = json.loads(d[key])
    d["alcohol_free"] = bool(d["alcohol_free"])
    d["fragrance_free"] = bool(d["fragrance_free"])
    d["in_stock"] = bool(d["in_stock"])
    d["is_own_brand"] = bool(d["is_own_brand"])
    return d


def _ingredient_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("aliases", "functions", "incompatible_with", "synergistic_with"):
        d[key] = json.loads(d[key])
    d["photosensitive"] = bool(d["photosensitive"])
    return d


def _order_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("address"):
        d["address"] = json.loads(d["address"])
    return d


# ── Schema DDL ───────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id                 TEXT PRIMARY KEY,
    skin_type               TEXT,
    skin_concerns           TEXT DEFAULT '[]',
    known_allergies         TEXT DEFAULT '[]',
    budget_min              INTEGER DEFAULT 0,
    budget_max              INTEGER DEFAULT 500,
    brand_prefs             TEXT DEFAULT '[]',
    age_range               TEXT,
    questionnaire_completed INTEGER DEFAULT 0,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id          TEXT PRIMARY KEY,
    name_cn             TEXT NOT NULL,
    name_en             TEXT,
    brand               TEXT NOT NULL,
    category            TEXT NOT NULL,
    suitable_skin_types TEXT DEFAULT '[]',
    skin_concerns       TEXT DEFAULT '[]',
    retail_price        REAL NOT NULL,
    ingredients_full    TEXT DEFAULT '[]',
    key_ingredients     TEXT DEFAULT '[]',
    alcohol_free        INTEGER DEFAULT 0,
    fragrance_free      INTEGER DEFAULT 0,
    rating_avg          REAL DEFAULT 0.0,
    rating_count        INTEGER DEFAULT 0,
    search_text         TEXT,
    description         TEXT,
    in_stock            INTEGER DEFAULT 1,
    is_own_brand        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ingredients (
    inci_name               TEXT PRIMARY KEY,
    name_cn                 TEXT NOT NULL,
    aliases                 TEXT DEFAULT '[]',
    functions               TEXT DEFAULT '[]',
    ewg_score               INTEGER,
    irritation_risk         TEXT DEFAULT 'low',
    mechanism               TEXT,
    effective_concentration TEXT,
    incompatible_with       TEXT DEFAULT '[]',
    synergistic_with        TEXT DEFAULT '[]',
    photosensitive          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS compatibility_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_a    TEXT NOT NULL,
    ingredient_b    TEXT NOT NULL,
    relationship    TEXT NOT NULL,
    severity        TEXT DEFAULT 'medium',
    reason          TEXT,
    recommendation  TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id            TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    product_id          TEXT NOT NULL,
    quantity            INTEGER DEFAULT 1,
    unit_price          REAL NOT NULL,
    total_price         REAL NOT NULL,
    status              TEXT DEFAULT 'pending',
    logistics_no        TEXT,
    logistics_co        TEXT,
    created_at          TEXT NOT NULL,
    shipped_at          TEXT,
    estimated_delivery  TEXT,
    address             TEXT
);

CREATE TABLE IF NOT EXISTS session_summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    summary     TEXT NOT NULL,
    key_facts   TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_signals (
    user_id     TEXT NOT NULL,
    product_id  TEXT NOT NULL,
    signal      TEXT NOT NULL,
    source      TEXT DEFAULT 'explicit',
    noted_at    TEXT NOT NULL,
    PRIMARY KEY (user_id, product_id, signal)
);

CREATE INDEX IF NOT EXISTS idx_products_category  ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_brand     ON products(brand);
CREATE INDEX IF NOT EXISTS idx_products_price     ON products(retail_price);
CREATE INDEX IF NOT EXISTS idx_orders_user        ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_summaries_user     ON session_summaries(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_user       ON product_signals(user_id);
"""
