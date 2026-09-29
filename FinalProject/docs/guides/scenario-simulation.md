# Scenario simulation — 11 kịch bản vận hành

Hướng dẫn từng bước để tái hiện 11 tình huống vận hành trên stack local, kèm **kết quả mong đợi** và **bằng chứng
đã đo** (từ [`reports/simulations/`](../../reports/simulations/), Alertmanager webhook và log ngày 28/09/2026, giờ UTC).
Dùng cho demo, QA ([`docs/qa/`](../qa/README.md)) và diễn tập on-call.

## Chuẩn bị chung

```bash
cd FinalProject
make up                                           # 15 service healthy (xem local-quickstart.md)
source .venv/bin/activate
export API_URL=http://localhost:18020
export API_KEY=$(grep -E '^API_KEYS=' .env | cut -d= -f2 | cut -d, -f1)
export COMPOSE_PROFILES=core,monitoring,orchestration
dc() { docker compose -f deploy/compose/docker-compose.yml --env-file .env "$@"; }   # helper cho bash/zsh
make alerts                                       # kỳ vọng: không có alert firing
```

Mở sẵn: Grafana <http://localhost:13000> (4 dashboard), Prometheus alerts <http://localhost:19090/alerts>,
Alertmanager <http://localhost:19093>, Airflow <http://localhost:18080>, webhook <http://localhost:19095/alerts>.

**Kênh thông báo:** mọi alert đi tới `alert-webhook` (luôn bật, xem bằng `make alerts`). Có `TELEGRAM_BOT_TOKEN` +
`TELEGRAM_CHAT_ID` trong `.env` thì đồng thời gửi Telegram với cùng nội dung.

**Sau mỗi kịch bản:** `make chaos-restore` (nếu có dùng chaos) → `make simulate SCENARIO=normal` → `make alerts` cho tới
khi mọi alert `resolved`.

| # | Kịch bản | Lệnh chính | Alert / tín hiệu | Thời gian |
|---|---|---|---|---|
| 1 | Ngày bình thường | `simulate SCENARIO=normal` | Không alert, PSI < 0.1 | 3 phút |
| 2 | Gen-Z drift → retrain | `simulate SCENARIO=drift`, `drift-dag` | `DataDriftDetected` → `model_retrain` | 10 phút |
| 3 | Promote không downtime | `retrain-dag` / `manage_registry.py promote` + reload | 0 lỗi khi đổi model | 5 phút |
| 4 | Retrain trượt gate | `retrain-fail` | `RetrainFailed` | 5 phút |
| 5 | Rollback model | `make rollback` + reload | 0 lỗi, về version trước | 3 phút |
| 6 | API down | `chaos-api-down` / `simulate SCENARIO=outage` | `APIDown` → resolved | 5 phút |
| 7 | Latency spike | `chaos-latency` + `simulate SCENARIO=load` | `HighLatencyP95` | 8 phút |
| 8 | Input sai / thiếu key | curl 4xx; `chaos-model-unloaded` | 4xx chuẩn; `HighErrorRate` (5xx) | 8 phút |
| 9 | MLflow / Postgres down | `dc stop postgres`, `dc stop mlflow` | readiness `degraded`, `ModelServedFromFallback` | 8 phút |
| 10 | Tấn công nợ quá hạn | `simulate SCENARIO=attack` | DECLINE tăng, `PredictionDistributionShift` | 5 phút |
| 11 | Fairness trước/sau | `make responsible-ai` | DI/DPD/EOD cải thiện | 5–10 phút |

---

## Kịch bản 1 — Ngày bình thường

**Mục tiêu:** xác lập baseline — traffic cùng phân phối với dữ liệu train không gây drift hay alert.

**Bước:**

