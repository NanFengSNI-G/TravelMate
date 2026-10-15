import pytest
from datetime import date, timedelta
from app.contracts import Task, validate_tasks, merge_results, Request
from app.auth import password_hash, password_ok, token, decode


def test_dag_and_merge():
    assert validate_tasks(
        [Task(id="f", role="flight"), Task(id="h", role="hotel", depends_on=["f"])]
    )
    with pytest.raises(ValueError):
        validate_tasks([Task(id="f", role="flight", depends_on=["h"])])
    assert merge_results({"f": 1}, {"h": 2}) == {"f": 1, "h": 2}
    with pytest.raises(ValueError):
        merge_results({"f": 1}, {"f": 2})


def test_password_and_token():
    stored = password_hash("secret")
    assert password_ok("secret", stored) and not password_ok("other", stored)
    assert decode(token("alice")) == "alice"
    with pytest.raises(ValueError):
        decode(token("alice") + "tampered")


def test_date_validation():
    with pytest.raises(ValueError):
        Request(intent="plan", start=date.today(), end=date.today())


def test_native_dashscope_embedding(monkeypatch):
    from types import SimpleNamespace
    import dashscope
    from app.encoding import embedding
    from llama_index.embeddings.dashscope import DashScopeEmbedding

    def call(**kwargs):
        assert kwargs["model"] == "text-embedding-v3"
        texts = kwargs["input"]
        if isinstance(texts, str):
            texts = [texts]
        return SimpleNamespace(
            status_code=200,
            output={
                "embeddings": [
                    {"text_index": i, "embedding": [1.0] * 1024}
                    for i, _ in enumerate(texts)
                ]
            },
        )

    monkeypatch.setattr(dashscope.TextEmbedding, "call", call)
    monkeypatch.setattr(
        "app.encoding.settings",
        lambda: SimpleNamespace(
            embed_mode="live",
            embed_model="text-embedding-v3",
            embed_dim=1024,
            model_api_key="test-only",
        ),
    )
    embed = embedding()
    assert isinstance(embed, DashScopeEmbedding)
    assert len(embed.get_text_embedding("酒店取消")) == 1024
    assert len(embed.get_query_embedding("取消费")) == 1024
