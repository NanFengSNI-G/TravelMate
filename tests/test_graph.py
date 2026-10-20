from app.domain import Domain
from app.graph import build_graph
from app.runs import Runs
from app.models import Conversation
from app.db import sessions
from app.worker import process
from tests.test_domain import req


def conversation():
    with sessions().begin() as s:
        c = Conversation(owner="alice")
        s.add(c)
        s.flush()
        return c.id


def test_direct_booking_approval_resume(env, saver):
    runs = Runs()
    cid = conversation()
    rid = runs.submit("alice", cid, req().model_dump(mode="json"))
    graph = build_graph(Domain(env), saver)
    r = runs.claim()
    process(r, graph, runs)
    waiting = runs.get("alice", rid)
    assert waiting.status == "WAITING"
    snapshot = graph.get_state({"configurable": {"thread_id": rid}})
    assert not snapshot.values.get("results")
    assert snapshot.next == ("approval",)
    runs.resume("alice", rid, {"decision": "approve", "version": 1})
    r = runs.claim()
    process(r, graph, runs)
    assert runs.get("alice", rid).status == "DONE"
    assert len(Domain(env).orders("alice")) == 2
    assert (
        runs.resume("alice", rid, {"decision": "approve", "version": 1})["status"]
        == "DONE"
    )


def test_fencing_and_reject(env, saver):
    runs = Runs()
    rid = runs.submit("alice", conversation(), req().model_dump(mode="json"))
    r = runs.claim()
    graph = build_graph(Domain(env), saver)
    process(r, graph, runs)
    runs.resume("alice", rid, {"decision": "reject", "version": 1})
    r = runs.claim()
    process(r, graph, runs)
    assert not Domain(env).orders("alice")
    assert not runs.heartbeat(rid, r.fence - 1)


def test_cancel_queued_and_waiting(env, saver):
    runs = Runs()
    rid = runs.submit("alice", conversation(), req().model_dump(mode="json"))
    assert runs.cancel("alice", rid)["status"] == "CANCELLED"
    assert runs.claim() is None
    rid = runs.submit("alice", conversation(), req().model_dump(mode="json"))
    graph = build_graph(Domain(env), saver)
    process(runs.claim(), graph, runs)
    assert runs.cancel("alice", rid)["status"] == "CANCELLED"
    assert not Domain(env).orders("alice")


def test_daily_greeting_does_not_create_a_support_case(env, saver):
    from app.agents import classify
    from app.models import Case
    from sqlalchemy import select

    request = classify(
        "你好", [{"text": "之前咨询过人工服务", "request": {"intent": "support"}}]
    )
    assert request.intent == "chat" and request.question == "你好"
    runs = Runs()
    rid = runs.submit("alice", conversation(), request.model_dump(mode="json"), "你好")
    graph = build_graph(Domain(env), saver)
    process(runs.claim(), graph, runs)
    result = runs.get("alice", rid)
    assert result.status == "DONE" and result.result["customer"]["answer"]
    assert "approval" not in result.result
    with sessions()() as s:
        assert not list(s.scalars(select(Case)))
