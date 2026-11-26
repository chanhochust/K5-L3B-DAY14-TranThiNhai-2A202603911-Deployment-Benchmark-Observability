import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=settings.log_level, handlers=[_handler], force=True)
logger = logging.getLogger("agent")


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": {"event": event, **fields}})


START_TIME = time.time()
VERSION = "1.0.0"


# ── Graceful shutdown (tiêu chí 11) ──
# uvicorn bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong,
# rồi chạy phần sau `yield` của lifespan → dọn dẹp → process thoát với exit code 0.
@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", environment=settings.environment, version=VERSION,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              daily_budget_usd=settings.daily_budget_usd)
    yield
    log_event("shutdown", uptime_seconds=round(time.time() - START_TIME, 1))
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    log_event("request", method=request.method, path=request.url.path,
              status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response


# ── Xử lý lỗi: trả mã rõ ràng, không lộ stack trace ra client ──
@app.exception_handler(redis.RedisError)
async def redis_error_handler(request: Request, exc: redis.RedisError):
    log_event("redis_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", exc_info=exc,
                 extra={"fields": {"event": "unhandled_error", "path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)


# ── Liveness (tiêu chí 4): luôn 200 khi process còn chạy, KHÔNG phụ thuộc Redis ──
@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION, "environment": settings.environment,
            "uptime_seconds": round(time.time() - START_TIME, 1)}


# ── Readiness (tiêu chí 5): 503 khi không kết nối được Redis ──
@app.get("/ready")
def ready():
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "redis": "unreachable"})
    return {"ready": True, "redis": "ok"}


# `def` (không phải async def): FastAPI chạy trong threadpool, nên lệnh Redis / LLM
# chặn đồng bộ không khoá event loop (bài học từ Part 5).
@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)                 # 429
    check_budget()                            # 402
    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question) // 4)    # ước lượng ~4 ký tự / token
    output_tokens = max(1, len(answer) // 4)
    cost = record_cost(input_tokens, output_tokens)
    log_event("ask", user_id=body.user_id, question_chars=len(body.question),
              input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=round(cost, 8))
    return {
        "question": body.question,
        "answer": answer,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": round(cost, 8)},
    }
