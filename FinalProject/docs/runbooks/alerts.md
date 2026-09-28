# Runbook — Alert của hệ thống Credit Risk

Mỗi alert Prometheus có `runbook_url` trỏ vào đúng mục dưới đây. Rule nằm ở
[`monitoring/prometheus/rules/`](../../monitoring/prometheus/rules/), unit test "bắn → resolve" ở
[`monitoring/prometheus/tests/alerts_test.yml`](../../monitoring/prometheus/tests/alerts_test.yml) (`make alerts-test`).

**Luồng thông báo:** Prometheus → Alertmanager → `alert-webhook` (luôn nhận, xem `make alerts` hoặc
<http://localhost:19095/alerts>) + Telegram (khi `.env` có `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID`).
Inhibit: `APIDown` chặn `HighErrorRate`/`HighLatencyP95`/`ModelNotLoaded`/`ModelServedFromFallback`
(triệu chứng của cùng một sự cố).

| Alert | Điều kiện | `for` | Severity | Kích hoạt (demo) | Resolve |
|---|---|---|---|---|---|
| [APIDown](#apidown) | `up{job="credit-risk-api"} == 0` | 1m | critical | `make chaos-api-down` | `make chaos-restore` |
| [HighErrorRate](#higherrorrate) | 5xx / tổng request `/api/v1/*` > 5% (rate 2m, ≥ 0.05 req/s) | 2m | critical | `make chaos-model-unloaded` + `make simulate SCENARIO=load SIM_ARGS="--concurrency 4 --duration 240"` | `make chaos-restore` |
| [HighLatencyP95](#highlatencyp95) | p95 `POST /api/v1/predict` > 100 ms (rate 2m) | 2m | warning | `make chaos-latency` + `make simulate SCENARIO=load` | `make chaos-restore` |
| [ModelNotLoaded](#modelnotloaded) | `credit_model_loaded == 0` | 1m | critical | `make chaos-model-unloaded` | `make chaos-restore` |
| [ModelServedFromFallback](#modelservedfromfallback) | `credit_model_degraded == 1` (và model vẫn loaded) | 5m | warning | `docker compose stop mlflow` rồi `docker compose restart api` | start `mlflow` + `POST /api/v1/model/reload` |
| [DataDriftDetected](#datadriftdetected) | `credit_drift_detected == 1` (PSI feature chính ≥ 0.25 hoặc drift share ≥ 50%) | 2m | warning | `make simulate SCENARIO=drift` | `make simulate SCENARIO=normal` |
| [PredictionDistributionShift](#predictiondistributionshift) | PSI phân phối xác suất dự đoán ≥ 0.25 (≥ 50 mẫu) | 2m | warning | `make simulate SCENARIO=attack` (hoặc `drift`) | `make simulate SCENARIO=normal` |
| [RetrainFailed](#retrainfailed) | `credit_retrain_last_run_failed == 1` | 0 | critical | `make retrain-fail` | `make retrain-dag` (run thành công kế tiếp) |
| [DriftMonitorDown](#driftmonitordown) | `up{job="drift-monitor"} == 0` | 2m | warning | `make chaos-drift-down` | `make chaos-restore` |
| [DriftAnalysisStale](#driftanalysisstale) | không có phân tích thành công > 15 phút | 5m | warning | `make chaos-drift-stale` (~20 phút) | `make chaos-restore` |
| [AirflowDagImportErrors](#airflowdagimporterrors) | `airflow_dag_import_errors > 0` | 5m | warning | `make chaos-dag-import-error` | `make chaos-restore` |

Kiểm tra trạng thái: `make alerts` (alert đang firing trong Prometheus + trạng thái cuối cùng từng alert ở
webhook: `fired=True resolved=True` là bằng chứng bắn → resolve). UI: Prometheus
<http://localhost:19090/alerts>, Alertmanager <http://localhost:19093>, dashboard *Infra & SLA* (bảng *Active alerts*).

> Ngưỡng `for` ngắn để demo trong vài phút. Production nên dùng SLO burn-rate đa cửa sổ (ví dụ 1h/5m và
> 6h/30m) cho `HighErrorRate`, và `for: 5m` cho `HighLatencyP95`.

---

## APIDown

**Ý nghĩa:** Prometheus không scrape được `api:8000/metrics` quá 1 phút — không chấm điểm được hồ sơ.

**Kích hoạt:** `make chaos-api-down` (hoặc `make simulate SCENARIO=outage` — dừng API 90 s rồi tự bật lại, đo
thời gian phục hồi). Alert firing sau ~1–1.5 phút.

**Xử lý:**
1. `make ps` / `docker compose logs api --tail=100` — crash loop, OOM (`docker inspect $(docker compose -f deploy/compose/docker-compose.yml ps -q api) --format '{{.State.OOMKilled}}'`)?
2. Phụ thuộc: `postgres`, `mlflow` healthy? (`make health`).
3. Khởi động lại: `docker compose up -d api` (hoặc `make chaos-restore`). Nếu lỗi do release mới: `deploy.sh rollback`.

## HighErrorRate

**Ý nghĩa:** > 5% request nghiệp vụ `/api/v1/*` trả 5xx trong 2 phút (health probe không được tính).

**Kích hoạt:** `make chaos-model-unloaded` (API không có model → `/api/v1/predict` trả 503), sau đó
`make simulate SCENARIO=load SIM_ARGS="--concurrency 4 --duration 240"`. Firing sau ~2–3 phút (kèm `ModelNotLoaded`).

**Xử lý:** log JSON của API (`docker compose logs api | grep '"status": 5'`), tìm `request_id`; kiểm tra model
(`GET /api/v1/model/info`), DB (`inference_logs`), MLflow. Rollback model nếu lỗi sau promote: `make rollback`.

## HighLatencyP95

**Ý nghĩa:** p95 latency `POST /api/v1/predict` vượt SLO 100 ms trong 2 phút.

**Kích hoạt:** `make chaos-latency` (giới hạn API còn 0.5 CPU) rồi `make simulate SCENARIO=load` (32 luồng, 180 s). Không hạ xuống 0.1 CPU: API ngừng trả lời scrape → `APIDown` bắn và inhibit `HighLatencyP95`.
Firing sau ~2–3 phút; `make chaos-restore` trả CPU về 2 → resolve sau ~2 phút.

**Xử lý:** dashboard *Infra & SLA* (CPU/memory API), *ML Model* (latency inference); tăng `cpus` của service `api`,
thêm worker uvicorn, hoặc bật cache; kiểm tra batch lớn gọi `/api/v1/predict/batch` đồng thời.

## ModelNotLoaded

**Ý nghĩa:** API không nạp được model nào (MLflow `@champion` lẫn artifact local) — `/health/ready` 503, predict 503.

**Kích hoạt:** `make chaos-model-unloaded` (override [`chaos/model-unloaded.yml`](../../deploy/compose/chaos/model-unloaded.yml):
MLflow không tới được + thư mục model rỗng). Firing sau ~1 phút.

**Xử lý:** `make registry` (alias `@champion` còn không?), MinIO bucket `mlflow` còn artifact? Chạy
`POST /api/v1/model/reload` sau khi sửa; nếu registry trống: `docker compose run --rm model-bootstrap`.

## ModelServedFromFallback

**Ý nghĩa:** API đang phục vụ artifact dự phòng đóng gói trong image thay vì `@champion` trên MLflow (registry
không tới được lúc nạp gần nhất) — dự đoán có thể là model cũ.

**Kích hoạt:** `docker compose stop mlflow`, rồi `docker compose restart api` (API khởi động lại không tới được registry nên nạp artifact dự phòng). Chỉ gọi reload thì không đủ: reload lỗi sẽ giữ nguyên model đang phục vụ (`unchanged_on_failure`). Firing sau 5 phút.

**Xử lý:** khôi phục MLflow (`docker compose start mlflow`) rồi reload model; alert resolve sau lần scrape kế tiếp.

## DataDriftDetected

**Ý nghĩa:** Drift monitor (Evidently + PSI) so sánh `DRIFT_WINDOW_SIZE` (mặc định 500) inference log gần nhất với
`data/reference`: PSI của một feature chính ≥ 0.25 hoặc ≥ 50% feature bị Evidently đánh dấu drift.

**Kích hoạt:** `make simulate SCENARIO=drift` — replay `stream_drifted.csv` (chiến dịch Gen-Z, tuổi TB 26 vs 38),
AGE PSI ≈ 13. Drift monitor phân tích mỗi 60 s; alert firing sau ~2–3 phút. DAG `drift_monitoring`
(`make drift-dag` hoặc lịch `*/30`) gửi thông báo và trigger `model_retrain` (cooldown 60 phút).

**Xử lý:** xem report HTML (<http://localhost:18085/reports>), dashboard *Data Drift*; xác nhận nguồn drift
(chiến dịch marketing, lỗi pipeline dữ liệu); theo dõi kết quả `model_retrain`. Resolve: traffic trở lại phân
phối chuẩn (`make simulate SCENARIO=normal` đẩy 600 bản ghi chuẩn → cửa sổ 500 không còn drift).

## PredictionDistributionShift

**Ý nghĩa:** Phân phối xác suất vỡ nợ dự đoán lệch khỏi phân phối của champion trên tập reference (PSI ≥ 0.25) —
có thể do tấn công/nhóm khách hàng mới hoặc model lỗi. Không tự trigger retrain (DAG chỉ retrain khi feature drift).

**Kích hoạt:** `make simulate SCENARIO=attack` (70% hồ sơ "speculator" nợ quá hạn ≥ 2 kỳ). Firing sau ~2–3 phút.

**Xử lý:** dashboard *Business* (tỷ lệ decline tăng vọt?), *ML Model* (histogram xác suất). Nếu tấn công có tổ
chức: chặn nguồn, xem lại ngưỡng `DECLINE_THRESHOLD`; nếu model lỗi: `make rollback`.

## RetrainFailed

**Ý nghĩa:** Lần chạy gần nhất của DAG `model_retrain` thất bại (train lỗi, dưới sàn ROC-AUC, promote lỗi, hoặc
API không reload đúng version). `@champion` giữ nguyên (hoặc đã được `rollback_champion` trả về version trước).
Gauge `credit_retrain_last_run_failed` do callback DAG đẩy qua StatsD → statsd-exporter.

**Kích hoạt:** `make retrain-fail` (trigger với `min_roc_auc=0.99`). Alert firing ngay khi DAG run kết thúc
(~1–2 phút).

**Resolve:** `make retrain-dag` — run thành công (promote hoặc giữ champion vì challenger không tốt hơn) đặt gauge về 0.

**Xử lý:** Airflow UI <http://localhost:18080> → `model_retrain` → task lỗi → log; kiểm tra MLflow
(<http://localhost:15040>), dữ liệu feedback `data/processed/ground_truth_feedback.csv`.

## DriftMonitorDown

**Ý nghĩa:** không scrape được drift monitor — drift không được đo, hai alert drift không thể bắn.

**Kích hoạt:** `make chaos-drift-down`. Firing sau ~2 phút. **Xử lý:** `docker compose logs drift-monitor`;
reference không nạp được (thiếu `data/reference`) → `/health` 503; khởi động lại service.

## DriftAnalysisStale

**Ý nghĩa:** drift monitor vẫn chạy nhưng > 15 phút không có phân tích thành công (DB không tới được, lỗi phân tích). Bao gồm cả trường hợp service vừa khởi động lại và chưa từng phân tích thành công (gauge timestamp = 0, so với `process_start_time_seconds`).

**Kích hoạt:** `make chaos-drift-stale` (recreate drift monitor với DB không tới được). Firing sau ~20 phút kể từ lúc container khởi động (15 phút + `for` 5m).

**Xử lý:** `GET http://localhost:18085/drift/latest`, log `drift-monitor`; kiểm tra `DATABASE_URL`, bảng `inference_logs`.

## AirflowDagImportErrors

**Ý nghĩa:** có file DAG không import được → lịch của DAG đó ngừng chạy.

**Kích hoạt:** `make chaos-dag-import-error` (tạo `dags/_chaos_broken_dag.py`). Scheduler quét thư mục mỗi 30 s;
firing sau ~5–6 phút. **Xử lý:** `make dags-check` hoặc
`docker compose exec airflow-scheduler airflow dags list-import-errors`; sửa/xoá file lỗi (`make chaos-restore`).
