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

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

File: `02-docker/develop/Dockerfile`

**1. Base image là gì?**

`python:3.11` (dòng 8) — bản Python **đầy đủ** dựa trên Debian, kèm sẵn bộ công cụ build (gcc, make, header C, git, curl…) để có thể compile package từ source. Đổi lại image rất nặng: đo trên máy tôi bằng `docker image inspect`, `python:3.11` = **1054 MB**, trong khi `python:3.11-slim` = **119 MB**. App của bài chỉ cần FastAPI + uvicorn (có sẵn wheel, không cần compile) nên phần lớn dung lượng đó là thừa khi chạy.

**2. Working directory là gì?**

`/app` (dòng 11, `WORKDIR /app`). Lệnh này tạo thư mục `/app` nếu chưa có và đặt nó làm thư mục hiện tại cho mọi lệnh phía sau (`COPY`, `RUN`, `CMD`). Vì vậy:
- `COPY 02-docker/develop/requirements.txt .` (dòng 14) → file nằm ở `/app/requirements.txt`
- `COPY utils/mock_llm.py utils/` (dòng 24) → `/app/utils/mock_llm.py`
- `CMD ["python", "app.py"]` chạy trong `/app`, nên `from utils.mock_llm import ask` trong `app.py` tìm thấy module.

Dùng `WORKDIR` thay cho `RUN cd ...` vì mỗi `RUN` chạy trong một shell riêng — `cd` không giữ lại cho lệnh sau.

**3. Tại sao COPY `requirements.txt` trước?**

Mỗi lệnh trong Dockerfile tạo một **layer** và Docker cache từng layer. Khi build lại, Docker dùng lại cache cho tới lệnh **đầu tiên có input thay đổi**, từ đó trở xuống phải chạy lại hết.

Thứ tự trong file: `COPY requirements.txt` (dòng 14) → `RUN pip install` (dòng 17, bước chậm nhất) → `COPY app.py` (dòng 20) → `COPY utils/` (dòng 24).

- Khi chỉ sửa `app.py` (việc xảy ra liên tục): dòng 14 và 17 dùng cache → **không cài lại thư viện**, chỉ chạy lại từ dòng 20 → build mất vài giây.
- Nếu `COPY . .` trước rồi mới `pip install`: sửa bất kỳ file code nào cũng làm layer COPY thay đổi → `pip install` chạy lại từ đầu mỗi lần build, mất hàng chục giây đến vài phút (và tải lại package từ mạng).

Nguyên tắc: thứ **ít thay đổi** (danh sách thư viện) đặt **trước**, thứ **hay thay đổi** (source code) đặt **sau**.
*(Lưu ý: `pip install --no-cache-dir` ở dòng 17 tắt cache tải package của pip để image nhỏ hơn — khác với Docker layer cache.)*

**4. CMD vs ENTRYPOINT khác nhau thế nào?**

| | `CMD` | `ENTRYPOINT` |
|---|---|---|
| Vai trò | Lệnh/tham số **mặc định** khi container start | Lệnh **cố định**, container luôn chạy lệnh này |
| Tham số khi `docker run <image> <args>` | `<args>` **thay thế toàn bộ** CMD | `<args>` được **nối thêm** vào sau ENTRYPOINT |
| Muốn đổi | Chỉ cần thêm lệnh sau tên image | Phải dùng `docker run --entrypoint ...` |

Dockerfile này dùng `CMD ["python", "app.py"]` (dòng 30), nên `docker run my-agent:develop python -c "..."` sẽ chạy lệnh khác thay vì server — tiện để debug. Hai lệnh thường được dùng kết hợp: `ENTRYPOINT ["uvicorn"]` + `CMD ["app:app", "--port", "8000"]` → lệnh cố định, tham số mặc định có thể đổi.

Dòng 30 dùng **exec form** (mảng JSON) chứ không phải shell form (`CMD python app.py`): với exec form, `python` là PID 1 trong container nên nhận trực tiếp SIGTERM khi `docker stop` → tắt gọn gàng. Shell form chạy qua `/bin/sh -c`, shell làm PID 1 và có thể không chuyển tín hiệu cho app → Docker chờ hết 10 giây rồi kill cứng.

Thí nghiệm ghi đè CMD (chạy sau khi build ở 2.2):

```text
$ docker run --rm my-agent:develop python -c "print('CMD bi ghi de')"
CMD bi ghi de
```

→ Container in chuỗi rồi thoát ngay, **không khởi động server**: tham số sau tên image đã thay thế toàn bộ `CMD ["python", "app.py"]`.

**Quan sát thêm khi đọc Dockerfile:**
- Thư mục `02-docker/develop/` có file `.dockerignore`, nhưng lệnh build dùng **gốc repo làm build context** (`docker build -f 02-docker/develop/Dockerfile ... .`), nên Docker áp dụng `.dockerignore` **ở gốc repo**; file trong thư mục con không có tác dụng.
- Dockerfile `COPY` từng file cụ thể (`requirements.txt`, `app.py`, `utils/mock_llm.py`) thay vì `COPY . .` → image không bị lẫn file thừa hay secret dù build context là cả repo.
- Không có lệnh `USER` → container chạy bằng **root** (kiểm chứng ở 2.2 bằng `whoami`); bản production ở 2.3 sửa điểm này bằng user `appuser`.

### Exercise 2.2: Build & run

Chạy từ gốc repo (WSL2 Ubuntu, Docker 28.0.4).

**Build lần 1 — 20,35 giây**, gần như toàn bộ là bước `pip install`:

```text
$ time docker build --progress=plain -f 02-docker/develop/Dockerfile -t my-agent:develop .
#4 [1/7] FROM docker.io/library/python:3.11
#4 DONE 0.2s
#6 [2/7] WORKDIR /app
#7 [3/7] COPY 02-docker/develop/requirements.txt .
#8 [4/7] RUN pip install --no-cache-dir -r requirements.txt
#8 17.05 Successfully installed annotated-types-0.8.0 anyio-4.16.0 click-8.5.1 fastapi-0.115.0 h11-0.16.0 httptools-0.9.0 idna-3.20 pydantic-2.14.4 pydantic-core-2.50.5 python-dotenv-1.2.4 pyyaml-6.0.4 starlette-0.38.6 typing-extensions-4.16.0 typing-inspection-0.4.5 uvicorn-0.30.0 uvloop-0.23.0 watchfiles-1.3.0 websockets-17.4
#8 17.05 WARNING: Running pip as the 'root' user can result in broken permissions ...
#8 DONE 18.0s
#9 [5/7] COPY 02-docker/develop/app.py .
#10 [6/7] RUN mkdir -p utils
#11 [7/7] COPY utils/mock_llm.py utils/
#12 naming to docker.io/library/my-agent:develop done

real    0m20.350s
```

**Build lần 2 (không đổi gì) — 0,2 giây**, mọi bước đều `CACHED`:

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
[+] Building 0.2s (12/12) FINISHED
 => CACHED [2/7] WORKDIR /app
 => CACHED [3/7] COPY 02-docker/develop/requirements.txt .
 => CACHED [4/7] RUN pip install --no-cache-dir -r requirements.txt
 => CACHED [5/7] COPY 02-docker/develop/app.py .
 => CACHED [6/7] RUN mkdir -p utils
 => CACHED [7/7] COPY utils/mock_llm.py utils/
```

**Chạy container và gọi API**

```text
$ docker run -d --name agent-develop -p 8000:8000 my-agent:develop
5a7cea6bcdca83b0aa851047f54bbf9120f2ce5bb58ed9962362a4918ce25fa2

$ docker ps
CONTAINER ID   IMAGE              COMMAND           CREATED         STATUS         PORTS                    NAMES
5a7cea6bcdca   my-agent:develop   "python app.py"   8 seconds ago   Up 8 seconds   0.0.0.0:8000->8000/tcp   agent-develop

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":15.2,"container":true}

$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

**Log và bên trong container**

```text
$ docker logs agent-develop
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:59234 - "GET /health HTTP/1.1" 200 OK
INFO:     172.17.0.1:55446 - "POST /ask?question=What%20is%20Docker HTTP/1.1" 200 OK

$ docker exec agent-develop sh -c "whoami; pwd; ls -la; python --version"
root
/app
drwxr-xr-x 2 root root 4096 Nov 26 08:12 __pycache__
-rwxrwxrwx 1 root root  743 Nov 25 10:15 app.py
-rwxrwxrwx 1 root root   45 Nov 25 10:15 requirements.txt
drwxr-xr-x 1 root root 4096 Nov 26 08:12 utils
Python 3.11.18
```

**Kích thước image**

```text
$ docker images my-agent:develop
REPOSITORY   TAG       IMAGE ID       CREATED         SIZE
my-agent     develop   3913d9d41614   2 minutes ago   1.15GB
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| Build lần 1: 20,35 s (riêng `pip install` 18,0 s) → lần 2: 0,2 s, tất cả `CACHED` | Kiểm chứng câu 3 của 2.1: layer cache bỏ qua bước cài thư viện. Nếu chỉ sửa `app.py`, chỉ bước 5–7 chạy lại |
| Image **1.15 GB**, trong đó base `python:3.11` đã chiếm 1054 MB | App + thư viện chỉ ~100 MB; gần 90% dung lượng là base image đầy đủ — lý do bản production chuyển sang `slim` |
| `whoami` → **root**; pip cũng cảnh báo `Running pip as the 'root' user` | Dockerfile không có `USER` → nếu app bị khai thác, kẻ tấn công có quyền root trong container |
| `Started server process [1]` | Nhờ `CMD` dạng exec form, `python` là **PID 1** → nhận trực tiếp SIGTERM khi `docker stop` |
| `Uvicorn running on http://0.0.0.0:8000`, `PORTS 0.0.0.0:8000->8000/tcp` | App bind `0.0.0.0` nên `-p 8000:8000` hoạt động; request đến từ `172.17.0.1` (gateway của mạng bridge Docker), không phải `127.0.0.1` |
| `pydantic-2.14.4`, `starlette-0.38.6`… được cài dù `requirements.txt` chỉ ghim `fastapi` và `uvicorn` | Thư viện phụ thuộc **không được ghim phiên bản** → build lại vào ngày khác có thể ra image khác. Production nên khoá toàn bộ phiên bản (lock file / `pip freeze`) |
| `__pycache__` được tạo lúc chạy | Python ghi file `.pyc` vào `/app` khi import; với user root thì ghi được, với user non-root cần quyền ghi (bản production `chown` thư mục cho `appuser`) |

Dọn dẹp: `docker stop agent-develop && docker rm agent-develop` (giữ image để so sánh ở 2.3).

### Exercise 2.3: Multi-stage build & image size

File: `02-docker/production/Dockerfile`

**Stage 1 — `builder` (dòng 16-29):** bắt đầu từ `python:3.11-slim`, cài công cụ build (`gcc`, `libpq-dev`) bằng apt, rồi `pip install --user` toàn bộ thư viện vào `/root/.local`. Stage này chỉ để **chuẩn bị** — nó không bao giờ được đem đi deploy.

**Stage 2 — `runtime` (dòng 36-72):** bắt đầu **lại từ đầu** với một `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local` (thư viện đã cài) cùng `main.py` và `utils/`, `chown` cho `appuser`, chuyển `USER appuser`, thêm `HEALTHCHECK`, rồi chạy uvicorn với 2 worker. Đây là image được deploy.

**Tại sao image nhỏ hơn?**
1. **Base slim thay vì base đầy đủ:** `python:3.11-slim` (119 MB) so với `python:3.11` (1054 MB) — bỏ toàn bộ bộ công cụ build và thư viện hệ thống không cần khi chạy.
2. **Chỉ mang theo kết quả, bỏ lại công cụ:** `gcc`, `libpq-dev`, cache apt… nằm ở layer của stage `builder`; image cuối chỉ được thêm đúng một layer thư viện đã cài (37.8 MB). Kiểm chứng bằng `which gcc` bên dưới.

#### Build

```text
$ docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
[+] Building 52.9s (17/17) FINISHED
 => [builder 1/5] FROM docker.io/library/python:3.11-slim                       0.1s
 => [runtime 2/8] RUN groupadd -r appuser && useradd -r -g appuser appuser       0.4s
 => [builder 2/5] WORKDIR /app                                                   0.1s
 => [builder 3/5] RUN apt-get update && apt-get install -y gcc libpq-dev ...    33.7s
 => [runtime 3/8] WORKDIR /app                                                   0.0s
 => [builder 4/5] COPY 02-docker/production/requirements.txt .                   0.1s
 => [builder 5/5] RUN pip install --no-cache-dir --user -r requirements.txt     17.6s
 => [runtime 4/8] COPY --from=builder /root/.local /home/appuser/.local          0.3s
 => [runtime 5/8] COPY 02-docker/production/main.py .                            0.1s
 => [runtime 6/8] RUN mkdir -p /app/utils                                        0.2s
 => [runtime 7/8] COPY utils/mock_llm.py /app/utils/mock_llm.py                  0.1s
 => [runtime 8/8] RUN chown -R appuser:appuser /app                              0.2s
 => => naming to docker.io/library/my-agent:advanced                             0.0s
```

#### So sánh kích thước

```text
$ docker images my-agent
REPOSITORY   TAG        IMAGE ID       CREATED              SIZE
my-agent     advanced   3bb3916975a9   About a minute ago   163MB
my-agent     develop    3913d9d41614   6 minutes ago        1.15GB
```

