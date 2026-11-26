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
