"""模型选择只负责组装官方集成；不自行实现嵌入算法或 HTTP 协议。"""

from llama_index.core.embeddings import MockEmbedding
from llama_index.core.llms import MockLLM
from llama_index.embeddings.dashscope import DashScopeEmbedding
from llama_index.llms.dashscope import DashScope
from app.config import settings


def embedding():
    conf = settings()
    if conf.embed_mode == "fixture":
        # 框架自带常量向量，仅用于机制测试，不能用于语义质量评测。
        return MockEmbedding(embed_dim=32)
    if conf.embed_mode != "live" or not conf.model_api_key:
        raise ValueError("live embedding 需要 API key")
    # 此版本原生集成不提供任意 dimensions/base_url 参数。
    # 固定选择 v3 的默认 1024 维；不能把未转发的参数假装已经生效。
    if conf.embed_model != "text-embedding-v3" or conf.embed_dim != 1024:
        raise ValueError(
            "本教程原生 DashScope 集成固定使用 text-embedding-v3 / 1024 维"
        )
    return DashScopeEmbedding(
        model_name=conf.embed_model,
        api_key=conf.model_api_key,
        embed_batch_size=10,
    )


def rag_llm():
    conf = settings()
    if conf.model_mode == "fixture":
        return MockLLM(max_tokens=32)
    if conf.model_mode != "live" or not conf.model_api_key:
        raise ValueError("live RAG 需要 API key")
    return DashScope(model_name=conf.model_name, api_key=conf.model_api_key)