```bash
make simulate SCENARIO=normal SIM_ARGS="--count 2500"
curl -s localhost:18085/drift/latest | jq '{is_drifted, drift_share, max_psi, prediction_psi, current_samples}'
make alerts
```

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo (`normal_20260928T125811Z.json`) |
|---|---|---|
| Lỗi | 0 | 2500 request, 0 lỗi, 100 % HTTP 200 |
| Latency client | p95 < 100 ms | p95 39.9 ms |
| Quyết định | REVIEW ≈ 55 %, APPROVE ≈ 26 %, DECLINE ≈ 20 % | 54.6 % / 25.7 % / 19.6 % |
| Drift | `is_drifted=false`, max PSI < 0.10 | drift share 0.0, max PSI 0.0226, prediction PSI 0.023 |
| Alert | Không có | none |

**Kiểm chứng:** Grafana *Infra & SLA* toàn xanh (success ratio 100 %, p95 < 100 ms); *Data Drift* hiển thị
`Dataset drift = No`; *Business KPIs* có tỉ lệ duyệt như trên.

## Kịch bản 2 — Chiến dịch Gen-Z gây data drift → retrain tự động

**Mục tiêu:** chiến dịch marketing thu hút khách < 30 tuổi (tuổi TB 26 so với 38 của tập train) → drift monitor phát
hiện → alert → Airflow trigger retrain.

**Bước:**

```bash
make simulate SCENARIO=drift                          # 600 request từ stream_drifted.csv + persona campaign_drift
curl -s -X POST localhost:18085/analyze | jq '{is_drifted, drift_share, max_psi, prediction_psi, reasons}'
# chờ ~2 phút (for: 2m) rồi:
make alerts                                           # DataDriftDetected firing
make drift-dag                                        # không chờ lịch 30 phút
```

Trong Airflow UI → DAG `drift_monitoring` → run mới nhất: `run_drift_analysis` → `decide` → `alert_drift` +
`check_retrain_cooldown` → `trigger_model_retrain` (bỏ qua nếu đã retrain trong 60 phút — `RETRAIN_COOLDOWN_MINUTES`).
Sau đó DAG `model_retrain` có run mới.

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo (`drift_20260928T115745Z.json`) |
|---|---|---|
| Drift | `is_drifted=true`, AGE PSI ≥ 0.25 hoặc share ≥ 0.5 | drift share 0.7391, max PSI 3.3354, prediction PSI 0.24 |
| Quyết định | DECLINE tăng so với baseline | DECLINE 34.2 % (baseline 19.6 %) |
| Alert | `DataDriftDetected` firing → webhook/Telegram | firing 12:00:31, resolved 12:03:31 (sau khi chạy lại traffic normal) |
| Airflow | `trigger_model_retrain` success, `model_retrain` được tạo | run `model_retrain` thật: challenger v2 ROC-AUC 0.7485 vs champion 0.7507 → gate giữ champion (xem kịch bản 3) |

**Resolve:** `make simulate SCENARIO=normal SIM_ARGS="--count 600"` — cửa sổ 500 log mới nhất trở lại phân phối cũ,
alert resolve sau ~2–3 phút.

## Kịch bản 3 — Retrain thành công → promote champion không downtime

**Mục tiêu:** challenger tốt hơn được promote thành `@champion`, API hot-reload trong khi vẫn đang nhận traffic, không
có request lỗi.

**Đường tự động (Airflow):** `make retrain-dag REASON="scenario 3"` → `train_challenger` → `quality_gate` →
`decide_promotion` → `promote_champion` → `reload_api` (kiểm tra API thật sự phục vụ version mới, sai thì
`rollback_champion`) → `refresh_drift_reference` → `notify_promoted`. Gate chỉ promote khi challenger **tốt hơn**
(ROC-AUC không giảm quá 0.005, expected loss không tăng, cải thiện ít nhất một chỉ số); nếu không, nhánh
`keep_champion` chạy và DAG vẫn **success** (không phải lỗi).

> Với dữ liệu hiện tại, retrain thật cho challenger kém hơn champion một chút (0.7485 vs 0.7507) nên gate giữ champion
> — đúng thiết kế. Nhánh promote → reload → rollback đã được kiểm chứng bằng `airflow tasks test`. Để demo hot reload
> dưới traffic một cách tất định, dùng đường thủ công dưới đây.

**Đường thủ công (tất định, dùng cho demo):**

