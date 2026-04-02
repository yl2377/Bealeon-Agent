"""
美妆智能顾问 - 控制台入口
"""

import asyncio
import logging
from pathlib import Path

from openai import AsyncOpenAI

from config import settings
from agents.orchestrator import Orchestrator
from memory.session_memory import SessionMemory
from questionnaire.flow import QuestionnaireFlow
from retrieval.bm25_search import BM25Search
from retrieval.vector_store import VectorStore
from retrieval.hybrid_search import HybridSearch
from storage.database import Database

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    # ── 初始化 ────────────────────────────────────────────────────────────────
    print("正在初始化，请稍候...")

    db = Database(settings.db_path)
    await db.init()

    products = await db.get_all_products()

    vector_store = VectorStore(settings.chroma_path, settings.embedding_model)
    await vector_store.build_index(products)

    bm25 = BM25Search()
    bm25.build_index(products)

    hybrid_search = HybridSearch(
        vector_store,
        bm25,
        rrf_k=settings.rrf_k,
        vector_top_k=settings.vector_top_k,
        bm25_top_k=settings.bm25_top_k,
    )

    client = AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        default_headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Cookie": settings.cookie,
        },
    )

    orchestrator = Orchestrator(client, db, hybrid_search)
    session = SessionMemory()
    questionnaire = QuestionnaireFlow()
    user_id = "console_user"

    print("初始化完成！输入 exit 或 quit 退出。\n")
    print("=" * 50)

    # ── 对话循环 ──────────────────────────────────────────────────────────────
    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "退出"):
            print("再见！")
            break

        print("\n顾问：", end="", flush=True)

        # 问卷流程
        profile = await db.get_profile(user_id)
        if not profile or not profile.questionnaire_completed:
            response = await questionnaire.handle(user_input, user_id, session, db)
            session.append({"role": "user", "content": user_input})
            session.append({"role": "assistant", "content": response})
            print(response)
            continue

        # 正常对话（流式输出）
        session.append({"role": "user", "content": user_input})

        if session.should_compress():
            history_text = "\n".join(
                f"{m['role']}: {m['content']}" for m in session.to_list()
            )
            summary_resp = await client.chat.completions.create(
                model=settings.model,
                max_tokens=512,
                messages=[
                    {"role": "system", "content": "请用3-5句话总结以下对话的核心信息，包括用户的肤质、关注的产品和主要需求。"},
                    {"role": "user", "content": history_text},
                ],
            )
            summary = summary_resp.choices[0].message.content or ""
            session.compress(summary)

        full_response = ""
        async for chunk in orchestrator.stream(user_input, user_id, session):
            print(chunk, end="", flush=True)
            full_response += chunk

        print()  # 换行
        session.append({"role": "assistant", "content": full_response})


if __name__ == "__main__":
    asyncio.run(main())
