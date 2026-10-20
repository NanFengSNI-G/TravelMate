import json
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, wrap_model_call
from langchain_core.messages import (
    ToolMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_openai import ChatOpenAI
from app.config import settings
from app.contracts import Request, CandidateReview, PlanDesign, TurnUnderstanding
from app.prompts import TURN_PROMPT, CUSTOMER_PROMPT, dated_prompt
from app.conversations import (
    select_option,
    messages as conversation_messages,
)
from langchain.agents.structured_output import ToolStrategy


def model():
    conf = settings()
    return ChatOpenAI(
        model=conf.model_name,
        base_url=conf.model_base_url,
        api_key=conf.dashscope_api_key,
        extra_body={"enable_thinking": False},
        temperature=0,
        timeout=60,
        max_retries=1,
        max_tokens=4096,
    )


def classify(text: str, history=None):
    understanding = (
        model()
        .with_structured_output(TurnUnderstanding, method="function_calling")
        .invoke(
            [
                SystemMessage(content=dated_prompt(TURN_PROMPT)),
                *conversation_messages(history, text),
            ]
        )
    )
    request = Request(
        intent=understanding.intent,
        question=text,
        resolved_question=understanding.resolved_question,
        **understanding.parameters.model_dump(exclude_none=True),
    )
    return select_option(request, history or [], understanding.selected_option_index)


class Agents:
    def __init__(self, domain):
        self.domain = domain

    def customer(self, owner, req, messages=None, *, dialogue=None, pending=False):
        from langchain_core.tools import tool

        @tool
        def get_travel_catalog() -> str:
            """读取本地目录支持的城市、可选日期范围与资源规模，不生成预订或修改库存。"""
            return json.dumps(self.domain.catalog_summary(), ensure_ascii=False)

        @tool
        def get_my_orders() -> str:
            """读取当前登录用户订单。"""
            return json.dumps(self.domain.orders(owner), ensure_ascii=False)

        @tool
        def get_my_plans() -> str:
            """读取当前登录用户已经保存的行程及方案；不生成或修改行程。"""
            return json.dumps(self.domain.plans(owner), ensure_ascii=False)

        @tool
        def get_pending_proposals() -> str:
            """只读查询当前用户待确认报价，包含资源、费用差额及是否过期；不批准或执行。"""
            return json.dumps(self.domain.pending_quotes(owner), ensure_ascii=False)

        @tool
        def retrieve_policy() -> str:
            """仅在本轮已明确一个订单或资源时查询适用政策；没有目标应先澄清，不默认选择酒店。"""
            evidence = self.domain.evidence(owner, req)
            return json.dumps(
                self.domain.knowledge.answer(
                    req.resolved_question or req.question, evidence
                ),
                ensure_ascii=False,
            )

        required_tool = {"orders": "get_my_orders", "plans": "get_my_plans"}.get(
            req.intent
        )
        if pending and req.intent == "chat":
            required_tool = "get_pending_proposals"

        @wrap_model_call
        def require_business_lookup(request, handler):
            last_user = max(
                (
                    i
                    for i, m in enumerate(request.messages)
                    if isinstance(m, HumanMessage)
                ),
                default=-1,
            )
            queried = any(
                isinstance(m, ToolMessage) and m.name == required_tool
                for m in request.messages[last_user + 1 :]
            )
            if required_tool and not queried:
                return handler(
                    request.override(
                        tool_choice={
                            "type": "function",
                            "function": {"name": required_tool},
                        }
                    )
                )
            return handler(request)

        agent = create_agent(
            model=model(),
            tools=(
                [get_my_orders]
                if req.intent == "orders"
                else (
                    [get_my_plans]
                    if req.intent == "plans"
                    else [
                        get_my_orders,
                        get_my_plans,
                        get_pending_proposals,
                        retrieve_policy,
                        get_travel_catalog,
                    ]
                )
            ),
            middleware=[
                require_business_lookup,
                SummarizationMiddleware(
                    model=model(),
                    trigger=("tokens", settings().context_max_tokens),
                    keep=("messages", 6),
                ),
            ],
            system_prompt=dated_prompt(CUSTOMER_PROMPT),
        )
        context = (
            dialogue
            if dialogue is not None
            else conversation_messages(messages, req.question)
        )
        result = agent.invoke(
            {"messages": context},
            config={"recursion_limit": 12},
        )
        if required_tool and not any(
            isinstance(m, ToolMessage) and m.name == required_tool
            for m in result["messages"]
        ):
            raise ValueError("回答未读取本人的业务数据，拒绝返回无依据结果")
        return {
            "answer": str(result["messages"][-1].content),
            "trace": [
                {
                    "role": m.type,
                    "content": str(m.content),
                    "calls": getattr(m, "tool_calls", []),
                }
                for m in result["messages"]
            ],
        }

    def specialist(self, role, req, context=None):
        from langchain_core.tools import tool

        @tool
        def search_resources() -> str:
            """查询当前领域真实库存、费用与候选；只读。"""
            return json.dumps(candidates, ensure_ascii=False)

        agent = create_agent(
            model=model(),
            tools=[search_resources],
            response_format=ToolStrategy(CandidateReview),
            system_prompt=(
                f"你是{role}方案评审助手。必须查询真实候选，再根据人数、日期、预算和用户偏好比较。"
                "ranked_ids 按适合程度排序，最多三个，只能使用工具返回的 ID。"
                "reasoning 解释价格与约束之间的取舍，warnings 写工具无法证明的限制。"
                "没有候选不编造，不执行预订。"
            ),
        )
        candidates = self.domain.search(role, req)
        if not candidates:
            return {"candidates": [], "answer": "当前日期无可用候选", "tool_calls": 0}
        result = agent.invoke(
            {"messages": conversation_messages(context, req.model_dump_json())},
            {"recursion_limit": 12},
        )
        outputs = [
            m
            for m in result["messages"]
            if isinstance(m, ToolMessage) and m.name == "search_resources"
        ]
        if not outputs:
            raise ValueError("领域助手未查询资源")
        actual = {c["id"]: c for c in json.loads(outputs[-1].content)}
        review = result["structured_response"]
        if (
            len(review.ranked_ids) != len(set(review.ranked_ids))
            or not set(review.ranked_ids) <= actual.keys()
        ):
            raise ValueError("领域助手返回了无效候选")
        return {
            "candidates": [actual[rid] for rid in review.ranked_ids],
            "answer": review.reasoning,
            "warnings": review.warnings,
            "tool_calls": len(outputs),
        }

    def compose_plan(self, req, results, draft, context=None):
        from pydantic import model_validator

        domain = self.domain

        class ValidatedPlanDesign(PlanDesign):
            """选择真实可行组合，并为活动提供有效指南出处。"""

            @model_validator(mode="after")
            def check_business_constraints(self):
                domain.validate_plan(req, draft, self, "validation")
                return self

        agent = create_agent(
            model=model(),
            tools=[],
            response_format=ToolStrategy(ValidatedPlanDesign),
            system_prompt=(
                "你是行程规划协调员。从 feasible.options 选择一至两组不同组合。"
                "解释费用、人数和偏好取舍。只能使用候选资源 ID，不填写虚构报价。"
                "活动 days 可为空；非空时只根据 evidence 中的指南生成，并给出对应 node_id。"
                "没有指南证据时不编造景点或活动。日期必须在入住日到退房日前一天内。"
                "若校验返回错误，按错误修正，不能绕过约束。"
            ),
        )
        result = agent.invoke(
            {
                "messages": [
                    *conversation_messages(context),
                    HumanMessage(
                        content=json.dumps(
                            {
                                "request": req.model_dump(mode="json"),
                                "reviews": results,
                                "feasible": draft,
                            },
                            ensure_ascii=False,
                        )
                    ),
                ]
            },
            {"recursion_limit": 12},
        )
        return result["structured_response"]
