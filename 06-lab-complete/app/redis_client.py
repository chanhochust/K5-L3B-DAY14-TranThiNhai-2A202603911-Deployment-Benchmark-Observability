import redis

from app.config import settings

r = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,   # Redis chết thì /ready trả 503 nhanh, không treo
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: ping được Redis → True, lỗi kết nối → False."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