- **Develop:** 1.15 GB ≈ **1150 MB**
- **Production (advanced):** **163 MB**
- **Difference:** (1150 − 163) / 1150 ≈ **85.8 % nhỏ hơn** (nhỏ hơn ~7 lần), và dưới ngưỡng 500 MB của Part 6.

#### Kiểm chứng: không có build tools, không chạy root

```text
$ docker run --rm my-agent:advanced sh -c "whoami; which gcc || echo 'no gcc in final image'"
appuser
no gcc in final image

$ docker run --rm my-agent:develop  sh -c "whoami; which gcc"
root
/usr/bin/gcc
```

→ `gcc` đã được cài ở stage `builder` (bước 33.7 s) nhưng **không có mặt trong image cuối**; image develop thì mang cả `gcc` theo khi chạy. Image production chạy bằng `appuser` thay vì `root`.

#### Các layer của image cuối

```text
$ docker history my-agent:advanced
CREATED BY                                      SIZE
CMD ["uvicorn" "main:app" "--host" "0.0.0.0"…   0B
HEALTHCHECK &{["CMD-SHELL" "python -c \"impo…   0B
EXPOSE map[8000/tcp:{}]                         0B
ENV PYTHONPATH=/app                             0B
ENV PATH=/home/appuser/.local/bin:/usr/local…   0B
USER appuser                                    0B
RUN /bin/sh -c chown -R appuser:appuser /app…   3.65kB
COPY utils/mock_llm.py /app/utils/mock_llm.p…   1.56kB
RUN /bin/sh -c mkdir -p /app/utils              0B
COPY 02-docker/production/main.py .             2.09kB
COPY /root/.local /home/appuser/.local          37.8MB
WORKDIR /app                                    0B
RUN /bin/sh -c groupadd -r appuser && userad…   4.31kB
--- các layer dưới đây thuộc base python:3.11-slim ---
RUN /bin/sh -c set -eux;   savedAptMark="$(a…   42.5MB
RUN /bin/sh -c set -eux;  apt-get update;  a…   3.81MB
# debian.sh --arch 'amd64' out/ 'trixie' ...    78.8MB
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| Không có layer nào chứa `apt-get install gcc libpq-dev` hay `pip install` trong lịch sử image cuối | Mọi thứ của stage `builder` bị bỏ lại; chỉ kết quả (`/root/.local`, 37.8 MB) được copy sang |
| 163 MB ≈ base slim (~125 MB: 78.8 + 42.5 + 3.81) + thư viện (37.8 MB) + code (vài KB) | Phần app chiếm rất ít; chọn base image là quyết định lớn nhất về kích thước |
| Bước apt trong builder mất **33.7 s / 52.9 s** tổng thời gian build | Với `requirements.txt` hiện tại (chỉ FastAPI + uvicorn, đều có wheel sẵn) thì `gcc`/`libpq-dev` không cần — có thể bỏ để build nhanh hơn. Chúng chỉ cần khi có package phải compile (ví dụ `psycopg2` từ source) |
| `[runtime 2/8] groupadd` chạy xen kẽ với các bước `builder` | BuildKit build **song song** hai stage vì `runtime` chỉ phụ thuộc `builder` ở bước `COPY --from=builder` |
| `chown` và `USER appuser` đứng trước `CMD` | App chạy không phải root, nhưng vẫn ghi được vào `/app` (ví dụ `__pycache__`) |

### Exercise 2.4: Docker Compose stack

File: `02-docker/production/docker-compose.yml`, `02-docker/production/nginx/nginx.conf`. Chạy với `-p k5-day14-docker` để không trùng project với Part 5 / Part 7.

#### Sơ đồ kiến trúc

```text
                    Máy host (Windows/WSL)
                            │
            curl http://localhost/...  (cổng 80 — cổng DUY NHẤT mở ra ngoài)
                            │           (443 cũng được map nhưng nginx chưa có listen 443)
┌───────────────────────────┼─────────────────── network "internal" (bridge, 172.20.0.0/16) ──┐
│                           ▼                                                                  │
│                ┌─────────────────────┐                                                       │
│                │  nginx  172.20.0.5  │  reverse proxy / load balancer                        │
│                │  :80                │  • rate limit 10 req/s/IP, burst 20 → 429             │
│                │                     │  • thêm security headers (X-Frame-Options...)         │
│                │                     │  • /health: không rate limit, không ghi access log    │
│                └──────────┬──────────┘                                                       │
│                           │ proxy_pass http://agent:8000   (gọi bằng TÊN service, Docker DNS) │
│                           ▼                                                                  │
│                ┌─────────────────────┐                                                       │
│                │  agent  172.20.0.4  │  FastAPI, uvicorn 2 workers, user appuser             │
│                │  :8000 (không publish ra host)  HEALTHCHECK GET /health                    │
│                └─────┬──────────┬────┘                                                       │
│     REDIS_URL=       │          │   QDRANT_URL=                                              │
│     redis://redis:6379/0        │   http://qdrant:6333                                       │
│                      ▼          ▼                                                            │
│   ┌────────────────────┐   ┌──────────────────────┐                                          │
│   │ redis  172.20.0.2  │   │ qdrant  172.20.0.3   │                                          │
│   │ :6379  cache/      │   │ :6333  vector DB     │                                          │
│   │ session, LRU 256MB │   │ (RAG)                │                                          │
│   └─────────┬──────────┘   └──────────┬───────────┘                                          │
│             ▼                         ▼                                                      │
│      volume redis_data         volume qdrant_data     (dữ liệu còn sau khi container restart) │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

Thứ tự khởi động (depends_on): redis (healthy) + qdrant (healthy) → agent → nginx
```

**Các service giao tiếp thế nào:** cả 4 container nằm chung network bridge `internal`; Docker có DNS nội bộ nên các service gọi nhau bằng **tên service** (`agent`, `redis`, `qdrant`) thay vì IP (IP có thể đổi mỗi lần tạo lại container). Chỉ `nginx` publish cổng ra host; `agent`, `redis`, `qdrant` chỉ truy cập được từ bên trong network.

#### Khởi động

```text
$ docker compose -p k5-day14-docker -f 02-docker/production/docker-compose.yml up -d --build
WARN[0000] ... the attribute `version` is obsolete, it will be ignored
 ✔ qdrant Pulled                                   16.7s
 ✔ nginx Pulled                                    19.0s
[+] Building 0.3s (18/18) FINISHED       ← mọi bước CACHED, dùng lại layer đã build ở 2.3
 ✔ Network k5-day14-docker_internal      Created
 ✔ Volume "k5-day14-docker_redis_data"   Created
 ✔ Volume "k5-day14-docker_qdrant_data"  Created
 ✔ Container k5-day14-docker-redis-1     Healthy  11.1s
 ✔ Container k5-day14-docker-qdrant-1    Healthy   6.1s
 ✔ Container k5-day14-docker-agent-1     Started  11.1s
 ✔ Container k5-day14-docker-nginx-1     Started  11.2s

$ docker compose -p k5-day14-docker -f ... ps     (ngay sau khi up)
NAME                       STATUS                            PORTS
k5-day14-docker-agent-1    Up 3 seconds (health: starting)   8000/tcp
k5-day14-docker-nginx-1    Up 3 seconds                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   Up 14 seconds (healthy)           6333-6334/tcp
k5-day14-docker-redis-1    Up 14 seconds (healthy)           6379/tcp

$ docker compose ... ps     (khoảng 2 phút sau)
agent     Up 2 minutes (healthy)   8000/tcp
nginx     Up 2 minutes             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    Up 2 minutes (healthy)   6333-6334/tcp
redis     Up 2 minutes (healthy)   6379/tcp
```

#### Test qua Nginx

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":9.6,"version":"2.0.0","timestamp":"2026-11-26T08:24:15.098903"}

$ curl -i http://localhost/ready
HTTP/1.1 200 OK
Server: nginx
{"ready":true}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl -i http://localhost:8000/health        ← gọi thẳng agent, bỏ qua nginx
curl: (7) Failed to connect to localhost port 8000 after 0 ms: Couldn't connect to server
```

#### Rate limit của Nginx (40 request liên tiếp vào `/`)

```text
$ for i in $(seq 1 40); do curl -s -o /dev/null -w '%{http_code} ' http://localhost/; done
200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 429 429 429 429 429 429 429 429 200 429 429 429 429 429 429 429 429 429
```

```text
$ docker compose ... logs agent | tail -20
agent-1  | INFO:     172.20.0.5:42506 - "GET / HTTP/1.1" 200 OK
agent-1  | INFO:     172.20.0.5:42506 - "GET / HTTP/1.1" 200 OK
... (20 dòng, tất cả đều 200)
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| Response có `Server: nginx` và 3 header bảo mật `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection` | Request đi qua nginx; nginx là nơi tập trung chính sách chung (header bảo mật, ẩn version `server_tokens off`) mà không phải sửa code agent |
| `localhost:8000` → **connection refused** | Agent không publish cổng ra host (compose không có `ports:` cho agent) → mọi truy cập bắt buộc đi qua nginx, nơi có rate limit. Giảm bề mặt tấn công |
| 22 request đầu **200**, sau đó **429**; xen một **200** ở request thứ 31 | Đúng cấu hình `rate=10r/s burst=20 nodelay`: cho qua ngay ~20 request "vượt" + request đang được phép, sau đó từ chối. Hạn mức hồi lại 1 request mỗi 100 ms nên giữa chuỗi 429 lại có 1 request lọt qua |
| Log agent chỉ có dòng 200, **không có 429** | Request bị chặn ngay tại nginx, **không bao giờ tới agent** → agent không tốn tài nguyên (và không tốn tiền LLM) cho traffic vượt hạn mức |
| Log agent ghi IP `172.20.0.5` | Đó là IP của **nginx** (kiểm chứng bằng `docker network inspect`), không phải IP client thật. Muốn biết IP thật, agent phải đọc header `X-Real-IP` / `X-Forwarded-For` mà nginx gắn vào |
| `redis`, `qdrant` lên `healthy` trước, agent mới start; nginx start ngay sau agent dù agent còn `health: starting` | `depends_on: condition: service_healthy` chờ được DB sẵn sàng; nhưng nginx chỉ `depends_on: agent` (không có điều kiện) nên có thể nhận request khi agent chưa sẵn sàng |
| `/health` có `location` riêng: không rate limit, `access_log off` | Health check của platform/LB gọi rất thường xuyên — không được để rate limit chặn nhầm (sẽ bị coi là chết) và không làm đầy log |
| Cổng **443** được map nhưng `nginx.conf` không có `listen 443` / chứng chỉ | Mở cổng mà không dùng — HTTPS chưa thật sự được cấu hình |
| `main.py` **không hề import redis hay qdrant**; `requirements.txt` chỉ có `fastapi`, `uvicorn` | `REDIS_URL`, `QDRANT_URL` được truyền vào nhưng agent chưa dùng: stack mô tả kiến trúc mục tiêu, còn `/ready` vẫn trả `{"ready":true}` dù Redis có chết hay không. Part 6 sẽ phải nối thật vào Redis và cho `/ready` trả 503 khi mất Redis |
| `the attribute version is obsolete` | Compose v2 bỏ qua trường `version:`; chỉ là cảnh báo |

Dọn dẹp sau khi làm xong: `docker compose -p k5-day14-docker -f 02-docker/production/docker-compose.yml down -v`

---

## Part 3: Cloud Deployment

Theo lịch K5, Part 3 làm sau Part 6 và deploy **chính agent Part 6** (`06-lab-complete/`) thay vì app mẫu trong `03-cloud-deployment/`. Chi tiết đầy đủ: [DEPLOYMENT.md](DEPLOYMENT.md).

### Exercise 3.1: Railway deployment (nền tảng chính)

- **URL:** https://agent-production-cdec363a.up.railway.app
- **Project:** `day14-agent` — 2 service: `agent` (build từ `06-lab-complete/Dockerfile`) + `Redis` (Railway Redis)
- **Screenshots:** [dashboard](screenshots/dashboard.png) · [running](screenshots/running.png) · [test](screenshots/test.png)

**Các bước (Railway CLI 5.75, chạy trong `06-lab-complete/`):**

```bash
railway init --name day14-agent                    # tạo project, liên kết thư mục
railway add --database redis                       # service Redis
railway add --service agent                        # service rỗng cho agent
railway service link agent
railway variable set AGENT_API_KEY --stdin --service agent --skip-deploys     # key ngẫu nhiên, đọc từ stdin
railway variable set 'REDIS_URL=${{Redis.REDIS_URL}}' ENVIRONMENT=production RATE_LIMIT_PER_MINUTE=10 \
    DAILY_BUDGET_USD=1.0 LOG_LEVEL=INFO --service agent --skip-deploys
railway up --service agent --ci                    # upload + build Dockerfile + deploy
railway domain --service agent                     # sinh URL public
```

Trạng thái sau deploy (`railway status`, `railway service status`):

```text
Project:         day14-agent
Environment:     production
agent
    status:        ● Online
    url:           https://agent-production-cdec363a.up.railway.app
    region:        iad
