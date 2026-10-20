from typing import TypedDict, Annotated
import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from langgraph.types import RetryPolicy
from app.contracts import Request, EvidenceBundle, merge_results


class State(TypedDict, total=False):
    owner: str
    run_id: str
    conversation_id: str
    fence: int
    request: dict
    context: list[dict]
    messages: Annotated[list[AnyMessage], add_messages]
    results: Annotated[dict, merge_results]
    evidence: dict
    draft: dict
    customer: dict
    outcome: dict
    proposal: dict
    stopped: bool


READ_RETRY = RetryPolicy(
    max_attempts=2,
    initial_interval=1,
    retry_on=(
        APIConnectionError,
        APITimeoutError,
        RateLimitError,
        InternalServerError,
        httpx.TransportError,
    ),
)


def policy_graph(domain):
    def retrieve(state):
        req = Request.model_validate(state["request"])
        return {"evidence": domain.evidence(state["owner"], req).model_dump()}

    def answer(state):
        req = Request.model_validate(state["request"])
        result = domain.knowledge.answer(
            req.resolved_question or req.question,
            EvidenceBundle.model_validate(state["evidence"]),
        )
        return {
            "outcome": {
                "customer": {"answer": result["answer"]},
                "evidence": state["evidence"],
            }
        }

    g = StateGraph(State)
    g.add_node("retrieve", retrieve, retry_policy=READ_RETRY)
    g.add_node("answer", answer, retry_policy=READ_RETRY)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "answer")
    g.add_edge("answer", END)
    return g.compile()


def planning_graph(domain, agents):
    def expert(role):
        def run(state):
            return {
                "results": {
                    role: agents.specialist(
                        role,
                        Request.model_validate(state["request"]),
                        state.get("context", []),
                    )
                }
            }

        return run

    def feasibility(state):
        req = Request.model_validate(state["request"])
        try:
            return {"draft": domain.plan_draft(state["owner"], req, state["results"])}
        except ValueError as exc:
            return {"stopped": True, "outcome": {"message": str(exc)}}

    def compose(state):
        req = Request.model_validate(state["request"])
        design = agents.compose_plan(
            req, state["results"], state["draft"], state.get("context", [])
        )
        return {
            "draft": domain.validate_plan(req, state["draft"], design, state["run_id"])
        }

    def prepare(state):
        return {
            "proposal": domain.pending(
                state["owner"], "plan_create", state["draft"], state["run_id"]
            )
        }

    g = StateGraph(State)
    for role in ("flight", "hotel"):
        g.add_node(role, expert(role), retry_policy=READ_RETRY)
        g.add_edge(START, role)
    g.add_node("feasibility", feasibility, retry_policy=READ_RETRY)
    g.add_node("compose", compose, retry_policy=READ_RETRY)
    g.add_node("prepare_plan", prepare)
    g.add_edge(["flight", "hotel"], "feasibility")
    g.add_conditional_edges(
        "feasibility",
        lambda s: END if s.get("stopped") else "compose",
        [END, "compose"],
    )
    g.add_edge("compose", "prepare_plan")
    g.add_edge("prepare_plan", END)
    return g.compile()


def repair_graph(domain, saver):
    from app.recovery import Recovery, ResearchUnavailable

    def research(state):
        try:
            report = Recovery(domain, saver).run(
                state["owner"],
                state["run_id"],
                Request.model_validate(state["request"]),
            )
        except ResearchUnavailable as exc:
            return {
                "stopped": True,
                "outcome": {
                    "message": f"暂时无法生成调整报告：{exc}。请调整日期、人数或预算后重试；原行程和订单继续保留。"
                },
            }
        return {"draft": {"plan_id": state["request"]["plan_id"], "report": report}}

    def prepare(state):
        return {
            "proposal": domain.pending(
                state["owner"], "repair_save", state["draft"], state["run_id"]
            )
        }

    g = StateGraph(State)
    g.add_node("research", research)
    g.add_node("prepare_report", prepare)
    g.add_edge(START, "research")
    g.add_conditional_edges(
        "research",
        lambda s: END if s.get("stopped") else "prepare_report",
        [END, "prepare_report"],
    )
    g.add_edge("prepare_report", END)
    return g.compile()
