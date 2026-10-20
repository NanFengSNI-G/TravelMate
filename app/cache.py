import hashlib
import json
import logging
from functools import lru_cache
from redis import Redis
from redis.exceptions import RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry
from app.config import settings

log = logging.getLogger(__name__)


@lru_cache
def redis_client():
    return Redis.from_url(
        settings().redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        retry=Retry(NoBackoff(), 0),
    )


def conversation_prefix(owner, conversation):
    identity = hashlib.sha256(f"{owner}\0{conversation}".encode()).hexdigest()
    return f"travelmate:conversation:v1:{identity}:"


def snapshot_key(owner, conversation, version, before_run=None):
    boundary = hashlib.sha256((before_run or "latest").encode()).hexdigest()[:16]
    return f"{conversation_prefix(owner, conversation)}{version}:{boundary}"


def read_snapshot(key):
    try:
        raw = redis_client().get(key)
        if raw is not None:
            value = json.loads(raw)
            if isinstance(value, list) and all(
                isinstance(item, dict) for item in value
            ):
                return value
    except (RedisError, ValueError, TypeError):
        log.warning("Redis 会话缓存不可用或内容损坏，本次从 MySQL 读取")
    return None


def write_snapshot(key, entries):
    try:
        redis_client().set(
            key,
            json.dumps(entries, ensure_ascii=False),
            ex=settings().conversation_cache_ttl_seconds,
        )
    except RedisError:
        log.warning("Redis 会话缓存写入失败，MySQL 会话记录保持有效")


def clear_conversation(owner, conversation):
    try:
        client = redis_client()
        for key in client.scan_iter(
            match=conversation_prefix(owner, conversation) + "*", count=100
        ):
            client.unlink(key)
    except RedisError:
        log.warning("Redis 会话缓存清理失败，键将在 TTL 后过期")