```bash
make registry                                         # chọn một version đã đăng ký, vd. @challenger = 5
make simulate SCENARIO=normal SIM_ARGS="--count 1500" &   # traffic chạy nền
sleep 5
python scripts/manage_registry.py promote 5 --reason "scenario 3 demo"
curl -s -X POST -H "X-API-Key: $API_KEY" $API_URL/api/v1/model/reload | jq '{status, previous_version, v: .model.model_version}'
wait                                                  # đợi simulation xong, đọc Summary
```

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo (28/09 13:32) |
|---|---|---|
| Reload | `{"status":"reloaded","previous_version":"1","v":"5"}` | đúng như kỳ vọng, reload < 1 s |
| Lỗi trong lúc đổi model | 0 | Prometheus `increase(credit_api_requests_total{endpoint="/api/v1/predict"}[10m])`: 838 × 200, không có 5xx |
| Chuyển version | Request trước reload → v cũ, sau → v mới | `inference_logs`: v1 tới 13:32:05, v5 từ 13:32:05 |
| Readiness | `ready`, `mlflow_registry version 5` | đúng |

**Kiểm chứng:** Grafana *ML Model* → *Model in production* đổi version, *Reloads OK (24h)* tăng 1. Khôi phục: kịch bản 5.

## Kịch bản 4 — Retrain trượt quality gate

**Mục tiêu:** retrain lỗi thật (challenger dưới sàn chất lượng) → không promote, champion giữ nguyên, alert
`RetrainFailed`.

**Bước:**

```bash
make registry | grep -A3 aliases                      # ghi lại @champion hiện tại
make retrain-fail                                     # trigger model_retrain với min_roc_auc = 0.99
# Airflow UI: train_challenger success → quality_gate FAILED ("ROC-AUC 0.7x < floor 0.9900")
make alerts                                           # RetrainFailed firing (for: 0)
make registry | grep -A3 aliases                      # @champion không đổi; version mới gắn @challenger
```

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo |
|---|---|---|
| DAG | `failed` ở `quality_gate` (AirflowFailException, không retry) | đúng |
| Registry | `@champion` giữ nguyên, challenger → `@challenger` | đúng |
| Metric | `credit_retrain_last_run_failed = 1` | đúng |
| Alert | `RetrainFailed` (critical) firing → webhook/Telegram | firing 11:35:11, resolved 11:37:11 |

**Resolve:** `make retrain-dag` — run thành công kế tiếp (kể cả khi gate giữ champion) đặt gauge về 0 → alert resolve.

## Kịch bản 5 — Rollback model

**Mục tiêu:** model mới cho kết quả xấu trong production → quay `@champion` về version trước ngay lập tức, không
downtime.

**Bước:**

```bash
make simulate SCENARIO=normal SIM_ARGS="--count 1500" &
sleep 5
make rollback                                         # @champion ← @previous_champion (hoặc VERSION=<n>)
curl -s -X POST -H "X-API-Key: $API_KEY" $API_URL/api/v1/model/reload | jq '{status, previous_version, v: .model.model_version}'
wait
curl -s -X POST localhost:18085/reference/refresh     # chấm lại reference drift bằng champion hiện tại
```

`make rollback` chỉ đổi alias (version bị rollback thành `@previous_champion`, gắn tag `rolled_back=true` — rollback lần
nữa sẽ quay lại nó); reload API là bước riêng.

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo (`normal_20260928T133502Z.json`, 13:35) |
|---|---|---|
| Alias | `champion: 1`, `previous_champion: 5` | đúng (`Rolled back ... from version 5 to 1`) |
| Reload | `{"status":"reloaded","previous_version":"5","v":"1"}` | đúng |
| Traffic trong lúc rollback | 0 lỗi | 1500 request, 0 lỗi, p95 42.0 ms, p99 47.6 ms |
| Chuyển version | v5 → v1 liền mạch | `inference_logs`: v5 488 request tới 13:35:10, v1 1012 request từ 13:35:10 |

