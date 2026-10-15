import sys
import importlib.metadata
import httpx
from sqlalchemy import text
from app.db import engine
from app.config import settings

assert sys.version_info[:2] == (3, 12), "本教程固定 Python 3.12"
print("Python:", sys.version.split()[0])
for p in [
    "langchain",
    "langgraph",
    "deepagents",
    "llama-index-core",
    "qdrant-client",
    "langgraph-checkpoint-mysql",
]:
    print(p, importlib.metadata.version(p))
with engine().connect() as c:
    print("MySQL:", c.execute(text("SELECT VERSION()")).scalar())
with httpx.Client(trust_env=False) as c:
    resp = c.get(settings().qdrant_url + "/collections")
    resp.raise_for_status()
    print("Qdrant:", resp.json()["status"])
