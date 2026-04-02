"""4-layer session memory for the beauty agent.

Layer 1 — Short-term:   deque sliding window (last 20 turns = 40 messages)
Layer 2 — Mid-term:     in-session summary string (compressed after 15 turns)
Layer 3 — Task state:   dict tracking questionnaire progress and pending questions
"""
from __future__ import annotations

from collections import deque
from typing import Any

class SessionMemory:
    """Holds all in-session memory for a single user conversation."""

    def __init__(self, max_turns: int = 20) -> None:
        # Layer 1: sliding window — deque auto-evicts oldest messages when full
        self._messages: deque[dict] = deque(maxlen=max_turns * 2)

        # Layer 2: mid-term summary produced by Claude after N turns
        self._mid_term_summary: str = ""

        # Layer 3: task state for questionnaire flow and pending questions
        self._task_state: dict[str, Any] = {}

    # ── Layer 1: message window ─────────────────────────────────────────────

    def append(self, message: dict) -> None:
        self._messages.append(message)

    def to_list(self) -> list[dict]:
        return list(self._messages)

    def turn_count(self) -> int:
        """Number of complete user+assistant turns in the window."""
        return len(self._messages) // 2

    def should_compress(self, threshold: int = 15) -> bool:
        """True when it's time to produce a mid-term summary and compress the window."""
        return self.turn_count() >= threshold and not self._mid_term_summary

    def compress(self, summary: str) -> None:
        """Replace oldest half of the window with a summary sentinel, set mid-term summary."""
        self._mid_term_summary = summary
        # Keep only the most recent 10 turns after compression
        recent = list(self._messages)[-20:]
        self._messages.clear()
        self._messages.extend(recent)

    # ── Layer 2: mid-term summary ───────────────────────────────────────────

    def get_mid_term_summary(self) -> str:
        return self._mid_term_summary

    # ── Layer 3: task state ─────────────────────────────────────────────────

    def set_task(self, key: str, value: Any) -> None:
        self._task_state[key] = value

    def get_task(self, key: str, default: Any = None) -> Any:
        return self._task_state.get(key, default)

    def clear_task(self, key: str) -> None:
        self._task_state.pop(key, None)

    def has_task(self, key: str) -> bool:
        return key in self._task_state
