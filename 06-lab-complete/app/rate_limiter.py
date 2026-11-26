import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _redis_key(api_key: str) -> str:
    # Không lưu API key thật trong Redis — chỉ lưu hash
    return "ratelimit:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    now = time.time()
    rkey = _redis_key(key)

    # 1) Xoá request cũ hơn 60 giây  2) Đếm số request còn trong cửa sổ
    pipe = r.pipeline()
    pipe.zremrangebyscore(rkey, 0, now - WINDOW_SECONDS)
    pipe.zcard(rkey)
    _, count = pipe.execute()

    if count >= limit:
        oldest = r.zrange(rkey, 0, 0, withscores=True)
        retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit,
                    "window_seconds": WINDOW_SECONDS, "retry_after_seconds": retry_after},
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    # 3) Ghi nhận request này  4) Key tự hết hạn khi không còn dùng
    pipe = r.pipeline()
    pipe.zadd(rkey, {f"{now}-{uuid.uuid4().hex[:8]}": now})
    pipe.expire(rkey, WINDOW_SECONDS)
    pipe.execute()

