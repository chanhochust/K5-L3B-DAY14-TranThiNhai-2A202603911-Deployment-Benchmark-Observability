# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây lấy từ file JSON trong `reports/` (load test, eval) — chạy thật, không ước lượng.

**Họ tên:** Tran Thi Nhai
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

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
