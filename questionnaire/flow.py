"""First-use questionnaire — skin profile cold-start system.

State machine: INIT → Q1_SKIN_TYPE → Q2_CONCERNS → Q3_BUDGET → COMPLETE

Design principles:
  - Every question offers quick-select options (A/B/C) to lower friction
  - Every question has a "跳过" (skip) option
  - The user's original question is cached in SessionMemory (Layer 3)
    and answered automatically after the questionnaire completes
"""
from __future__ import annotations

import logging
from enum import Enum

from memory.session_memory import SessionMemory
from storage.database import Database, UserProfile

logger = logging.getLogger(__name__)

# ── State machine ────────────────────────────────────────────────────────────

class QState(str, Enum):
    INIT       = "init"
    Q1_SKIN    = "q1_skin"
    Q2_CONCERN = "q2_concern"
    Q3_BUDGET  = "q3_budget"
    COMPLETE   = "complete"


# ── Questionnaire prompts ────────────────────────────────────────────────────

def _Q1_TEXT() -> str:
    return (
        "**Q1 / 3 — 你的肤质是？**\n"
        "A. 干皮（容易干燥、脱皮）\n"
        "B. 油皮（T区或全脸容易出油）\n"
        "C. 混合皮（T区油，两颊干）\n"
        "D. 敏感肌（容易泛红、刺痛）\n"
        "E. 中性皮（水油均衡）\n"
        "（输入字母或描述均可）"
    )


_WELCOME = (
    "你好！我是你的专属美妆顾问 ✨\n\n"
    "为了给你最精准的推荐，我需要先了解你的皮肤情况，只需3个小问题（约1分钟）。\n"
    "你也可以在任意一步输入 **跳过** 直接进入对话。\n\n"
    + _Q1_TEXT()
)

def _Q2_TEXT() -> str:
    return (
        "**Q2 / 3 — 你目前最想改善的皮肤问题？**（可多选，如 A C）\n"
        "A. 干燥缺水\n"
        "B. 毛孔粗大 / 控油\n"
        "C. 痘痘 / 痤疮\n"
        "D. 暗沉 / 提亮\n"
        "E. 细纹 / 抗老\n"
        "F. 敏感泛红 / 屏障受损\n"
        "（输入 跳过 则跳过此题）"
    )

def _Q3_TEXT() -> str:
    return (
        "**Q3 / 3 — 单品预算范围？**\n"
        "A. 100元以内\n"
        "B. 100–300元\n"
        "C. 300–600元\n"
        "D. 600元以上 / 不限\n"
        "（输入 跳过 则跳过此题）"
    )


# ── Parsing helpers ──────────────────────────────────────────────────────────

_SKIN_TYPE_MAP: dict[str, str] = {
    "a": "dry", "干": "dry", "干皮": "dry", "干燥": "dry",
    "b": "oily", "油": "oily", "油皮": "oily", "出油": "oily",
    "c": "combination", "混合": "combination", "混合皮": "combination", "混": "combination",
    "d": "sensitive", "敏感": "sensitive", "敏感肌": "sensitive", "泛红": "sensitive",
    "e": "normal", "中性": "normal", "中性皮": "normal", "均衡": "normal",
}

_CONCERN_MAP: dict[str, str] = {
    "a": "dryness", "干燥": "dryness", "缺水": "dryness",
    "b": "pores", "毛孔": "pores", "控油": "oiliness", "出油": "oiliness",
    "c": "acne", "痘痘": "acne", "痤疮": "acne", "闭口": "acne",
    "d": "brightening", "暗沉": "brightening", "提亮": "brightening", "美白": "brightening",
    "e": "anti_aging", "细纹": "anti_aging", "抗老": "anti_aging", "皱纹": "anti_aging",
    "f": "sensitivity", "敏感": "sensitivity", "泛红": "sensitivity", "屏障": "barrier_repair",
}

_BUDGET_MAP: dict[str, tuple[int, int]] = {
    "a": (0, 100),
    "b": (100, 300),
    "c": (300, 600),
    "d": (600, 9999),
}


def _parse_skin(text: str) -> str | None:
    t = text.strip().lower()
    for key, val in _SKIN_TYPE_MAP.items():
        if key in t:
            return val
    return None


def _parse_concerns(text: str) -> list[str]:
    concerns: list[str] = []
    t = text.strip().lower()
    for key, val in _CONCERN_MAP.items():
        if key in t and val not in concerns:
            concerns.append(val)
    return concerns


def _parse_budget(text: str) -> tuple[int, int] | None:
    t = text.strip().lower()
    for key, val in _BUDGET_MAP.items():
        if key in t:
            return val
    return None


def _is_skip(text: str) -> bool:
    return any(w in text.lower() for w in ["跳过", "skip", "不填", "下一题"])


# ── Main flow class ──────────────────────────────────────────────────────────

class QuestionnaireFlow:
    """Drives the 3-question skin profile onboarding flow."""

    async def handle(
        self,
        user_message: str,
        user_id: str,
        session: SessionMemory,
        db: Database,
    ) -> str:
        """Process user input and return the next prompt or completion message.

        Returns:
            str — the response to show the user (next question or completion msg)
        """
        state = QState(session.get_task("q_state", QState.INIT.value))

        if state == QState.INIT:
            session.set_task("q_state", QState.Q1_SKIN.value)
            return (
                "👋 你好！我是专属美妆顾问，先来了解一下你的皮肤吧～\n\n"
                + _Q1_TEXT()
            )

        if state == QState.Q1_SKIN:
            if not _is_skip(user_message):
                skin = _parse_skin(user_message)
                if skin:
                    session.set_task("skin_type", skin)
                else:
                    return "没有识别到肤质，请输入 A/B/C/D/E 或描述（如「油皮」），或输入 跳过：\n\n" + _Q1_TEXT()
            session.set_task("q_state", QState.Q2_CONCERN.value)
            return _Q2_TEXT()

        if state == QState.Q2_CONCERN:
            if not _is_skip(user_message):
                concerns = _parse_concerns(user_message)
                session.set_task("skin_concerns", concerns)
            session.set_task("q_state", QState.Q3_BUDGET.value)
            return _Q3_TEXT()

        if state == QState.Q3_BUDGET:
            bmin, bmax = 0, 9999
            if not _is_skip(user_message):
                budget = _parse_budget(user_message)
                if budget:
                    bmin, bmax = budget
            session.set_task("budget_min", bmin)
            session.set_task("budget_max", bmax)
            session.set_task("q_state", QState.COMPLETE.value)

            # Persist profile to SQLite
            profile = UserProfile(
                user_id=user_id,
                skin_type=session.get_task("skin_type", "normal"),
                skin_concerns=session.get_task("skin_concerns", []),
                known_allergies=[],
                budget_min=bmin,
                budget_max=bmax,
                brand_prefs=[],
                age_range="",
                questionnaire_completed=True,
            )
            await db.save_profile(profile)
            logger.info("Profile saved for user %s: skin=%s", user_id, profile.skin_type)

            pending = session.get_task("pending_question", "")
            if pending:
                session.clear_task("pending_question")
                return (
                    f"✅ 档案建立成功！\n\n"
                    f"好的，回到你刚才的问题：**{pending}**\n\n正在为你查询..."
                )
            return (
                "✅ 皮肤档案建立完成！现在可以开始咨询啦～\n"
                "试试问我：推荐一款适合我的精华？或者：烟酰胺和视黄醇能一起用吗？"
            )

        # Should not reach here
        return "档案已完成，请直接提问～"
