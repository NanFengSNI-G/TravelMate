from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import select, delete
from app.db import sessions, engine
from app.domain import Domain
from app.contracts import Request
from app.models import (
    User,
    Resource,
    Inventory,
    Revision,
    Quote,
    Proposal,
    Order,
    Operation,
    now,
)


@pytest.fixture
def booking_rows():
    assert engine().dialect.name == "mysql"
    prefix = "guard_" + uuid4().hex[:16]
    owner, other, rid, rev = [prefix + suffix for suffix in ("_u", "_v", "_r", "_rev")]
    slots = [rid + "-2026-11-14", rid + "-2026-11-15"]
    with sessions().begin() as s:
        s.add_all(
            [
                User(id=owner, name=owner, password="unused"),
                User(id=other, name=other, password="unused"),
            ]
        )
        s.add(
            Resource(
                id=rid,
                kind="hotel",
                name="重复预订校验记录",
                supplier=prefix,
                product="standard",
                price=30000,
                version=1,
                details={"destination": "上海", "max_people": 2},
            )
        )
        s.add(
            Revision(
                id=rev,
                document=prefix,
                supplier=prefix,
                product="standard",
                language="zh",
                valid_from="2020-01-01",
                valid_to="2099-12-31",
                original_valid_to="2099-12-31",
                status="PUBLISHED",
                digest=prefix,
                rules={"cancel_fee_cents": 0},
                source="transaction-guard",
            )
        )
        for slot in slots:
            s.add(Inventory(id=slot, resource=rid, day=slot[-10:], available=6))
    data = SimpleNamespace(
        prefix=prefix, owner=owner, other=other, rid=rid, rev=rev, slots=slots
    )
    try:
        yield data
    finally:
        with sessions().begin() as s:
            s.execute(delete(Order).where(Order.owner.in_([owner, other])))
            for cls in (
                Operation,
                Proposal,
                Quote,
                Order,
                Inventory,
                Revision,
                Resource,
                User,
            ):
                s.execute(delete(cls).where(cls.id.startswith(prefix)))


def proposal(data, suffix, slots=None):
    pid, qid = data.prefix + "_p" + suffix, data.prefix + "_q" + suffix
    with sessions().begin() as s:
        s.add(
            Quote(
                id=qid,
                owner=data.owner,
                resource=data.rid,
                resource_version=1,
                revision=data.rev,
                amount=60000,
                quantity=1,
                slots=slots or data.slots,
                expires=now() + 600,
            )
        )
        s.add(
            Proposal(
                id=pid,
                owner=data.owner,
                status="PENDING",
                actions=[{"kind": "book", "quote": qid}],
                evidence=[],
                expires=now() + 600,
            )
        )
    Domain(None).decide(data.owner, pid, 1, "approve")
    return pid


@pytest.mark.integration
def test_same_user_concurrent_proposals_cannot_create_duplicate_orders(booking_rows):
    d, data = Domain(None), booking_rows
    ids = [proposal(data, str(i)) for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pid: d.execute(data.owner, pid), ids))
    assert sorted(result[0]["status"] for result in results) == ["FAILED", "SUCCESS"]
    assert "重复预订" in next(
        r[0]["message"] for r in results if r[0]["status"] == "FAILED"
    )
    with sessions()() as s:
        orders = list(s.scalars(select(Order).where(Order.owner == data.owner)))
        assert len(orders) == 1
        assert all(s.get(Inventory, sid).available == 5 for sid in data.slots)
    successful_pid = next(
        pid for pid, result in zip(ids, results) if result[0]["status"] == "SUCCESS"
    )
    assert d.execute(data.owner, successful_pid)[0]["status"] == "SUCCESS"
    assert len(d.orders(data.owner)) == 1


@pytest.mark.integration
def test_overlap_cancelled_other_user_and_change_exclusion(booking_rows):
    data = booking_rows
    oid = data.prefix + "_existing"
    with sessions().begin() as s:
        s.add(
            Order(
                id=oid,
                owner=data.owner,
                resource=data.rid,
                revision=data.rev,
                amount=60000,
                quantity=1,
                slots=data.slots,
                status="CONFIRMED",
            )
        )
    with sessions()() as s:
        resource = s.get(Resource, data.rid)
        with pytest.raises(ValueError, match="重复预订"):
            Domain.ensure_not_booked(s, data.owner, resource, [data.slots[1]])
        Domain.ensure_not_booked(s, data.other, resource, data.slots)
        Domain.ensure_not_booked(s, data.owner, resource, [data.rid + "-2026-11-17"])
        Domain.ensure_not_booked(s, data.owner, resource, data.slots, exclude_order=oid)
    with pytest.raises(ValueError, match="重复预订"):
        Domain(None).make_quote(
            data.owner,
            data.rid,
            Request(intent="book", start=date(2026, 11, 14), end=date(2026, 11, 16)),
        )
    with sessions().begin() as s:
        s.get(Order, oid).status = "CANCELLED"
    with sessions()() as s:
        Domain.ensure_not_booked(s, data.owner, s.get(Resource, data.rid), data.slots)


@pytest.mark.integration
def test_pending_quote_lookup_is_owned_and_does_not_execute(booking_rows):
    data = booking_rows
    pid = proposal(data, "_lookup")
    with sessions().begin() as s:
        s.get(Proposal, pid).status = "PENDING"
    result = Domain(None).pending_quotes(data.owner)
    assert result[0]["actions"][0]["amount_cents"] == 60000
    assert result[0]["actions"][0]["name"] == "重复预订校验记录"
    assert not Domain(None).pending_quotes(data.other)
    assert not Domain(None).orders(data.owner)
    with sessions()() as s:
        assert s.get(Proposal, pid).status == "PENDING"
