import os
from contextlib import nullcontext
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from app.checkpoints import TutorialMySQLSaver
from app.api import app
from app.domain import Domain
from app.graph import build_graph
from app.runs import Runs
from app.worker import process
from tests.test_domain import req


def test_full_user_journey(env):
    client = TestClient(app)
    runs = Runs()

    def login(name):
        response = client.post(
            "/api/login", json={"name": name, "password": "tutorial123"}
        )
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["token"]}

    alice = login("alice")
    admin = login("admin")
    cid = client.post("/api/conversations", headers=alice, json={}).json()["id"]
    from app.config import settings

    cp = settings().checkpoint_url
    with (
        TutorialMySQLSaver.from_conn_string(cp) if cp else nullcontext(InMemorySaver())
    ) as saver:
        if cp:
            saver.setup()
        graph = build_graph(Domain(env), saver)

        def submit(r):
            response = client.post(
                f"/api/conversations/{cid}/messages",
                headers=alice,
                json={"text": "教学案例", "request": r.model_dump(mode="json")},
            )
            assert response.status_code == 200, response.text
            rid = response.json()["run_id"]
            process(runs.claim(), graph, runs)
            return rid, client.get(f"/api/runs/{rid}", headers=alice).json()

        def confirm(rid, headers=alice):
            response = client.post(
                f"/api/runs/{rid}/approval",
                headers=headers,
                json={"decision": "approve", "version": 1},
            )
            assert response.status_code == 200
            process(runs.claim(), graph, runs)
            return client.get(f"/api/runs/{rid}", headers=headers).json()

        rid, result = submit(req("plan"))
        assert result["status"] == "WAITING"
        result = confirm(rid)
        assert (
            result["status"] == "DONE" and len(result["result"]["plan"]["options"]) == 2
        )
        chosen = result["result"]["plan"]["options"][0]
        request = req()
        request.resource_ids = chosen["resource_ids"]
        rid, result = submit(request)
        assert result["status"] == "WAITING"
        response = client.post(
            f"/api/runs/{rid}/approval",
            headers=alice,
            json={"decision": "approve", "version": 1},
        )
        assert response.status_code == 200
        process(runs.claim(), graph, runs)
        orders = client.get("/api/orders", headers=alice).json()
        assert len(orders) == 2
        events = client.get(f"/api/runs/{rid}/events", headers=alice)
        import json

        frames = [
            json.loads(line[6:])
            for line in events.text.splitlines()
            if line.startswith("data: ")
        ]
        assert "event: complete" in events.text and any(
            e.get("type") == "result" for e in frames
        )
        cancel = req("cancel", order=orders[0]["id"])
        rid, result = submit(cancel)
        client.post(
            f"/api/runs/{rid}/approval",
            headers=alice,
            json={"decision": "approve", "version": 1},
        )
        process(runs.claim(), graph, runs)
        assert any(
            o["status"] == "CANCELLED"
            for o in client.get("/api/orders", headers=alice).json()
        )
        rid, result = submit(req("support"))
        assert result["status"] == "WAITING"
        case = confirm(rid)["result"]["case_id"]
        claim = client.post(f"/api/cases/{case}/claim", headers=admin, json={})
        assert claim.status_code == 200
        process(runs.claim(), graph, runs)
        assert client.get("/api/cases", headers=alice).json()[0]["status"] == "OPEN"
        confirm(claim.json()["run_id"], admin)
        reply = client.post(
            f"/api/cases/{case}/reply",
            headers=admin,
            json={"text": "已说明演示取消费用。", "close": True},
        )
        assert reply.status_code == 200
        process(runs.claim(), graph, runs)
        assert not client.get("/api/cases", headers=alice).json()[0]["replies"]
        confirm(reply.json()["run_id"], admin)
        assert client.get("/api/cases", headers=alice).json()[0]["status"] == "CLOSED"