Service: agent
Status: SUCCESS
```

**4 lệnh tự kiểm (CP6):**

```text
$ BASE=https://agent-production-cdec363a.up.railway.app
$ AGENT_API_KEY=$(tr -d '\r\n' < /mnt/c/Users/HP/day14-railway-key.txt)   # key lưu ngoài repo, không in ra
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
     ✅ Public URL: GET https://agent-production-cdec363a.up.railway.app/health → 200
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| `/ready` → **200** trên cloud | Agent kết nối được Redis của Railway qua `REDIS_URL=${{Redis.REDIS_URL}}` — biến *tham chiếu*, Railway tự điền URL nội bộ (có mật khẩu) nên không phải chép secret của Redis bằng tay |
| Không cần cấu hình port | Railway cấp biến `PORT`, `CMD` của Dockerfile nghe `${PORT:-8000}`; healthcheck `/health` khai báo trong `railway.toml` phải 200 thì Railway mới chuyển traffic sang bản deploy mới |
| `ENVIRONMENT=production` | Bật fail fast trong `config.py`: nếu quên đặt `AGENT_API_KEY` thì app không khởi động → deploy fail ở healthcheck, bản cũ vẫn chạy, thay vì lên một agent không có bảo vệ |
| Đặt key bằng `--stdin`, key lưu ở file ngoài repo | Key không xuất hiện trên terminal, lịch sử lệnh, code hay commit. File `.env` (key test 5 ký tự dùng ở máy) không vào image nhờ `.dockerignore` |
| Region `iad` (US East), mỗi request từ Việt Nam ~0.8–1.5 s | Railway chọn region mặc định ở Mỹ; production phục vụ người dùng Việt Nam nên chọn region gần (Singapore) để giảm latency |
| CLI cảnh báo *"Config as Code (railway.toml) is deprecated … Existing files keep working until 2026-12-01"* | Railway đang chuyển sang `.railway/railway.ts`. Bản deploy hiện tại không bị ảnh hưởng; giữ `railway.toml` vì lab yêu cầu file này |

### Exercise 3.2: So sánh `railway.toml` với `render.yaml`

So sánh file tôi dùng để deploy (`06-lab-complete/railway.toml`) với Blueprint mẫu `03-cloud-deployment/render/render.yaml`:

| Khía cạnh | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
|---|---|---|
| Định dạng / phạm vi | TOML, cấu hình **build + deploy của một service** | YAML, **Infrastructure as Code cho cả hệ thống**: khai báo nhiều service (web + Redis) trong một file |
| Cách build | `builder = "DOCKERFILE"` → build theo Dockerfile; lệnh chạy lấy từ `CMD` | `runtime: python` + `buildCommand: pip install -r requirements.txt` + `startCommand: uvicorn app:app --port $PORT` — Render tự dựng môi trường Python, không cần Dockerfile (có thể đổi sang `runtime: docker`) |
| Healthcheck | `healthcheckPath = "/health"`, `healthcheckTimeout = 60` | `healthCheckPath: /health` |
| Khởi động lại khi lỗi | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | Không khai báo trong file (Render tự xử lý) |
| Biến môi trường & secret | **Không có trong file** — đặt bằng CLI/dashboard (`railway variable set`) | Khai báo **trong file**: giá trị thường ghi thẳng (`ENVIRONMENT: production`); secret dùng `sync: false` (nhập tay trên dashboard) hoặc `generateValue: true` (Render tự sinh, ví dụ `AGENT_API_KEY`) — giá trị thật không nằm trong Git |
| Redis | Tạo service riêng bằng `railway add --database redis`; nối bằng biến tham chiếu `${{Redis.REDIS_URL}}` | Khai báo ngay trong file: `type: redis`, `plan: free`, `maxmemoryPolicy: allkeys-lru` |
| Region / gói | Không khai báo → mặc định (`iad`) | `region: singapore`, `plan: free` khai báo trong file |
| Cách deploy | `railway up` upload thư mục từ máy (hoặc nối GitHub) | Push GitHub → Dashboard **New → Blueprint** → Render đọc file; `autoDeploy: true` tự deploy mỗi lần push |
| Thư mục con | `railway up` chạy ngay trong `06-lab-complete/` | Blueprint đọc `render.yaml` ở gốc repo → app nằm trong thư mục con phải khai báo thêm `rootDir` |

**Vì sao khác nhau:** Railway tách *code/build* (trong file) khỏi *hạ tầng và biến môi trường* (thao tác trên nền tảng) — nhanh để thử, ít khai báo. Render đặt **toàn bộ hạ tầng vào một file trong Git**: tái tạo được cả hệ thống, review được qua pull request, và buộc phải nghĩ cách xử lý secret ngay trong file (`sync: false` / `generateValue`).

**Điểm cần lưu ý trong `render.yaml` mẫu:** file khai báo service `agent-cache` (Redis) nhưng web service **không có biến nào trỏ tới nó** — thiếu `REDIS_URL` dạng `fromService: {type: redis, name: agent-cache, property: connectionString}`. Deploy nguyên file này thì Redis được tạo ra nhưng agent không dùng được (với agent Part 6, `/ready` sẽ trả 503). Railway gặp đúng vấn đề tương tự nếu quên đặt `REDIS_URL=${{Redis.REDIS_URL}}`.

### Exercise 3.3: GCP Cloud Run — pipeline CI/CD

`cloudbuild.yaml` mô tả pipeline 4 bước chạy trên Cloud Build mỗi khi push lên `main`: **(1) test** — cài `requirements.txt` + `pytest` rồi chạy `pytest tests/`, fail thì dừng toàn bộ; **(2) build** Docker image, gắn 2 tag `:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache; **(3) push** image lên Container Registry; **(4) deploy** bằng `gcloud run deploy` image đúng tag `$COMMIT_SHA` lên region `asia-southeast1`, public (`--allow-unauthenticated`), 1–10 instance, 1 CPU / 512 Mi, timeout 60 s, `ENVIRONMENT=production` và secret `OPENAI_API_KEY` lấy từ **Secret Manager**. `service.yaml` mô tả cùng service đó dạng khai báo (Knative): `minScale: 1` để tránh cold start, `maxScale: 10`, mỗi instance nhận tối đa 80 request đồng thời, secret lấy bằng `secretKeyRef`, **liveness probe `/health`** và **startup probe `/ready`** — đúng hai endpoint đã làm ở Part 5/6.

Nhận xét thêm:
- Deploy theo tag `$COMMIT_SHA` (không dùng `latest`) → biết chính xác commit nào đang chạy và rollback được bằng cách deploy lại image cũ.
- Bước test chạy `pytest tests/` nhưng thư mục mẫu **không có `tests/`** → pipeline sẽ dừng ngay ở bước 1 nếu chạy nguyên trạng.
- `cloudbuild.yaml` chỉ nạp `OPENAI_API_KEY`, trong khi `service.yaml` còn cần `AGENT_API_KEY` — hai cách deploy không đồng nhất; nên chọn một nguồn sự thật (ví dụ `gcloud run services replace service.yaml`).
- `service.yaml` tự đặt biến `PORT` — Cloud Run tự cấp biến `PORT` theo `containerPort` và không cho người dùng tự khai báo biến này, nên nên bỏ dòng đó.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication

File: `04-api-gateway/develop/app.py`

#### Câu hỏi

**API key được check ở đâu?**
- Dòng 36: `APIKeyHeader(name="X-API-Key", auto_error=False)` khai báo app đọc key từ header `X-API-Key`. `auto_error=False` để khi thiếu header, FastAPI không tự trả lỗi mà giao cho hàm của mình xử lý.
- Dòng 39-54: hàm `verify_api_key()` so sánh key nhận được với `API_KEY` (đọc từ biến môi trường `AGENT_API_KEY`, dòng 35).
- Dòng 70: `_key: str = Depends(verify_api_key)` gắn kiểm tra vào `/ask` dưới dạng **dependency** — FastAPI chạy hàm này **trước** khi vào thân endpoint; nếu hàm raise lỗi thì endpoint không bao giờ chạy (không tốn tiền gọi LLM). Endpoint nào muốn bảo vệ chỉ cần thêm `Depends(verify_api_key)`; `/` và `/health` không có nên vẫn công khai.

**Điều gì xảy ra nếu sai key?**
- **Thiếu** header → `401 Unauthorized`, `"Missing API key. Include header: X-API-Key: <your-key>"` (dòng 44-48).
- **Sai** key → `403 Forbidden`, `"Invalid API key."` (dòng 49-53).
- Cả hai trường hợp request bị chặn trước khi tới LLM. (Lưu ý: Part 6 yêu cầu *sai* key cũng phải trả **401**, nên không dùng lại nguyên cách phân biệt 401/403 này.)

**Làm sao rotate key?**
- Với code hiện tại: đổi giá trị `AGENT_API_KEY` trên môi trường/platform rồi **restart** app — không phải sửa code (nhờ key đọc từ env). Nhược điểm: app chỉ nhận **đúng một** key, nên ngay khi restart mọi client còn dùng key cũ bị chặn → phải đổi key ở tất cả client cùng lúc, dễ gây gián đoạn.
- Cách tốt hơn: cho app chấp nhận **nhiều key cùng lúc** (ví dụ `AGENT_API_KEYS=key_moi,key_cu`), phát key mới cho client, chờ tất cả chuyển xong rồi mới xoá key cũ. Nếu key bị lộ thì xoá key đó ngay. Nên gắn mỗi client một key riêng để thu hồi được từng client và biết request đến từ ai.

#### Kết quả test

Chạy server: `AGENT_API_KEY=secret-key-123 python app.py`

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok"}
```

Log server:

```text
API Key: secret-key-123
Test: curl -H 'X-API-Key: secret-key-123' http://localhost:8000/ask?question=hello
INFO:     Will watch for changes in these directories: [...]
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [1486] using WatchFiles
INFO:     127.0.0.1:35926 - "POST /ask HTTP/1.1" 401 Unauthorized
INFO:     127.0.0.1:35930 - "POST /ask HTTP/1.1" 403 Forbidden
INFO:     127.0.0.1:45194 - "POST /ask HTTP/1.1" 200 OK
INFO:     127.0.0.1:57722 - "GET /health HTTP/1.1" 200 OK
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| 3 lệnh `/ask` → **401 / 403 / 200** đúng theo thiếu / sai / đúng key | Dependency `verify_api_key` chặn đúng; chỉ request có key hợp lệ mới tới LLM |
| `/health` → **200** dù không gửi key | Health check phải công khai: platform/LB gọi nó mà không có key |
| Khi khởi động app **in nguyên API key** ra terminal (`API Key: secret-key-123`, dòng 91-92) | Anti-pattern giống Part 1: trên cloud, stdout chính là log → ai xem được log đều thấy key |
| Dòng gợi ý `Test: curl -H ... http://localhost:8000/ask?question=hello` | Gợi ý sai: curl không có `-X POST` nên gửi **GET** (endpoint chỉ nhận POST → 405), và câu hỏi đặt ở query trong khi `/ask` đọc JSON body |
| `Started reloader process` | `reload=True` cố định (dòng 93) — chế độ dev, giống anti-pattern ở Part 1 |
| Nếu không đặt `AGENT_API_KEY`, key mặc định là `"demo-key-change-in-production"` (dòng 35) | Quên đặt biến môi trường thì app vẫn chạy với một key **ai cũng biết** (nằm trong source code). An toàn hơn là fail fast như `config.py` ở Part 1 |
| So sánh bằng `api_key != API_KEY` (dòng 49) | So sánh chuỗi thường có thể bị *timing attack*; nên dùng `secrets.compare_digest()` cho secret |

### Exercise 4.2: JWT authentication

File: `04-api-gateway/production/auth.py`, `app.py`

#### JWT flow

```text
1. Client ──POST /auth/token {"username","password"}──▶ Server
                                                       authenticate_user(): so với DEMO_USERS (auth.py:70-75)
                                                       create_token(): payload {sub, role, iat, exp=+60 phút}
                                                       ký HS256 bằng JWT_SECRET (auth.py:35-43)
2. Client ◀──── {"access_token": "<header>.<payload>.<chữ ký>"} ────
3. Client ──POST /ask + "Authorization: Bearer <token>"──▶ Server
                                                       verify_token() (auth.py:46-67):
                                                       • thiếu header        → 401 (+ WWW-Authenticate: Bearer)
                                                       • chữ ký sai/hỏng     → 403 "Invalid token."
                                                       • hết hạn (exp)       → 401 "Token expired"
                                                       • hợp lệ → lấy {username, role} từ payload
                                                       → rate limit → cost guard → LLM
```

Điểm mấu chốt: server **không lưu token và không tra database** ở bước 3 — chỉ cần kiểm tra chữ ký bằng `JWT_SECRET`. Vì vậy JWT là *stateless*: instance nào có cùng secret cũng xác thực được, phù hợp khi scale nhiều instance.

**So với API key (4.1):** API key là một chuỗi bí mật cố định, không tự hết hạn, không mang thông tin người dùng. JWT gắn với **một user cụ thể**, có **role** (phân quyền user/admin, rate limit khác nhau) và **tự hết hạn** sau 60 phút → lộ token thì thiệt hại có giới hạn thời gian.

#### Kết quả test

Chạy server: `cd 04-api-gateway/production && python app.py`

