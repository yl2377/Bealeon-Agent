"""Central configuration — all settings loaded from environment / .env file."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8")

    # ── LLM ────────────────────────────────────────────────────────────────
    api_key: str = Field(..., description="API key")
    base_url: str = Field(
        default="https://api.scnet.cn/api/llm/v1",
        description="OpenAI-compatible API base URL",
    )
    cookie: str = Field(
        default="SKIP_SESSION_UPDATE=1775035134158",
        description="Cookie header required by the API gateway",
    )
    model: str = "MiniMax-M2.5"
    # 本地 embedding 模型（sentence-transformers，无需 API key）
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # ── Storage paths ───────────────────────────────────────────────────────
    db_path: Path = Path("data/beauty.db")
    chroma_path: Path = Path("data/chroma")

    # ── Memory tuning ───────────────────────────────────────────────────────
    short_term_max_turns: int = 20       # deque maxlen = max_turns * 2
    summary_trigger_turns: int = 15      # compress after N turns
    long_term_summary_limit: int = 3     # inject last N session summaries

    # ── Retrieval ───────────────────────────────────────────────────────────
    vector_top_k: int = 10
    bm25_top_k: int = 10
    rrf_k: int = 60                      # RRF constant (empirically validated)
    final_top_k: int = 5                 # results returned to agent

    # ── Agentic loop ────────────────────────────────────────────────────────
    max_tool_iterations: int = 10        # safety limit per sub-agent call


settings = Settings()  # singleton — import this everywhere
