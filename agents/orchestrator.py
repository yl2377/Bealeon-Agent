"""
Orchestrator - 意图路由与多 Agent 协调
负责理解用户意图，分发任务给子 Agent，合成最终回复
"""

import asyncio
import json
import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from config import settings
from memory.session_memory import SessionMemory
from storage.database import Database, UserProfile
from .recommendation import RecommendationAgent
from .analyst import AnalystAgent
from .collocation import CollocationAgent
from .commerce import CommerceAgent

logger = logging.getLogger(__name__)


ROUTER_SYSTEM = """你是美妆智能顾问的【意图路由器】。

## 你的职责
分析用户的问题，判断需要调用哪些子 Agent 来回答。

## 可用的子 Agent
1. **recommendation**：个性化产品推荐
   - 适用场景：用户想找适合自己的产品、需要推荐、比较产品
   - 示例："推荐一款敏感肌面霜"、"有什么适合我的精华"

2. **analyst**：产品详情与成分分析
   - 适用场景：询问具体产品信息、成分安全性、功效原理
   - 示例："这款产品含什么成分"、"烟酰胺的作用是什么"

3. **collocation**：护肤品搭配与流程规划
   - 适用场景：询问产品能否一起用、配伍冲突、护肤步骤
   - 示例："烟酰胺和视黄醇能一起用吗"、"帮我规划早晚护肤流程"

4. **commerce**：电商服务（购买、订单、物流）
   - 适用场景：购买产品、查询订单、追踪物流
   - 示例："帮我买这款产品"、"我的订单到哪了"

## 路由规则
- 如果问题涉及多个领域，可以调用多个 Agent（并行执行）
- 如果问题模糊，优先选择 recommendation
- 如果是闲聊或问候，直接回复，不调用 Agent

## 输出格式
返回 JSON 数组，每个元素包含：
- agent: Agent 名称（recommendation/analyst/collocation/commerce）
- task: 传递给该 Agent 的具体任务描述

示例：
[{"agent": "recommendation", "task": "推荐适合敏感肌的保湿面霜，预算300元以内"}]
"""


SYNTHESIS_SYSTEM = """你是美妆智能顾问的【回复合成器】。

## 你的职责
将各个子 Agent 的回复整合成一个连贯、自然的最终回复。

## 合成原则
1. **保持完整性**：不要遗漏任何子 Agent 的关键信息
2. **自然流畅**：让回复读起来像一个人说的，而不是机械拼接
3. **结构清晰**：如果信息较多，用分段或列表组织
4. **用户友好**：用亲切、专业的语气，避免生硬的技术术语

## 注意事项
- 如果多个 Agent 的回复有重复信息，去重后呈现
- 如果 Agent 回复之间有矛盾，优先采用更专业的判断
- 保持简洁，不要过度解释
"""


class Orchestrator:
    """Orchestrator 协调器，负责意图路由和结果合成"""

    def __init__(self, client: AsyncOpenAI, db: Database, hybrid_search):
        self.client = client
        self.db = db
        self.hybrid_search = hybrid_search

        # 初始化子 Agent
        self.agents = {
            "recommendation": RecommendationAgent(client, db, hybrid_search),
            "analyst": AnalystAgent(client, db),
            "collocation": CollocationAgent(client, db),
            "commerce": CommerceAgent(client, db),
        }

    async def _route_intent(
        self, user_message: str, memory_context: str, profile: UserProfile | None
    ) -> list[dict]:
        """路由用户意图到子 Agent"""
        profile_context = profile.to_prompt_context() if profile else ""
        prompt = f"""用户消息：{user_message}

{profile_context}

会话上下文：
{memory_context}

请分析用户意图，返回需要调用的 Agent 列表（JSON 格式）。"""

        response = await self.client.chat.completions.create(
            model=settings.model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )

        text = response.choices[0].message.content or "[]"

        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            routes = json.loads(text)
            if not isinstance(routes, list):
                routes = []
        except Exception as e:
            logger.warning(f"[Orchestrator] Failed to parse routing: {e}, text: {text}")
            routes = []

        logger.info(f"[Orchestrator] Routed to: {[r.get('agent') for r in routes]}")
        return routes

    async def _dispatch_agents(
        self, routes: list[dict], profile: UserProfile
    ) -> dict[str, str]:
        """并行调用子 Agent"""
        tasks = []
        agent_names = []

        for route in routes:
            agent_name = route.get("agent")
            task_desc = route.get("task", "")

            if agent_name in self.agents:
                agent = self.agents[agent_name]
                tasks.append(agent.run(task_desc, profile))
                agent_names.append(agent_name)
            else:
                logger.warning(f"[Orchestrator] Unknown agent: {agent_name}")

        if not tasks:
            return {}

        results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_results = {}
        for name, result in zip(agent_names, results):
            if isinstance(result, Exception):
                logger.error(f"[Orchestrator] Agent {name} failed: {result}")
                agent_results[name] = f"[{name} 处理失败]"
            else:
                agent_results[name] = result

        return agent_results

    async def stream(
        self, user_message: str, user_id: str, session: SessionMemory
    ) -> AsyncIterator[str]:
        """流式处理用户消息"""
        # 1. 加载用户档案
        profile = await self.db.get_profile(user_id)

        # 2. 构建记忆上下文
        memory_context = "\n".join(
            f"{m['role']}: {m['content']}" for m in session.to_list()[-6:]
        )

        # 3. 路由意图（非流式）
        routes = await self._route_intent(user_message, memory_context, profile)

        # 如果没有路由到任何 Agent，直接回复
        if not routes:
            async for chunk in self._stream_direct_reply(user_message, memory_context, profile):
                yield chunk
            return

        # 4. 并行调用子 Agent（非流式）
        agent_results = await self._dispatch_agents(routes, profile)

        # 5. 流式合成最终回复
        async for chunk in self._stream_synthesis(
            user_message, agent_results, memory_context, profile
        ):
            yield chunk

    async def _stream_direct_reply(
        self, user_message: str, memory_context: str, profile: UserProfile | None
    ) -> AsyncIterator[str]:
        """直接回复（闲聊、问候等）"""
        profile_context = profile.to_prompt_context() if profile else ""
        system = f"""你是美妆智能顾问，一个专业、亲切的护肤美妆助手。
用户的问题不需要调用专业工具，请直接友好地回复。

{profile_context}"""

        prompt = f"""用户消息：{user_message}

会话上下文：
{memory_context}

请自然地回复用户。"""

        stream = await self.client.chat.completions.create(
            model=settings.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def _stream_synthesis(
        self, user_message: str, agent_results: dict[str, str], memory_context: str,
        profile: UserProfile | None
    ) -> AsyncIterator[str]:
        """流式合成子 Agent 的回复"""
        profile_context = profile.to_prompt_context() if profile else ""
        agent_outputs = "\n\n".join(
            f"【{name} 的回复】\n{result}" for name, result in agent_results.items()
        )

        prompt = f"""{profile_context}

用户问题：{user_message}

各个专家的回复：
{agent_outputs}

会话上下文：
{memory_context}

请将上述专家回复整合成一个连贯、自然的最终回复。"""

        stream = await self.client.chat.completions.create(
            model=settings.model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": SYNTHESIS_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
