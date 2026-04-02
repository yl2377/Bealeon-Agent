"""BM25 keyword search over product catalog using jieba Chinese tokenization.

rank_bm25 (pure Python, no binary deps) + jieba for Chinese word segmentation.
Index is built once at startup from SQLite product data.
"""
from __future__ import annotations

import logging

import jieba
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# Initialise jieba silently at import time (avoids first-query delay)
jieba.initialize()
jieba.setLogLevel(logging.WARNING)


class BM25Search:
    """BM25Okapi index over product search_text fields."""

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._bm25: BM25Okapi | None = None

    # ── Index management ────────────────────────────────────────────────────

    def build_index(self, products: list[dict]) -> None:
        """Tokenise product search_text fields and build the BM25 index.

        Call once at startup after loading products from the database.
        """
        self._ids = [p["product_id"] for p in products]
        tokenised = [
            list(jieba.cut(p.get("search_text") or p.get("name_cn", "")))
            for p in products
        ]
        self._bm25 = BM25Okapi(tokenised)
        logger.info("BM25 index built: %d products", len(self._ids))

    # ── Search ──────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Return top-k products by BM25 score.

        Returns: [{"id": product_id, "rank": 1-based, "score": float}]
        """
        if self._bm25 is None:
            logger.warning("BM25 index not built — returning empty results")
            return []

        tokens = list(jieba.cut(query))
        scores = self._bm25.get_scores(tokens)

        # Pair (product_id, score), sort descending, take top_k
        ranked = sorted(
            zip(self._ids, scores), key=lambda x: x[1], reverse=True
        )[:top_k]

        return [
            {"id": pid, "rank": rank + 1, "score": float(score)}
            for rank, (pid, score) in enumerate(ranked)
            if score > 0  # omit products with zero BM25 relevance
        ]