```text
# Lấy token (token đã được che)
$ curl -s -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token":"eyJhbGciOiJIUzI1NiIs...<đã che>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."}

# Sai mật khẩu → 401
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"wrong"}'
HTTP/1.1 401 Unauthorized
server: uvicorn
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Invalid credentials"}

# Lưu token vào biến
$ TOKEN=$(curl -s -X POST http://localhost:8000/auth/token ... | python3 -c "...['access_token']")
$ echo "${TOKEN:0:15}..."
eyJhbGciOiJIUzI...

# Có token → 200
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}

# Không có token → 401
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hi"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Token giả → 403
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question":"Hi"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

# Giải mã phần payload của token
$ python3 -c "import sys,base64;p=sys.argv[1].split('.')[1];p+='='*(-len(p)%4);print(base64.urlsafe_b64decode(p).decode())" "$TOKEN"
{"sub":"student","role":"user","iat":1795682557,"exp":1795686157}
```

Log server:

```text
=== Demo credentials ===
  student / demo123  (10 req/min, $1/day budget)
  teacher / teach456 (100 req/min, $1/day budget)
INFO:     Started reloader process [1496] using WatchFiles
INFO:app:Security layer initialized
INFO:     127.0.0.1:33016 - "POST /auth/token HTTP/1.1" 200 OK
INFO:     127.0.0.1:56524 - "POST /auth/token HTTP/1.1" 401 Unauthorized
INFO:     127.0.0.1:51118 - "POST /auth/token HTTP/1.1" 200 OK
INFO:cost_guard:Usage: user=student req=1 cost=$0.0000/1.0
INFO:     127.0.0.1:54982 - "POST /ask HTTP/1.1" 200 OK
INFO:     127.0.0.1:56696 - "POST /ask HTTP/1.1" 401 Unauthorized
INFO:     127.0.0.1:35478 - "POST /ask HTTP/1.1" 403 Forbidden
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| Payload giải mã được ngay: `{"sub":"student","role":"user",...}` mà **không cần secret** | JWT chỉ được **ký**, không được **mã hoá** — ai cầm token cũng đọc được nội dung. Không được đặt dữ liệu nhạy cảm (mật khẩu, email...) vào payload. Chữ ký chỉ đảm bảo nội dung **không bị sửa** |
| `exp − iat = 1795686157 − 1795682557 = 3600` giây | Token sống đúng **60 phút** như `ACCESS_TOKEN_EXPIRE_MINUTES` (auth.py:24) |
| Không token → **401** kèm `www-authenticate: Bearer`; token giả → **403** | Code phân biệt "chưa xác thực" (401) với "token không hợp lệ" (403). Header `WWW-Authenticate` báo cho client biết cần dùng cơ chế Bearer |
| `"requests_remaining": 9` sau request đầu | Rate limiter (10 req/phút cho user) đã đếm request này — xem tiếp ở 4.3 |
| `"budget_remaining_usd": 2.1e-05` | **Sai tên/giá trị**: `app.py:160` trả về `usage.total_cost_usd` — số tiền **đã tiêu**, không phải số tiền còn lại (đúng ra ≈ $0.999979). Xem thêm ở 4.4 |
| Response có `x-content-type-options`, `x-frame-options`, `x-xss-protection`, `referrer-policy` | Middleware `security_headers` (app.py:75-86) thêm header bảo mật vào mọi response, kể cả response lỗi |
| Nhưng header **`server: uvicorn` vẫn còn** dù middleware có `del response.headers["server"]` (dòng 84-85) | Header `Server` do **uvicorn** gắn ở tầng giao thức, sau khi app trả response, nên middleware không xoá được. Muốn ẩn phải chạy uvicorn với `--no-server-header` (hoặc để reverse proxy như nginx xử lý) |
| Khi khởi động, app **in username/password demo** ra log; `DEMO_USERS` lưu mật khẩu **dạng chữ thường** trong code (auth.py:27-30) | Chỉ chấp nhận được cho demo. Thực tế mật khẩu phải được **hash** (bcrypt/argon2) và lưu trong database |
| `JWT_SECRET` có giá trị mặc định `"super-secret-change-in-production-please"` (auth.py:22) | Nếu quên đặt biến môi trường, ai đọc được source code cũng **tự ký được token**, kể cả token `role: "admin"`. Phải bắt buộc đặt secret (fail fast) khi chạy production |
| Không có cơ chế thu hồi token | Vì stateless, token bị lộ vẫn dùng được tới khi hết hạn (60 phút). Muốn thu hồi sớm phải có danh sách chặn (ví dụ lưu trong Redis) hoặc đổi `JWT_SECRET` (làm mọi token mất hiệu lực) — kiểm chứng ở thí nghiệm 4.3 (c) |

### Exercise 4.3: Rate limiting

File: `04-api-gateway/production/rate_limiter.py`

#### Câu hỏi

**Algorithm nào được dùng?**
**Sliding window** (dạng *sliding window log*): mỗi user có một `deque` lưu thời điểm (timestamp) của từng request đã được chấp nhận (dòng 27). Mỗi lần có request mới (`check()`, dòng 29-71):
1. Xoá các timestamp cũ hơn `now − 60s` khỏi đầu deque (dòng 39-40).
2. Nếu số timestamp còn lại ≥ giới hạn → trả **429**, kèm `Retry-After` = thời gian tới khi request cũ nhất rời khỏi cửa sổ (dòng 45-62).
3. Ngược lại → thêm `now` vào deque và cho qua (dòng 65).

Khác *fixed window* (đếm theo từng phút cố định, có thể bị dồn 2× request quanh ranh giới phút), sliding window luôn tính đúng **60 giây gần nhất**. Khác *token bucket* (cho phép "dồn" một lượng burst rồi hồi dần — kiểu Nginx ở Part 2).

**Limit là bao nhiêu requests/minute?**
- User thường (`role: user`, ví dụ `student`): **10 request / 60 giây** (dòng 86).
- Admin (`role: admin`, ví dụ `teacher`): **100 request / 60 giây** (dòng 87).
- Đếm **theo username** (`limiter.check(username)`, app.py:142), không theo IP.

**Làm sao bypass limit cho admin?**
Code không bỏ qua hẳn rate limit cho admin mà **chọn limiter khác theo role** lấy từ JWT: `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user` (app.py:141). Admin dùng bộ đếm riêng với ngưỡng cao gấp 10 lần. Vì `role` nằm trong payload JWT đã được ký, user không tự sửa thành admin được (sửa payload thì chữ ký sai → 403). Muốn admin không bị giới hạn hoàn toàn thì có thể bỏ qua `limiter.check()` khi `role == "admin"` — nhưng vẫn nên giữ một giới hạn cao để phòng token admin bị lộ.

#### Kết quả test

**15 request liên tiếp với token của `student`**

```text
$ for i in $(seq 1 15); do printf "Request %2d: " $i; curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" ...; done
Request  1: 200
Request  2: 200
Request  3: 200
Request  4: 200
Request  5: 200
Request  6: 200
Request  7: 200
Request  8: 200
Request  9: 200
Request 10: 200
Request 11: 429
Request 12: 429
Request 13: 429
Request 14: 429
Request 15: 429
```

**Response 429 đầy đủ**

```text
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"one more"}'
HTTP/1.1 429 Too Many Requests
date: Thu, 26 Nov 2026 08:46:27 GMT
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795682848
retry-after: 50

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":50}}
```

**Log server tương ứng** (rút gọn)

```text
INFO:cost_guard:Usage: user=student req=2 cost=$0.0000/1.0
INFO:     127.0.0.1:39762 - "POST /ask HTTP/1.1" 200 OK
...
INFO:cost_guard:Usage: user=student req=11 cost=$0.0002/1.0
INFO:     127.0.0.1:39848 - "POST /ask HTTP/1.1" 200 OK
INFO:     127.0.0.1:39864 - "POST /ask HTTP/1.1" 429 Too Many Requests
INFO:     127.0.0.1:39880 - "POST /ask HTTP/1.1" 429 Too Many Requests
INFO:     127.0.0.1:39896 - "POST /ask HTTP/1.1" 429 Too Many Requests
INFO:     127.0.0.1:39904 - "POST /ask HTTP/1.1" 429 Too Many Requests
INFO:     127.0.0.1:39914 - "POST /ask HTTP/1.1" 429 Too Many Requests
INFO:     127.0.0.1:53600 - "POST /ask HTTP/1.1" 429 Too Many Requests
```

#### Thí nghiệm (a) — admin trong lúc student đang bị chặn

```text
teacher /ask: 200
student /admin/stats: 403
$ curl -s http://localhost:8000/admin/stats -H "Authorization: Bearer $ADMIN"
{"total_users":"N/A (in-memory demo)","global_cost_usd":0.0002205,"global_budget_usd":10.0}
```

→ `student` đang bị 429 nhưng `teacher` vẫn gọi `/ask` được (200): mỗi user có bộ đếm riêng, và admin dùng limiter 100 req/phút. `/admin/stats` phân quyền theo `role` trong JWT: `student` → **403**, `teacher` → **200**.

#### Thí nghiệm (b) — restart server trong vòng 60 giây sau khi bị 429, dùng lại token cũ

```text
# Lấy token, gọi 11 lần liên tiếp cho tới khi bị chặn
$ for i in $(seq 1 11); do curl -s -o /dev/null -w '%{http_code} ' -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" ...; done; echo; date +%T
200 200 200 200 200 200 200 200 200 200 429
15:54:54

# Tab A: Ctrl+C → python app.py

