from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send, interrupt
from app.contracts import Request, Task, validate_tasks, merge_results
from app.agents import Agents
from app.recovery import Recovery


class State(TypedDict, total=False):
    owner: str
    run_id: str
    conversation_id: str
    fence: int
    request: dict
    tasks: list[dict]
    task: dict
    results: Annotated[dict, merge_results]
    customer: dict
    outcome: dict
    proposal: dict
    stopped: bool


def build_graph(domain, saver):
    agents = Agents(domain, saver)

    def customer(state):
        req = Request.model_validate(state["request"])
        if req.intent in ("search", "plan", "book", "change", "repair") and (
            not req.start or not req.end
        ):
            return {
                "stopped": True,
                "outcome": {"message": "请补充起止日期，住宿需 1—14 晚。"},
            }
        if req.intent == "admin_write":
            return {"customer": {}, "tasks": [], "stopped": False}
        result = agents.customer(
            state["owner"], req, state.get("conversation_id", state["run_id"])
        )
        tasks = []
        if req.intent in ("search", "plan", "book", "change"):
            tasks = [
                Task(id="flight", role="flight"),
                Task(
                    id="hotel",
                    role="hotel",
                    depends_on=["flight"] if req.intent == "change" else [],
                ),
            ]
        validate_tasks(tasks)
        return {
            "customer": result,
            "tasks": [t.model_dump() for t in tasks],
            "stopped": False,
        }

    def dispatch(state):
        return {}

    def route(state):
        if state.get("stopped"):
            return "finish"
        completed = set(state.get("results", {}))
        ready = [
            t
            for t in state.get("tasks", [])
            if t["id"] not in completed and set(t["depends_on"]) <= completed
        ]
        if ready:
            return [Send(t["role"], {**state, "task": t}) for t in ready]
        return "join"

    def specialist(role):
        def run(state):
            result = agents.specialist(role, Request.model_validate(state["request"]))
            return {"results": {state["task"]["id"]: result}}

        return run

    def join(state):
        req = Request.model_validate(state["request"])
        owner = state["owner"]
        if req.intent == "policy":
            ev = domain.evidence(owner, req)
            return {
                "outcome": {"evidence": ev.model_dump(), "customer": state["customer"]}
            }
        if req.intent == "search":
            return {"outcome": {"results": state.get("results", {})}}
        if req.intent == "plan":
            draft = domain.plan_draft(owner, req, state["results"])
            return {
                "proposal": domain.pending(owner, "plan_create", draft, state["run_id"])
            }
        if req.intent == "support":
            context = {
                "request": req.model_dump(mode="json"),
                "customer": state["customer"],
            }
            return {
                "proposal": domain.pending(
                    owner, "case_create", context, state["run_id"]
                )
            }
        if req.intent == "repair":
            report = Recovery(domain, saver).run(owner, state["run_id"], req)
            return {
                "proposal": domain.pending(
                    owner,
                    "repair_save",
                    {"plan_id": req.plan_id, "report": report},
                    state["run_id"],
                )
            }
        if req.intent == "admin_write":
            return {
                "proposal": domain.prepare_admin(
                    owner, req.admin_action, state["run_id"]
                )
            }
        if req.intent in ("book", "change", "cancel"):
            # run ID 作为稳定提案 ID，节点重跑不会创建第二个待批准提案。
            return {"proposal": domain.proposal(owner, req, request_id=state["run_id"])}
        return {"outcome": {"message": "请选择业务类型"}}

    def after_join(state):
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

    def after_approval(state):
        return "execute" if state["outcome"]["decision"] == "approve" else "finish"

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
        return {}

    g = StateGraph(State)
    for name, fn in [
        ("customer", customer),
        ("dispatch", dispatch),
        ("flight", specialist("flight")),
        ("hotel", specialist("hotel")),
        ("join", join),
        ("approval", approval),
        ("execute", execute),
        ("finish", finish),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "customer")
    g.add_edge("customer", "dispatch")
    g.add_conditional_edges("dispatch", route)
    g.add_edge("flight", "dispatch")
    g.add_edge("hotel", "dispatch")
    g.add_conditional_edges("join", after_join)
    g.add_conditional_edges("approval", after_approval)
    g.add_edge("execute", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=saver)
