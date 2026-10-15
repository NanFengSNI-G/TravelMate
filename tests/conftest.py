import uuid
import asyncio
import pytest
from app.config import settings
from app.db import engine, sessions
from app.models import Base
from app.seed import seed
from llama_index.core.embeddings import MockEmbedding
from app.knowledge import Knowledge, load_samples
from qdrant_client import QdrantClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    # 复用开发服务和数据库；只在当前 pytest 进程改动映射的表名。
    monkeypatch.setenv("MODEL_MODE", "fixture")
    monkeypatch.setenv("EMBED_MODE", "fixture")
    monkeypatch.setenv("RERANK_MODE", "none")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "artifacts"))
    settings.cache_clear()
    engine.cache_clear()
    sessions.cache_clear()
    prefix = "verify_" + uuid.uuid4().hex[:12] + "_"
    tables = list(Base.metadata.sorted_tables)
    names = {table: table.name for table in tables}
    for table in tables:
        table.name = prefix + names[table]
    client = QdrantClient(url=settings().qdrant_url)
    k = Knowledge(
        client=client, embed=MockEmbedding(embed_dim=32), collection=prefix + "policies"
    )
    try:
        seed()
        load_samples(k)
        yield k
    finally:
        # 只删除本次创建的验证表；绝不能清空开发业务表。
        assert all(table.name == prefix + names[table] for table in tables)
        Base.metadata.drop_all(engine())
        if client.collection_exists(k.collection):
            client.delete_collection(k.collection)
        client.close()
        asyncio.run(k.aclient.close())
        engine().dispose()
        for table in tables:
            table.name = names[table]
        settings.cache_clear()
        engine.cache_clear()
        sessions.cache_clear()