# Gọi lại bằng CÙNG token đó (không đăng nhập lại)
$ date +%T; curl -s -o /dev/null -w 'after restart: %{http_code}\n' -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" ...
15:55:06
after restart: 200
```

Log server:

```text
INFO:cost_guard:Usage: user=student req=10 cost=$0.0002/1.0
INFO:     127.0.0.1:60804 - "POST /ask HTTP/1.1" 200 OK
INFO:     127.0.0.1:60812 - "POST /ask HTTP/1.1" 429 Too Many Requests
^CINFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:app:Shutdown
INFO:     Application shutdown complete.
INFO:     Finished server process [1606]
...
INFO:     Started server process [1628]
INFO:cost_guard:Usage: user=student req=1 cost=$0.0000/1.0
INFO:     127.0.0.1:55580 - "POST /ask HTTP/1.1" 200 OK
```

Kết luận:
- **Rate limiter mất state khi restart:** bị **429 lúc 15:54:54**, restart, và chỉ **12 giây sau** (15:55:06) — khi lẽ ra còn bị chặn khoảng 48 giây nữa — request đã **200**. Bộ đếm `self._windows` nằm trong RAM của process nên biến mất cùng process cũ.
- **Cost guard cũng mất state:** trước restart log ghi `user=student req=10`, sau restart đếm lại từ `req=1` — tổng chi phí trong ngày bị xoá, dù budget tính theo ngày chứ không phải 60 giây.
- **Token cũ vẫn dùng được** sau restart (200, không đăng nhập lại) → JWT stateless: server không lưu phiên, chỉ cần cùng `JWT_SECRET` để kiểm tra chữ ký.

Hệ quả production: mỗi lần deploy/restart, mọi user được "xoá án" rate limit và budget; chạy 3 instance thì mỗi instance đếm riêng → thực tế cho phép tới 30 request/phút. **Cách sửa: lưu state trong Redis** (yêu cầu của Part 6 — script chấm restart agent và kiểm tra vẫn bị 429).

#### Thí nghiệm (c) — đổi `JWT_SECRET`

Tab A: `JWT_SECRET=another-secret-for-test python app.py`

```text
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"new secret"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}
```

→ Token cũ được ký bằng secret mặc định nên không còn khớp chữ ký với secret mới → **403**. Đổi secret là cách thu hồi **toàn bộ** token cùng lúc (khi secret bị lộ), đổi lại mọi user phải đăng nhập lại. Cũng vì vậy, khi chạy nhiều instance, **tất cả phải dùng chung một `JWT_SECRET`**, nếu không token do instance A cấp sẽ bị instance B từ chối.

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| Đúng **10 × 200** rồi **429** từ request thứ 11 | Khớp `max_requests=10`. Request `Explain JWT` ở 4.2 (08:42:49) đã ra khỏi cửa sổ 60 giây nên không bị tính vào lượt này |
| Các request 429 **không có dòng `Usage:`** trong log | Rate limit chạy **trước** cost guard và trước khi gọi LLM → request bị chặn không tốn tiền. Request 429 cũng không được thêm vào deque nên spam liên tục không làm thời gian bị chặn kéo dài thêm |
| `retry-after: 50` nhưng `x-ratelimit-reset: 1795682848` = thời điểm hiện tại **+ 60 giây** | Hai header **mâu thuẫn**: `Retry-After` tính đúng theo request cũ nhất (dòng 47), còn `X-RateLimit-Reset` chỉ lấy `now + window` (dòng 43). Client đọc `X-RateLimit-Reset` sẽ chờ lâu hơn cần thiết |
| Response 429 có `x-ratelimit-limit`, `x-ratelimit-remaining`, `retry-after` | Client biết được giới hạn và nên chờ bao lâu thay vì thử lại liên tục |
| Log khi tắt: `Waiting for application shutdown` → `INFO:app:Shutdown` → `Finished server process` | Lifespan shutdown chạy đúng (graceful), nhưng không có bước nào lưu state rate limit/cost ra ngoài → mất khi tắt |

### Exercise 4.4: Cost guard

File: `04-api-gateway/production/cost_guard.py`

#### Cách cost guard hiện tại hoạt động

Trong `/ask` (app.py:140-153), thứ tự là: **JWT → rate limit → `check_budget()` → gọi LLM → `record_usage()`**.

| Bước | Code | Làm gì |
|---|---|---|
| Trước khi gọi LLM | `check_budget(user_id)` (dòng 60-91) | 1. Tổng chi phí **toàn hệ thống** ≥ $10/ngày → **503** (dừng dịch vụ cho mọi người). 2. Chi phí **của user** trong ngày ≥ $1 → **402 Payment Required**. 3. Đã dùng ≥ 80% → ghi log cảnh báo |
| Sau khi gọi LLM | `record_usage(user_id, input_tokens, output_tokens)` (dòng 93-110) | Cộng token vào bản ghi của user trong ngày, cộng chi phí vào tổng toàn hệ thống |
| Tính tiền | `total_cost_usd` (dòng 33-36) | `input/1000 × $0.00015 + output/1000 × $0.0006` (giá GPT-4o-mini) |
| Reset | `_get_record()` (dòng 53-58) | Khi sang ngày mới (`time.strftime("%Y-%m-%d")` khác), tạo bản ghi mới cho user |
| Đếm token | app.py:151-152 | Ước lượng thô: `số từ × 2` (mock) |

Lý do kiểm tra **trước** và ghi nhận **sau**: trước khi gọi chưa biết response dài bao nhiêu nên chưa biết chính xác chi phí; nếu đã hết budget thì chặn luôn để không tốn tiền.

#### Kết quả test

```text
$ curl -s http://localhost:8000/me/usage -H "Authorization: Bearer $TOKEN"
{"user_id":"student","date":"2026-11-26","requests":1,"input_tokens":2,"output_tokens":30,"cost_usd":1.8e-05,"budget_usd":1.0,"budget_remaining_usd":0.999982,"budget_used_pct":0.0}
```

Kiểm tra lại phép tính: câu hỏi `"x"` = 1 từ → 2 input token; câu trả lời 15 từ → 30 output token.
`2/1000 × 0.00015 + 30/1000 × 0.0006 = 0.0000003 + 0.000018 = 0.0000183 ≈ $1.8e-05` ✅ khớp `cost_usd`.

So sánh với response của `/ask` ở 4.2 (`"budget_remaining_usd": 2.1e-05`): `/me/usage` trả đúng **số tiền còn lại** (0.999982), còn `/ask` trả nhầm **số tiền đã tiêu** — xác nhận lỗi ở app.py:160.

#### Nhận xét về code hiện tại

| Vấn đề | Chi tiết | Hệ quả |
|---|---|---|
| **State trong RAM** | `self._records`, `self._global_cost` là biến của object Python | Restart là mất (đã chứng minh ở 4.3 b: `req=10` → `req=1`); nhiều instance thì mỗi instance có budget riêng → 3 instance = $3/ngày/user |
| **Không bao giờ chạm được $1/ngày trong demo** | Mỗi request ngắn tốn ~$0.0000183 → cần ~**54.600 request** để hết $1; rate limit 10 req/phút chỉ cho tối đa 14.400 request/ngày ≈ **$0.26/ngày** | Với câu hỏi ngắn, rate limit chặn trước khi cost guard kịp có tác dụng. Cost guard chỉ thật sự cần khi request đắt: prompt dài, model đắt, nhiều output token |
| **Tổng toàn hệ thống không bao giờ reset** | `_global_today` được gán ở dòng 50 nhưng **không được dùng ở đâu cả**; `_global_cost` chỉ tăng | Sau vài ngày chạy liên tục, tổng cộng dồn vượt $10 → **cả hệ thống trả 503 vĩnh viễn** tới khi restart |
| **Kiểm tra theo số đã tiêu, không tính request sắp tới** | `if total_cost >= budget` | Request cuối cùng vẫn được chạy dù làm vượt budget; nhiều request đồng thời cùng qua bước check rồi mới cùng ghi → có thể vượt nhiều hơn (race condition) |
| **Reset theo giờ máy, nhưng thông báo nói "midnight UTC"** | `time.strftime` dùng múi giờ local của server | Trên máy GMT+7, ngày mới bắt đầu lúc 0h GMT+7 chứ không phải 0h UTC |
| **Đếm token bằng `số từ × 2`** | app.py:151-152 | Chỉ để demo; thực tế phải lấy `usage.input_tokens` / `output_tokens` mà API LLM trả về |

#### Cách implement cost guard đúng (Redis, $10/tháng)

Yêu cầu trong CODE_LAB: mỗi user $10/tháng, lưu trong Redis, reset đầu tháng.

```python
import os
from datetime import datetime, timezone
import redis
from fastapi import HTTPException

r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "10"))

def _key(user_id: str) -> str:
    month = datetime.now(timezone.utc).strftime("%Y-%m")     # theo UTC, key mới mỗi tháng
    return f"budget:{user_id}:{month}"

def check_budget(user_id: str, estimated_cost: float) -> None:
    """Trước khi gọi LLM: tính cả chi phí ước lượng của request sắp chạy."""
    spent = float(r.get(_key(user_id)) or 0)
    if spent + estimated_cost > MONTHLY_BUDGET_USD:
        raise HTTPException(status_code=402, detail={
            "error": "Monthly budget exceeded",
            "used_usd": round(spent, 6), "budget_usd": MONTHLY_BUDGET_USD,
        })

def record_cost(user_id: str, actual_cost: float) -> float:
    """Sau khi gọi LLM: cộng chi phí THẬT (từ usage do API trả về)."""
    key = _key(user_id)
    pipe = r.pipeline()
    pipe.incrbyfloat(key, actual_cost)      # nguyên tử: nhiều worker/instance cộng không bị mất
    pipe.expire(key, 35 * 24 * 3600)        # tự xoá sau ~1 tháng, không cần job reset
    total, _ = pipe.execute()
    return float(total)
```

Giải thích các lựa chọn:
- **Redis thay vì RAM:** mọi worker và mọi instance đọc/ghi chung một số → restart hay scale ra nhiều instance không làm mất hoặc nhân đôi budget.
- **Key theo tháng** `budget:{user}:{YYYY-MM}` (UTC): sang tháng mới tự dùng key mới = **tự reset đầu tháng**, không cần cron job; `EXPIRE` ~35 ngày để key cũ tự bị xoá.
- **`INCRBYFLOAT` là thao tác nguyên tử** trong Redis: hai request đồng thời cộng vào cùng key không ghi đè lên nhau (khác với đọc → cộng → ghi trong Python).
- **Check có tính `estimated_cost`:** chặn luôn request sẽ làm vượt budget thay vì để nó chạy rồi mới phát hiện. Nếu cần chặt tuyệt đối khi có nhiều request đồng thời, có thể "giữ chỗ" bằng cách `INCRBYFLOAT` chi phí ước lượng trước, rồi điều chỉnh lại bằng chênh lệch thực tế sau khi gọi (hoặc dùng Lua script để check-và-cộng trong một bước).
- **Mã 402** cho user hết budget; một ngưỡng **tổng toàn hệ thống** (key `budget:global:{YYYY-MM}`) vẫn nên giữ để chặn trường hợp nhiều user cùng tiêu.

#### Vì sao cần cả rate limit và cost guard?

- **Rate limit bảo vệ tốc độ / tài nguyên:** chặn spam, chặn một user chiếm hết server, giới hạn số request trên một đơn vị thời gian. Nhưng nó không biết request đó **đắt hay rẻ**.
- **Cost guard bảo vệ tiền:** một user gửi ít request nhưng mỗi request có prompt rất dài, gọi model đắt, sinh nhiều output token vẫn có thể đốt hết budget mà không bao giờ chạm rate limit. Ngược lại như đo ở trên, với request rẻ thì rate limit chặn trước.
- Hai lớp bổ sung cho nhau: rate limit chặn **số lượng**, cost guard chặn **tổng chi phí**. Cả hai đều chạy **trước** khi gọi LLM, nên request bị chặn không tốn tiền.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

File: `05-scaling-reliability/develop/app.py`

#### Liveness vs Readiness

| | `GET /health` — **liveness** | `GET /ready` — **readiness** |
|---|---|---|
| Code | dòng 104-144 | dòng 147-168 |
| Trả lời câu hỏi | Process **còn sống** không? | Instance có **sẵn sàng nhận traffic** không? |
| Trả lỗi khi nào | Gần như không bao giờ — chỉ báo `"degraded"` khi RAM ≥ 90% (vẫn HTTP 200) | **503** khi `_is_ready = False`: đang khởi động (model chưa load xong) hoặc đang shutdown |
| Platform làm gì khi fail | **Restart / thay container** | **Ngừng gửi traffic** vào instance đó, *không* restart; khi `/ready` OK trở lại thì gửi tiếp |
| Nên kiểm tra gì | Chỉ bản thân process (đừng phụ thuộc DB/Redis) | Các dependency cần để phục vụ request (model, Redis, DB...) |

**Vì sao phải tách hai endpoint?**
- Nếu `/health` kiểm tra cả Redis/DB: khi Redis chập chờn, platform tưởng app chết → **restart hàng loạt** mọi instance, dù app không có lỗi gì và restart cũng không sửa được Redis → biến sự cố nhỏ thành sập toàn bộ.
- Nếu chỉ có `/health` mà không có `/ready`: lúc instance đang khởi động hoặc đang tắt, load balancer vẫn đẩy request vào → client nhận lỗi.
- Tách ra: **liveness** quyết định *có restart không*, **readiness** quyết định *có gửi traffic không*. (Part 6 áp dụng đúng nguyên tắc này: `/health` luôn 200 kể cả khi Redis chết, `/ready` trả 503 khi mất Redis.)

#### Kết quả test

Chạy server: `cd 05-scaling-reliability/develop && python app.py`

```text
$ curl -s http://localhost:8000/health | python3 -m json.tool
{
    "status": "ok",
    "uptime_seconds": 8.1,
    "version": "1.0.0",
    "environment": "development",
    "timestamp": "2026-11-26T09:10:35.752028+00:00",
    "checks": {
        "memory": {
            "status": "ok",
            "used_percent": 25.8
        }
    }
}

$ curl -s http://localhost:8000/ready | python3 -m json.tool
{
    "ready": true,
    "in_flight_requests": 1
}

$ time curl -s -X POST "http://localhost:8000/ask?question=hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
real    0m3.016s
```

Log khởi động:

```text
2026-11-26 16:10:27,606 INFO Starting agent on port 8000
INFO:     Started server process [897]
INFO:     Waiting for application startup.
2026-11-26 16:10:27,716 INFO Agent starting up...
2026-11-26 16:10:27,716 INFO Loading model and checking dependencies...
2026-11-26 16:10:27,917 INFO ✅ Agent is ready!
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| `/health` trả `uptime_seconds`, `version`, `environment`, `checks.memory` | Ngoài trạng thái sống/chết còn cho biết đang chạy **phiên bản nào**, chạy bao lâu (uptime reset → biết vừa bị restart), mức RAM. `used_percent: 25.8` là RAM của máy ảo WSL nơi app chạy |
| `/ready` trả `"in_flight_requests": 1` dù không có request nào khác | Middleware `track_requests` (dòng 72-81) tăng bộ đếm **trước** khi vào endpoint, nên chính request `/ready` cũng được đếm |
| Từ `Agent starting up` (16:10:27,716) tới `Agent is ready` (16:10:27,917) ≈ 0.2 s | Giả lập thời gian load model (`time.sleep(0.2)`, dòng 48). Trong khoảng này `_is_ready = False` → `/ready` trả 503, còn `/health` vẫn 200. Với model thật, khoảng này có thể vài chục giây — đó là lý do cần readiness riêng |
| `/ask` mất **3.016 s** | Mock LLM cố tình chờ 3 giây (`delay=3.0` trong `utils/mock_llm.py`) để có thời gian test graceful shutdown ở 5.2 |

### Exercise 5.2: Graceful shutdown

#### Cơ chế trong code

- `uvicorn.run(..., timeout_graceful_shutdown=30)` (dòng 193-199): khi nhận SIGTERM, uvicorn **ngừng nhận kết nối mới** nhưng **chờ tối đa 30 giây** cho các request đang xử lý hoàn thành.
- Sau đó uvicorn chạy phần shutdown của `lifespan` (dòng 54-66): đặt `_is_ready = False`, chờ `_in_flight_requests` về 0, log `Shutdown complete`.
- `handle_sigterm` (dòng 175-187) chỉ để ghi log.

#### Test: SIGTERM khi đang có 2 request

```text
$ PID=$(pgrep -f "python app.py" | head -1); echo "PID=$PID"
PID=897
$ date +%T
16:11:01
$ curl -s -w '  -> [%{http_code}] %{time_total}s\n' -X POST "http://localhost:8000/ask?question=hello" &
$ curl -s -w '  -> [%{http_code}] %{time_total}s\n' -X POST "http://localhost:8000/ask?question=hello" &
$ sleep 0.5 && kill -TERM $PID && echo "SIGTERM sent at $(date +%T)"
SIGTERM sent at 16:11:02
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}  -> [200] 6.617147s
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}  -> [200] 6.617213s
$ wait; date +%T
16:11:10
$ curl -s -o /dev/null -w 'after shutdown /health: %{http_code}\n' http://localhost:8000/health
after shutdown /health: 000
```

