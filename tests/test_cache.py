import pytest
from sqlalchemy import select, event
from app.cache import redis_client, snapshot_key, write_snapshot
from app.config import settings
from app.conversations import history
from app.db import sessions, engine
from app.models import Conversation
from app.runs import Runs
from tests.test_graph import conversation


@pytest.fixture
def cache_ready(db_env):
    client = redis_client()
    assert client.ping()
    yield client


def version(cid):
    with sessions()() as s:
        return s.scalar(
            select(Conversation.context_version).where(Conversation.id == cid)
        )


def test_cache_hit_and_result_version_invalidates_late_write(cache_ready):
    runs, cid = Runs(), conversation()
    rid = runs.submit("alice", cid, {"intent": "chat", "question": "请记住林舟"})
    queries = []

    def observe(connection, cursor, statement, parameters, context, many):
        queries.append(statement)

    event.listen(engine(), "before_cursor_execute", observe)
    try:
        prior = history("alice", cid)
        cold_queries = len(queries)
        old_key = snapshot_key("alice", cid, version(cid))
        assert cache_ready.exists(old_key) and 0 < cache_ready.ttl(old_key) <= 1800
        queries.clear()
        assert history("alice", cid) == prior
        assert 0 < len(queries) < cold_queries
    finally:
        event.remove(engine(), "before_cursor_execute", observe)
    run = runs.claim()
    runs.complete(rid, run.fence, "DONE", {"customer": {"answer": "记住了，林舟"}})
    write_snapshot(old_key, prior)
    current = history("alice", cid)
    assert current[0]["status"] == "DONE"
    assert current[0]["result"]["customer"]["answer"] == "记住了，林舟"
    assert snapshot_key("alice", cid, version(cid)) != old_key


def test_cache_miss_rebuild_and_user_conversation_boundary(cache_ready):
    cid, other = conversation(), conversation()
    assert history("alice", cid) == []
    key = snapshot_key("alice", cid, version(cid))
    assert cache_ready.exists(key)
    cache_ready.unlink(key)
    assert history("alice", cid) == [] and cache_ready.exists(key)
    with pytest.raises(ValueError, match="会话不存在"):
        history("bob", cid)
    assert snapshot_key("alice", cid, 0) != snapshot_key("bob", cid, 0)
    assert snapshot_key("alice", cid, 0) != snapshot_key("alice", other, 0)
    assert snapshot_key("alice", cid, 0) != snapshot_key("alice", cid, 0, "run-1")


def test_corrupt_snapshot_rebuilt_from_mysql(cache_ready):
    cid = conversation()
    key = snapshot_key("alice", cid, version(cid))
    cache_ready.set(key, "{damaged", ex=60)
    assert history("alice", cid) == []
    assert cache_ready.get(key) == "[]"


def test_redis_unreachable_reads_mysql(db_env, monkeypatch, caplog):
    cid = conversation()
    redis_client().close()
    redis_client.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
            settings.cache_clear()
            assert history("alice", cid) == []
            assert "从 MySQL 读取" in caplog.text
    finally:
        redis_client().close()
        redis_client.cache_clear()
        settings.cache_clear()