Rollback **ứng dụng** (image + code) trên server là thao tác khác: `deploy.sh rollback`
([ubuntu-deployment §11](ubuntu-deployment.md#11-rollback)).

## Kịch bản 6 — API down

**Mục tiêu:** API ngừng hoạt động → `APIDown` → thông báo webhook/Telegram → khôi phục → resolved.

**Bước (cách A — đo thời gian phục hồi tự động):**

```bash
make simulate SCENARIO=outage                         # dừng api 90 s trong khi traffic vẫn chạy, rồi bật lại
make alerts
```

**Bước (cách B — thủ công):** `make chaos-api-down` → chờ ~1.5 phút → `make alerts` → `make chaos-restore`.

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo (`outage_20260928T121410Z.json`) |
|---|---|---|
| Downtime | ≈ `--down-seconds` | 94.1 s |
| Phục hồi sau khi start | < 30 s tới `/health/ready` 200 | 7.1 s |
| Traffic | Lỗi `ConnectionError` chỉ trong cửa sổ down | 470 request: 76 × 200, 394 × ConnectionError |
| Alert | `APIDown` (critical) sau 1 phút; `HighErrorRate`/`ModelNotLoaded` bị inhibit | firing 11:41:16, resolved 11:43:16 |
| Thông báo | Webhook nhận `firing` rồi `resolved`; Airflow `service_health_check` gửi thêm `ServiceHealthCheck` | đúng (`make alerts`: `fired=True resolved=True`) |

## Kịch bản 7 — Latency spike / load test

**Mục tiêu:** tài nguyên API bị bóp (CPU) dưới tải cao → p95 vượt SLO 100 ms → `HighLatencyP95`.

**Bước:**

```bash
make bench                                            # baseline: p95 /predict khi chưa chaos
make chaos-latency                                    # docker update --cpus 0.5 api
make simulate SCENARIO=load                           # 32 luồng × 180 s
make alerts                                           # HighLatencyP95 firing (~2–3 phút sau khi bắt đầu load)
make chaos-restore                                    # trả CPU về 2
```

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo |
|---|---|---|
| Baseline (`latency_benchmark.json`) | p95 < 100 ms | p95 20.59 ms, p99 29.49 ms, 500 request, 0 lỗi |
| Dưới tải + 0.5 CPU (`load_20260928T115410Z.json`) | p95 ≫ 100 ms, không 5xx | 5002 request, 0 lỗi, p95 1712.6 ms, 24.9 rps |
| Alert | `HighLatencyP95` (warning) | firing 11:56:31, resolved 12:00:31 (sau `chaos-restore`) |

**Kiểm chứng:** *Infra & SLA* → *Latency /api/v1/predict* p95 vượt đường SLO; *CPU usage* của api chạm 0.5 core.
Load test phân tán bằng Locust là hướng mở rộng tiếp theo ([`tests/load/README.md`](../../tests/load/README.md)).

## Kịch bản 8 — Input sai / thiếu API key

**Mục tiêu:** lỗi phía client trả **4xx chuẩn** (không làm sập service, không tính là lỗi hệ thống); lỗi phía server
(5xx) mới kích hoạt `HighErrorRate`.

**Bước 1 — lỗi client:**

```bash
B=$(python -c "import json;print(json.dumps({'LIMIT_BAL':200000,'SEX':2,'EDUCATION':1,'MARRIAGE':2,'AGE':35,**{k:0 for k in ['PAY_0','PAY_2','PAY_3','PAY_4','PAY_5','PAY_6']},**{f'BILL_AMT{i}':40000 for i in range(1,7)},**{f'PAY_AMT{i}':5000 for i in range(1,7)}}))")
curl -s -H 'Content-Type: application/json' -d "$B" $API_URL/api/v1/predict                          # 401 MISSING_API_KEY
curl -s -H 'X-API-Key: wrong' -H 'Content-Type: application/json' -d "$B" $API_URL/api/v1/predict   # 403 INVALID_API_KEY
curl -s -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' -d '{"LIMIT_BAL":-1,"AGE":12}' $API_URL/api/v1/predict | jq '.code, .details[0]'   # 422
python -c "import json,sys;b=json.loads(sys.argv[1]);print(json.dumps({'applicants':[b]*501}))" "$B" > /tmp/big.json
curl -s -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' -d @/tmp/big.json $API_URL/api/v1/predict/batch | jq .code   # 413 BATCH_TOO_LARGE
curl -s localhost:18020/metrics | grep credit_api_auth_failures_total
```

**Bước 2 — lỗi server (5xx):**

```bash
make chaos-model-unloaded                             # API chạy nhưng không có model → /predict trả 503
make simulate SCENARIO=load SIM_ARGS="--concurrency 4 --duration 240"
make alerts                                           # ModelNotLoaded + HighErrorRate firing
make chaos-restore
```

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo |
|---|---|---|
| 401 / 403 / 422 / 413 | Body chung `{code, message, details, request_id}`; 422 liệt kê từng field, **không** echo giá trị input | đúng (mẫu trong [API reference §4](../04-api-reference.md#4-error-contract)) |
| Metric auth | `credit_api_auth_failures_total{reason="missing"}` và `{reason="invalid"}` tăng; panel *Auth failures* | đúng |
| 4xx và alert | 4xx **không** kích hoạt `HighErrorRate` (rule chỉ đếm 5xx — lỗi client không phải sự cố hệ thống) | đúng |
| 5xx (`load_20260928T114330Z.json`) | 503 `MODEL_UNAVAILABLE` hàng loạt | 133,637 request, 100 % 503 |
| Alert | `ModelNotLoaded` → `HighErrorRate` (critical) | `ModelNotLoaded` 11:44:11 → 11:48:11; `HighErrorRate` 11:46:16 → 11:49:16 |

Tấn công dò key hàng loạt: theo dõi tốc độ `credit_api_auth_failures_total`; production có Nginx rate limit 20 r/s/IP
(`429`).

## Kịch bản 9 — MLflow / Postgres down

**Mục tiêu:** dependency lỗi không làm dừng chấm điểm: API phục vụ bằng model đang giữ trong bộ nhớ hoặc artifact local,
readiness báo đúng trạng thái `degraded`.

**Bước:**

```bash
# 9a. Postgres down: inference log không ghi được, chấm điểm vẫn chạy
dc stop postgres; sleep 12
curl -s $API_URL/health/ready | jq '{status, reasons, db: .checks.database}'
python scripts/sample_predict.py                      # vẫn 200
dc start postgres

# 9b. MLflow down lúc API khởi động: dùng artifact local
dc stop mlflow && dc restart api; sleep 15
curl -s $API_URL/health/ready | jq '{status, reasons, model: .checks.model}'
curl -s localhost:18020/metrics | grep -E '^credit_model_(loaded|degraded) '
dc start mlflow; sleep 20
curl -s -X POST -H "X-API-Key: $API_KEY" $API_URL/api/v1/model/reload | jq '{status, previous_version, v: .model.model_version, src: .model.source}'
```

**Kết quả mong đợi** (đã đo 28/09 13:36–13:37)

| Bước | Readiness (HTTP 200) | Chấm điểm | Ghi chú |
|---|---|---|---|
| 9a Postgres down | `degraded`, `reasons: ["database_unavailable"]`, database `down` ("predictions are not logged") | 200, `served_by: mlflow_registry` | Không mất dịch vụ; chỉ mất audit log trong thời gian down |
| 9b MLflow down + restart API | `degraded`, `reasons: ["model_served_from_local_fallback","mlflow_unreachable"]` | 200, `served_by: local_artifact`, `model_version: credit_model_v1` | `credit_model_loaded 1`, `credit_model_degraded 1` |
| MLflow lên + reload | `ready`, `reasons: []` | `{"status":"reloaded","previous_version":"credit_model_v1","v":"1","src":"mlflow_registry"}` | |
| Alert | `ModelServedFromFallback` (warning) sau 5 phút ở trạng thái degraded | — | Lần đo trước: firing 12:11:26, resolved 12:13:26 |

Chỉ khi **không có model nào** (registry và artifact đều hỏng) readiness mới `not_ready` (503) và Docker/Nginx ngừng
gửi traffic — xem kịch bản 8 bước 2.

## Kịch bản 10 — Tấn công nợ quá hạn có tổ chức

**Mục tiêu:** một nhóm hồ sơ giả mạo (70 % maxed-out, `PAY_0 ≥ 2`) dồn dập nộp đơn → tỉ lệ DECLINE tăng vọt →
`PredictionDistributionShift` cảnh báo dù đây không phải drift tự nhiên.

**Bước:**

```bash
make simulate SCENARIO=attack
curl -s -X POST localhost:18085/analyze | jq '{is_drifted, prediction_psi, max_psi, drift_share}'
make alerts                                           # PredictionDistributionShift (+ DataDriftDetected)
```

**Kết quả mong đợi**

| Chỉ số | Kỳ vọng | Đã đo (`attack_20260928T115925Z.json`) |
|---|---|---|
| Quyết định | DECLINE ≫ baseline 20 % | DECLINE 83 % (498/600), APPROVE 12.2 %, REVIEW 4.8 % |
| Prediction PSI | ≥ 0.25 | 3.8275 (max feature PSI 5.3056, drift share 0.913) |
| Alert | `PredictionDistributionShift` (warning) | firing 12:01:56, resolved 12:02:56 |
| Business | *Business KPIs*: *Decline rate* và *Loss avoided* tăng đột biến | đúng |

**Phản ứng đúng:** đây là tấn công, **không** phải tín hiệu để retrain.

1. Tạm dừng retrain tự động: `docker exec credit-risk-mlops-airflow-scheduler-1 airflow dags pause drift_monitoring`.
2. Xác định nguồn qua `request_id` / log Nginx; thu hồi API key bị lạm dụng (bỏ khỏi `API_KEYS`), siết rate limit.
3. Retrain chỉ dùng dữ liệu có nhãn thật (`ground_truth_feedback`), không dùng traffic tấn công — replay strategy của
   `model_retrain` đảm bảo điều này.
4. `make simulate SCENARIO=normal` → alert resolve → `airflow dags unpause drift_monitoring`.

## Kịch bản 11 — Kiểm tra fairness trước / sau mitigation

**Mục tiêu:** đo bias của champion theo thuộc tính nhạy cảm và so sánh các chiến lược giảm bias.

**Bước:**

```bash
make responsible-ai                                   # fairness audit + mitigation + SHAP/LIME
less reports/fairness_report.md                       # hoặc xem docs/06-responsible-ai.md (bảng tự sinh)
jq '.mitigation | keys' reports/fairness_report.json
```

Ngưỡng (`configs/responsible_ai.yaml`): DI ≥ 0.80, |DPD| ≤ 0.10, |EOD| ≤ 0.10.

**Kết quả mong đợi — nhóm tuổi (`age_group`), test split 5,000 dòng**

| Biến thể | ROC-AUC | Expected loss | DI | DPD | EOD | Đánh giá |
|---|---|---|---|---|---|---|
| Champion (trước) | 0.7599 | 1.0734 | **0.772** | **0.1817** | **0.1461** | Vi phạm cả 3 ngưỡng |
| Reweighing | 0.7593 | 1.1302 | 0.911 | 0.0672 | 0.0694 | Đạt |
| Unawareness | 0.7585 | 1.1346 | 0.926 | 0.0549 | 0.0477 | Đạt — khuyến nghị (kết hợp reweighing) |
| ThresholdOptimizer | 0.7137 | 1.1288 | 0.963 | 0.0253 | 0.0835 | Đạt nhưng mất ROC-AUC và cần thuộc tính nhạy cảm lúc quyết định → không dùng production |

Cả 4 thuộc tính (`SEX`, `age_group`, `EDUCATION`, `MARRIAGE`) ở trạng thái WARN với champion hiện tại. Explainability:
SHAP top feature `PAY_0` 17.6 %, `PAY_AMT1` 16.9 %, `LIMIT_BAL` 10.2 %; SHAP và LIME trùng 67 % top feature.
Phân tích trade-off và khuyến nghị: [06 — Responsible AI §4](../06-responsible-ai.md#4-mitigation-và-trade-off).
Mitigation **không** tự động thay champion — challenger mitigated vẫn phải qua quality gate (kịch bản 3).
