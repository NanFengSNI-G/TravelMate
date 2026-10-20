from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import app
from app.auth import token
from app.cache import snapshot_key, write_snapshot
from app.conversations import history
from app.db import sessions
from app.models import Conversation, Plan, Run
from app.runs import Runs


ALICE = {"Authorization": "Bearer " + token("alice")}
BOB = {"Authorization": "Bearer " + token("bob")}


def create(client):
    return client.post("/api/conversations", headers=ALICE).json()["id"]


def test_rename_persists_and_is_owner_scoped(db_env):
    client = TestClient(app)
    cid = create(client)
    path = f"/api/conversations/{cid}"
    for headers in (BOB, {}):
        expected = 404 if headers else 401
        assert (
            client.patch(
                path, headers=headers, json={"title": "别人的对话"}
            ).status_code
            == expected
        )
        assert client.delete(path, headers=headers).status_code == expected
    for invalid in ("", "   ", "长" * 65):
        assert (
            client.patch(path, headers=ALICE, json={"title": invalid}).status_code
            == 422
        )
    assert (
        client.patch(path, headers=ALICE, json={"title": "  成都五日游  "}).json()[
            "title"
        ]
        == "成都五日游"
    )
    rid = Runs().submit("alice", cid, {"intent": "chat"}, "首条消息不应该覆盖标题")
    rows = client.get("/api/conversations", headers=ALICE).json()
    assert next(row for row in rows if row["id"] == cid)["title"] == "成都五日游"
    assert cid not in [
        row["id"] for row in client.get("/api/conversations", headers=BOB).json()
    ]
    with sessions()() as s:
        assert s.get(Conversation, cid).title == "成都五日游"
        assert s.get(Run, rid).conversation == cid


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING", "WAITING"])
def test_delete_requires_finishing_or_stopping_active_operations(db_env, status):
    client = TestClient(app)
    cid = create(client)
    rid = Runs().submit("alice", cid, {"intent": "chat"}, "处理中的消息")
    with sessions().begin() as s:
        s.get(Run, rid).status = status
    assert client.delete(f"/api/conversations/{cid}", headers=ALICE).status_code == 409
    with sessions()() as s:
        assert s.get(Conversation, cid).deleted == 0
        assert s.get(Run, rid).status == status
    stopped = client.post(f"/api/runs/{rid}/cancel", headers=ALICE).json()
    if status == "RUNNING":
        assert stopped["status"] == "RUNNING"
        assert (
            client.delete(f"/api/conversations/{cid}", headers=ALICE).status_code == 409
        )
        with sessions().begin() as s:
            s.get(Run, rid).status = "CANCELLED"
    assert client.delete(f"/api/conversations/{cid}", headers=ALICE).status_code == 200


def test_delete_hides_history_invalidates_cache_and_preserves_business(db_env):
    client, runs = TestClient(app), Runs()
    cid, other = create(client), create(client)
    rid = runs.submit("alice", cid, {"intent": "chat"}, "已完成的消息")
    with sessions().begin() as s:
        s.get(Run, rid).status = "DONE"
        s.add(Plan(id="saved-plan", owner="alice", options=[]))
        version = s.get(Conversation, cid).context_version
    cached = history("alice", cid)
    assert cached
    assert client.delete(f"/api/conversations/{cid}", headers=ALICE).status_code == 200
    write_snapshot(snapshot_key("alice", cid, version), cached)
    with pytest.raises(ValueError, match="会话不存在"):
        history("alice", cid)
    assert client.get(f"/api/conversations/{cid}", headers=ALICE).status_code == 404
    assert (
        client.patch(
            f"/api/conversations/{cid}", headers=ALICE, json={"title": "恢复"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/conversations/{cid}", headers=ALICE).status_code == 404
    assert (
        client.post(
            f"/api/conversations/{cid}/messages",
            headers=ALICE,
            json={"text": "继续", "request": {"intent": "chat"}},
        ).status_code
        == 409
    )
    with pytest.raises(ValueError, match="会话不存在"):
        runs.submit("alice", cid, {"intent": "chat"})
    assert client.get(f"/api/runs/{rid}", headers=ALICE).status_code == 409
    assert rid not in [r["id"] for r in client.get("/api/runs", headers=ALICE).json()]
    assert [
        c["id"] for c in client.get("/api/conversations", headers=ALICE).json()
    ] == [other]
    assert client.get("/api/plans", headers=ALICE).json()[0]["id"] == "saved-plan"
    with sessions()() as s:
        assert s.get(Run, rid) is not None
        assert s.get(Conversation, cid).history


def test_submit_and_delete_serialize_on_conversation(db_env):
    client = TestClient(app)
    for _ in range(5):
        cid = create(client)
        barrier = Barrier(2)

        def submit():
            barrier.wait()
            try:
                return Runs().submit("alice", cid, {"intent": "chat"}, "并发提交")
            except ValueError:
                return None

        def delete():
            barrier.wait()
            return client.delete(f"/api/conversations/{cid}", headers=ALICE).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            message, deletion = pool.submit(submit), pool.submit(delete)
            rid, status = message.result(), deletion.result()
        with sessions()() as s:
            row = s.get(Conversation, cid)
            active = s.scalar(
                select(Run.id).where(Run.conversation == cid, Run.status == "QUEUED")
            )
            assert not (row.deleted and active)
            assert (status == 200 and rid is None) or (
                status == 409 and rid is not None
            )
