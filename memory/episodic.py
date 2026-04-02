"""Episodic memory — summarise a session and persist it to SQLite.

Called by the orchestrator when a conversation ends (user types "退出" / "bye").
The summary is injected into future sessions via long_term.py.
"""
from __future__ import annotations

import json
import logging

import anthropic

from memory.session_memory import SessionMemory
from storage.database import Database

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = """你是对话分析助手。分析这段美妆顾问对话，提取以下信息，**只输出JSON**，不要其他文字：
{
  "summary": "一句话总结本次对话（20字内）",
  "new_skin_concerns": ["用户提到的新皮肤问题（若无则空数组）"],
  "products_discussed": ["本次讨论过的产品名称"],
  "preferences_revealed": ["用户透露的偏好或厌恶，如'不喜欢酒精配方'"],
  "unresolved_questions": ["用户还未得到满意答案的问题（若无则空数组）"]
}"""


async def summarize_and_save(
    client: anthropic.AsyncAnthropic,
    model: str,
    session: SessionMemory,
    user_id: str,
    db: Database,
) -> None:
    """Summarise current session messages and save to session_summaries table."""
    messages = session.to_list()
    if not messages:
        return

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=512,
            system=_SUMMARY_SYSTEM,
            messages=messages,
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        facts: dict = json.loads(raw)

        await db.save_session_summary(
            user_id=user_id,
            summary=facts.get("summary", ""),
            key_facts={
                "new_skin_concerns": facts.get("new_skin_concerns", []),
                "products_discussed": facts.get("products_discussed", []),
                "preferences_revealed": facts.get("preferences_revealed", []),
                "unresolved_questions": facts.get("unresolved_questions", []),
            },
        )
        logger.info("Session summary saved for user %s: %s", user_id, facts["summary"])

    except Exception:
        logger.exception("Failed to summarise session for user %s", user_id)
