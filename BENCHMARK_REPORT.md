# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây lấy từ file JSON trong `reports/` (load test, eval) — chạy thật, không ước lượng.

**Họ tên:** Trần Thị Nhài
**Ngày chạy:** 2026-11-26
**Môi trường:** Laptop Windows 11, AMD Ryzen 5 5600H (6 nhân / 12 luồng), RAM 7.3 GB; chạy trong WSL2 Ubuntu (giới hạn 3 GB RAM), Python 3.12.3. Phần 2–3: agent `develop/app.py` chạy trực tiếp bằng Python (1 process uvicorn), load generator chạy trên cùng máy. Docker Desktop 28.0.4 dùng cho phần 4–5.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < **500 ms** | LLM mock mất ~150–230 ms/request (p50 ≈ 190 ms ở mọi mức tải bình thường); 500 ms cho 95% người dùng vẫn là cảm giác "phản hồi ngay" và chừa dư địa ~2.5× cho dao động mạng/LLM. Đặt theo **p95** chứ không theo average vì average che mất request chậm (xem 2.2). Đây cũng là ngưỡng mặc định của `load_test.py` |
| Error rate `/ask` | < **2 %** | Upstream LLM (mock) có ~1% lỗi sẵn (`MOCK_ERROR_RATE=0.01`); ngưỡng 2% chấp nhận mức lỗi nền đó nhưng báo động khi lỗi tăng gấp đôi. Error budget = 2% số request. Alert (phần 4) đặt lỏng hơn (5% trong 1 phút) để tránh báo động vì spike ngắn |
| Accuracy trên golden dataset | ≥ **85 %** | v2 sau khi sửa đạt 100%, v2 ban đầu 91.3%; 85% cho phép sai tối đa 3/23 câu khi đổi prompt/model nhưng chặn được bản tệ hẳn (v1: 4.3%). Kèm điều kiện **không có regression** so với bản đang chạy. Đây là ngưỡng dùng trong quality gate CI (mục 3) |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (`MOCK_SLOW_RATE` mặc định 0.03).

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.04 | 188.5 | 220.9 | 1671.9 | 0.00% | ✅ PASS |
| 10 | 40.26 | 189.5 | 221.4 | 1681.9 | 1.00% (3 × 503) | ✅ PASS |
| 50 | 105.89 | 193.9 | 244.0 | 1704.5 | 0.00% | ✅ PASS |
| 100 | 60.56 | 403.9 | 2964.2 | 3225.9 | 2.67% (8 × 503) | ❌ FAIL (cả p95 lẫn error rate) |

File: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS **không tăng tuyến tính** theo concurrency:
- **1 → 10:** tăng gần đúng 10 lần (4.04 → 40.26 RPS) trong khi p50 gần như không đổi (188.5 → 189.5 ms). Agent còn dư sức: mỗi request chủ yếu *chờ* LLM (`asyncio.sleep` trong mock), event loop phục vụ nhiều request chờ cùng lúc.
- **10 → 50:** chỉ tăng 2.6 lần (40.26 → 105.89) thay vì 5 lần. Theo định luật Little, RPS ≈ concurrency / latency = 50 / 0.229 s ≈ 218 RPS nếu không có nghẽn; thực tế chỉ đạt ~106 → hệ thống bắt đầu **bão hoà**: một process uvicorn duy nhất (1 event loop, 1 nhân CPU cho phần Python) phải xử lý JSON, metrics, routing cho mọi request, cộng thêm chính load generator chạy trên cùng máy tranh CPU.
- **50 → 100:** RPS **giảm** (105.89 → 60.56), p50 tăng gấp đôi (403.9 ms), p95 vọt lên 2964 ms, max 4667.9 ms. Khi vượt quá khả năng xử lý, request **xếp hàng**: thời gian chờ trong hàng đợi cộng vào latency, thêm chi phí chuyển đổi giữa hàng trăm kết nối → thông lượng thực giảm. Đây là điểm quá tải: tăng tải thêm không phục vụ thêm được ai mà làm mọi người chậm đi. Error rate 2.67% (8 × `503`) — các lỗi upstream mô phỏng, cộng với tải cao làm SLO lỗi cũng bị vi phạm.
- Với cấu hình này, **mức chịu tải an toàn ~50 request đồng thời (~100 RPS)**; muốn hơn phải scale ngang (nhiều worker / instance — phần 5).

