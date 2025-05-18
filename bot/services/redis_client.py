import redis.asyncio as redis
from bot.config import settings

class RedisClient:
    _client: redis.Redis | None = None

    @classmethod
    def get_client(cls) -> redis.Redis:
        if cls._client is None:
            cls._client = redis.from_url(
                settings.redis_url,
                encoding='utf-8',
                decode_responses=True
            )
        return cls._client