"""
分析 Agent - 产品详情与成分安全分析
提供产品详细信息、成分解析、安全性评估
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from config import settings
from storage.database import UserProfile
from tools.product_analyzer import TOOL_SCHEMA as ANALYZER_SCHEMA, product_analyzer

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是美妆智能顾问的【产品分析专家】。

## 你的职责
- 提供产品的详细信息（品牌、价格、成分、评分等）
- 深度解析产品成分的功效、安全性、刺激风险
- 基于 EWG 评分和科学文献评估成分安全性
- 识别用户可能过敏的成分并给出警示

## 分析维度
1. **产品概览**：品牌、价格、适用肤质、核心功效
2. **成分分析**：关键成分的作用机制、有效浓度、科学依据
3. **安全评估**：EWG 评分、刺激风险、光敏性、孕妇适用性
4. **个性化建议**：结合用户肤质和过敏史给出使用建议

## 工具使用
- 使用 product_analyzer 工具获取产品详情和成分分析
- 工具会自动交叉比对用户的已知过敏成分
- 如果产品名称模糊，工具会进行模糊匹配

## 回复风格
- 专业严谨，引用科学数据
- 对安全风险保持警觉，明确标注警示信息
- 用通俗语言解释专业术语
- 客观中立，不夸大也不贬低产品

{user_context}
"""


class AnalystAgent:
    """产品分析 Agent，使用 ReAct 模式"""

    TOOLS = [ANALYZER_SCHEMA]

    def __init__(self, client: AsyncOpenAI, db):
        self.client = client
        self.db = db

    def _inject_profile(self, profile: UserProfile) -> str:
        """将用户档案注入 System Prompt"""
        context = profile.to_prompt_context() if profile else "用户档案：暂无"
        return SYSTEM_PROMPT.replace("{user_context}", f"\n## 用户档案\n{context}")

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """执行工具调用"""
        if tool_name == "product_analyzer":
            return await product_analyzer(
                self.db,
                product_query=tool_input.get("product_query", ""),
                user_allergies=tool_input.get("user_allergies", []),
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

    async def run(self, task: str, profile: UserProfile) -> str:
        """运行 ReAct 循环"""
        messages = [
            {"role": "system", "content": self._inject_profile(profile)},
            {"role": "user", "content": task},
        ]

        for iteration in range(settings.max_tool_iterations):
            logger.info(f"[AnalystAgent] Iteration {iteration + 1}")
            print(messages)
            response = await self.client.chat.completions.create(
                model=settings.model,
                max_tokens=2048,
                messages=messages,
                tools=self.TOOLS,
            )

            msg = response.choices[0].message
            messages.append(msg)

            if response.choices[0].finish_reason == "stop":
                return msg.content or "分析完成。"

            if not msg.tool_calls:
                return msg.content or "分析完成。"

            for tc in msg.tool_calls:
                logger.info(f"[AnalystAgent] Tool call: {tc.function.name}")
                tool_input = json.loads(tc.function.arguments)
                result = await self._execute_tool(tc.function.name, tool_input)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        logger.warning("[AnalystAgent] Max iterations reached")
        return "抱歉，分析处理超时，请重试或简化您的需求。"

