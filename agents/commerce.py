"""
电商 Agent - 自有品牌购买与订单服务
处理产品浏览、下单、订单查询、物流追踪
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from config import settings
from storage.database import UserProfile
from tools.order_service import TOOL_SCHEMA as ORDER_SCHEMA, order_service

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是美妆智能顾问的【电商服务专家】。

## 你的职责
- 展示和推荐自有品牌产品
- 处理用户的购买需求，创建订单
- 查询订单状态和历史订单
- 提供物流追踪信息

## 服务范围
1. **产品浏览**：展示自有品牌产品列表，介绍产品特点
2. **下单服务**：确认产品、数量、收货地址，生成订单
3. **订单查询**：查看订单状态（待支付/已支付/已发货/已送达/已取消）
4. **物流追踪**：提供快递公司、运单号、物流进度

## 工具使用
- 使用 order_service 工具，根据需求选择 action：
  - "browse"：浏览自有品牌产品
  - "place_order"：创建新订单
  - "query_order"：查询订单状态
  - "track_logistics"：追踪物流信息

## 服务原则
- 下单前确认关键信息（产品、数量、地址）
- 清晰告知订单状态和预计送达时间
- 对于异常订单（如已取消）给出合理解释
- 主动提供售后支持建议

## 回复风格
- 热情专业，像电商客服一样
- 信息准确，格式清晰
- 对订单号、物流单号等关键信息突出显示
- 及时响应用户的购买和查询需求

{user_context}
"""


class CommerceAgent:
    """电商服务 Agent，使用 ReAct 模式"""

    TOOLS = [ORDER_SCHEMA]

    def __init__(self, client: AsyncOpenAI, db):
        self.client = client
        self.db = db

    def _inject_profile(self, profile: UserProfile) -> str:
        """将用户档案注入 System Prompt"""
        context = profile.to_prompt_context() if profile else "用户档案：暂无"
        return SYSTEM_PROMPT.replace("{user_context}", f"\n## 用户档案\n{context}")

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """执行工具调用"""
        if tool_name == "order_service":
            return await order_service(
                self.db,
                action=tool_input.get("action", "browse"),
                user_id=tool_input.get("user_id"),
                product_id=tool_input.get("product_id"),
                quantity=tool_input.get("quantity", 1),
                order_id=tool_input.get("order_id"),
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

    async def run(self, task: str, profile: UserProfile) -> str:
        """运行 ReAct 循环"""
        messages = [
            {"role": "system", "content": self._inject_profile(profile)},
            {"role": "user", "content": task},
        ]

        for iteration in range(settings.max_tool_iterations):
            logger.info(f"[CommerceAgent] Iteration {iteration + 1}")

            response = await self.client.chat.completions.create(
                model=settings.model,
                max_tokens=2048,
                messages=messages,
                tools=self.TOOLS,
            )

            msg = response.choices[0].message
            messages.append(msg)

            if response.choices[0].finish_reason == "stop":
                return msg.content or "服务完成。"

            if not msg.tool_calls:
                return msg.content or "服务完成。"

            for tc in msg.tool_calls:
                logger.info(f"[CommerceAgent] Tool call: {tc.function.name}")
                tool_input = json.loads(tc.function.arguments)
                result = await self._execute_tool(tc.function.name, tool_input)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        logger.warning("[CommerceAgent] Max iterations reached")
        return "抱歉，服务处理超时，请重试或简化您的需求。"

