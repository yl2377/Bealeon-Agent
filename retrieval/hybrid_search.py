"""Hybrid retrieval — fuses vector search and BM25 via Reciprocal Rank Fusion (RRF).

RRF formula:  score(d) = Σ  1 / (k + rank_i(d))
              where k=60 is the standard empirically validated constant.

Higher RRF score = more relevant. Documents appearing in both ranked lists
score higher than those in only one.
"""
from __future__ import annotations

import logging

from retrieval.bm25_search import BM25Search
from retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)


class HybridSearch:
    """Combines VectorStore and BM25Search results via RRF."""

    def __init__(
        self,
        vector_store: VectorStore,
        bm25: BM25Search,
        rrf_k: int = 60,
        vector_top_k: int = 10,
        bm25_top_k: int = 10,
    ) -> None:
        self._vector = vector_store
        self._bm25 = bm25
        self._rrf_k = rrf_k
        self._vector_top_k = vector_top_k
        self._bm25_top_k = bm25_top_k

    async def search(self, query: str, final_top_k: int = 5) -> list[str]:
        """Return top-N product IDs ranked by RRF-fused relevance score.

        Args:
            query:       Natural-language search query (Chinese or English)
            final_top_k: How many product IDs to return

        Returns:
            Ordered list of product_id strings (most relevant first)
        """
        # Run both searches (vector is async, BM25 is sync)
        vector_results = await self._vector.search(query, n_results=self._vector_top_k)
        bm25_results = self._bm25.search(query, top_k=self._bm25_top_k)

        fused = _rrf_fuse(vector_results, bm25_results, k=self._rrf_k)

        logger.debug(
            "Hybrid search '%s': vector=%d, bm25=%d, fused=%d",
            query[:30], len(vector_results), len(bm25_results), len(fused),
        )

        return [pid for pid, _ in fused[:final_top_k]]


def _rrf_fuse(
    vector_results: list[dict],
    bm25_results: list[dict],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Pure RRF fusion — no weights, both sources treated equally.

    Args:
        vector_results: [{"id": str, "rank": int, ...}]
        bm25_results:   [{"id": str, "rank": int, ...}]
        k:              RRF dampening constant (60 is the standard)

    Returns:
        Sorted list of (product_id, rrf_score) tuples, descending.
    """
    scores: dict[str, float] = {}
    for result_list in (vector_results, bm25_results):
        for item in result_list:
            pid = item["id"]
            rank = item["rank"]
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