### 2.2 Tail latency

Lệnh: `python load_test.py --url <agent v2> --requests 300 --concurrency 20 --out reports/load_v2_slow_<rate>.json`, khởi động lại agent v2 với `MOCK_SLOW_RATE` tương ứng (mỗi request "slow" bị cộng thêm 1500 ms).

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 188.6 | 215.9 | 228.6 |
| 0.03 (mặc định) | 235.5 | 225.8 | 1699.7 |
| 0.1 | 273.8 | 1670.0 | 1705.5 |

File: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.
*(Lần đo `MOCK_SLOW_RATE=0` dùng một agent v2 riêng ở cổng 8003 với cấu hình giống hệt, chỉ khác cổng — vì vậy `target` trong file là `:8003`. Lần đo đầu tiên vô tình chạy trên agent chưa nhận biến môi trường: kết quả có p99 ≈ 1690 ms, không thể có nếu thật sự không có request chậm, nên tôi đã đo lại.)*

**Nhận xét:**
- **p99 nhạy nhất.** Từ 0 → 3% request chậm: p99 tăng **7.4 lần** (228.6 → 1699.7 ms), trong khi avg chỉ tăng **25%** (188.6 → 235.5 ms) và p95 gần như không đổi (215.9 → 225.8 ms).
- **p95 chỉ "bắt" được khi tỉ lệ chậm vượt 5%.** Với 3% request chậm, 95% request vẫn nhanh nên p95 không đổi; lên 10% thì p95 nhảy lên 1670.0 ms (gấp 7.7 lần) — vi phạm SLO 500 ms.
- **Average che giấu vấn đề.** Ở 10% request chậm, avg = 273.8 ms — nhìn vẫn "ổn" và vẫn dưới 500 ms, trong khi cứ 10 người thì 1 người phải chờ ~1.7 giây. Average trộn số ít request rất chậm với số đông request nhanh nên chỉ tăng nhẹ; người dùng không trải nghiệm "trung bình" mà trải nghiệm từng request của họ. Vì vậy **SLO phải đặt theo percentile (p95/p99)**: p95 để bảo vệ đa số người dùng, p99 để phát hiện tail latency sớm (ở 3% chậm, chỉ p99 báo hiệu).
- Request chậm còn **giảm thông lượng**: với cùng concurrency 20, RPS giảm từ 102.58 (0%) xuống 61.45 (3%) và 58.32 (10%) — mỗi request chậm giữ chỗ 1 trong 20 "slot" đồng thời suốt 1.7 s.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Lệnh:
```bash
python eval/run_eval.py --url http://localhost:8001 --out reports/eval_v1.json
python eval/run_eval.py --url http://localhost:8002 --out reports/eval_v2.json --baseline reports/eval_v1.json
# sau khi sửa KNOWLEDGE_BASE và khởi động lại v2:
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
```

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | **100.0% (23/23)** |
| Avg tokens / câu | 57.4 | 109.0 | 113.7 |
| Tổng cost (USD) | 0.000409 | 0.000759 | 0.000790 |
| Cost / câu đúng (USD) | 0.00040875 | 0.00003616 | 0.00003436 |
| Latency p95 (ms) | 190.0 | 218.9 | 207.5 |
| Quality gate | ❌ FAIL (accuracy < 80%) | ✅ PASS (≥ 80%, 0 regression) | ✅ PASS (≥ 100%, 0 regression so với v2) |

