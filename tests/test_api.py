from fastapi.testclient import TestClient
from app.api import app
from app.auth import token


def test_ownership_and_admin(env):
    client = TestClient(app)
    alice = {"Authorization": "Bearer " + token("alice")}
    bob = {"Authorization": "Bearer " + token("bob")}
    assert (
        client.post(
            "/api/login", json={"name": "alice", "password": "tutorial123"}
        ).status_code
        == 200
    )
    cid = client.post("/api/conversations", headers=alice, json={}).json()["id"]
    response = client.post(
        f"/api/conversations/{cid}/messages",
        headers=alice,
        json={"text": "查询政策", "request": {"intent": "policy"}},
    )
    rid = response.json()["run_id"]
    assert client.get(f"/api/runs/{rid}", headers=bob).status_code == 409
    assert client.get("/api/knowledge/revisions", headers=alice).status_code == 403
    assert (
        client.get(
            "/api/knowledge/revisions",
            headers={"Authorization": "Bearer " + token("admin")},
        ).status_code
        == 200
    )
