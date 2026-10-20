import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, SecretStr, field_validator
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
    redis_url: SecretStr = Field(default="redis://127.0.0.1:6379/0", repr=False)
    conversation_cache_ttl_seconds: int = Field(default=1800, ge=1, le=86400)
    auth_secret: str = "replace-with-a-random-secret-at-least-32-characters"
    dashscope_api_host: str = Field(
        default="https://dashscope.aliyuncs.com",
        validation_alias="TRAVELMATE_DASHSCOPE_API_HOST",
    )
    model_name: Literal["qwen3.7-flash"] = Field(
        default="qwen3.7-flash", validation_alias="TRAVELMATE_CHAT_MODEL"
    )
    embed_model: Literal["qwen3.7-text-embedding"] = Field(
        default="qwen3.7-text-embedding", validation_alias="TRAVELMATE_EMBED_MODEL"
    )
    embed_dim: Literal[1024] = 1024
    rerank_model: Literal["qwen3.7-text-rerank"] = Field(
        default="qwen3.7-text-rerank", validation_alias="TRAVELMATE_RERANK_MODEL"
    )
    context_max_tokens: int = 6000
    worker_concurrency: int = Field(default=2, ge=1, le=8)
    artifact_dir: Path = Path("artifacts")

    @field_validator("dashscope_api_host")
    @classmethod
    def normalize_host(cls, value):
        value = value.strip().rstrip("/")
        if "://" not in value:
            value = "https://" + value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("API Host 必须是 HTTPS 域名，不包含 /api/v1 等路径")
        return value

    @property
    def model_base_url(self):
        return self.dashscope_api_host + "/compatible-mode/v1"

    @property
    def dashscope_base_url(self):
        return self.dashscope_api_host + "/api/v1"

    @property
    def dashscope_api_key(self):
        key = os.environ.get("TRAVELMATE_DASHSCOPE_API_KEY", "").strip()
        if not key:
            raise ValueError(
                "未设置主机环境变量 TRAVELMATE_DASHSCOPE_API_KEY；"
                "请在启动 API/worker 的终端设置，不要写入 .env 或代码"
            )
        return key


@lru_cache
def settings():
    return Settings()