Log server:

```text
INFO:     Shutting down
INFO:     127.0.0.1:35290 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:35296 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 16:11:10,577 INFO 🔄 Graceful shutdown initiated...
2026-11-26 16:11:10,577 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [897]
2026-11-26 16:11:10,577 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

#### So sánh: SIGKILL (`kill -9`)

```text
# Chạy lại python app.py, rồi:
$ PID=$(pgrep -f "python app.py" | head -1)
$ curl -s -w '  -> [%{http_code}]\n' -X POST "http://localhost:8000/ask?question=hello" &
$ sleep 0.5 && kill -9 $PID; wait
  -> [000]
[1]+  Exit 52                 curl -s -w ...
```

Log server: chỉ có một chữ `Killed` — không có `Shutting down`, không có dòng `POST /ask ... 200`, không chạy lifespan shutdown.

#### Kết luận

| | SIGTERM (graceful) | SIGKILL (`kill -9`) |
|---|---|---|
| Request đang xử lý | **Cả 2 hoàn thành, HTTP 200** | Bị cắt ngang: `[000]`, curl exit 52 = *Empty reply from server* |
| Log shutdown | `Shutting down` → 2 × `200 OK` → `Graceful shutdown initiated` → `Shutdown complete` → `Finished server process` | Chỉ `Killed` |
| Dọn dẹp (đóng kết nối DB/Redis, flush log...) | Có cơ hội chạy trong lifespan | Không có |
| Sau khi xong | Process thoát, `/health` → `000` (không còn lắng nghe) | Process chết ngay |

Platform (Docker, Railway, Kubernetes) khi deploy bản mới hoặc scale down sẽ gửi **SIGTERM trước**, chờ một khoảng (Docker mặc định 10 giây), hết thời gian mới gửi **SIGKILL**. App xử lý SIGTERM đúng thì người dùng không thấy lỗi khi deploy; không xử lý thì mỗi lần deploy là một lần cắt ngang request.

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| Thứ tự log: `Shutting down` **trước**, rồi mới tới 2 dòng `200 OK` | Uvicorn ngừng nhận kết nối mới ngay khi nhận SIGTERM nhưng vẫn để 2 request đang chạy hoàn tất — đúng ý nghĩa *graceful* |
| Cả 2 request đều mất **~6.6 s** (không phải ~3 s), kết thúc gần như cùng lúc | 2 request **không chạy song song**: `/ask` là `async def` nhưng gọi `ask()` có `time.sleep(3)` — lệnh chặn đồng bộ này **khoá event loop**, nên request thứ 2 phải chờ request 1 xong (3 s + 3 s). Response của request 1 cũng chỉ được gửi đi khi event loop rảnh. Cách sửa: dùng `def` thường (FastAPI chạy trong threadpool), `await asyncio.sleep()` / client async, hoặc chạy nhiều worker |
| Không xuất hiện dòng `Waiting for N in-flight requests...` | Khi lifespan shutdown chạy thì uvicorn **đã** chờ xong các request (`_in_flight_requests` = 0). Vòng chờ trong lifespan (dòng 61-64) thực tế không có việc gì làm; phần chờ thật sự do `timeout_graceful_shutdown` của uvicorn đảm nhận |
| `_is_ready = False` chỉ được đặt trong lifespan shutdown | Vì lifespan shutdown chạy **sau** khi server đã ngừng nhận kết nối, nên trên thực tế không bao giờ quan sát được `/ready` trả 503 lúc đang tắt. Muốn load balancer kịp rút traffic, cần đặt `_is_ready = False` **ngay khi nhận SIGTERM** (trong signal handler) và chờ vài giây trước khi ngừng nhận kết nối |
| `Received signal 15` xuất hiện **cuối cùng**, sau `Finished server process` | Uvicorn cài handler SIGTERM riêng khi chạy, thay handler của app; xử lý shutdown xong mới khôi phục và gọi lại handler cũ — nên log của `handle_sigterm` đến sau cùng |
| `after shutdown /health: 000` | Process đã thoát hẳn, không còn lắng nghe cổng 8000 |

### Exercise 5.3: Stateless design

File: `05-scaling-reliability/production/app.py`

**Anti-pattern — state trong RAM của process:**

```python
conversation_history = {}          # dict nằm trong bộ nhớ của MỘT process

@app.post("/ask")
def ask(user_id: str, question: str):
    history = conversation_history.get(user_id, [])
    ...
```

**Đúng — state trong Redis (cách `production/app.py` làm):**

```python
def save_session(session_id, data, ttl_seconds=3600):          # dòng 59-65
    _redis.setex(f"session:{session_id}", ttl_seconds, json.dumps(data))

def load_session(session_id):                                   # dòng 68-73
    data = _redis.get(f"session:{session_id}")
    return json.loads(data) if data else {}
```

- Mỗi session là một key `session:{session_id}` trong Redis, giá trị là JSON chứa `history`; `setex` đặt **TTL 3600 giây** → session tự hết hạn sau 1 giờ không dùng, Redis không phình mãi.
- `append_to_history()` (dòng 76-90) đọc session → thêm message → cắt còn **20 message gần nhất** (10 lượt) → ghi lại.
- Client giữ `session_id` và gửi kèm mỗi request; agent không nhớ gì giữa các request — mọi thứ đọc lại từ Redis.

**Tại sao phải stateless khi scale?**
Khi chạy nhiều instance sau load balancer, mỗi instance là một process riêng với **bộ nhớ riêng**. Nếu history nằm trong dict của instance 1, request tiếp theo của cùng user bị load balancer gửi sang instance 2 → instance 2 không thấy history → agent "quên" cuộc trò chuyện. Ngoài ra instance bị restart/deploy lại hoặc bị tắt khi scale down là mất sạch state. Đưa state ra một kho dùng chung (Redis) thì **instance nào cũng phục vụ được bất kỳ user nào**, có thể thêm/bớt/khởi động lại instance tuỳ ý — kiểm chứng ở 5.4 và 5.5.

**Điểm cần chú ý trong code:**
- **Fallback âm thầm sang RAM** (dòng 34-45): nếu lúc import không `ping` được Redis, app chuyển sang `_memory_store` và **giữ nguyên chế độ đó suốt đời process** (Redis lên sau cũng không kết nối lại), chỉ in một dòng cảnh báo. Với nhiều instance, chỉ cần một instance khởi động sớm hơn Redis là nó trở thành stateful — đúng lỗi mà bài muốn tránh. Compose giảm rủi ro bằng `depends_on: redis: condition: service_healthy`, nhưng an toàn hơn là **fail fast** (không khởi động / `/ready` trả 503) thay vì fallback. Response có trường `"storage"` nên có thể kiểm tra: ở 5.4 cả 10 request đều `storage=redis`.
- **Đọc–sửa–ghi không nguyên tử:** `append_to_history` làm `GET` → sửa trong Python → `SETEX`. Hai request cùng session đến hai instance cùng lúc có thể ghi đè lên nhau và **mất một message**. Dùng cấu trúc list của Redis (`RPUSH` + `LTRIM` + `EXPIRE`, đúng như gợi ý `r.lrange(...)` trong CODE_LAB) thì mỗi thao tác là nguyên tử.

### Exercise 5.4: Load balancing

```text
$ cd 05-scaling-reliability/production
$ C="docker compose -p k5-day14-scaling"
$ $C up -d --build --scale agent=3
[+] Building 43.6s (17/17) FINISHED
 ✔ Network k5-day14-scaling_agent_net  Created
 ✔ Container k5-day14-scaling-redis-1  Healthy   11.0s
 ✔ Container k5-day14-scaling-agent-3  Started   11.4s
 ✔ Container k5-day14-scaling-agent-1  Started   11.2s
 ✔ Container k5-day14-scaling-agent-2  Started   11.1s
 ✔ Container k5-day14-scaling-nginx-1  Started   11.7s

$ $C ps
NAME                       SERVICE   STATUS                    PORTS
k5-day14-scaling-agent-1   agent     Up 12 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   agent     Up 12 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   agent     Up 11 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   nginx     Up 11 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   redis     Up 22 seconds (healthy)   6379/tcp
```

**10 request qua Nginx (cổng 8080, `POST /chat`)**

```text
Request: served_by=instance-c117f0 storage=redis
Request: served_by=instance-4b4708 storage=redis
Request: served_by=instance-b55ecc storage=redis
Request: served_by=instance-c117f0 storage=redis
Request: served_by=instance-4b4708 storage=redis
Request: served_by=instance-b55ecc storage=redis
Request: served_by=instance-c117f0 storage=redis
Request: served_by=instance-4b4708 storage=redis
Request: served_by=instance-b55ecc storage=redis
Request: served_by=instance-c117f0 storage=redis

$ curl -si http://localhost:8080/health | grep -i x-served-by
X-Served-By: 172.20.0.3:8000

$ $C logs agent | grep "POST /chat" | awk '{print $1}' | sort | uniq -c
      3 agent-1
      3 agent-2
      4 agent-3
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| `served_by` xoay vòng đều `c117f0 → 4b4708 → b55ecc → c117f0 …` | Nginx dùng thuật toán **round-robin** mặc định: lần lượt gửi cho từng instance trong `upstream agent_cluster` |
| Log đếm được 3 / 3 / 4 request trên 3 container | Tải được chia đều; container nhận 4 request là `instance-c117f0` (xuất hiện 4 lần trong vòng lặp) |
| Mỗi container có một `INSTANCE_ID` ngẫu nhiên (`instance-xxxxxx`, dòng 52) | Không đặt biến `INSTANCE_ID` nên mỗi process tự sinh ID — đủ để thấy request rơi vào process nào |
| `X-Served-By: 172.20.0.3:8000` | Header do Nginx thêm (`add_header X-Served-By $upstream_addr`), cho biết **IP:port** của container đã xử lý trong network `agent_net` — một cách khác để quan sát load balancing mà không cần sửa app |
| Agent chỉ có `8000/tcp` (không publish), chỉ Nginx mở `8080` | Client chỉ vào được qua load balancer |
| Cả 10 request đều `storage=redis` | Không instance nào rơi vào chế độ fallback RAM — điều kiện để stateless hoạt động |
| Compose đã có `deploy.replicas: 3`, mỗi agent bị giới hạn `cpus: 0.5`, `memory: 256M` | `--scale agent=3` trùng với cấu hình sẵn; giới hạn tài nguyên giúp một instance không chiếm hết máy |

**Kiến trúc:**

```text
Client ──▶ nginx :8080 (round-robin) ──┬──▶ agent-1 (instance-…) ──┐
                                       ├──▶ agent-2 (instance-…) ──┼──▶ redis :6379  (session:{id}, TTL 1h)
                                       └──▶ agent-3 (instance-…) ──┘
```

### Exercise 5.5: Test stateless

**`test_stateless.py` — 5 câu hỏi trong cùng một session**

```text
$ python test_stateless.py
============================================================
Stateless Scaling Demo
============================================================

Session ID: 62f69488-e58e-46f5-b7b4-8f4ce7efe4ab

Request 1: [instance-b55ecc]
  Q: What is Docker?
Request 2: [instance-c117f0]
  Q: Why do we need containers?
Request 3: [instance-4b4708]
  Q: What is Kubernetes?
Request 4: [instance-b55ecc]
  Q: How does load balancing work?
Request 5: [instance-c117f0]
  Q: What is Redis used for?

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-b55ecc', 'instance-4b4708', 'instance-c117f0'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Redis used for?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...

✅ Session history preserved across all instances via Redis!
```

→ 5 câu của **cùng một session** được xử lý bởi **cả 3 instance**, nhưng history đủ **10 message** (5 hỏi + 5 đáp) **đúng thứ tự**. Mỗi instance đọc history do instance khác ghi — chỉ làm được vì state nằm trong Redis. Nếu lưu trong dict của từng process, mỗi instance chỉ thấy phần history của chính nó.

**Thí nghiệm thêm — tắt hẳn một instance giữa cuộc trò chuyện**

```text
$ SID=$(curl -s -X POST http://localhost:8080/chat -H "Content-Type: application/json" -d '{"question":"My name is Alice"}' | python3 -c "...['session_id']")
SID=af58001a-3bea-45f7-8b06-b91ce3c896f6

$ docker stop k5-day14-scaling-agent-1
k5-day14-scaling-agent-1

$ for i in 1 2 3; do curl -s -X POST http://localhost:8080/chat ... -d "{\"question\":\"Follow-up $i\",\"session_id\":\"$SID\"}" | ...; done
turn 3 served_by instance-c117f0
turn 4 served_by instance-4b4708
turn 5 served_by instance-c117f0

$ curl -s http://localhost:8080/chat/$SID/history | ...
history count: 8

$ docker start k5-day14-scaling-agent-1
$ $C down
```

