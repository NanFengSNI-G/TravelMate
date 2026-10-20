from datetime import date, timedelta
import pytest
from sqlalchemy import select
from app.domain import Domain
from app.contracts import Request
from app.db import sessions
from app.models import Inventory, Resource


def req(intent="book", ids=None, order=None):
    start = date.today() + timedelta(days=30)
    return Request(
        intent=intent,
        start=start,
        end=start + timedelta(days=3),
        resource_ids=ids or ["flight-0", "hotel-0"],
        order_id=order,
    )


def test_booking_idempotence_cancel_isolation(env):
    d = Domain(env)
    p = d.proposal("alice", req())
    with pytest.raises(ValueError):
        d.execute("alice", p["id"])
    d.decide("alice", p["id"], 1, "approve")
    first = d.execute("alice", p["id"])
    second = d.execute("alice", p["id"])
    assert first == second and len(d.orders("alice")) == 2
    oid = first[0]["order"]
    with pytest.raises(ValueError):
        d.order("bob", oid)
    cancel = d.proposal("alice", req("cancel", order=oid))
    d.decide("alice", cancel["id"], 1, "approve")
    assert d.execute("alice", cancel["id"])[0]["fee"] == 10000
    assert d.order("alice", oid).status == "CANCELLED"


def test_partial_and_price_change(env):
    d = Domain(env)
    p = d.proposal("alice", req())
    d.decide("alice", p["id"], 1, "approve")
    with sessions().begin() as s:
        stocks = s.scalars(
            select(Inventory).where(Inventory.resource == "hotel-0")
        ).all()
        for row in stocks:
            row.available = 0
    results = d.execute("alice", p["id"])
    assert [r["status"] for r in results] == ["SUCCESS", "FAILED"]
    assert len(d.orders("alice")) == 1
    p2 = d.proposal("bob", req(ids=["flight-0"]))
    d.decide("bob", p2["id"], 1, "approve")
    with sessions().begin() as s:
        s.get(Resource, "flight-0").version += 1
    assert d.execute("bob", p2["id"])[0]["status"] == "FAILED"


def test_change_same_kind_and_policy_revoke(env):
    d = Domain(env)
    p = d.proposal("alice", req(ids=["flight-0"]))
    d.decide("alice", p["id"], 1, "approve")
    oid = d.execute("alice", p["id"])[0]["order"]
    changed = req("change", ids=["flight-1"], order=oid)
    changed.start += timedelta(days=1)
    changed.end += timedelta(days=1)
    update = d.proposal("alice", changed)
    d.decide("alice", update["id"], 1, "approve")
    assert d.execute("alice", update["id"])[0]["status"] == "SUCCESS"
    cancel = d.proposal("alice", req("cancel", order=oid))
    d.decide("alice", cancel["id"], 1, "approve")
    env.revoke(d.order("alice", oid).revision)
    assert d.execute("alice", cancel["id"])[0]["status"] == "FAILED"


@pytest.mark.integration
def test_mysql_inventory_race(env):
    from concurrent.futures import ThreadPoolExecutor
    from app.db import engine

    if engine().dialect.name != "mysql":
        pytest.skip("库存竞争需真实 MySQL 行锁")
    d = Domain(env)
    r = req(ids=["flight-0"])
    r.people = 6
    proposals = [d.proposal(owner, r) for owner in ("alice", "bob")]
    for owner, p in zip(("alice", "bob"), proposals):
        d.decide(owner, p["id"], 1, "approve")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(d.execute, owner, p["id"])
            for owner, p in zip(("alice", "bob"), proposals)
        ]
        results = [f.result() for f in futures]
    assert sorted(x[0]["status"] for x in results) == ["FAILED", "SUCCESS"]
    with sessions()() as s:
        assert s.get(Inventory, "flight-0").available == 0
