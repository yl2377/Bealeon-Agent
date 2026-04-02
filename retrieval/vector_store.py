"""ChromaDB vector store — semantic product search using local sentence-transformers.

Uses paraphrase-multilingual-MiniLM-L12-v2 for embedding:
- 支持中文，无需 API Key
- 模型体积约 120MB，首次启动自动下载，后续从本地缓存加载
- CPU 推理，配置较低的机器也能运行
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import chromadb
from chromadb import PersistentClient
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "products"
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class VectorStore:
    """ChromaDB-backed semantic search over product descriptions."""

    def __init__(self, chroma_path: Path, embedding_model: str = _MODEL_NAME) -> None:
        self._client = PersistentClient(path=str(chroma_path))
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Loading local embedding model: %s", embedding_model)
        self._model = SentenceTransformer(embedding_model)
        logger.info("Embedding model loaded.")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """同步 encode，返回 list[list[float]]"""
        vecs = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return vecs.tolist()

    # ── Index management ────────────────────────────────────────────────────

    async def build_index(self, products: list[dict]) -> None:
        """Embed all product descriptions and upsert into ChromaDB.

        Idempotent — skips products already in the index.
        """
        existing_ids: set[str] = set()
        try:
            existing = self._collection.get()
            existing_ids = set(existing["ids"])
        except Exception:
            pass

        new_products = [p for p in products if p["product_id"] not in existing_ids]
        if not new_products:
            logger.info("Vector index already up to date (%d products)", len(existing_ids))
            return

        logger.info("Embedding %d new products...", len(new_products))

        texts = [
            f"{p['name_cn']} {p['brand']} {p['description']}"
            for p in new_products
        ]

        # sentence-transformers encode 是 CPU 同步操作，放进线程池避免阻塞事件循环
        embeddings = await asyncio.to_thread(self._embed, texts)

        # Upsert into ChromaDB (sync call — wrap in thread)
        await asyncio.to_thread(
            self._collection.upsert,
            ids=[p["product_id"] for p in new_products],
            embeddings=embeddings,
            documents=texts,
            metadatas=[{"name_cn": p["name_cn"], "category": p["category"]} for p in new_products],
        )
        logger.info("Vector index built: %d products indexed", len(products))

    # ── Search ──────────────────────────────────────────────────────────────

    async def search(self, query: str, n_results: int = 10) -> list[dict]:
        """Return top-n products by semantic similarity.

        Returns: [{"id": product_id, "rank": 1-based, "score": cosine_sim}]
        """
        query_embedding = await asyncio.to_thread(self._embed, [query])

        # Query ChromaDB (sync — wrap in thread)
        results = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=query_embedding,
            n_results=min(n_results, self._collection.count()),
        )

        ids = results["ids"][0]
        distances = results["distances"][0]  # cosine distance; lower = more similar

        return [
            {
                "id": pid,
                "rank": rank + 1,
                "score": 1.0 - dist,  # convert distance → similarity
            }
            for rank, (pid, dist) in enumerate(zip(ids, distances))
        ]

    def count(self) -> int:
        return self._collection.count()
