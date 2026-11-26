# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

File: `01-localhost-vs-production/develop/app.py`

| # | Dòng | Anti-pattern | Hậu quả khi lên production | Bản `production/` sửa thế nào |
|---|---|---|---|---|
| 1 | 17 | **Hardcode API key** `OPENAI_API_KEY = "sk-..."` trong source code | Push lên GitHub public là key bị lộ ngay (bot quét key liên tục); muốn đổi key phải sửa code và deploy lại; key nằm vĩnh viễn trong lịch sử git | `config.py:27` đọc `os.getenv("OPENAI_API_KEY")` |
| 2 | 18 | **Hardcode connection string kèm mật khẩu DB** `postgresql://admin:password123@localhost...` | Lộ mật khẩu database; `localhost` chỉ đúng trên laptop, lên cloud/container sẽ không kết nối được | Cấu hình đi qua biến môi trường, không có credential trong code |
| 3 | 34 | **Log ra secret** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | Ai đọc được log (dashboard Railway, hệ thống gom log, đồng nghiệp) đều thấy key — log thường được giữ lâu và chia sẻ rộng hơn code | `app.py:110-115` chỉ log metadata (`question_length`, `client_ip`), không log secret |
| 4 | 33, 38, 48 | **Dùng `print()` thay vì logging có cấu trúc**, không có log level | Không lọc được theo mức độ (INFO/ERROR), không parse/search được trong log aggregator; in nguyên câu hỏi và câu trả lời của user ra log (rò rỉ dữ liệu người dùng) | `app.py:28-31` dùng `logging` với format JSON |
| 5 | 21-22 | **Config cứng trong code** (`DEBUG = True`, `MAX_TOKENS = 500`) | Muốn đổi giữa dev/staging/production phải sửa code → build lại; không thể cùng một image chạy nhiều môi trường (vi phạm 12-Factor "Config") | `config.py` tập trung toàn bộ config, đọc từ env, có giá trị mặc định |
| 6 | 42-43 | **Không có health check** (`/health`, `/ready`) | Platform không biết app còn sống hay đã treo → không tự restart; load balancer vẫn đẩy traffic vào instance chưa sẵn sàng | `app.py:135-161` có `/health` (liveness) và `/ready` (readiness, trả 503 khi chưa sẵn sàng) |
| 7 | 51 | **Bind `host="localhost"`** | Trong container/cloud, app chỉ nghe trên loopback nội bộ → request từ bên ngoài container không vào được dù port đã map | `config.py:17` mặc định `HOST=0.0.0.0` |
| 8 | 52 | **Port cố định `8000`** | Railway/Render cấp port qua biến `PORT`; app không nghe đúng port → health check của platform fail, deploy thất bại | `config.py:18` đọc `PORT` từ env |
| 9 | 53 | **`reload=True` luôn bật** | Chế độ dev: theo dõi file và tự restart, tốn CPU/RAM, có thể restart giữa chừng khi file thay đổi; không dùng được cùng nhiều worker | `app.py:198` chỉ bật reload khi `DEBUG=true` |
| 10 | cả file | **Không xử lý SIGTERM / không graceful shutdown** | Khi platform deploy bản mới hoặc scale down, process bị tắt ngang → request đang xử lý bị cắt, client nhận lỗi; không có chỗ đóng kết nối DB/Redis | `app.py:39-67` dùng `lifespan` để dọn dẹp, `app.py:180-189` đăng ký handler SIGTERM |
| 11 | 30-31 | **Nhận `question` qua query string, không validate** | Câu hỏi nằm trên URL → bị ghi vào access log của proxy/LB; không giới hạn độ dài, câu hỏi rỗng vẫn được gửi cho LLM (tốn tiền, dễ bị lạm dụng) | `app.py:102-108` nhận JSON body và trả 422 khi `question` rỗng |
| 12 | 30 | **Endpoint `/ask` không có xác thực** | Ai có URL cũng gọi được → tiêu tiền LLM không giới hạn | `config.py:32,42-43` có `AGENT_API_KEY` và fail fast nếu thiếu khi `ENVIRONMENT=production` (auth đầy đủ làm ở Part 4) |

**Tóm lại:** code develop chạy được trên laptop nhưng vi phạm các nguyên tắc 12-Factor cơ bản — config/secret nằm trong code, không có health check, không graceful shutdown, chỉ nghe trên localhost với port cố định — nên sẽ lộ secret hoặc không chạy được khi deploy lên container/cloud.

### Exercise 1.2: Run basic version

Chạy bản develop (WSL2 Ubuntu, venv Python 3.12.3):

```bash
cd 01-localhost-vs-production/develop
python app.py
```

**Test 1 — gọi `/ask` với câu hỏi qua query string → 200 OK**

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 07:33:50 GMT
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