File: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` — "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` | Thêm vào `KNOWLEDGE_BASE` (`develop/utils/mock_llm.py`) tài liệu kích hoạt bởi từ khoá `jwt`: *"API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn; server xác minh chữ ký mà không cần tra database."* |
| `scaling-03` — "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` | Thêm tài liệu kích hoạt bởi `hpa`, `kubernetes`, `autoscal`: *"Kubernetes HPA (Horizontal Pod Autoscaler) scale số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi."* |

Nguyên nhân gốc: v2 trả lời bằng tài liệu tìm được trong `KNOWLEDGE_BASE`; với 2 câu này **không có tài liệu nào khớp** nên v2 trả lời chung chung → thiếu toàn bộ keyword (score 0.00). Chọn từ khoá kích hoạt sao cho **chỉ khớp đúng 2 câu này** (trong 23 câu, chỉ `security-02` chứa "jwt" và chỉ `scaling-03` chứa "kubernetes"/"hpa") để tài liệu mới không "cướp" chỗ tài liệu của câu khác → kết quả eval cuối: **câu được cải thiện 2, regression 0**. Không sửa `golden_dataset.jsonl`.

**Quality gate & chặn merge bằng exit code:** `run_eval.py` trả **exit code 0** khi đạt (accuracy ≥ `--min-accuracy` và không có câu regression so với `--baseline`), **exit code 1** khi không đạt. Đã kiểm chứng:

```text
$ python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.85; echo "exit code v2 = $?"
  Accuracy      : 100.0%  (23/23)
  Quality gate (accuracy ≥ 85%, không regression): ✅ PASS
exit code v2 = 0

$ python eval/run_eval.py --url http://localhost:8001 --min-accuracy 0.85 --baseline reports/eval_v2.json; echo "exit code v1 = $?"
  Accuracy      : 4.3%  (1/23)
  ⚠️  Câu bị regression : 20 ['docker-01', 'docker-02', 'probe-01', ...]
  Quality gate (accuracy ≥ 85%, không regression): ❌ FAIL
exit code v1 = 1
```

Trong CI, một bước trả exit code khác 0 làm cả job **fail**; bật *branch protection* với job này là *required status check* thì pull request **không merge được** cho tới khi eval đạt. Job GitHub Actions:

```yaml
# .github/workflows/eval.yml
name: quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - name: Run agent + eval
        working-directory: 06-lab-complete/benchmark-observability/develop
        run: |
          pip install -r requirements.txt
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
          sleep 3
          python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85
```

(`MOCK_ERROR_RATE=0` để lỗi upstream ngẫu nhiên không làm CI fail ngẫu nhiên — CI phải đo chất lượng câu trả lời, không đo độ ổn định của LLM.)

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chất lượng:** v2 tăng accuracy từ 4.3% lên 91.3% (100% sau khi bổ sung tài liệu) — 20 câu được cải thiện, 0 regression. v1 chỉ đúng 1 câu nhờ câu trả lời có sẵn cho từ "deploy".
- **Chi phí mỗi câu:** v2 tốn **gấp ~1.9 lần** token (109.0 so với 57.4) và gấp ~1.86 lần tổng cost (0.000759 so với 0.000409 USD) vì prompt phải chứa thêm tài liệu tìm được (RAG).
- **Chi phí mỗi câu đúng:** v2 lại **rẻ hơn ~11.3 lần** (0.00003616 so với 0.00040875 USD) — v1 tốn tiền cho 22 câu trả lời sai vô ích. Đây là lý do so sánh hai phiên bản bằng *cost / câu đúng* chứ không phải *cost / câu*: điều người dùng cần là câu trả lời đúng.
- **Latency:** bước retrieval làm p95 tăng ~29 ms (190.0 → 218.9 ms) — nhỏ so với SLO 500 ms. Bổ sung 2 tài liệu chỉ tăng thêm 4.7 token/câu và ~$0.000031 tổng cost.
- **Kết luận:** v2 đáng giá — trả thêm ~2 lần token và ~30 ms để có câu trả lời đúng gần như mọi lúc. Rủi ro cần theo dõi: chất lượng của v2 phụ thuộc hoàn toàn vào việc knowledge base có tài liệu phù hợp — câu hỏi ngoài phạm vi tài liệu sẽ bị trả lời sai mà không có metric hạ tầng nào báo động (thí nghiệm E ở phần 4), nên eval phải chạy định kỳ.