Kết luận:
- Sau khi `agent-1` bị tắt, cả 3 request tiếp theo **vẫn thành công**, chỉ do 2 instance còn lại xử lý (`c117f0`, `4b4708`) — `instance-b55ecc` không còn xuất hiện, tức `agent-1` chính là `b55ecc`.
- Client **không nhận lỗi nào**: Nginx có `proxy_next_upstream error timeout http_503` + `proxy_next_upstream_tries 3` — khi gửi vào container đã chết bị lỗi kết nối, Nginx tự chuyển request sang instance kế tiếp.
- History vẫn đủ **8 message** (4 hỏi + 4 đáp): câu `My name is Alice` có thể đã được chính instance vừa bị tắt xử lý, nhưng nội dung không mất vì nằm trong Redis → instance chết không làm mất cuộc trò chuyện.

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| Lượt hỏi thứ 2, 3, 4 của session được báo là `turn 3, 4, 5` | **Lỗi đếm lượt (off-by-one)** trong `chat()` (dòng 140-154): câu hỏi hiện tại được `append_to_history` **trước**, rồi history được load lại và `turn = số câu user + 1` → câu hiện tại bị đếm 2 lần. History thật vẫn đúng (`count: 8` = 4 lượt). Sửa: bỏ `+ 1`, hoặc tính `turn` trước khi append |
| Thứ tự `c117f0, 4b4708, c117f0` sau khi 1 instance chết | Nginx vẫn round-robin qua cả 3 địa chỉ đã resolve lúc khởi động; lượt rơi vào container chết bị lỗi và được thử lại sang instance kế tiếp |
| Nginx resolve `server agent:8000` **một lần lúc khởi động** (`resolver` chỉ có tác dụng với biến, không áp dụng cho `server` tĩnh trong `upstream`) | Nếu scale thêm instance **sau** khi Nginx đã chạy, Nginx không tự thấy instance mới; phải reload Nginx hoặc dùng `server agent:8000 resolve` (cách Part 7 làm) |
| Redis không có volume (`docker compose down` xoá luôn container Redis) | State sống sót qua việc agent chết/restart, nhưng **không** sống sót nếu chính Redis bị xoá. Production cần Redis có persistence (volume, AOF/RDB) hoặc Redis managed |
| Redis chạy `--maxmemory 128mb --maxmemory-policy allkeys-lru` | Khi đầy bộ nhớ, Redis tự xoá key ít dùng nhất — session cũ có thể bị xoá trước khi hết TTL |

---

## Part 6: Final Project — Production-ready agent

Code nằm trong `06-lab-complete/`. Kết quả chấm bằng `python check_production_ready.py` (chế độ đầy đủ, có Docker, chạy trong WSL2 Ubuntu): **PASS 12/12 · 41/41 checks**.

### Output `check_production_ready.py` — 📋 Checklist Deliverable

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 41/41 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

<details>
<summary>Chi tiết từng check (output đầy đủ)</summary>

```text
✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Dockerfile tồn tại
     ✅ requirements.txt tồn tại
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 1s
     ✅ Docker: image < 500 MB — 183 MB
     ✅ Docker: container chạy được, GET /health → 200

✅ 2. docker-compose.yml (agent + redis)
     ✅ docker-compose.yml tồn tại
     ✅ Có service agent (build từ Dockerfile) + redis — services: agent, redis — đọc bằng docker compose config
     ✅ Service agent kết nối redis (REDIS_URL + depends_on)

✅ 3. .dockerignore
     ✅ .dockerignore tồn tại và có nội dung
     ✅ .dockerignore loại trừ .env (secrets)
     ✅ .dockerignore loại trừ __pycache__, venv

✅ 4. Health check endpoint (GET /health)
     ✅ Code có route /health
     ✅ Khi chạy: GET /health → 200 — uvicorn --workers 2

✅ 5. Readiness endpoint (GET /ready)
     ✅ Code có route /ready
     ✅ Khi chạy: GET /ready → 200
     ✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)

✅ 6. API Key authentication
     ✅ Code đọc header X-API-Key
     ✅ Khi chạy: thiếu / sai API key → 401
     ✅ Khi chạy: API key đúng → 200

✅ 7. Rate limiting
     ✅ Code trả HTTP 429 khi vượt giới hạn
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429

✅ 8. Cost guard
     ✅ Code trả HTTP 402 khi hết budget
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1

✅ 9. Config từ environment variables
     ✅ app/config.py đọc biến môi trường
     ✅ .env.example liệt kê đủ biến cấu hình
     ✅ .env nằm trong .gitignore
     ✅ Không hard-code secret trong code
     ✅ Khi chạy: agent dùng AGENT_API_KEY và RATE_LIMIT_PER_MINUTE từ env

✅ 10. Structured logging
     ✅ Code ghi log dạng JSON
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 17 dòng JSON

✅ 11. Graceful shutdown
     ✅ Code xử lý SIGTERM / lifespan shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.7s

✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ App lắng nghe theo biến PORT do platform cấp
```

</details>

**Trước khi làm** (bản khung, `--static-only`): `Result: 0/12 tiêu chí đạt · 5/24 checks passed` — Dockerfile 1 lệnh `FROM` với `python:3.11`, không có `USER`/`HEALTHCHECK`; compose chỉ có `agent`; `.dockerignore`, `railway.toml` chỉ có comment; code chưa có `/health`, `/ready`, `X-API-Key`, 429, 402, log JSON, lifespan.

### Cách tôi làm từng tiêu chí

| # | Tiêu chí | File | Cách làm |
|---|---|---|---|
| 1 | Dockerfile multi-stage < 500 MB | `Dockerfile` | Stage `builder` (`python:3.11-slim`) cài thư viện vào virtualenv `/opt/venv`; stage `runtime` (`python:3.11-slim` sạch) chỉ copy `/opt/venv` + `app/` + `utils/`, tạo và chạy bằng user `app` (non-root), có `HEALTHCHECK` gọi `/health`. Image **183 MB**. Dùng venv thay vì `pip install --user` để user non-root luôn tìm thấy package (không phụ thuộc `HOME`/`PYTHONUSERBASE`) |
| 2 | Compose agent + Redis | `docker-compose.yml` | `agent` build từ Dockerfile, đọc `.env` với `required: false`, `REDIS_URL=redis://redis:6379/0`, `depends_on: redis: condition: service_healthy`; `redis:7-alpine` có healthcheck `redis-cli ping`, volume + `--appendonly yes` để dữ liệu còn sau khi Redis restart |
| 3 | `.dockerignore` | `.dockerignore` | Loại `.env`, `.env.*` (giữ `.env.example`), `__pycache__/`, `*.pyc`, `venv/`, `.venv/`, `.git/`, tài liệu, `benchmark-observability/`, script chấm |
| 4 | `/health` (liveness) | `app/main.py` | Luôn 200 khi process còn chạy, **không gọi Redis** → container vẫn healthy khi Redis chưa lên (script chấm chạy container không có Redis) |
| 5 | `/ready` (readiness) | `app/main.py`, `app/redis_client.py` | `redis_healthy()` ping Redis (timeout 2 s); lỗi → **503**. Client Redis tạo bằng `from_url` không kết nối lúc import nên app vẫn khởi động được khi Redis chết |
| 6 | API key | `app/auth.py` | `APIKeyHeader("X-API-Key", auto_error=False)` + tự raise **401** cho cả thiếu và sai key (không dùng 403 như bản develop Part 4, không để FastAPI trả 422); so sánh bằng `secrets.compare_digest`; `AGENT_API_KEY` rỗng → từ chối mọi request |
| 7 | Rate limit | `app/rate_limiter.py` | Sliding window 60 s bằng **Redis sorted set** theo từng API key (key Redis là hash của API key, không lưu key thật): `ZREMRANGEBYSCORE` → `ZCARD` → vượt `RATE_LIMIT_PER_MINUTE` thì **429** + `Retry-After` → `ZADD` + `EXPIRE`. State trong Redis nên 2 worker dùng chung và **restart vẫn bị 429** |
| 8 | Cost guard | `app/cost_guard.py` | Key `cost:daily:{YYYY-MM-DD}` (UTC) → tự reset mỗi ngày; `check_budget()` trước khi gọi LLM, tổng ≥ `DAILY_BUDGET_USD` → **402**; `record_cost()` sau khi gọi LLM, cộng bằng `INCRBYFLOAT` (nguyên tử giữa các worker) + `EXPIRE` 2 ngày. Đây là cách đã đề xuất ở Exercise 4.4, sửa các vấn đề tìm thấy trong bản Part 4 (state trong RAM, tổng không reset) |
| 9 | Config từ env | `app/config.py`, `.env.example` | Dataclass đọc `PORT`, `ENVIRONMENT`, `LOG_LEVEL`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD` bằng `os.getenv` (qua `default_factory`); **fail fast** khi `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY`. `.env.example` liệt kê đủ biến, không có secret thật |
| 10 | Log JSON | `app/main.py` | Tự viết `JsonFormatter` (`json.dumps`), gắn vào root logger bằng `basicConfig(..., force=True)` **trước** mọi lệnh log — tránh đúng lỗi phát hiện ở Part 1 (log bị cấu hình mặc định trước). Middleware ghi `{"event":"request","method","path","status","ms"}` cho mọi request; `/ask` ghi token và chi phí, **không ghi API key hay nội dung câu hỏi** |
| 11 | Graceful shutdown | `app/main.py`, `Dockerfile` | Dùng `lifespan` (log `startup`/`shutdown`, đóng kết nối Redis); để uvicorn xử lý SIGTERM (không tự đè signal handler). `CMD ["sh","-c","exec uvicorn ..."]`: `exec` làm uvicorn thành **PID 1** nên nhận SIGTERM khi `docker stop`; `--timeout-graceful-shutdown 8` đảm bảo tắt trước khi Docker SIGKILL ở giây thứ 10. Kết quả: `docker stop` exit code 0 sau **0.7 s** |
| 12 | Deploy config | `railway.toml`, `Dockerfile` | `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`, restart khi lỗi; CMD nghe `--port ${PORT:-8000}` theo biến `PORT` do Railway cấp. Secret đặt trên dashboard, không ghi trong file |

**Các điểm áp dụng từ những phần trước:**
- `/ask` khai báo bằng `def` (không phải `async def`) → FastAPI chạy trong threadpool, lệnh Redis và LLM chặn đồng bộ **không khoá event loop** (lỗi quan sát được ở Exercise 5.2: 2 request mất ~6.6 s vì chạy nối tiếp).
- Exception handler: lỗi Redis → **503** `"Service temporarily unavailable"`, lỗi khác → **500** `"Internal server error"`; stack trace chỉ ghi vào log JSON, **không trả ra client**. Input sai (`question` rỗng hoặc > 2000 ký tự) → **422** do Pydantic.
- Thứ tự trong `/ask`: `Depends(verify_api_key)` (401) → `check_rate_limit` (429) → `check_budget` (402) → LLM → `record_cost` — request bị chặn ở bước nào cũng **không tốn tiền gọi LLM**.

### Chạy thử bằng Docker Compose

```text
$ cp .env.example .env            # đổi AGENT_API_KEY thành key riêng; .env nằm trong .gitignore
$ docker compose -p k5-day14-final up -d --build
 ✔ Network k5-day14-final_default      Created
 ✔ Volume "k5-day14-final_redis-data"  Created
 ✔ Container k5-day14-final-redis-1    Healthy   5.9s
 ✔ Container k5-day14-final-agent-1    Started   6.1s

$ docker compose -p k5-day14-final ps
NAME                     COMMAND                  SERVICE   STATUS                                     PORTS
k5-day14-final-agent-1   "sh -c 'exec uvicorn…"   agent     Up Less than a second (health: starting)   0.0.0.0:8000->8000/tcp
k5-day14-final-redis-1   "docker-entrypoint.s…"   redis     Up 6 seconds (healthy)                     6379/tcp