**Test 2 — gửi JSON body như một API bình thường → 422**

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity
date: Thu, 26 Nov 2026 07:34:52 GMT
server: uvicorn
content-length: 94
content-type: application/json

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

**Test 3 — gọi health check → 404**

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
date: Thu, 26 Nov 2026 07:35:19 GMT
server: uvicorn
content-length: 22
content-type: application/json

{"detail":"Not Found"}
```

**Log phía server (terminal chạy `python app.py`)**

```text
Starting agent on localhost:8000...
INFO:     Will watch for changes in these directories: ['/mnt/d/AI20K/lab/lab14/K5-L3B-DAY14-TranThiNhai-2A202603911-Deployment-Benchmark-Observability/01-localhost-vs-production/develop']
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [2419] using WatchFiles
INFO:     Started server process [2421]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
INFO:     127.0.0.1:34750 - "POST /ask?question=Hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:49492 - "POST /ask HTTP/1.1" 422 Unprocessable Entity
INFO:     127.0.0.1:47710 - "GET /health HTTP/1.1" 404 Not Found
```

**Quan sát:** app *chạy được* trên máy local nhưng **chưa sẵn sàng cho production**. Output thực tế xác nhận các anti-pattern ở Exercise 1.1:

| Quan sát từ output | Anti-pattern tương ứng (1.1) |
|---|---|
| Log in nguyên API key: `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this` | #1 hardcode secret, #3 log ra secret |
| Log in nguyên câu hỏi và câu trả lời của user bằng `print()`, không có level, không phải JSON | #4 `print()` thay cho structured logging |
| `GET /health` → **404 Not Found** — platform không có endpoint nào để kiểm tra app còn sống | #6 không có health check |
| Gửi JSON body → **422**; câu hỏi phải nằm trên URL (`/ask?question=Hello`) và xuất hiện nguyên văn trong access log `"POST /ask?question=Hello"` | #11 nhận input qua query string |
| `Uvicorn running on http://localhost:8000` — chỉ nghe trên loopback, port cố định | #7 bind `localhost`, #8 port cố định |
| `Will watch for changes...` / `Started reloader process` — chế độ auto-reload của môi trường dev đang bật | #9 `reload=True` luôn bật |
| Gọi `/ask` không cần header xác thực nào vẫn nhận 200 | #12 không có xác thực |

### Exercise 1.3: Comparison table

#### Chạy bản production

```bash
cd ../production
cp .env.example .env      # .env đã nằm trong .gitignore, không commit
python app.py
```

```text
WARNING:root:OPENAI_API_KEY not set — using mock LLM
INFO:     Started server process [2431]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:59834 - "GET / HTTP/1.1" 200 OK
INFO:     127.0.0.1:50504 - "GET /health HTTP/1.1" 200 OK
INFO:     127.0.0.1:58870 - "GET /ready HTTP/1.1" 200 OK
INFO:     127.0.0.1:45460 - "POST /ask HTTP/1.1" 200 OK
INFO:     127.0.0.1:53170 - "POST /ask HTTP/1.1" 422 Unprocessable Entity
```

Gọi thử các endpoint:

```text
$ curl -s http://localhost:8000/
{"app":"AI Agent","version":"1.0.0","environment":"development","status":"running"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":36.0,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:41:32.524341+00:00"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":""}'
HTTP/1.1 422 Unprocessable Entity
{"detail":"question field is required"}
```

So với bản develop: cùng một yêu cầu, `/health` từ **404 → 200**, có thêm `/ready`; `/ask` nhận **JSON body** (develop trả 422 cho JSON) và trả **422 có thông báo rõ ràng** khi câu hỏi rỗng; server nghe trên **`0.0.0.0`** thay vì `localhost`; không còn dòng log nào in ra API key; không còn reloader (`Started reloader process`) vì `DEBUG=false`.

