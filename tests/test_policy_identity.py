import hashlib
import json
from types import SimpleNamespace
import pytest
from app.contracts import PolicyMetadata
from app.knowledge import policy_digests, choose_policy_revision


def metadata():
    return PolicyMetadata.model_validate(
        {
            "document": "airline",
            "supplier": "演示航空",
            "product": "economy",
            "valid_from": "2020-01-01",
            "valid_to": "2099-12-31",
            "rules": {"cancel_fee_cents": 10000},
        }
    ).model_dump(mode="json")


def test_old_and_new_index_digests_resolve_to_the_published_policy():
    text, meta = "# 航班条款\n取消费 100 元。", metadata()
    canonical, compatible = policy_digests(text, meta)
    base = text + json.dumps(meta, sort_keys=True)
    old = hashlib.sha256(
        (base + "native-v2:unknown:hierarchy-256-64").encode()
    ).hexdigest()
    current = hashlib.sha256(
        (base + "native-v3:qwen3.7-text-embedding:hierarchy-256-64").encode()
    ).hexdigest()
    assert {canonical, old, current} <= compatible
    published = SimpleNamespace(id="original-policy", status="PUBLISHED", digest=old)
    unapproved = SimpleNamespace(
        id="new-index-policy", status="VERIFIED", digest=current
    )
    assert choose_policy_revision([unapproved, published], canonical) is published


@pytest.mark.parametrize("change", ["text", "fee", "date"])
def test_real_policy_changes_get_a_different_identity(change):
    text, meta = "# 航班条款\n取消费 100 元。", metadata()
    before, _ = policy_digests(text, meta)
    if change == "text":
        text += "\n新增改签限制。"
    elif change == "fee":
        meta["rules"]["cancel_fee_cents"] = 20000
    else:
        meta["valid_from"] = "2030-01-01"
    after, _ = policy_digests(text, meta)
    assert before != after


def test_reindex_does_not_implicitly_reactivate_a_revoked_policy():
    revoked = SimpleNamespace(id="old", status="REVOKED", digest="legacy")
    unapproved = SimpleNamespace(id="new", status="VERIFIED", digest="canonical")
    assert choose_policy_revision([unapproved, revoked], "canonical") is revoked


def test_multiple_published_copies_require_manual_review():
    rows = [
        SimpleNamespace(id=str(i), status="PUBLISHED", digest="same") for i in range(2)
    ]
    with pytest.raises(ValueError, match="多个已发布"):
        choose_policy_revision(rows, "canonical")
