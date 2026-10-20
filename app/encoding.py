import dashscope
from llama_index.embeddings.dashscope import DashScopeEmbedding
from llama_index.llms.openai_like import OpenAILike
from llama_index.postprocessor.dashscope_rerank import DashScopeRerank
from app.config import settings


def configure_dashscope():
    conf = settings()
    dashscope.base_http_api_url = conf.dashscope_base_url
    return conf


def embedding():
    conf = configure_dashscope()
    return DashScopeEmbedding(
        model_name=conf.embed_model,
        api_key=conf.dashscope_api_key,
        embed_batch_size=10,
    )


def reranker(top_n=5):
    conf = configure_dashscope()
    return DashScopeRerank(
        model=conf.rerank_model,
        top_n=top_n,
        api_key=conf.dashscope_api_key,
    )


def rag_llm():
    conf = settings()
    return OpenAILike(
        model=conf.model_name,
        api_base=conf.model_base_url,
        api_key=conf.dashscope_api_key,
        is_chat_model=True,
        is_function_calling_model=True,
        context_window=32768,
        max_tokens=4096,
        temperature=0,
        additional_kwargs={"extra_body": {"enable_thinking": False}},
        timeout=60,
        max_retries=1,
    )
