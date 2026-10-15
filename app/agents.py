import json
from uuid import uuid4
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    ToolMessage,
    HumanMessage,
    SystemMessage,
    trim_messages,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_openai import ChatOpenAI
from app.config import settings
from app.contracts import Request


class ScriptModel(BaseChatModel):
    script: list[dict] = []
    answer: str = "完成"
    structured: dict | None = None

    @property
    def _llm_type(self):
        return "tutorial-script-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last_user = max(
            (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)),
            default=-1,
        )
        count = sum(isinstance(m, ToolMessage) for m in messages[last_user + 1 :])
        if count < len(self.script):
            call = {
                **self.script[count],
                "id": "call-" + uuid4().hex,
                "type": "tool_call",
            }
            msg = AIMessage(content="", tool_calls=[call])
        elif self.structured is not None:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "RepairReport",
                        "args": self.structured,
                        "id": "report-" + uuid4().hex,
                        "type": "tool_call",
                    }
                ],
            )
        else:
            msg = AIMessage(content=self.answer)
        return ChatResult(generations=[ChatGeneration(message=msg)])


def model(script=None, answer="完成", structured=None):
    conf = settings()
    if conf.model_mode == "fixture":
        return ScriptModel(script=script or [], answer=answer, structured=structured)
    if conf.model_mode != "live" or not conf.model_api_key:
        raise ValueError("真实模型需要配置 API key")
    return ChatOpenAI(
        model=conf.model_name,
        base_url=conf.model_base_url,
        api_key=conf.model_api_key,
        temperature=0,
        timeout=30,
        max_retries=1,
    )


def classify(text: str, history=None):
    if settings().model_mode == "fixture":
        raise ValueError("fixture 模式请在表单提交结构化 Request；它不模拟自然语言理解")
    # 业务历史不是权限依据；上下文预算交给 LangChain 的消息裁剪器。
    messages = [
        HumanMessage(content=json.dumps(item, ensure_ascii=False))
        for item in history or []
    ]
    messages.append(HumanMessage(content=text))
    messages = trim_messages(
        messages,
        max_tokens=settings().context_max_tokens,
        token_counter=count_tokens_approximately,
        strategy="last",
        start_on="human",
    )
    return (
        model()
        .with_structured_output(Request, method="function_calling")
        .invoke(
            [
                SystemMessage(
                    content="将用户需求解析为 Request，不编造资源或订单 ID，缺失日期为 null。"
                ),
                *messages,
            ]
        )
    )


class Agents:
    def __init__(self, domain, saver=None):
        self.domain = domain
        self.saver = saver

    def customer(self, owner, req, conversation_id=None):
        from langchain_core.tools import tool

        @tool
        def get_my_orders() -> str:
            """读取当前登录用户订单。"""
            return json.dumps(self.domain.orders(owner), ensure_ascii=False)

        @tool
        def retrieve_policy() -> str:
            """按当前订单或资源查询适用政策，返回出处。"""
            evidence = self.domain.evidence(owner, req)
            return json.dumps(
                self.domain.knowledge.answer(req.question, evidence), ensure_ascii=False
            )

        calls = [{"name": "get_my_orders", "args": {}}]
        if req.intent == "policy":
            calls.append({"name": "retrieve_policy", "args": {}})
        agent = create_agent(
            model=model(calls, "已读取本人订单和工具结果。"),
            tools=[get_my_orders, retrieve_policy],
            checkpointer=self.saver,
            middleware=[
                SummarizationMiddleware(
                    model=model(answer="fixture 上下文摘要，不用于真实内容质量验收"),
                    trigger=("tokens", settings().context_max_tokens),
                    keep=("messages", 6),
                )
            ],
            system_prompt="你是旅行客服。必须使用工具读取事实，政策回答引用工具中的 node_id。无证据要说明不足；不要承诺操作成功。",
        )
        result = agent.invoke(
            {"messages": [("user", req.model_dump_json())]},
            config={
                "recursion_limit": 12,
                "configurable": {
                    "thread_id": f"customer:{owner}:{conversation_id or uuid4().hex}"
                },
            },
        )
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

    def specialist(self, role, req):
        from langchain_core.tools import tool

        @tool
        def search_resources() -> str:
            """查询对应领域的可用资源、日期库存和费用。"""
            return json.dumps(self.domain.search(role, req), ensure_ascii=False)

        agent = create_agent(
            model=model(
                [{"name": "search_resources", "args": {}}], "已整理候选，尚未预订。"
            ),
            tools=[search_resources],
            system_prompt=f"你是{role}业务助手，只查询并解释候选，不执行交易。必须调用 search_resources。",
        )
        result = agent.invoke(
            {"messages": [("user", req.model_dump_json())]},
            config={"recursion_limit": 10},
        )
        tool_outputs = [
            m
            for m in result["messages"]
            if isinstance(m, ToolMessage) and m.name == "search_resources"
        ]
        if not tool_outputs:
            raise ValueError("业务助手未调用查询工具")
        return {
            "candidates": json.loads(tool_outputs[-1].content),
            "answer": str(result["messages"][-1].content),
            "tool_calls": len(tool_outputs),
        }
