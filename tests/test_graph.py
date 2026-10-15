from langgraph.checkpoint.memory import InMemorySaver
from app.domain import Domain
from app.graph import build_graph
from app.runs import Runs
from app.models import Conversation, Run
from app.db import sessions
from app.worker import process
from tests.test_domain import req


def conversation():
    with sessions().begin() as s:
        c = Conversation(owner="alice")
        s.add(c)
        s.flush()
        return c.id


def test_graph_parallel_approval_resume(env):
    runs = Runs()
    cid = conversation()
    rid = runs.submit("alice", cid, req().model_dump(mode="json"))
    graph = build_graph(Domain(env), InMemorySaver())
    r = runs.claim()
    process(r, graph, runs)
    waiting = runs.get("alice", rid)
    assert waiting.status == "WAITING"
    snapshot = graph.get_state({"configurable": {"thread_id": rid}})
    assert set(snapshot.values["results"]) == {"flight", "hotel"}
    runs.resume("alice", rid, {"decision": "approve", "version": 1})
    r = runs.claim()
    process(r, graph, runs)
    assert runs.get("alice", rid).status == "DONE"
    assert len(Domain(env).orders("alice")) == 2
    assert (
        runs.resume("alice", rid, {"decision": "approve", "version": 1})["status"]
        == "DONE"
    )


def test_fencing_and_reject(env):
    runs = Runs()
    rid = runs.submit("alice", conversation(), req().model_dump(mode="json"))
    r = runs.claim()
    graph = build_graph(Domain(env), InMemorySaver())
    process(r, graph, runs)
    runs.resume("alice", rid, {"decision": "reject", "version": 1})
    r = runs.claim()
    process(r, graph, runs)
    assert not Domain(env).orders("alice")
    assert not runs.heartbeat(rid, r.fence - 1)


def test_cancel_queued_and_waiting(env):
    runs = Runs()
    rid = runs.submit("alice", conversation(), req().model_dump(mode="json"))
    assert runs.cancel("alice", rid)["status"] == "CANCELLED"
    assert runs.claim() is None
    rid = runs.submit("alice", conversation(), req().model_dump(mode="json"))
    graph = build_graph(Domain(env), InMemorySaver())
    process(runs.claim(), graph, runs)
    assert runs.cancel("alice", rid)["status"] == "CANCELLED"
    assert not Domain(env).orders("alice")
