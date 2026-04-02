"""
推荐 Agent - 个性化产品推荐
基于用户肤质、问题、预算等档案，结合混合检索推荐合适产品
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from config import settings
from storage.database import UserProfile
from tools.product_search import TOOL_SCHEMA as PRODUCT_SEARCH_SCHEMA, product_search

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是美妆智能顾问的【个性化推荐专家】。

## 你的职责
- 根据用户的肤质、肌肤问题、预算等个人档案，推荐最合适的护肤品
- 使用 product_search 工具进行混合检索（语义+关键词）
- 综合考虑产品的适用肤质、功效、成分安全性、价格、评分等因素
- 给出清晰的推荐理由，帮助用户做出明智选择

## 推荐原则
1. **精准匹配**：优先推荐适合用户肤质的产品
2. **问题导向**：针对用户的具体肌肤问题（如痘痘、暗沉、细纹）
3. **成分安全**：避免用户已知过敏成分，关注敏感肌的温和性
4. **预算友好**：在用户预算范围内推荐性价比高的产品
5. **多样选择**：提供2-3个不同价位或品牌的选项供用户对比

## 工具使用
- 使用 product_search 工具时，合理设置过滤条件（skin_type, category, price_range, exclude_ingredients）
- 如果首次搜索结果不理想，可以调整查询词或放宽过滤条件再次搜索
- 搜索结果会包含产品的详细信息，仔细分析后再给出推荐

## 回复风格
- 专业但亲切，像资深美妆顾问一样
- 用简洁的语言解释推荐理由
- 突出产品的核心优势和适用场景
- 如果有多个选项，清晰对比它们的差异

{user_context}
"""


class RecommendationAgent:
    """个性化推荐 Agent，使用 ReAct 模式"""

    TOOLS = [PRODUCT_SEARCH_SCHEMA]

    def __init__(self, client: AsyncOpenAI, db, hybrid_search):
        self.client = client
        self.db = db
        self.hybrid_search = hybrid_search

    def _inject_profile(self, profile: UserProfile) -> str:
        """将用户档案注入 System Prompt"""
        context = profile.to_prompt_context() if profile else "用户档案：暂无"
        return SYSTEM_PROMPT.replace("{user_context}", f"\n## 用户档案\n{context}")

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """执行工具调用"""
        if tool_name == "product_search":
            return await product_search(
                self.hybrid_search,
                self.db,
                query=tool_input.get("query", ""),
                skin_type=tool_input.get("skin_type"),
                category=tool_input.get("category"),
                price_min=tool_input.get("price_min"),
                price_max=tool_input.get("price_max"),
                exclude_ingredients=tool_input.get("exclude_ingredients"),
                limit=tool_input.get("limit", 5),
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

    async def run(self, task: str, profile: UserProfile) -> str:
        """运行 ReAct 循环"""
        messages = [
            {"role": "system", "content": self._inject_profile(profile)},
            {"role": "user", "content": task},
        ]

        for iteration in range(settings.max_tool_iterations):
            logger.info(f"[RecommendationAgent] Iteration {iteration + 1}")

            response = await self.client.chat.completions.create(
                model=settings.model,
                max_tokens=2048,
                messages=messages,
                tools=self.TOOLS,
            )

            msg = response.choices[0].message
            messages.append(msg)

            # 如果模型结束对话，提取文本返回
            if response.choices[0].finish_reason == "stop":
                return msg.content or "推荐完成。"

            # 处理工具调用
            if not msg.tool_calls:
                return msg.content or "推荐完成。"

            for tc in msg.tool_calls:
                logger.info(f"[RecommendationAgent] Tool call: {tc.function.name}")
                tool_input = json.loads(tc.function.arguments)
                result = await self._execute_tool(tc.function.name, tool_input)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        logger.warning("[RecommendationAgent] Max iterations reached")
        return "抱歉，推荐处理超时，请重试或简化您的需求。"

