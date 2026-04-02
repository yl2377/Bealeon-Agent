"""
搭配 Agent - 护肤品配伍与流程规划
检测成分配伍冲突，生成科学的护肤步骤
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from config import settings
from storage.database import UserProfile
from tools.routine_planner import TOOL_SCHEMA as PLANNER_SCHEMA, routine_planner

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是美妆智能顾问的【搭配规划专家】。

## 你的职责
- 检测多个产品之间的成分配伍冲突（如视黄醇+果酸、烟酰胺+VC等）
- 规划科学的早晚护肤流程（清洁→水→精华→乳液→防晒）
- 识别光敏性成分，建议使用时段（如视黄醇仅晚间使用）
- 提供成分协同建议，最大化护肤效果

## 配伍原则
1. **安全第一**：避免刺激性成分叠加（如多种酸类、高浓度活性物）
2. **时段分离**：光敏成分放晚间，抗氧化剂放早间
3. **功效协同**：利用成分协同作用（如神经酰胺+透明质酸）
4. **步骤科学**：遵循"水状→精华→乳状→膏状"的质地顺序

## 工具使用
- 使用 routine_planner 工具进行配伍检测和流程规划
- action="check_compatibility" 用于检测冲突
- action="build_routine" 用于生成完整护肤流程
- 工具会自动处理产品名称/ID的模糊匹配

## 回复风格
- 专业但易懂，解释配伍原理
- 对冲突给出明确警示和替代方案
- 流程规划要具体到每个步骤的使用顺序
- 提供使用技巧（如等待时间、用量建议）

{user_context}
"""


class CollocationAgent:
    """搭配规划 Agent，使用 ReAct 模式"""

    TOOLS = [PLANNER_SCHEMA]

    def __init__(self, client: AsyncOpenAI, db):
        self.client = client
        self.db = db

    def _inject_profile(self, profile: UserProfile) -> str:
        """将用户档案注入 System Prompt"""
        context = profile.to_prompt_context() if profile else "用户档案：暂无"
        return SYSTEM_PROMPT.replace("{user_context}", f"\n## 用户档案\n{context}")

    async def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """执行工具调用"""
        if tool_name == "routine_planner":
            return await routine_planner(
                self.db,
                products=tool_input.get("products", []),
                action=tool_input.get("action", "check_compatibility"),
            )
        return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

    async def run(self, task: str, profile: UserProfile) -> str:
        """运行 ReAct 循环"""
        messages = [
            {"role": "system", "content": self._inject_profile(profile)},
            {"role": "user", "content": task},
        ]

        for iteration in range(settings.max_tool_iterations):
            logger.info(f"[CollocationAgent] Iteration {iteration + 1}")

            response = await self.client.chat.completions.create(
                model=settings.model,
                max_tokens=2048,
                messages=messages,
                tools=self.TOOLS,
            )

            msg = response.choices[0].message
            messages.append(msg)

            if response.choices[0].finish_reason == "stop":
                return msg.content or "规划完成。"

            if not msg.tool_calls:
                return msg.content or "规划完成。"

            for tc in msg.tool_calls:
                logger.info(f"[CollocationAgent] Tool call: {tc.function.name}")
                tool_input = json.loads(tc.function.arguments)
                result = await self._execute_tool(tc.function.name, tool_input)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        logger.warning("[CollocationAgent] Max iterations reached")
        return "抱歉，规划处理超时，请重试或简化您的需求。"

