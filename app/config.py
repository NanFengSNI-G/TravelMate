from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = (
        "mysql+pymysql://travelmate:travelmate_local@127.0.0.1:13316/travelmate"
    )
    checkpoint_url: str = (
        "mysql://travelmate:travelmate_local@127.0.0.1:13316/travelmate"
    )
    qdrant_url: str = "http://127.0.0.1:16333"
    auth_secret: str = "replace-with-a-random-secret-at-least-32-characters"
    model_mode: str = "fixture"
    embed_mode: str = "fixture"
    model_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_name: str = "qwen-plus"
    model_api_key: str = ""
    embed_model: str = "text-embedding-v3"
    embed_dim: int = 1024
    rerank_mode: str = "none"
    rerank_model: str = "gte-rerank-v2"
    context_max_tokens: int = 6000
    artifact_dir: Path = Path("artifacts")


@lru_cache
def settings():
    return Settings()
