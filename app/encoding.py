import hashlib
import math
from collections import Counter
import jieba
from llama_index.core.embeddings import BaseEmbedding
import asyncio
import httpx
from pydantic import Field
from app.config import settings


def terms(text):
    return [t.lower() for t in jieba.lcut(text) if t.strip()]


def sparse_batch(texts):
    indices, values = [], []
    for text in texts:
        counts = Counter(
            int.from_bytes(hashlib.sha256(t.encode()).digest()[:4], "big")
            for t in terms(text)
        )
        keys = sorted(counts)
        indices.append(keys)
        values.append([1 + math.log(counts[k]) for k in keys])
    return indices, values


class FixtureEmbedding(BaseEmbedding):
    model_name: str = "fixture-hash-v1"

    def _get_text_embedding(self, text):
        vec = [0.0] * 32
        for t in terms(text):
            vec[
                int.from_bytes(hashlib.sha256(t.encode()).digest()[:4], "big") % 32
            ] += 1
        norm = math.sqrt(sum(v * v for v in vec)) or 1
        return [v / norm for v in vec]

    def _get_query_embedding(self, query):
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query):
        return self._get_query_embedding(query)


class DashScopeEmbedding(BaseEmbedding):
    model_name: str = "text-embedding-v3"
    api_key: str = Field(repr=False, exclude=True)
    base_url: str
    dimensions: int = 1024

    def _call(self, texts):
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(
                self.base_url.rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model_name,
                    "input": texts,
                    "dimensions": self.dimensions,
                    "encoding_format": "float",
                },
            )
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            vectors = [row["embedding"] for row in rows]
            if len(vectors) != len(texts) or any(
                len(v) != self.dimensions for v in vectors
            ):
                raise ValueError("嵌入返回数量或维度不符合配置")
            return vectors

    def _get_text_embedding(self, text):
        return self._call([text])[0]

    def _get_text_embeddings(self, texts):
        return self._call(texts)

    def _get_query_embedding(self, query):
        return self._get_text_embedding(query)

    async def _aget_query_embedding(self, query):
        return await asyncio.to_thread(self._get_query_embedding, query)


def embedding():
    conf = settings()
    if conf.embed_mode == "fixture":
        return FixtureEmbedding()
    if conf.embed_mode != "live" or not conf.model_api_key:
        raise ValueError("live embedding 需要 API key")
    return DashScopeEmbedding(
        model_name=conf.embed_model,
        dimensions=conf.embed_dim,
        api_key=conf.model_api_key,
        base_url=conf.model_base_url,
        embed_batch_size=10,
    )


def rrf(dense, sparse, alpha=0.5, top_k=20):
    from llama_index.core.vector_stores.types import VectorStoreQueryResult

    nodes = {}
    scores = {}
    for result in (dense, sparse):
        for rank, node in enumerate(result.nodes or [], 1):
            nodes[node.node_id] = node
            scores[node.node_id] = scores.get(node.node_id, 0) + 1 / (60 + rank)
    ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return VectorStoreQueryResult(
        nodes=[nodes[i] for i in ids], similarities=[scores[i] for i in ids], ids=ids
    )