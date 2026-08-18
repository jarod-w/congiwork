"""Redis 客户端。

Consent 的运行时态以 Redis `consent:{user_id}` hash 为优先读取路径（P0-07 §4）。
Redis 不可用时授权检查必须仍能工作 —— 回落到 Postgres，而不是把产品停掉。
"""

from __future__ import annotations

import logging

from redis import Redis
from redis.exceptions import RedisError

from .config import Settings

logger = logging.getLogger("cogniwork.redis")


def open_redis(settings: Settings) -> Redis | None:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        client.ping()
    except RedisError:
        logger.warning("Redis unreachable; consent checks will fall back to Postgres")
        try:
            client.close()
        except RedisError:
            pass
        return None
    return client
