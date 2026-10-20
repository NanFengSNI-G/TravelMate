import pytest
from datetime import date
from app.contracts import merge_results, Request
from app.auth import password_hash, password_ok, token, decode


def test_parallel_merge():
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


def test_real_model_configuration():
    from app.config import Settings

    conf = Settings(_env_file=None)
    assert conf.model_name == "qwen3.7-flash"
    assert conf.embed_model == "qwen3.7-text-embedding" and conf.embed_dim == 1024
    assert conf.rerank_model == "qwen3.7-text-rerank"
    assert "dashscope_api_key" not in conf.model_dump()
    assert not hasattr(conf, "model_mode") and not hasattr(conf, "embed_mode")


def test_api_host_derives_both_protocol_urls():
    from app.config import Settings

    conf = Settings(
        _env_file=None,
        TRAVELMATE_DASHSCOPE_API_HOST="llm-example.cn-beijing.maas.aliyuncs.com",
    )
    assert (
        conf.model_base_url
        == "https://llm-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    assert (
        conf.dashscope_base_url
        == "https://llm-example.cn-beijing.maas.aliyuncs.com/api/v1"
    )
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            TRAVELMATE_DASHSCOPE_API_HOST="https://dashscope.aliyuncs.com/api/v1",
        )


def test_key_must_come_from_host_environment(tmp_path, monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("TRAVELMATE_DASHSCOPE_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "TRAVELMATE_DASHSCOPE_API_KEY=file-only-value\nMODEL_API_KEY=legacy-value\n"
    )
    conf = Settings(_env_file=path)
    with pytest.raises(ValueError, match="TRAVELMATE_DASHSCOPE_API_KEY"):
        _ = conf.dashscope_api_key
    from app.agents import model
    from app.encoding import embedding, reranker, rag_llm

    for factory in (model, embedding, reranker, rag_llm):
        with pytest.raises(ValueError, match="TRAVELMATE_DASHSCOPE_API_KEY"):
            factory()


@pytest.mark.live
@pytest.mark.integration
def test_native_dashscope_embedding():
    from app.encoding import embedding
    from llama_index.embeddings.dashscope import DashScopeEmbedding

    embed = embedding()
    assert isinstance(embed, DashScopeEmbedding)
    document = embed.get_text_embedding("酒店取消费用为五十元。")
    query = embed.get_query_embedding("酒店取消多少钱？")
    assert len(document) == len(query) == 1024