---

## 4. Observability stack (production)

Stack: `production/docker-compose.yml` (agent + Nginx + Prometheus + Grafana + Jaeger + Locust), chạy với `docker compose -p k5-day14-observability ...`. Kiểm tra ban đầu:

```text
$ curl -s -i -X POST http://localhost:8080/ask -H "X-API-Key: day14-lab-key" ... -d '{"question": "Trong distributed tracing, span là gì?"}'
HTTP/1.1 200 OK
x-trace-id: cc6608fd41ec30cc6f6c8e18127dc509
X-Served-By: 172.20.0.4:8000
$ curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/metrics
404
$ docker run --rm -v "$PWD/prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml
Processing test file: /p/alert_rules_test.yml
  SUCCESS
```

**Sự cố khi dựng stack — agent crash `ModuleNotFoundError: No module named 'uvicorn'`.** Lần `up` đầu, cả 2 agent `Restarting (1)` liên tục, Nginx trả 502 cho 100% request. Nguyên nhân trong `production/Dockerfile` có sẵn: `useradd -d /app` đặt HOME của user `agent` là `/app` nên Python tìm package ở `/app/.local`, trong khi thư viện được copy vào `/home/agent/.local`. Sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local` (đúng lỗi CODE_LAB đã cảnh báo; Part 6 tránh được nhờ dùng virtualenv). Các số liệu dưới đây đều đo **sau** khi sửa.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải — [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png): Traffic 17.1 req/s, Error rate 1.08%, p95 296.87 ms, In-flight 8, Instances up 2, LLM cost (1h) $1.0818; biểu đồ latency thấy rõ p99 (~2 s) tách xa p50/avg (~200 ms), biểu đồ req/s thấy 2 đợt benchmark 100 users rồi tải nền
- [x] Một trace chậm trong Jaeger — [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png): trace `1f61d42`, 2.5 s, span `chat mock-llm-small` 1.7 s (mục 4.3)
- [x] Một trace lỗi trong Jaeger — [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png): trace `37b901a`, 87.9 ms, span `chat mock-llm-small` có `error.type = upstream_unavailable` và event `exception`: `utils.mock_llm.LLMError — Upstream LLM error: 503 Service Unavailable (mock)`
- [x] Trang Alerts của Prometheus với **2 alert firing** — [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png): nhóm `agent-slo` FIRING (2): `AgentHighErrorRate` (value 0.1879 = 18.8%) và `AgentHighLatencyP95` (value 1.903 s)

Log JSON tương ứng với trace lỗi (cùng `trace_id`):

```json
{"ts": "2026-11-26T11:51:39.132243+00:00", "level": "INFO", "service": "observable-agent", "instance": "5421c0a72ce8", "event": "llm_error", "trace_id": "37b901aca4d87e0c87947feae6450b13", "span_id": "51f5e4dc259fc008", "request_id": "77afe95d1831", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-26T11:51:39.132759+00:00", "level": "INFO", "service": "observable-agent", "instance": "5421c0a72ce8", "event": "http_request", "trace_id": "37b901aca4d87e0c87947feae6450b13", "span_id": "51f5e4dc259fc008", "request_id": "77afe95d1831", "method": "POST", "route": "/ask", "status": 503, "ms": 87.0}
```

**Trả lời Exercise 7.4:**
1. *p95 và avg; khoảng cách nói lên gì?* Khi chụp dashboard: p95 = 296.87 ms; trên biểu đồ latency avg ~250 ms, p50 ~200 ms nhưng p99 ~2 s. p95 và avg gần nhau nghĩa là phần lớn request đồng đều; khoảng cách lớn giữa avg và p99 là *tail latency* do ~3% request bị LLM chậm thêm 1.5 s (`MOCK_SLOW_RATE=0.03`) — đúng như phần 2.2.
2. *Nginx chia đều traffic cho 2 instance không?* Có. Ở benchmark 3 instance (mục 5) Prometheus thấy đủ 3 target `up=1` sau ~25 s nhờ `dns_sd_configs` + `server agent:8000 resolve`, và tải tách đều theo round-robin; ở bài 5.4 (Part 5) đếm log được 3/3/4 request trên 3 instance.
3. *Vì sao input tokens/s lớn hơn output tokens/s?* Agent v2 làm RAG: prompt gồm câu hỏi **cộng tài liệu tìm được** từ knowledge base, nên dài hơn câu trả lời. Đo ở thí nghiệm E: v2 input 1259.8 token/s so với output 649.5 token/s (gấp ~1.9 lần).
4. *`curl http://localhost:8080/metrics` trả gì?* **404** — Nginx chặn `location = /metrics { return 404; }`. `/metrics` lộ thông tin nội bộ (route, version, chi phí, số lỗi) nên chỉ cho Prometheus scrape trực tiếp từng agent trong mạng nội bộ Docker, không public qua load balancer.

### 4.2 Thí nghiệm "phá hệ thống"

Tải nền chạy suốt thí nghiệm (Locust 30 users, sau đó `load_test.py` 10 request song song qua Nginx). Thời gian đo bằng script hỏi `GET /api/v1/alerts` của Prometheus mỗi 5 giây; T0 = lúc agent được tạo lại với cấu hình mới.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (value 0.1879 ≈ 18.8% > 5%) | Lần 1: pending +33 s → **firing +94 s**. Lần 2: pending +10 s → **firing +75 s** | *Error rate* (Golden Signals) chuyển đỏ; *Requests/s theo status code* thấy đường `503` tăng; Jaeger có nhiều trace `error=true` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (value 1.903 s > 1 s) | Lần 1: pending +23 s → **firing +143 s**. Lần 2: pending +10 s → **firing +137 s** | *Latency /ask — p50/p95/p99*: p95 vọt lên ~1.9 s, avg tăng ít hơn; *LLM latency p95* |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | Không đổi model riêng; alert này **đã firing do tải**: 2 đợt benchmark 100 users đẩy *Cost burn rate* lên ~$8/giờ > ngưỡng $2/giờ (`activeAt` 18:55:17, đang firing lúc 19:01:19); khi chạy lại với 10 request song song (thí nghiệm D), alert này lại firing lúc 19:55:45 | *Cost burn rate (USD/giờ)*, *LLM cost (1h)* |
| D | `docker pause` 1 instance | `AgentInstanceDown` (instance `172.18.0.5:8000`, `up=0`) | pending +13 s → **firing +46 s** | *Instances up* giảm 2 → 1; *Requests/s theo instance* mất 1 đường |
| E | `AGENT_VERSION=v1` | **Không có alert nào** (theo dõi 150 s: `no active alerts`) | — | *Tokens/s* giảm, *Retrieval hit ratio* mất số liệu, bảng *version* đổi sang v1 |

Ảnh `prometheus-alert-firing.png` chụp ở **lần 2** của thí nghiệm A+B (A và B bật cùng lúc).

**Phân tích:**
- **Thời gian tới firing ≈ thời gian rule bắt đầu đúng + `for`.** A: pending +10 s, `for: 1m` → firing +75 s; B: `for: 2m` → firing +137 s; D: `for: 30s` → firing +46 s. Phần lẻ là chu kỳ đánh giá 5 s + thời gian cửa sổ `rate(...[1m])` tích luỹ đủ dữ liệu xấu. Lần 1 của A chậm hơn (pending +33 s) vì agent vừa tạo lại, cửa sổ 1 phút còn lẫn dữ liệu tốt của bản cũ.
- **`for` chống báo động giả nhưng làm phát hiện chậm hơn:** B mất >2 phút mới firing dù p95 đã xấu từ giây thứ 10. Đây là đánh đổi chủ động giữa *alert fatigue* và tốc độ phát hiện; alert latency có `severity: warning` nên chấp nhận chờ lâu hơn alert lỗi (`critical`, `for: 1m`).
- **D — Nginx che lỗi cho người dùng:** trong lúc instance bị pause, 12/12 request gửi qua Nginx vẫn trả **200**, error rate theo metric của agent chỉ 0.95%. Nginx cấu hình `proxy_next_upstream error timeout` + `proxy_read_timeout 10s`: request rơi vào container bị pause chờ hết 10 s rồi được chuyển sang instance còn sống (client chậm thêm, không lỗi), sau đó Nginx tạm loại instance lỗi. Nếu không có retry này, client sẽ nhận 504 — và 504 sinh ra ở Nginx nên **không xuất hiện trong metric của agent**; chỉ `AgentInstanceDown` (Prometheus không scrape được) mới phát hiện. Vì sao phải `pause` chứ không `stop`: container bị stop biến mất khỏi DNS → Prometheus coi như target không còn tồn tại (không phải "down") nên không có alert; container bị pause vẫn còn trong DNS nhưng không trả lời → `up == 0`.
- **Sự cố ngoài kế hoạch:** trong lúc chờ chụp ảnh lần 1, máy hết RAM, WSL2 treo, cả 2 agent `unhealthy` và `AgentInstanceDown` firing cho cả 2 instance — chính alert availability đã bắt được sự cố hạ tầng thật. Sau khi khôi phục, tôi chạy lại A+B (lần 2) để chụp ảnh.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Số đo khi đổi v2 → v1 (cùng tải 4 request song song, mỗi mốc là `rate(...[1m])`):

| Chỉ số | v2 | v1 (sau 150 s) |
|---|---|---|
| Req/s `/ask` | 17.18 | 20.75 |
| Error rate | 1.06% | 1.40% |
| p95 | 0.293 s | 0.197 s |
| Input / output tokens/s | 1259.8 / 649.5 | 719.9 / 405.2 |
| Retrieval (hit/s) | 17.20 | không còn số liệu (v1 không retrieval) |
| Cost (USD/giờ) | 2.08 | 1.26 |
| Alert | không | **không** |

Mọi chỉ số hạ tầng đều **đẹp hơn** (nhanh hơn, rẻ hơn ~40%) trong khi chất lượng sụp từ 100% xuống 4.3% (eval phần 3). Metrics hạ tầng chỉ đo *hệ thống có chạy không*, không đo *câu trả lời có đúng không*. Cách phát hiện:
1. **Quality gate trước khi deploy:** chạy `run_eval.py` trong CI (phần 3) — v1 trả exit code 1 với 20 câu regression → chặn ngay từ pull request, không lên production được.
2. **Eval định kỳ trên production:** cron chạy golden dataset vào bản đang chạy (ví dụ mỗi giờ), đẩy `eval_accuracy` thành metric và đặt alert `eval_accuracy < 0.85`.
3. **Metric proxy cho chất lượng:** alert khi *retrieval hit ratio* giảm mạnh hoặc mất (v1 không còn `agent_retrieval_total`), khi số token/câu thay đổi bất thường, hoặc khi `agent_info{version}` đổi ngoài lịch deploy.
4. **Tín hiệu từ người dùng:** tỉ lệ 👍/👎, tỉ lệ hỏi lại, LLM-as-judge chấm mẫu ngẫu nhiên một phần nhỏ traffic thật.

### 4.3 Debug bằng trace

Chọn trace chậm nhất **có thời gian khớp với log** (xem ghi chú bên dưới):

- `trace_id`: `1f61d42925ea6b12304184e33e21caeb`
- Tổng thời gian: **2479.2 ms** (span `POST /ask`; log của agent ghi `"ms": 2478.5`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small` — 1674.8 ms (67.6%)**; `agent.run` 1776.3 ms (71.6%), `agent.retrieve_context` 101.3 ms (4.1%)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-26T11:45:40.482195+00:00", "level": "INFO", "service": "observable-agent", "instance": "5421c0a72ce8", "event": "llm_call", "trace_id": "1f61d42925ea6b12304184e33e21caeb", "span_id": "d57a07f2dae3d2af", "request_id": "25d7d1783300", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 72, "output_tokens": 40, "cost_usd": 3.5e-05, "llm_ms": 1675.3}
{"ts": "2026-11-26T11:45:40.482836+00:00", "level": "INFO", "service": "observable-agent", "instance": "5421c0a72ce8", "event": "http_request", "trace_id": "1f61d42925ea6b12304184e33e21caeb", "span_id": "d57a07f2dae3d2af", "request_id": "25d7d1783300", "method": "POST", "route": "/ask", "status": 200, "ms": 2478.5}
```

**Đọc trace:**
- Request chậm vì **gọi LLM** (1.67 s — một request "slow" của mock, cộng thêm ~1.5 s), không phải vì code của agent: retrieval chỉ 101 ms. Log `llm_ms: 1675.3` khớp span 1674.8 ms.
- **~700 ms nằm ngoài `agent.run`:** span `POST /ask` 2479 ms nhưng `agent.run` chỉ bắt đầu sau ~0.7 s. Trace này thuộc đợt benchmark 1 instance (100 users, agent giới hạn `cpus: 0.5`) — request phải **xếp hàng** trong process trước khi handler chạy. Trace cho thấy được thời gian chờ này, điều mà metric `llm_request_duration_seconds` không thấy.

**Ghi chú về các trace "chậm nhất" bị phóng đại:** sắp xếp *Longest First*, Jaeger đưa lên đầu các trace ~5–6.5 s (ví dụ `f78c9f34…` = 6556.5 ms) nhưng log của chính request đó ghi `"ms": 1697.5`. Đối chiếu 940 trace chậm có log: 725 trace khớp (lệch < 30 ms), **212 trace bị phóng đại 3.5–4.9 s**. Nguyên nhân: OpenTelemetry đo span bằng **đồng hồ thực** (wall clock), còn app đo bằng **đồng hồ monotonic**; đồng hồ của VM Docker/WSL bị chỉnh nhảy (kernel log ghi *"Time jumped backwards"*) nên span nào đi qua lúc chỉnh giờ bị cộng sai. Bài học: không tin tuyệt đối duration của trace — đối chiếu với log/metric qua `trace_id`.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh: `docker compose -p k5-day14-observability run --rm locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_<n>`; giữa 2 lần chạy `up -d --scale agent=3`, chờ 25 s và xác nhận Prometheus thấy đủ 3 target `up=1`. Số liệu dòng `POST /ask` trong `benchmark-results/scale_1_stats.csv`, `scale_3_stats.csv`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 54.02 | 200 | 500 | 1700 | 68 / 7011 (0.97%) — 68 × `503` |
| 3 | 54.49 | 190 | 300 | 1700 | 70 / 7067 (0.99%) — 68 × `503`, 2 × `502` |

(Dòng *Aggregated* gồm cả `/health`: 59.40 → 59.87 req/s, p95 410 → 280 ms.)

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?
- **p95 cải thiện 500 → 300 ms (−40%)**, p50 gần như không đổi (200 → 190 ms). Với 1 instance (giới hạn 0.5 CPU), lúc tải cao request phải xếp hàng trong process (thấy rõ ở trace mục 4.3: ~700 ms chờ trước khi handler chạy) → đuôi p95 dài ra; 3 instance chia tải nên hàng đợi ngắn lại.
- **RPS gần như không đổi (54.0 → 54.5)** vì giới hạn nằm ở **phía tạo tải**, không phải server: Locust mô phỏng 100 người dùng, mỗi người nghỉ 0.5–2 s (trung bình 1.25 s) giữa 2 lần gọi. Trần lý thuyết ≈ 100 / (1.25 s + ~0.25 s phản hồi) ≈ 67 request/s cho mọi endpoint, ~10/11 trong đó là `/ask` → ~60 req/s. Server đã phục vụ gần sát trần đó ngay với 1 instance nên thêm instance không làm tăng thông lượng; muốn thấy RPS tăng phải tăng số user.
- **p99 = 1700 ms ở cả hai cấu hình** — nút thắt thật sự là **latency của LLM**: ~3% request bị mock LLM chậm thêm 1.5 s, scale ngang không làm LLM nhanh hơn. Đúng như gợi ý "xem panel LLM latency".
- **Error rate không đổi (~1%)** vì lỗi đến từ upstream LLM (`MOCK_ERROR_RATE=0.01` → `503`), không phải do quá tải; 2 lỗi `502` ở lần 3 instance xuất hiện lúc 11:48:11 khi Nginx vừa nhận instance mới qua DNS — lỗi chuyển tiếp lúc scale.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average nói dối, percentile mới nói thật.** Ở 10% request chậm, avg = 273.8 ms vẫn "đẹp" nhưng p95 = 1670 ms; ở 3% thì chỉ p99 phản ánh (228.6 → 1699.7 ms). SLO và alert phải đặt theo p95/p99. Scale ngang cải thiện p95 (500 → 300 ms) nhưng không chạm được p99 vì nút thắt ở LLM.
  2. **Metrics hạ tầng không đo được chất lượng.** Đổi sang v1 làm accuracy rơi từ 100% xuống 4.3% mà dashboard còn đẹp hơn và không alert nào kêu. Chất lượng phải được bảo vệ bằng eval + quality gate trong CI (exit code 1 chặn merge) và eval định kỳ trên production.
  3. **Ba trụ cột phải đối chiếu với nhau, không tin một nguồn duy nhất.** Metric báo *có vấn đề* (p95, error rate), trace chỉ *ở bước nào* (span LLM 67.6%, ~700 ms xếp hàng), log cho *chi tiết* — nối với nhau bằng `trace_id`. Chính việc đối chiếu trace với log đã lộ ra 212 trace bị phóng đại do đồng hồ VM nhảy, và `X-Trace-ID` trên response giúp đi từ lỗi người dùng báo tới đúng trace.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Chất lượng:** metric `eval_accuracy` từ eval định kỳ + alert `< 0.85`; metric *retrieval hit ratio* + alert khi giảm đột ngột hoặc biến mất; tỉ lệ phản hồi tiêu cực của người dùng.
  - **Tầng load balancer / bên ngoài:** metric và alert cho `5xx` tại Nginx (504/502 không hiện trong metric của agent — thí nghiệm D), và **synthetic check** từ bên ngoài gọi `/ask` mỗi phút (như 4 lệnh tự kiểm ở Railway).
  - **SLO burn-rate alert nhiều cửa sổ** (ví dụ 5 phút và 1 giờ) thay cho ngưỡng cố định, để báo sớm khi error budget bị đốt nhanh mà vẫn ít báo động giả.
  - **Saturation:** CPU/memory của từng container và độ dài hàng đợi (in-flight) kèm alert — trace 4.3 cho thấy request đã xếp hàng ~700 ms trước khi alert latency kịp phát hiện.
  - **Chi phí theo người dùng/API key** và alert budget theo ngày (nối với cost guard Part 6), cùng alert khi `agent_info{version, model}` thay đổi ngoài lịch deploy.
  - **Đồng bộ đồng hồ (NTP) cho host** và đo latency bằng đồng hồ monotonic để trace không bị phóng đại.
