"""Long-term memory — reads from SQLite to build the memory context injected
into every agent's system prompt at the start of a new session.

Layer 4: cross-session persistent memory backed by SQLite.
  - User skin profile (structured)
  - Product preference signals (liked / disliked / purchased)
  - Recent session summaries (episodic)
"""
from __future__ import annotations

import logging

from storage.database import Database, UserProfile

logger = logging.getLogger(__name__)

# Signals worth surfacing to agents
_AVOID_SIGNALS = {"disliked"}
_PREFER_SIGNALS = {"liked", "purchased"}


async def build_memory_context(
    user_id: str,
    profile: UserProfile,
    db: Database,
    summary_limit: int = 3,
) -> str:
    """Return a formatted memory block to prepend to agent system prompts."""
    sections: list[str] = [profile.to_prompt_context()]

    # ── Product preference signals ─────────────────────────────────────────
    signals = await db.get_product_signals(user_id)
    liked_ids    = [s["product_id"] for s in signals if s["signal"] in _PREFER_SIGNALS]
    disliked_ids = [s["product_id"] for s in signals if s["signal"] in _AVOID_SIGNALS]

    if liked_ids or disliked_ids:
        liked_names    = await _ids_to_names(liked_ids, db)
        disliked_names = await _ids_to_names(disliked_ids, db)
        pref_block = "【产品偏好记忆】"
        if liked_names:
            pref_block += f"\n- 曾表示喜欢：{', '.join(liked_names)}"
        if disliked_names:
            pref_block += f"\n- 曾表示不喜欢/不适合：{', '.join(disliked_names)}"
        sections.append(pref_block)

    # ── Recent session summaries ───────────────────────────────────────────
    summaries = await db.get_recent_summaries(user_id, limit=summary_limit)
    if summaries:
        ep_lines = ["【历史会话记忆】"]
        for s in summaries:
            date = s["created_at"][:10]
            ep_lines.append(f"- {date}：{s['summary']}")
            prefs = s["key_facts"].get("preferences_revealed", [])
            if prefs:
                ep_lines.append(f"  偏好线索：{'；'.join(prefs)}")
        sections.append("\n".join(ep_lines))

    return "\n\n".join(sections)


async def _ids_to_names(ids: list[str], db: Database) -> list[str]:
    if not ids:
        return []
    products = await db.get_products_by_ids(ids)
    return [p["name_cn"] for p in products]


async def save_signal(
    user_id: str, product_id: str, signal: str, db: Database
) -> None:
    """Convenience wrapper — called from orchestrator when user expresses preference."""
    await db.save_product_signal(user_id, product_id, signal)
    logger.debug("Signal saved: user=%s product=%s signal=%s", user_id, product_id, signal)
