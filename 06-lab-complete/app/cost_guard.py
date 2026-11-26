from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

def _today_key() -> str:
    # Sang ngày mới (UTC) → key mới → tự "reset" budget, không cần cron job
    return f"cost:daily:{datetime.now(timezone.utc):%Y-%m-%d}"

def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    spent = float(r.get(_today_key()) or 0)
    if spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={"error": "Daily budget exceeded", "spent_usd": round(spent, 6),
                    "budget_usd": settings.daily_budget_usd, "resets": "00:00 UTC"},
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    key = _today_key()
    pipe = r.pipeline()
    pipe.incrbyfloat(key, cost)          # nguyên tử: nhiều worker cộng cùng lúc không bị mất
    pipe.expire(key, 2 * 24 * 3600)      # key cũ tự xoá sau 2 ngày
    pipe.execute()
    return cost
