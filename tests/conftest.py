import uuid
import asyncio
import pytest
from app.config import settings
from app.db import engine, sessions
from app.models import Base
from app.seed import seed
from app.knowledge import Knowledge, load_samples
from qdrant_client import QdrantClient


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "artifacts"))
    settings.cache_clear()
    engine.cache_clear()
    sessions.cache_clear()
    prefix = "verify_" + uuid.uuid4().hex[:12] + "_"
    tables = list(Base.metadata.sorted_tables)
    names = {table: table.name for table in tables}
    for table in tables:
        table.name = prefix + names[table]
    try:
        seed()
        yield prefix
    finally:
        from sqlalchemy import select, text, bindparam
        from app.models import Run, Conversation
        from app.cache import clear_conversation

        with sessions()() as session:
            ids = list(session.scalars(select(Run.id)))
            conversations = list(
                session.execute(select(Conversation.owner, Conversation.id))
            )
        for owner, cid in conversations:
            clear_conversation(owner, cid)
        if ids:
            ids += [rid + "-recovery" for rid in list(ids)]
            with engine().begin() as connection:
                for name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    exists = connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=:name"
                        ),
                        {"name": name},
                    )
                    if exists:
                        connection.execute(
                            text(
                                f"DELETE FROM {name} WHERE thread_id IN :ids"
                            ).bindparams(bindparam("ids", expanding=True)),
                            {"ids": ids},
                        )
        assert all(table.name == prefix + names[table] for table in tables)
        Base.metadata.drop_all(engine())
        engine().dispose()
        for table in tables:
            table.name = names[table]
        settings.cache_clear()
        engine.cache_clear()
        sessions.cache_clear()


@pytest.fixture
def env(db_env):
    settings().dashscope_api_key
    client = QdrantClient(url=settings().qdrant_url)
    k = Knowledge(client=client, collection=db_env + "policies")
    try:
        load_samples(k, all_destinations=False)
        yield k
    finally:
        if client.collection_exists(k.collection):
            client.delete_collection(k.collection)
        client.close()
        asyncio.run(k.aclient.close())


@pytest.fixture
def saver():
    from app.checkpoints import MySQLCheckpointSaver

    with MySQLCheckpointSaver.from_conn_string(settings().checkpoint_url) as checkpoint:
        checkpoint.setup()
        yield checkpoint


def pytest_collection_modifyitems(items):
    for item in items:
        if "env" in item.fixturenames:
            item.add_marker(pytest.mark.live)
        if any(name in item.fixturenames for name in ("env", "db_env", "saver")):
            item.add_marker(pytest.mark.integration)
        if item.name == "test_native_summarization_runs_in_agent_loop":
            item.add_marker(pytest.mark.live)
