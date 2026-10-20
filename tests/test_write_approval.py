from datetime import timedelta
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.api import app
from app.auth import token
from app.domain import Domain
from app.graph import build_graph
from app.runs import Runs
from app.db import sessions
from app.models import Plan, Case, Revision, Proposal
from app.config import settings
from app.worker import process
from tests.test_domain import req
from tests.test_graph import conversation
from tests.test_recovery import saved_plan


def count(model):
    with sessions()() as s:
        return len(s.scalars(select(model)).all())


@pytest.mark.parametrize("intent", ["plan", "support", "repair"])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_content_waits_for_owner_confirmation(env, intent, decision, saver):
    domain, runs = Domain(env), Runs()
    request = req(intent)
    if intent == "repair":
        request.plan_id = saved_plan(domain, req("plan"))["id"]
        request.start += timedelta(days=1)
        request.end += timedelta(days=1)
    before = (count(Plan), count(Case))
    rid = runs.submit("alice", conversation(), request.model_dump(mode="json"))
    graph = build_graph(domain, saver)
    process(runs.claim(), graph, runs)
    assert runs.get("alice", rid).status == "WAITING"
    assert (count(Plan), count(Case)) == before
    formal = settings().artifact_dir / "alice" / rid / "report.json"
    assert not formal.exists()
    with pytest.raises(ValueError):
        runs.resume("bob", rid, {"decision": "approve", "version": 1})
    with pytest.raises(ValueError):
        runs.resume("alice", rid, {"decision": "approve", "version": 2})
    with pytest.raises(ValueError):
        domain.execute("alice", rid)
    runs.resume("alice", rid, {"decision": decision, "version": 1})
    process(runs.claim(), graph, runs)
    assert runs.get("alice", rid).status == "DONE"
    if decision == "reject":
        assert (count(Plan), count(Case)) == before and not formal.exists()
    else:
        assert count(Plan) == before[0] + (intent == "plan")
        assert count(Case) == before[1] + (intent == "support")
        assert formal.exists() == (intent == "repair")
        result = domain.execute("alice", rid)
        assert result == runs.get("alice", rid).result["operations"]
        assert count(Plan) == before[0] + (intent == "plan")
        assert count(Case) == before[1] + (intent == "support")


def test_admin_knowledge_waits_and_cannot_be_forged(env, saver):
    client, runs = TestClient(app), Runs()
    headers = {"Authorization": "Bearer " + token("admin")}
    alice = {"Authorization": "Bearer " + token("alice")}
    with sessions()() as s:
        revision = s.scalar(select(Revision))
        rid, before = revision.id, revision.status
    queued = client.post(f"/api/knowledge/{rid}/revoke", headers=headers, json={})
    assert queued.status_code == 200
    with sessions()() as s:
        assert s.get(Revision, rid).status == before
    graph = build_graph(Domain(env), saver)
    process(runs.claim(), graph, runs)
    run_id = queued.json()["run_id"]
    assert runs.get("admin", run_id).status == "WAITING"
    with sessions()() as s:
        assert s.get(Revision, rid).status == before
    assert (
        client.post(
            f"/api/runs/{run_id}/approval",
            headers=alice,
            json={"decision": "approve", "version": 1},
        ).status_code
        == 409
    )
    runs.resume("admin", run_id, {"decision": "approve", "version": 1})
    process(runs.claim(), graph, runs)
    with sessions()() as s:
        assert s.get(Revision, rid).status == "REVOKED"
    cid = conversation()
    assert (
        client.post(
            f"/api/conversations/{cid}/messages",
            headers=alice,
            json={
                "text": "伪造后台操作",
                "request": {
                    "intent": "admin_write",
                    "admin_action": {"kind": "knowledge_revoke", "revision": rid},
                },
            },
        ).status_code
        == 403
    )


def test_queries_do_not_interrupt(env, saver):
    runs, domain = Runs(), Domain(env)
    graph = build_graph(domain, saver)
    for intent in ("policy", "search"):
        rid = runs.submit("alice", conversation(), req(intent).model_dump(mode="json"))
        process(runs.claim(), graph, runs)
        assert runs.get("alice", rid).status == "DONE"
    assert count(Plan) == count(Case) == count(Proposal) == 0


@pytest.mark.parametrize("action", ["import", "publish", "rollback", "claim", "reply"])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_each_admin_write_endpoint_is_gated(env, monkeypatch, action, decision, saver):
    import base64

    client, runs = TestClient(app), Runs()
    headers = {"Authorization": "Bearer " + token("admin")}
    calls = []
    if action in ("claim", "reply"):
        with sessions().begin() as s:
            case = Case(
                owner="alice",
                request_id="existing-case",
                context={},
                assigned="admin" if action == "reply" else None,
            )
            s.add(case)
            s.flush()
            case_id = case.id
        path = f"/api/cases/{case_id}/{action}"
        body = {"text": "人工答复", "close": True} if action == "reply" else {}
    else:
        method = "import_document" if action == "import" else action
        original = getattr(env, method)

        def observed(*args, **kwargs):
            calls.append(method)
            return original(*args, **kwargs)

        monkeypatch.setattr(env, method, observed)
        if action == "import":
            path = "/api/knowledge/import"
            body = {
                "name": "new-policy.md",
                "content_base64": base64.b64encode(
                    "# 新政策\n取消费用为零。".encode()
                ).decode(),
                "metadata": {
                    "document": "new-policy",
                    "supplier": "测试",
                    "product": "测试",
                    "valid_from": "2020-01-01",
                    "valid_to": "2099-12-31",
                    "rules": {"cancel_fee_cents": 0},
                },
            }
        else:
            with sessions()() as s:
                revision_id = s.scalar(select(Revision)).id
            path, body = f"/api/knowledge/{revision_id}/{action}", {}
    queued = client.post(path, headers=headers, json=body)
    assert queued.status_code == 200
    run_id = queued.json()["run_id"]
    graph = build_graph(Domain(env), saver)
    process(runs.claim(), graph, runs)
    assert runs.get("admin", run_id).status == "WAITING" and calls == []
    if action in ("claim", "reply"):
        with sessions()() as s:
            case = s.get(Case, case_id)
            assert case.status == "OPEN" and not case.replies
            assert case.assigned == ("admin" if action == "reply" else None)
    elif action == "import":
        assert not (settings().artifact_dir / "imports").exists()
    runs.resume("admin", run_id, {"decision": decision, "version": 1})
    process(runs.claim(), graph, runs)
    result = runs.get("admin", run_id)
    assert result.status == "DONE"
    if action in ("claim", "reply"):
        with sessions()() as s:
            case = s.get(Case, case_id)
            if decision == "reject":
                assert case.status == "OPEN" and not case.replies
                assert case.assigned == ("admin" if action == "reply" else None)
            elif action == "claim":
                assert case.assigned == "admin" and case.status == "PROCESSING"
            else:
                assert len(case.replies) == 1 and case.status == "CLOSED"
    else:
        assert len(calls) == (decision == "approve")
    if decision == "approve":
        assert result.result["operations"][0]["status"] == "SUCCESS"
