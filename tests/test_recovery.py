from datetime import timedelta
from app.domain import Domain
from app.recovery import Recovery
from app.agents import Agents
from tests.test_domain import req


def saved_plan(d, r):
    import uuid

    results = {role: Agents(d).specialist(role, r) for role in ("flight", "hotel")}
    draft = d.plan_draft("alice", r, results)
    proposal = d.pending("alice", "plan_create", draft, str(uuid.uuid4()))
    d.decide("alice", proposal["id"], 1, "approve")
    return d.execute("alice", proposal["id"])[0]["plan"]


def test_deepagents_actual_tools_and_artifacts(env, saver):
    d = Domain(env)
    r = req("plan")
    plan = saved_plan(d, r)
    r.intent = "repair"
    r.plan_id = plan["id"]
    r.start += timedelta(days=1)
    r.end += timedelta(days=1)
    import uuid

    run_id = str(uuid.uuid4())
    report = Recovery(d, saver).run("alice", run_id, r)
    assert len(report["options"]) == 2
    names = [c["name"] for m in report["trace"] for c in m["calls"]]
    assert names.count("task") >= 2 and "write_file" in names and "write_todos" in names
    assert "RepairReport" in names
    from app.config import settings

    assert (
        settings().artifact_dir / ".drafts" / "alice" / run_id / "repair_plan.json"
    ).exists()
    assert not (settings().artifact_dir / "alice" / run_id).exists()
    assert not d.orders("alice")


import pytest
from app.checkpoints import MySQLCheckpointSaver


@pytest.mark.integration
def test_deep_mysql_new_connection_resume(env):
    from app.config import settings

    url = settings().checkpoint_url
    d = Domain(env)
    r = req("plan")
    plan = saved_plan(d, r)
    r.intent = "repair"
    r.plan_id = plan["id"]
    r.start += timedelta(days=1)
    r.end += timedelta(days=1)
    import uuid

    rid = str(uuid.uuid4())
    with MySQLCheckpointSaver.from_conn_string(url) as saver:
        saver.setup()
        before = Recovery(d, saver).run("alice", rid, r)
    with MySQLCheckpointSaver.from_conn_string(url) as saver:
        after = Recovery(d, saver).run("alice", rid, r)
    assert before["options"] == after["options"]
    names = [c["name"] for m in after["trace"] for c in m["calls"]]
    assert names.count("task") >= 2
