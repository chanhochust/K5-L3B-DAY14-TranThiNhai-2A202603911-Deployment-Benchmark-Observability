# Deployment Information

## Public URL

https://agent-production-cdec363a.up.railway.app

## Platform

**Railway** — project `day14-agent`, environment `production`, region `iad` (US East).

| Service | Nguồn | Vai trò |
|---|---|---|
| `agent` | `06-lab-complete/` — build bằng `Dockerfile` theo `railway.toml` | FastAPI agent (uvicorn, 2 worker), healthcheck `GET /health` |
| `Redis` | Railway Redis database | Lưu state rate limit + cost guard; agent kết nối qua `REDIS_URL` |

Deploy bằng Railway CLI, chạy trong thư mục `06-lab-complete/`:

```bash
railway init --name day14-agent
railway add --database redis
railway add --service agent
railway service link agent
railway variable set AGENT_API_KEY --stdin --service agent      # đọc key từ stdin, không lộ trên terminal
railway variable set 'REDIS_URL=${{Redis.REDIS_URL}}' ENVIRONMENT=production \
    RATE_LIMIT_PER_MINUTE=10 DAILY_BUDGET_USD=1.0 LOG_LEVEL=INFO --service agent
railway up --service agent --ci
railway domain --service agent
```

## Test Commands

Đặt biến trước khi test (thay `YOUR_KEY` bằng API key được cấp):

```bash
BASE=https://agent-production-cdec363a.up.railway.app
AGENT_API_KEY=YOUR_KEY
```

### Health check (liveness)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Expected: 200   — body: {"status":"ok","version":"1.0.0","environment":"production",...}
```

### Readiness (agent kết nối được Redis)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Expected: 200   — body: {"ready":true,"redis":"ok"}
```

### Không có API key → 401

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'
# Expected: 401
```

### Có API key → 200

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Expected: 200
```

Xem nội dung trả lời:

```bash
curl -s -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"user_id":"test","question":"What is deployment?"}'
# {"question":"What is deployment?","answer":"...","usage":{"input_tokens":...,"output_tokens":...,"cost_usd":...}}
```

### Kết quả thực tế (2026-11-26)

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
401
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
200

$ python check_production_ready.py --static-only --public-url https://agent-production-cdec363a.up.railway.app
✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ App lắng nghe theo biến PORT do platform cấp
     ✅ Public URL: GET https://agent-production-cdec363a.up.railway.app/health → 200
```

## Environment Variables Set

Đặt trên Railway (service `agent` → Variables), **không ghi trong code hay repo**:

| Biến | Giá trị / nguồn |
|---|---|
| `AGENT_API_KEY` | Secret ngẫu nhiên 32 ký tự (`secrets.token_urlsafe(24)`), đặt bằng `--stdin` — không ghi ở đây |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` — tham chiếu tới service Redis, Railway tự điền URL nội bộ |
| `ENVIRONMENT` | `production` (bật fail fast: thiếu `AGENT_API_KEY` thì app không khởi động) |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | Railway tự cấp; app nghe theo `${PORT:-8000}` trong `CMD` của Dockerfile |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
