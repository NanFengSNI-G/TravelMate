import sys
import importlib.metadata
import httpx
from sqlalchemy import text
from app.db import engine
from app.config import settings
from app.cache import redis_client

assert sys.version_info[:2] == (3, 12), "项目需要 Python 3.12"
print("Python:", sys.version.split()[0])
for p in [
    "langchain",
    "langgraph",
    "deepagents",
    "llama-index-core",
    "qdrant-client",
    "langgraph-checkpoint-mysql",
    "redis",
]:
    print(p, importlib.metadata.version(p))
with engine().connect() as c:
    print("MySQL:", c.execute(text("SELECT VERSION()")).scalar())
with httpx.Client(trust_env=False) as c:
    resp = c.get(settings().qdrant_url + "/collections")
    resp.raise_for_status()
    print("Qdrant:", resp.json()["status"])

client = redis_client()
assert client.ping(), "Redis PING 失败"
print(
    "Redis:",
    client.info("server")["redis_version"],
    "会话缓存 TTL:",
    settings().conversation_cache_ttl_seconds,
    "秒",
)

conf = settings()
print("主模型:", conf.model_name)
print("向量模型:", conf.embed_model, "默认维度:", conf.embed_dim)
print("重排模型:", conf.rerank_model)
print("模型服务:", conf.dashscope_api_host)
try:
    conf.dashscope_api_key
except ValueError as exc:
    raise SystemExit(str(exc))
print("TRAVELMATE_DASHSCOPE_API_KEY: 已设置（不显示内容）")
print("三种模型的实际调用验证：python -m scripts.live_smoke")