$ docker compose -p k5-day14-final down
```

→ Agent chỉ start **sau khi** Redis `healthy` (`depends_on: condition: service_healthy`); lệnh khởi động là `sh -c 'exec uvicorn…'` đúng như Dockerfile.

### Test tay qua Docker Compose

Key được đọc từ `.env` vào biến shell, không gõ và không in ra màn hình:

```text
$ KEY=$(grep -E '^AGENT_API_KEY=' .env | cut -d= -f2- | tr -d '\r')
$ docker compose -p k5-day14-final up -d
 ✔ Container k5-day14-final-redis-1  Healthy   5.8s
 ✔ Container k5-day14-final-agent-1  Started   5.9s

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","version":"1.0.0","environment":"development","uptime_seconds":7.0}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"redis":"ok"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
www-authenticate: ApiKey
{"detail":"Missing or invalid API key. Include header: X-API-Key: <key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"question":"What is deployment?"}'
HTTP/1.1 200 OK
{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":4,"output_tokens":19,"cost_usd":1.2e-05}}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"question":""}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"string_too_short","loc":["body","question"],"msg":"String should have at least 1 character","input":"","ctx":{"min_length":1}}]}

$ docker compose -p k5-day14-final logs agent | tail -6
agent-1  | INFO:     172.20.0.1:46618 - "POST /ask HTTP/1.1" 401 Unauthorized
agent-1  | {"ts": "2026-11-26T09:51:46.947+00:00", "lvl": "INFO", "logger": "agent", "msg": "ask", "event": "ask", "user_id": null, "question_chars": 19, "input_tokens": 4, "output_tokens": 19, "cost_usd": 1.2e-05}
agent-1  | {"ts": "2026-11-26T09:51:46.948+00:00", "lvl": "INFO", "logger": "agent", "msg": "request", "event": "request", "method": "POST", "path": "/ask", "status": 200, "ms": 147.3}
agent-1  | INFO:     172.20.0.1:46620 - "POST /ask HTTP/1.1" 200 OK
agent-1  | {"ts": "2026-11-26T09:51:46.958+00:00", "lvl": "INFO", "logger": "agent", "msg": "request", "event": "request", "method": "POST", "path": "/ask", "status": 422, "ms": 0.9}
agent-1  | INFO:     172.20.0.1:46630 - "POST /ask HTTP/1.1" 422 Unprocessable Entity

$ docker compose -p k5-day14-final down
```

**Quan sát:**

| Quan sát | Ý nghĩa |
|---|---|
| `/health` 200, `/ready` 200 với `"redis":"ok"`, không key → **401**, đúng key → **200**, câu hỏi rỗng → **422** | Đủ các mã trả về theo yêu cầu; lỗi input trả JSON nêu rõ trường sai (`body.question`, `min_length: 1`), không có stack trace |
| `cost_usd: 1.2e-05` với 4 input + 19 output token | Tự kiểm lại: `4/1000 × 0.00015 + 19/1000 × 0.0006 = 0.0000006 + 0.0000114 = 0.000012` ✅ |
| Log app là JSON (`event: ask` / `event: request`, có `status`, `ms`) xen kẽ với dòng access log dạng chữ của uvicorn | Log của app parse được bằng máy; dòng `INFO: ...` là của uvicorn (script chấm không tính). Log `ask` chỉ ghi **độ dài** câu hỏi, token, chi phí — **không ghi API key và nội dung câu hỏi** |
| `ms: 147.3` cho request 200, `ms: 0.9` cho request 422 | Request hợp lệ tốn ~0.15 s chủ yếu do mock LLM (`delay=0.1` + ngẫu nhiên); request lỗi input bị chặn trước khi gọi LLM nên gần như không tốn thời gian (và không tốn tiền) |
| Request rỗng nhưng **sai key** (lần thử trước) trả **401**, không phải 422 | Xác thực chạy trước kiểm tra nội dung → người không có key không dò được định dạng input của API |

**Sự cố gặp khi test — ký tự `\r`:** lần đầu lấy key bằng `grep | cut` (không có `tr -d '\r'`), hai request có key trả **400 `Invalid HTTP request received`** từ uvicorn và log của app không có dòng nào cho chúng. Nguyên nhân: tôi sửa file trên Windows nên `.env` dùng xuống dòng CRLF; trong bash, key bị dính `\r` (độ dài 6 thay vì 5) → header HTTP không hợp lệ, uvicorn từ chối trước khi request vào app. Docker Compose tự bỏ `\r` khi đọc `env_file` nên agent vẫn nhận đúng key (độ dài 5) — lỗi chỉ nằm ở lệnh test. Cách sửa: thêm `tr -d '\r'`, hoặc chuyển `.env` sang LF (`sed -i 's/\r$//' .env`).

---

## AI log

| Thời gian | Hỏi AI gì | Nhận được gì | Tôi tự sửa / kiểm tra thế nào |
|---|---|---|---|
| 2026-11-25 | Claude Code: kiểm tra môi trường đã sẵn sàng hay chưa (dung lượng, Docker trên WSL2, mạng, Railway CLI) | Chẩn đoán lỗi (ổ C đầy, Docker engine treo, IPv6 hỏng) và lệnh sửa | Tự chuyển Docker sang ổ D, chạy lại `docker info`, `docker run hello-world`, `railway whoami` để xác nhận |
| 2026-11-26 | Claude Code: hướng dẫn CP1, kiểm tra anti-pattern người dùng đã phát hiện, bổ sung và soạn Exercise 1.1 (anti-patterns trong `develop/app.py`) | Nhận xét và hoàn thiện bảng anti-pattern, hậu quả và chỗ sửa trong `production/` | Đối chiếu, bổ sung từng số dòng với file `develop/app.py` và `production/app.py`, `config.py`; chạy thử bản develop để thấy secret bị in ra log |
| 2026-11-26 | Claude Code: trình bày Exercise 1.2 từ output curl và log server mà tôi tự chạy | Định dạng lại output thành các test case và bảng nối quan sát với anti-pattern ở 1.1 | Output (mã HTTP, thời gian, log) là của chính tôi chạy trong WSL; kiểm tra lại mỗi quan sát khớp với dòng log thật |
| 2026-11-26 | Claude Code: hoàn thiện Exercise 1.3 từ output bản production và 3 thí nghiệm (đổi env, fail fast, SIGTERM) tôi tự chạy | Bảng so sánh có cột "Tại sao"; phát hiện log JSON không xuất hiện và `.env` không được nạp, kèm giải thích nguyên nhân | Claude chạy lệnh kiểm tra trong venv của tôi (`allowed_origins` = `['*']`, root logger level = WARNING); tôi đọc lại kết quả và đối chiếu với `app.py` dòng 24-31 và `config.py` để hiểu nguyên nhân |
| 2026-11-26 | Claude Code: hướng dẫn CP2 và soạn Exercise 2.1 (4 câu hỏi về `02-docker/develop/Dockerfile`) | Câu trả lời cho base image, WORKDIR, thứ tự layer/cache, CMD vs ENTRYPOINT (kèm exec form vs shell form) và các quan sát thêm (`.dockerignore` ở gốc repo, container chạy root) | Đối chiếu từng số dòng với Dockerfile; kích thước `python:3.11` (1054 MB) và `python:3.11-slim` (119 MB) đo trên máy tôi bằng `docker image inspect`; sẽ tự chạy thí nghiệm ghi đè CMD và `whoami` ở 2.2 để kiểm chứng |
| 2026-11-26 | Claude Code: chẩn đoán `docker build` bị treo; trình bày Exercise 2.2 từ output tôi tự chạy | Nguyên nhân: Docker Desktop mất kết nối tới VM (`no route to host`), nghi do dịch vụ ExpressVPN; cách khắc phục. Định dạng output 2.2 và bảng quan sát | Tự dừng ExpressVPNService, khởi động lại Docker, build lại thành công (20,35 s rồi 0,2 s); mọi số liệu (thời gian build, 1.15GB, `root`, PID 1) lấy từ terminal của tôi |
| 2026-11-26 | Claude Code: trình bày Exercise 2.3 (multi-stage) từ output build, `docker images`, `whoami/which gcc`, `docker history` tôi tự chạy | Giải thích 2 stage, lý do image nhỏ hơn, tính % chênh lệch, bảng quan sát layer | Số đo 1.15GB / 163MB và % (≈85.8%) tự kiểm lại từ `docker images`; đối chiếu tổng layer trong `docker history` với 163 MB |
| 2026-11-26 | Claude Code: vẽ sơ đồ và trình bày Exercise 2.4 từ output compose/curl/rate-limit tôi tự chạy | Sơ đồ kiến trúc 4 service, bảng quan sát (rate limit 22×200 rồi 429, agent không publish cổng, IP nginx, agent chưa dùng Redis/Qdrant) | Claude chạy thêm `compose ps` (agent `healthy`) và `docker network inspect` để xác nhận 172.20.0.5 là nginx; tôi đối chiếu sơ đồ với `docker-compose.yml`, `nginx.conf`, `main.py` |
| 2026-11-26 | Claude Code: hướng dẫn CP3 và trình bày Exercise 4.1 từ output curl/log tôi tự chạy | Trả lời 3 câu hỏi (check key ở đâu, sai key thì sao, rotate key) và bảng quan sát (in key ra log, key mặc định, gợi ý curl sai, timing attack) | Mã 401/403/200 và log lấy từ terminal của tôi; đối chiếu số dòng 35-93 trong `develop/app.py` |
| 2026-11-26 | Claude Code: trình bày Exercise 4.2 (JWT) từ output curl/log tôi tự chạy | Sơ đồ JWT flow, so sánh với API key, bảng quan sát (payload đọc được, exp−iat=3600, lỗi `budget_remaining_usd`, header `server` không xoá được, `JWT_SECRET` mặc định) | Token đã che trước khi đưa vào bài; tự tính exp−iat từ payload đã giải mã; đối chiếu số dòng trong `auth.py` và `app.py` |
| 2026-11-26 | Claude Code: thiết kế thí nghiệm restart / đổi `JWT_SECRET` và trình bày Exercise 4.3 từ output tôi tự chạy | Trả lời 3 câu hỏi (sliding window, 10/100 req/phút, admin dùng limiter riêng), kết luận 3 thí nghiệm, phát hiện `X-RateLimit-Reset` mâu thuẫn với `Retry-After` | Tôi chạy toàn bộ lệnh; đo giờ trước/sau restart để chắc chắn còn trong cửa sổ 60 giây: 429 lúc 15:54:54 → restart → 200 lúc 15:55:06 (12 giây); tự kiểm tra reset = now+60 từ timestamp |
| 2026-11-26 | Claude Code: trình bày Exercise 4.4 (cost guard) từ output `/me/usage` tôi tự chạy, và đề xuất cách implement bằng Redis | Giải thích luồng check/record, bảng nhận xét (state trong RAM, `_global_today` không được dùng nên tổng toàn hệ thống không reset, race condition, múi giờ), code mẫu Redis $10/tháng | Tự tính lại cost 2 input + 30 output token = $0.0000183 khớp `cost_usd`; Claude grep xác nhận `_global_today` chỉ xuất hiện ở dòng 50; code Redis sẽ được tôi dùng và kiểm tra thật ở Part 6 |
| 2026-11-26 | Claude Code: hướng dẫn CP4 và trình bày Exercise 5.1, 5.2 từ output tôi tự chạy | Bảng liveness vs readiness, so sánh SIGTERM vs SIGKILL, phát hiện `time.sleep` trong `async def` khoá event loop (2 request ~6.6 s), vòng chờ in-flight trong lifespan không có tác dụng, `/ready` không kịp trả 503 khi tắt | mọi thời gian (3.016 s, 6.6 s, 16:11:01→16:11:10), mã 200/000 và log là của tôi; đối chiếu số dòng trong `develop/app.py` |
| 2026-11-26 | Claude Code: trình bày Exercise 5.3, 5.4, 5.5 từ output Docker/curl/`test_stateless.py` và thí nghiệm tắt instance tôi tự chạy | Giải thích anti-pattern vs Redis, bảng quan sát round-robin, phát hiện lỗi đếm `turn` (off-by-one), fallback RAM âm thầm, đọc–sửa–ghi không nguyên tử, Nginx chỉ resolve DNS lúc khởi động | Đọc code xác nhận 5.3; mọi output (instance ID, 3/3/4, history 10 và 8 message, turn 3-4-5) là của tôi; tự đối chiếu: 4 lượt hỏi nhưng turn báo tới 5 → xác nhận off-by-one ở `app.py` dòng 140-154; đã `down` stack |
| 2026-11-26 | Claude Code: đọc `check_production_ready.py` để liệt kê điều kiện chấm, hướng dẫn CP5 kèm code mẫu cho từng TODO (config, redis_client, auth, rate_limiter, cost_guard, main, Dockerfile, .dockerignore, compose, railway.toml) | Code cho 12 tiêu chí và giải thích từng lựa chọn (venv trong Dockerfile, `exec` để uvicorn là PID 1, Redis sorted set, INCRBYFLOAT, JSON formatter với `force=True`, `def` thay `async def`) | Tôi tự đưa code vào từng file, tôi tự chạy `--static-only` (0/12) → `docker compose up` → `check_production_ready.py` đầy đủ: PASS 12/12, 41/41, image 183 MB, docker stop 0.7 s |
| 2026-11-26 | Claude Code: chẩn đoán lỗi 400 `Invalid HTTP request received` khi test tay `/ask` | Nguyên nhân: `.env` dùng CRLF, key lấy bằng `grep` + `cut` dính `\r` (6 ký tự), còn Docker Compose đọc đúng 5 ký tự; cách sửa `tr -d '\r'` | Tôi chạy lại với `tr -d '\r'`: 200/200/401/200/422 đúng như mong đợi, tự kiểm lại cost 1.2e-05 từ số token |
| 2026-11-26 | Claude Code: hướng dẫn CP6, soạn `DEPLOYMENT.md` và mục Part 3 (so sánh railway.toml/render.yaml, pipeline Cloud Run) | Các lệnh deploy, nội dung DEPLOYMENT.md, bảng so sánh, mô tả pipeline và các điểm cần lưu ý (render.yaml thiếu REDIS_URL, cloudbuild thiếu tests/, PORT trong service.yaml) | Tôi tự chạy deploy và 4 lệnh tự kiểm: 200/200/401/200 và chụp các minh chứng. |
| 2026-11-26 | Claude Code: hướng dẫn CP7, sửa `KNOWLEDGE_BASE` (thêm tài liệu cho `scaling-03`, `security-02`), phát hiện lần đo `MOCK_SLOW_RATE=0` không nhận biến môi trường, điền phần 1–3 của `BENCHMARK_REPORT.md` | 2 mục KB mới (đã thử retrieval với 23 câu: không regression), cách đo lại ở cổng 8003, bảng số liệu + nhận xét (Little's law, p99 vs avg, cost / câu đúng), job CI | Tôi tự chạy toàn bộ load test và eval (v2_fixed 23/23, exit code v2=0 / v1=1); đo lại slow_0 đến khi max=236.1 ms; Claude đối chiếu tự động mọi số trong bảng với file JSON trong `reports/` |
