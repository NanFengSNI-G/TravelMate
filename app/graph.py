from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langchain_core.messages import AIMessage
from app.contracts import Request
from app.agents import Agents
from app.conversations import (
    history,
    messages as conversation_messages,
    assistant_content,
)
from app.workflows import State, READ_RETRY, policy_graph, planning_graph, repair_graph


def business_route(state):
    if state.get("stopped"):
        return "finish"
    return {
        "chat": "customer",
        "orders": "customer",
        "plans": "customer",
        "policy": "policy",
        "search": "search",
        "plan": "planning",
        "repair": "repair",
        "book": "prepare",
        "change": "prepare",
        "cancel": "prepare",
        "support": "prepare",
        "admin_write": "prepare",
    }[state["request"]["intent"]]


def build_graph(domain, saver):
    agents = Agents(domain)

    def context(state):
        req = Request.model_validate(state["request"])
        entries = history(state["owner"], state["conversation_id"], state["run_id"])
        base = {
            "context": entries,
            "messages": conversation_messages(entries, req.question, state["run_id"]),
        }
        missing = None
        if req.intent in ("search", "plan", "book", "change", "repair") and (
            not req.start or not req.end
        ):
            missing = "请补充起止日期，住宿需 1—14 晚。"
        elif req.intent in ("book", "change") and not req.resource_ids:
            missing = "请先选择要预订或更换的资源。"
        elif req.intent in ("change", "cancel") and not req.order_id:
            missing = "请先选择需要处理的本人订单。"
        elif req.intent == "repair" and not req.plan_id:
            missing = "请先选择需要调整的已保存行程。"
        elif req.intent == "policy" and not req.order_id and len(req.resource_ids) != 1:
            return {
                **base,
                "stopped": True,
                "outcome": {
                    "message": "不同航班和房型的政策可能不同。请选择本次要咨询的资源；已有订单请从订单详情查询，以保留原政策版本。",
                    "policy_choices": domain.policy_choices(),
                },
            }
        if missing:
            return {**base, "stopped": True, "outcome": {"message": missing}}
        return {**base, "stopped": False}

    def customer(state):
        result = agents.customer(
            state["owner"],
            Request.model_validate(state["request"]),
            dialogue=state["messages"],
            pending=any(entry.get("status") == "WAITING" for entry in state["context"]),
        )
        return {"customer": result, "outcome": {"customer": result}}

    def search(state):
        req = Request.model_validate(state["request"])
        return {
            "outcome": {
                "results": {
                    kind: {"candidates": domain.search(kind, req)}
                    for kind in set(req.resource_kinds)
                }
            }
        }

    def prepare(state):
        req, owner = Request.model_validate(state["request"]), state["owner"]
        try:
            if req.intent == "support":
                if req.case_id:
                    case = domain.support_case(owner, req.case_id)
                    if case.status == "CLOSED":
                        raise ValueError("该申请已结束，请重新发起服务申请")
                proposal = domain.pending(
                    owner,
                    "case_message" if req.case_id else "case_create",
                    {
                        "request": req.model_dump(mode="json"),
                        "conversation": state.get("context", []),
                    },
                    state["run_id"],
                )
            elif req.intent == "admin_write":
                proposal = domain.prepare_admin(
                    owner, req.admin_action, state["run_id"]
                )
            else:
                proposal = domain.proposal(owner, req, request_id=state["run_id"])
            return {"proposal": proposal}
        except ValueError as exc:
            return {"outcome": {"message": str(exc)}}

    def after_prepare(state):
        return "approval" if state.get("proposal") else "finish"

    def approval(state):
        proposal = state["proposal"]
        decision = interrupt({"type": "approval", "proposal": proposal})
        if decision.get("version") != proposal["version"] or decision.get(
            "decision"
        ) not in ("approve", "reject"):
            raise ValueError("审批版本或决定非法")
        domain.decide(
            state["owner"], proposal["id"], proposal["version"], decision["decision"]
        )
        return {"outcome": {"decision": decision["decision"]}}

    def execute(state):
        result = domain.execute(
            state["owner"], state["proposal"]["id"], state["run_id"], state["fence"]
        )
        outcome = {"operations": result, "proposal_id": state["proposal"]["id"]}
        for operation in result:
            if operation["status"] == "SUCCESS":
                outcome.update(
                    {
                        key: operation[key]
                        for key in ("plan", "case_id", "repair", "knowledge")
                        if key in operation
                    }
                )
        return {"outcome": outcome}

    def finish(state):
        return {
            "messages": [
                AIMessage(
                    content=assistant_content(state.get("outcome", {})),
                    id=state["run_id"] + ":assistant",
                )
            ]
        }

    g = StateGraph(State)
    g.add_node("context", context)
    g.add_node("customer", customer, retry_policy=READ_RETRY)
    g.add_node("search", search, retry_policy=READ_RETRY)
    g.add_node("policy", policy_graph(domain))
    g.add_node("planning", planning_graph(domain, agents))
    g.add_node("repair", repair_graph(domain, saver))
    g.add_node("prepare", prepare)
    g.add_node("approval", approval)
    g.add_node("execute", execute)
    g.add_node("finish", finish)
    g.add_edge(START, "context")
    g.add_conditional_edges(
        "context",
        business_route,
        ["customer", "search", "policy", "planning", "repair", "prepare", "finish"],
    )
    for node in ("customer", "search", "policy"):
        g.add_edge(node, "finish")
    for node in ("planning", "repair", "prepare"):
        g.add_conditional_edges(node, after_prepare, ["approval", "finish"])
    g.add_conditional_edges(
        "approval",
        lambda s: "execute" if s["outcome"]["decision"] == "approve" else "finish",
        ["execute", "finish"],
    )
    g.add_edge("execute", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=saver)