#### Bảng so sánh

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| **Config** | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`, dòng 21-22) | Đọc từ env qua `config.py`, có giá trị mặc định | Cùng một code/image chạy được ở dev, staging, production chỉ bằng cách đổi biến môi trường — không phải sửa code rồi build lại. Đã kiểm chứng ở thí nghiệm (a): đổi `PORT` và `ENVIRONMENT` mà không sửa dòng code nào |
| **Secrets** | `OPENAI_API_KEY = "sk-..."` và mật khẩu DB nằm trong code; còn bị **in ra log** | `os.getenv(...)`, không log secret; thiếu key thì cảnh báo `using mock LLM` | Code thường được push lên Git, chia sẻ, review — secret trong code coi như đã lộ và nằm mãi trong lịch sử commit. Secret nằm ở env thì đổi (rotate) được ngay trên platform mà không deploy lại code |
| **Host / Port** | `localhost:8000` cố định | `0.0.0.0` + `PORT` từ env (log: `Uvicorn running on http://0.0.0.0:8000`) | Trong container, `localhost` chỉ là loopback bên trong container → bên ngoài không gọi vào được. Railway/Render cấp port qua biến `PORT`; nghe sai port thì health check fail và deploy thất bại |
| **Health check** | Không có — `GET /health` → **404** | `GET /health` → **200** kèm `uptime_seconds`, `version`, `environment` | Platform gọi `/health` định kỳ để biết process còn sống; non-200 → tự restart container. Không có endpoint này thì app treo mà không ai biết |
| **Readiness** | Không có | `GET /ready` → **200** `{"ready":true}`, trả **503** khi đang khởi động/tắt | Khác với liveness: app có thể *sống* nhưng *chưa sẵn sàng* (đang load model, chưa nối Redis/DB). Load balancer dùng `/ready` để không đẩy traffic vào instance chưa sẵn sàng hoặc đang tắt → tránh lỗi cho user khi deploy/scale |
| **Logging** | `print()`, không level, in cả secret và nội dung câu hỏi/trả lời | Thiết kế: `logging` + JSON, chỉ log metadata (`question_length`, `client_ip`) | Log JSON có cấu trúc thì log aggregator (Loki, Datadog, Railway logs) lọc/tìm/đếm được theo field; có level để lọc lỗi. Không log secret và dữ liệu người dùng vì log được giữ lâu và nhiều người đọc được. *(Xem phát hiện #1 bên dưới: trên thực tế log JSON đang bị tắt)* |
| **Shutdown** | Không xử lý; tắt là cắt ngang | `lifespan` (đặt `is_ready=False`, dọn dẹp) + đăng ký handler SIGTERM; uvicorn tắt tuần tự (thí nghiệm c) | Platform gửi SIGTERM mỗi lần deploy bản mới hoặc scale down. Graceful shutdown cho request đang chạy hoàn thành và đóng kết nối đúng cách → user không nhận lỗi giữa chừng, không mất dữ liệu |
| **Debug / reload** | `reload=True` luôn bật (log: `Started reloader process`) | Chỉ bật khi `DEBUG=true`; mặc định tắt (log không còn reloader) | Reloader theo dõi file và tự restart — tốn tài nguyên, có thể restart bất ngờ, không dùng được với nhiều worker. Chỉ phù hợp khi đang code |
| **Input** | `question` qua query string; JSON body → 422 khó hiểu | JSON body; rỗng → 422 `"question field is required"` | Query string bị ghi nguyên văn vào access log của proxy/LB (lộ nội dung câu hỏi). Validate sớm giúp không tốn tiền gọi LLM cho request vô nghĩa và trả lỗi rõ ràng cho client |
| **Validate config** | Không có | `validate()` — `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` → **crash ngay khi khởi động** (thí nghiệm b) | *Fail fast*: lỗi cấu hình lộ ra ngay lúc deploy (deploy fail, bản cũ vẫn chạy) thay vì app chạy lên với endpoint không được bảo vệ và chỉ bị phát hiện khi đã có người lạm dụng |

#### Thí nghiệm

**(a) Đổi cấu hình bằng biến môi trường, không sửa code**

```text
$ PORT=8001 ENVIRONMENT=staging python app.py
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)

$ curl -s http://localhost:8001/health
{"status":"ok","uptime_seconds":10.7,"version":"1.0.0","environment":"staging","timestamp":"2026-11-26T07:45:01.953913+00:00"}
```

→ App nghe ở port 8001 và báo `environment: staging`. Đây đúng là cách Railway/Render cấu hình app: inject biến môi trường, không đụng vào code.

**(b) Fail fast khi thiếu secret ở production**

```text
$ ENVIRONMENT=production python app.py
Traceback (most recent call last):
  File ".../production/app.py", line 24, in <module>
    from config import settings
  File ".../production/config.py", line 50, in <module>
    settings = Settings().validate()
  File ".../production/config.py", line 43, in validate
    raise ValueError("AGENT_API_KEY must be set in production!")
ValueError: AGENT_API_KEY must be set in production!
```

→ App từ chối khởi động. Trên cloud, deploy này sẽ fail ở bước health check nên bản cũ vẫn phục vụ, thay vì đưa lên một agent không có xác thực.

**(c) Graceful shutdown khi nhận SIGTERM**

```text
$ python app.py & PID=$!
$ sleep 2; kill -TERM $PID
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [2454]
```

→ Nhận SIGTERM, uvicorn ngừng nhận kết nối mới (`Shutting down`), chạy phần shutdown của `lifespan` (`Waiting for application shutdown` → `Application shutdown complete`) rồi mới thoát. Bản develop không có phần dọn dẹp này.

#### Phát hiện thêm: 2 lỗi trong chính bản production

Khi so output với code, tôi thấy bản production **chưa làm đúng như nó tuyên bố** ở 2 điểm:

**#1 — Log JSON bị tắt âm thầm.** Output ở trên không có dòng log JSON nào của app (`{"event": "startup"...}`, `agent_request`, `Agent is ready...`, `shutting down gracefully...`), chỉ có log của uvicorn và dòng `WARNING:root:...` ở định dạng mặc định. Kiểm tra:

```text
root level: WARNING
root handler format: %(levelname)s:%(name)s:%(message)s
app logger INFO enabled: False
```

Nguyên nhân: `app.py` dòng 24 `from config import settings` chạy **trước** `logging.basicConfig(...)` ở dòng 28. Trong lúc import, `config.validate()` gọi `logging.warning(...)` → Python tự cấu hình root logger với format và level mặc định (WARNING). Đến dòng 28 thì `basicConfig` không làm gì nữa vì root đã có handler. Kết quả: mọi `logger.info(...)` (toàn bộ log JSON) bị bỏ qua.

Lỗi chỉ xảy ra khi `validate()` có cảnh báo để ghi — tức khi `OPENAI_API_KEY` để trống (đúng cấu hình mặc định của lab, dùng mock LLM). Kiểm chứng:

```text
OPENAI_API_KEY=''               → app logger INFO enabled: False | format: %(levelname)s:%(name)s:%(message)s
OPENAI_API_KEY='dummy-not-real' → app logger INFO enabled: True  | format: {"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}
```

Đây là loại bug nguy hiểm vì phụ thuộc cấu hình: dev có key thật thì thấy log đầy đủ, môi trường thiếu key thì mất log mà không có lỗi nào báo ra. Cách sửa: gọi `logging.basicConfig(...)` trước khi import `config`, hoặc thêm `force=True`.
→ Bài học: "có code logging" chưa chắc là "có log"; phải nhìn output thật để kiểm chứng.

**#2 — File `.env` không được nạp.** `.env` có `ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend.com` nhưng app vẫn dùng giá trị mặc định:

```text
allowed_origins from settings: ['*']
```

Nguyên nhân: `requirements.txt` có `python-dotenv` nhưng không file nào gọi `load_dotenv()`; `config.py` chỉ đọc `os.getenv`. Hậu quả: bước `cp .env.example .env` không có tác dụng — sửa `.env` không đổi được cấu hình, và CORS đang mở cho mọi origin (`*`) dù người vận hành tưởng đã giới hạn. Biến môi trường thật (như thí nghiệm a, hoặc Variables trên Railway) thì vẫn hoạt động. Cách sửa: gọi `load_dotenv()` ở đầu `config.py`.

---

## AI log

| Thời gian | Hỏi AI gì | Nhận được gì | Tôi tự sửa / kiểm tra thế nào |
|---|---|---|---|
| 2026-11-25 | Claude Code: kiểm tra môi trường đã sẵn sàng hay chưa (dung lượng, Docker trên WSL2, mạng, Railway CLI) | Chẩn đoán lỗi (ổ C đầy, Docker engine treo, IPv6 hỏng) và lệnh sửa | Tự chuyển Docker sang ổ D, chạy lại `docker info`, `docker run hello-world`, `railway whoami` để xác nhận |
| 2026-11-26 | Claude Code: hướng dẫn CP1, kiểm tra anti-pattern người dùng đã phát hiện, bổ sung và soạn Exercise 1.1 (anti-patterns trong `develop/app.py`) | Nhận xét và hoàn thiện bảng anti-pattern, hậu quả và chỗ sửa trong `production/` | Đối chiếu, bổ sung từng số dòng với file `develop/app.py` và `production/app.py`, `config.py`; chạy thử bản develop để thấy secret bị in ra log |
| 2026-11-26 | Claude Code: trình bày Exercise 1.2 từ output curl và log server mà tôi tự chạy | Định dạng lại output thành các test case và bảng nối quan sát với anti-pattern ở 1.1 | Output (mã HTTP, thời gian, log) là của chính tôi chạy trong WSL; kiểm tra lại mỗi quan sát khớp với dòng log thật |
| 2026-11-26 | Claude Code: hoàn thiện Exercise 1.3 từ output bản production và 3 thí nghiệm (đổi env, fail fast, SIGTERM) tôi tự chạy | Bảng so sánh có cột "Tại sao"; phát hiện log JSON không xuất hiện và `.env` không được nạp, kèm giải thích nguyên nhân | Claude chạy lệnh kiểm tra trong venv của tôi (`allowed_origins` = `['*']`, root logger level = WARNING); tôi đọc lại kết quả và đối chiếu với `app.py` dòng 24-31 và `config.py` để hiểu nguyên nhân |
