import json
from datetime import date
from pathlib import Path
from app.contracts import Query
from app.db import sessions
from app.models import Revision
from sqlalchemy import select


def test_applicability_and_parent(env):
    ev = env.retrieve(
        Query(
            question="取消费",
            supplier="演示酒店",
            product="standard",
            applicable_date=date.today(),
        )
    )
    assert ev.status == "SUPPORTED" and any("50 元" in e.text for e in ev.evidence)
    assert all(e.revision_id in ev.snapshot for e in ev.evidence)
    other = env.retrieve(
        Query(
            question="取消费",
            supplier="演示酒店",
            product="flexible",
            applicable_date=date.today(),
        )
    )
    assert any("0 元" in e.text for e in other.evidence)
    missing = env.retrieve(
        Query(
            question="取消",
            supplier="不存在",
            product="standard",
            applicable_date=date.today(),
        )
    )
    assert missing.status == "INSUFFICIENT"


def test_idempotent_ingest_and_revoke(env):
    meta = json.loads(Path("data/policies.json").read_text())[0]
    file = meta.pop("file")
    result = env.import_document(Path("data") / file, meta)
    assert result["cached"]
    env.revoke(result["revision"])
    q = Query(
        question="取消",
        supplier=meta["supplier"],
        product=meta["product"],
        applicable_date=date.today(),
        revision_id=result["revision"],
    )
    assert env.retrieve(q).status == "INSUFFICIENT"


def test_historical_revision(env, tmp_path):
    with sessions()() as s:
        old = s.scalar(select(Revision).where(Revision.document == "hotel-standard"))
        old_id = old.id
    meta = {
        "document": "hotel-standard",
        "supplier": "演示酒店",
        "product": "standard",
        "valid_from": "2031-01-01",
        "valid_to": "2099-12-31",
        "rules": {"cancel_fee_cents": 6000},
    }
    path = tmp_path / "new.md"
    path.write_text("# 演示新条款\n\n## 取消\n标准房取消费 60 元。")
    result = env.import_document(path, meta)
    env.publish(result["revision"])
    historical = env.retrieve(
        Query(
            question="取消",
            supplier="演示酒店",
            product="standard",
            applicable_date=date.today(),
            revision_id=old_id,
        )
    )
    assert historical.snapshot == [old_id] and any(
        "50 元" in e.text for e in historical.evidence
    )
    future = env.retrieve(
        Query(
            question="取消",
            supplier="演示酒店",
            product="standard",
            applicable_date=date(2032, 1, 1),
        )
    )
    assert future.snapshot == [result["revision"]]
    env.rollback(old_id)
    restored = env.retrieve(
        Query(
            question="取消",
            supplier="演示酒店",
            product="standard",
            applicable_date=date(2032, 1, 1),
        )
    )
    assert restored.snapshot == [old_id]


def test_reindex_preserves_published_revision_and_then_reuses_index(env):
    meta = json.loads(Path("data/policies.json").read_text())[0]
    path = Path("data") / meta.pop("file")
    first = env.import_document(path, meta)
    assert first["cached"] and first["status"] == "PUBLISHED"
    (env.root / first["revision"] / "index.json").unlink()
    rebuilt = env.import_document(path, meta)
    assert rebuilt["revision"] == first["revision"]
    assert rebuilt["status"] == "PUBLISHED" and not rebuilt["cached"]
    env.publish(rebuilt["revision"])
    assert env.import_document(path, meta)["cached"]


def test_changed_policy_with_same_start_date_is_still_rejected(env, tmp_path):
    import pytest

    meta = json.loads(Path("data/policies.json").read_text())[0]
    meta.pop("file")
    path = tmp_path / "changed-airline.md"
    path.write_text("# 航班条款\n取消费变为 200 元。")
    meta["rules"]["cancel_fee_cents"] = 20000
    changed = env.import_document(path, meta)
    with pytest.raises(ValueError, match="只能向后发布"):
        env.publish(changed["revision"])
