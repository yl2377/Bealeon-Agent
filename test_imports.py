"""
测试脚本 - 验证所有模块可以正常导入和初始化
不需要真实的 API Keys
"""

import os
import sys

# 设置 UTF-8 输出（Windows 兼容）
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

# 设置临时环境变量以通过 Pydantic 验证
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-import-testing"
os.environ["OPENAI_API_KEY"] = "sk-test-key-for-import-testing"

print("=" * 60)
print("美妆智能顾问 - 模块导入测试")
print("=" * 60)

try:
    print("\n[1/7] 测试配置模块...")
    from config import settings
    print(f"  [OK] 配置加载成功")
    print(f"    - Model: {settings.model}")
    print(f"    - Embedding: {settings.embedding_model}")
    print(f"    - Max iterations: {settings.max_tool_iterations}")

    print("\n[2/7] 测试数据模块...")
    from data.products import PRODUCTS
    from data.ingredients import INGREDIENTS, COMPATIBILITY_RULES
    from data.orders import ORDERS
    print(f"  [OK] Mock 数据加载成功")
    print(f"    - Products: {len(PRODUCTS)} 个")
    print(f"    - Ingredients: {len(INGREDIENTS)} 个")
    print(f"    - Orders: {len(ORDERS)} 个")

    print("\n[3/7] 测试存储模块...")
    from storage.database import Database
    print(f"  [OK] Database 类导入成功")

    print("\n[4/7] 测试记忆模块...")
    from memory.session_memory import SessionMemory
    print(f"  [OK] SessionMemory 类导入成功")

    print("\n[5/7] 测试检索模块...")
    from retrieval.vector_store import VectorStore
    from retrieval.bm25_search import BM25Search
    from retrieval.hybrid_search import HybridSearch
    print(f"  [OK] 检索模块导入成功")

    print("\n[6/7] 测试工具模块...")
    from tools.product_search import product_search
    from tools.product_analyzer import product_analyzer
    from tools.routine_planner import routine_planner
    from tools.order_service import order_service
    print(f"  [OK] 所有工具函数导入成功")

    print("\n[7/7] 测试 Agent 模块...")
    from agents import (
        RecommendationAgent,
        AnalystAgent,
        CollocationAgent,
        CommerceAgent,
        Orchestrator,
    )
    print(f"  [OK] 所有 Agent 类导入成功")

    print("\n" + "=" * 60)
    print("[SUCCESS] 所有模块导入测试通过！")
    print("=" * 60)
    print("\n下一步：")
    print("1. 编辑 .env 文件，填入真实的 API Keys")
    print("2. 运行 'python main.py' 启动 Gradio 界面")
    print("3. 浏览器访问 http://localhost:7860")
    print()

except Exception as e:
    print(f"\n[ERROR] 导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

