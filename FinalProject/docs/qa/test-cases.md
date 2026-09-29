# Test cases — Credit Default Risk Scoring

Test case thủ công và bán tự động chạy trên stack thật (`make up`, profile `core,monitoring,orchestration`) ngày
28/09/2026. Giờ ghi theo UTC (giờ máy test = UTC+7). Chiến lược và môi trường: [test-plan.md](test-plan.md). Tổng hợp,
số liệu và danh sách lỗi: [test-report.md](test-report.md). Evidence nằm trong [`evidence/`](evidence/), tên file
`<TC-ID>_<mô-tả>.png`; mọi ảnh là screenshot thật của trình duyệt (Chrome), Terminal.app hoặc Telegram Desktop; ảnh
retest sau fix chụp bằng Chrome headless (Grafana, report Locust, và output nguyên văn của lệnh `curl | jq` cho BUG-02).

Trạng thái: **PASS** (đạt kỳ vọng), **PASS\*** (đạt, có ghi chú/giới hạn), **FAIL** (lệch kỳ vọng, có mã lỗi `BUG-xx`
trong test report). Trạng thái dưới đây là **sau khi sửa BUG-01/02/03** và retest lúc 16:38–16:50 trên stack build lại
(API gunicorn 2 worker); kết quả lần đầu vẫn giữ trong từng TC.

| ID | Tính năng / kịch bản | Trạng thái |
|---|---|---|
| [TC-001](#tc-001--api-contract-và-swagger) | API contract, auth, error contract | PASS |
| [TC-002](#tc-002--traffic-bình-thường-baseline) | Kịch bản 1 — traffic bình thường | PASS |
| [TC-003](#tc-003--data-drift--alert--drift_monitoring) | Kịch bản 2 — data drift → alert → DAG `drift_monitoring` | PASS |
| [TC-004](#tc-004--promote-champion--hot-reload-dưới-traffic) | Kịch bản 3 — promote + hot reload dưới traffic | PASS |
| [TC-005](#tc-005--retrain-thất-bại-quality-gate--retrain-lại-thành-công) | Kịch bản 4 — retrain thất bại → alert → retrain lại | PASS |
| [TC-006](#tc-006--rollback-model-dưới-traffic) | Kịch bản 5 — rollback model | PASS |
| [TC-007](#tc-007--api-down--apidown) | Kịch bản 6 — API down | PASS |
| [TC-008](#tc-008--latency-tăng-dưới-tải--highlatencyp95) | Kịch bản 7 — latency tăng dưới tải | PASS |
| [TC-009](#tc-009--lỗi-client-4xx-và-mất-model-5xx) | Kịch bản 8 — lỗi 4xx, mất model 5xx | PASS |
| [TC-010](#tc-010--postgres--mlflow-down) | Kịch bản 9 — Postgres / MLflow down | PASS |
| [TC-011](#tc-011--tấn-công-từ-tài-khoản-nợ-quá-hạn) | Kịch bản 10 — tấn công có tổ chức | PASS |
| [TC-012](#tc-012--fairness-audit-và-mitigation) | Kịch bản 11 — fairness trước / sau mitigation | PASS |
| [TC-013](#tc-013--triển-khai-ubuntu-2404) | Triển khai Ubuntu 24.04 | PASS\* |
| [TC-014](#tc-014--alert-pipeline-đủ-11-rule) | Alert pipeline: 11 rule firing → resolved, webhook, Telegram | PASS |
| [TC-015](#tc-015--test-tự-động-lint-coverage-e2e) | Test tự động: lint, type check, coverage, e2e | PASS |
| [TC-016](#tc-016--load-test-tải-danh-định-locust) | Load test tải danh định (Locust 10 user) | PASS |
| [TC-017](#tc-017--load-test-tải-gấp-đôi-locust-20-user) | Load test tải gấp đôi (Locust 20 user) | PASS (BUG-01 đã sửa) |
| [TC-018](#tc-018--nghiệm-thu-đổi-framing-sang-quản-lý-hạn-mức-chủ-thẻ) | Nghiệm thu đổi framing sang quản lý hạn mức chủ thẻ (29/09) | PASS |

---

## TC-001 — API contract và Swagger

- **Tiền điều kiện:** stack chạy, `/health/ready` = `ready`, champion = v1.
- **Bước:** mở `http://localhost:18020/docs`; chạy `make test-e2e` (17 test trên stack thật); gửi request thiếu key,
  sai key, sai schema, batch 501 chủ thẻ.
- **Kỳ vọng:** Swagger liệt kê đủ endpoint `/api/v1/*`; 401 `MISSING_API_KEY`, 403 `INVALID_API_KEY`, 422
  `VALIDATION_ERROR` không echo input, 413 `BATCH_TOO_LARGE`; `/metrics` có `credit_api_requests_total`.
- **Thực tế:** đúng như kỳ vọng; e2e 17/17 pass (readiness, `/predict`, chủ thẻ rủi ro cao → DECLINE, batch, 401/403,
  422, 413, `/metrics`, alias MLflow khớp model đang phục vụ, drift `/analyze` + report HTML, Prometheus targets, 11
  alert rule, Alertmanager + webhook, 4 dashboard Grafana, Airflow DAG + `importErrors = 0`).
- **Evidence:** [TC-001_swagger-ui.png](evidence/TC-001_swagger-ui.png),
  [TC-001_swagger-batch-example.png](evidence/TC-001_swagger-batch-example.png),
  [TC-001_swagger-batch-schema-deprecated.png](evidence/TC-001_swagger-batch-schema-deprecated.png) (3 ảnh Swagger
  chụp lại 29/09 sau khi đổi mô tả API sang chủ thẻ, xem [TC-018](#tc-018--nghiệm-thu-đổi-framing-sang-quản-lý-hạn-mức-chủ-thẻ)),
  [TC-009_client-errors-4xx.png](evidence/TC-009_client-errors-4xx.png), [TC-015](#tc-015--test-tự-động-lint-coverage-e2e).
- **Trạng thái:** PASS

## TC-002 — Traffic bình thường (baseline)

- **Tiền điều kiện:** không có alert firing; reference drift đã chấm bằng champion.
- **Bước:** `make simulate SCENARIO=normal` (2 500 request) → `curl -X POST localhost:18085/analyze` → `make alerts`.
- **Kỳ vọng:** 0 lỗi, p95 < 100 ms, không drift, không alert; tỉ lệ quyết định gần baseline.
- **Thực tế (14:25:43–14:26:21):** 2 500 request, 0 lỗi; REVIEW 54.6 % / DECLINE 19.6 % / APPROVE 25.7 %; p95
  46.3 ms, p99 63.2 ms; `is_drifted=false`, max PSI 0.0226, prediction PSI 0.023; Prometheus không có alert.
  Report `reports/simulations/normal_20260928T142543Z.json`.
- **Evidence:** [TC-002_normal-traffic-simulation.png](evidence/TC-002_normal-traffic-simulation.png),
  [TC-002_normal-no-drift-no-alert.png](evidence/TC-002_normal-no-drift-no-alert.png),
  [TC-002_grafana-infra-sla-normal.png](evidence/TC-002_grafana-infra-sla-normal.png),
  [TC-002_grafana-business-kpis-normal.png](evidence/TC-002_grafana-business-kpis-normal.png) (chụp lại 29/09 sau khi
  đổi tên panel; traffic normal 1 800 request, xem [TC-018](#tc-018--nghiệm-thu-đổi-framing-sang-quản-lý-hạn-mức-chủ-thẻ))
- **Trạng thái:** PASS

## TC-003 — Data drift → alert → `drift_monitoring`

- **Tiền điều kiện:** baseline sạch (TC-002).
- **Bước:** `make simulate SCENARIO=drift` → `POST /analyze` → chờ `DataDriftDetected` → `make drift-dag` → xem run
  trong Airflow, report Evidently, dashboard drift → resolve bằng `make simulate SCENARIO=normal SIM_ARGS="--count 600"`.
- **Kỳ vọng:** `is_drifted=true` (AGE PSI ≥ 0.25 hoặc share ≥ 0.5), DECLINE tăng, `DataDriftDetected` firing → webhook +
  Telegram; DAG chạy `run_drift_analysis → decide → alert_drift + check_retrain_cooldown → trigger_model_retrain`
  (bỏ qua nếu đã retrain trong 60 phút).
- **Thực tế:** 600 request, 0 lỗi; drift share 0.7391 (17/23 cột), AGE PSI 3.3354, prediction PSI 0.24; DECLINE 34.2 %
  (baseline 19.6 %). `DataDriftDetected` pending 14:59:19 → firing 15:01:19 → resolved 15:10:50 (webhook 15:01:16 /
  15:11:16). Run `manual__2026-09-28T14:59:52+00:00` success: `alert_drift` success, `trigger_model_retrain` skipped
  vì retrain gần nhất lúc 14:40 còn trong cooldown 60 phút — đúng thiết kế. Report `drift_20260928T145833Z.json`.
- **Thực tế (chạy lại 15:46:07, đã qua cooldown):** 600 request, 0 lỗi; drift share 0.913, max PSI 0.9688, prediction
  PSI 0.5081. `DataDriftDetected` pending 15:46:09 → firing 15:48:09 (Telegram có tin FIRING). Run
  `manual__2026-09-28T15:46:23+00:00` success, lần này `check_retrain_cooldown` cho qua và `trigger_model_retrain`
  success → run `model_retrain` `manual__2026-09-28T15:46:28.892766+00:00` success: challenger v9 bị gate loại (expected
  loss cao hơn champion), `keep_champion` giữ v1; Telegram nhận tin `[DRIFT]` và `[RETRAIN] challenger v9 rejected`.
  Report `drift_20260928T154608Z.json`.
- **Ghi chú:** run DAG lần đầu bị trễ ~3 phút do scheduler treo sau sự cố đầy đĩa Docker Desktop trên máy test (không
  phải lỗi sản phẩm; restart `airflow-scheduler` → chạy tiếp bình thường, xem test report §6).
- **Evidence:** [TC-003_drift-simulation-analyze.png](evidence/TC-003_drift-simulation-analyze.png),
  [TC-003_prometheus-datadrift-firing.png](evidence/TC-003_prometheus-datadrift-firing.png),
  [TC-003_drift-dag-trigger.png](evidence/TC-003_drift-dag-trigger.png),
  [TC-003_airflow-drift-monitoring-run.png](evidence/TC-003_airflow-drift-monitoring-run.png),
  [TC-003_evidently-drift-report.png](evidence/TC-003_evidently-drift-report.png),
  [TC-003_grafana-drift-dashboard.png](evidence/TC-003_grafana-drift-dashboard.png),
  [TC-011_resolve-normal-unpause.png](evidence/TC-011_resolve-normal-unpause.png) (resolve); chạy lại:
  [TC-003_drift-rerun-retrain-trigger.png](evidence/TC-003_drift-rerun-retrain-trigger.png),
  [TC-003_airflow-drift-rerun-trigger-retrain.png](evidence/TC-003_airflow-drift-rerun-trigger-retrain.png),
  [TC-003_airflow-model-retrain-from-drift.png](evidence/TC-003_airflow-model-retrain-from-drift.png),
  [TC-003_telegram-DataDriftDetected.png](evidence/TC-003_telegram-DataDriftDetected.png)
- **Trạng thái:** PASS

## TC-004 — Promote champion + hot reload dưới traffic

- **Tiền điều kiện:** champion = v1, v5 đã đăng ký.
- **Bước:** `make registry`; chạy nền `make simulate SCENARIO=normal SIM_ARGS="--count 1500"`; sau 5 s
  `python scripts/manage_registry.py promote 5`; `POST /api/v1/model/reload`; đợi traffic xong; kiểm tra readiness.
- **Kỳ vọng:** `{"status":"reloaded","previous_version":"1","v":"5"}`, 0 lỗi trong lúc đổi model, readiness `ready`
  với `mlflow_registry version 5`.
- **Thực tế (15:10:30):** reload `1 → 5`; 1 500 request, 0 lỗi, p95 37.0 ms, p99 56.5 ms; readiness `ready`,
  `mlflow_registry version 5`; MLflow alias `@champion` → v5; Grafana ML Model hiện version 5, *Reloads OK* tăng.
  Panel "Model inference latency" lúc đó trống (BUG-03).
- **Retest sau fix BUG-03 (16:39–16:47):** `python scripts/sample_predict.py` rồi `make test-load-stress` →
  `credit_prediction_duration_seconds_count` từ 0 lên 14 sau 7 lần chạy script (cả 2 worker trả cùng giá trị);
  Prometheus `histogram_quantile` 5 phút: p50 7.0 ms, p95 30.1 ms thời gian model; panel có đủ 2 đường p50/p95. Reload
  dưới gunicorn 2 worker: `POST /api/v1/model/reload` → `reloaded`, 30 lần `GET /model/info` thấy 2 mốc `loaded_at`
  cách nhau 0.4 s (cả 2 worker đã nạp lại, đúng ADR 0007).
- **Evidence:** [TC-004_promote-hot-reload-under-traffic.png](evidence/TC-004_promote-hot-reload-under-traffic.png),
  [TC-004_mlflow-champion-v5.png](evidence/TC-004_mlflow-champion-v5.png),
  [TC-004_grafana-ml-model-version-5.png](evidence/TC-004_grafana-ml-model-version-5.png),
  [TC-004_mlflow-registry-aliases.png](evidence/TC-004_mlflow-registry-aliases.png) (trạng thái alias trước khi test),
  [TC-004_grafana-model-inference-latency.png](evidence/TC-004_grafana-model-inference-latency.png) (sau fix BUG-03)
- **Trạng thái:** PASS

## TC-005 — Retrain thất bại (quality gate) → retrain lại thành công

- **Tiền điều kiện:** champion v1; không có alert.
- **Bước:** `make retrain-fail` (floor ROC-AUC 0.99) cùng lúc `make chaos-drift-down` và `make chaos-dag-import-error`
  (chạy song song để rút ngắn thời gian chờ `for:`) → chờ alert → `make chaos-restore` → `make retrain-dag`.
- **Kỳ vọng:** run `model_retrain` failed ở `quality_gate`, champion không đổi; `RetrainFailed`, `DriftMonitorDown`,
  `AirflowDagImportErrors` firing → Telegram; sau restore tất cả resolved; retrain lại success (nhánh promote hoặc
  `keep_champion`).
- **Thực tế:** run `manual__2026-09-28T14:32:50+00:00` failed: "Quality gate failed: ROC-AUC 0.7485 < floor 0.9900
  (v7 stays @challenger, champion unchanged)". `RetrainFailed` firing 14:33:27 → resolved 14:41:18;
  `DriftMonitorDown` pending 14:33:17 → firing 14:35:18 → resolved 14:41:18; `AirflowDagImportErrors` pending 14:33:27
  → firing 14:38:28 → resolved 14:40:58. `make retrain-dag` 14:40:48 success, nhánh `keep_champion` (challenger v8 kém
  hơn champion → không promote, đúng gate). MLflow có 7 run `retrain-challenger`.
- **Evidence:** [TC-005_retrain-fail-trigger.png](evidence/TC-005_retrain-fail-trigger.png),
  [TC-005_airflow-quality-gate-failed.png](evidence/TC-005_airflow-quality-gate-failed.png),
  [TC-005_prometheus-3-alerts-firing.png](evidence/TC-005_prometheus-3-alerts-firing.png),
  [TC-005_alertmanager-3-alerts-firing.png](evidence/TC-005_alertmanager-3-alerts-firing.png),
  [TC-005_telegram-RetrainFailed.png](evidence/TC-005_telegram-RetrainFailed.png),
  [TC-005_restore-and-retrain-success.png](evidence/TC-005_restore-and-retrain-success.png),
  [TC-005_airflow-model-retrain-success-graph.png](evidence/TC-005_airflow-model-retrain-success-graph.png),
  [TC-005_mlflow-experiment-runs.png](evidence/TC-005_mlflow-experiment-runs.png)
- **Trạng thái:** PASS

## TC-006 — Rollback model dưới traffic

- **Tiền điều kiện:** champion v5, previous_champion v1 (sau TC-004).
- **Bước:** chạy nền 1 500 request normal → `make rollback` → `POST /model/reload` → đợi xong →
  `POST localhost:18085/reference/refresh` → readiness.
- **Kỳ vọng:** `{"status":"reloaded","previous_version":"5","v":"1"}`, 0 lỗi, reference chấm lại bằng v1.
- **Thực tế (15:11:51):** reload `5 → 1`; 1 500 request, 0 lỗi, p95 41.3 ms, p99 66.4 ms; reference
  `{"status":"refreshed","model_version":"1","model_source":"mlflow_registry"}`; readiness `mlflow_registry version 1`.
- **Evidence:** [TC-006_rollback-under-traffic.png](evidence/TC-006_rollback-under-traffic.png)
- **Trạng thái:** PASS

## TC-007 — API down → `APIDown`

- **Bước:** `make simulate SCENARIO=outage` (dừng container API ~95 s dưới traffic rồi bật lại).
- **Kỳ vọng:** `APIDown` (critical, `for: 1m`) firing → Telegram FIRING; API lên lại → RESOLVED.
- **Thực tế (14:41:40–14:43:45):** down 94.7 s, recovery 8.1 s; 486 request (78 × 200, 408 ConnectionError trong lúc
  down). `APIDown` firing 14:43:08 → resolved 14:43:48 (webhook 14:43:16 / 14:44:16); Telegram có cả FIRING và
  RESOLVED. Report `outage_20260928T144140Z.json`.
- **Evidence:** [TC-007_api-outage-simulation.png](evidence/TC-007_api-outage-simulation.png),
  [TC-007_prometheus-apidown-firing.png](evidence/TC-007_prometheus-apidown-firing.png),
  [TC-007_telegram-APIDown.png](evidence/TC-007_telegram-APIDown.png)
- **Trạng thái:** PASS

## TC-008 — Latency tăng dưới tải → `HighLatencyP95`

- **Bước:** `make bench` (baseline) → `make chaos-latency` (API 0.5 CPU) + `make simulate SCENARIO=load`
  (32 luồng × 180 s) → chờ alert → `make chaos-restore`.
- **Kỳ vọng:** baseline p95 < 100 ms; dưới chaos p95 vượt SLO → `HighLatencyP95` firing; restore → resolved.
- **Thực tế:** baseline 500 request, 0 lỗi, p95 20.59 ms, p99 29.49 ms (model p95 11.55 ms,
  `reports/latency_benchmark.json`). Chaos: 4 035 request, 0 lỗi, 22.4 rps, p50 1 397 ms, p95 2 084 ms, p99 2 807 ms
  (`load_20260928T144521Z.json`). `HighLatencyP95` pending 14:46:08 → firing 14:48:08; restore 14:49:15 → resolved
  14:50:38 (webhook 14:48:16 / 14:51:16). Grafana Infra & SLA ghi p95 ~2.5 s, CPU 0.5.
- **Evidence:** [TC-008_latency-bench-chaos-load.png](evidence/TC-008_latency-bench-chaos-load.png),
  [TC-008_prometheus-highlatency-firing.png](evidence/TC-008_prometheus-highlatency-firing.png),
  [TC-008_grafana-latency-spike.png](evidence/TC-008_grafana-latency-spike.png)
- **Trạng thái:** PASS

## TC-009 — Lỗi client (4xx) và mất model (5xx)

- **Bước 1 (4xx):** request thiếu key, sai key, sai schema, batch 501.
- **Kỳ vọng 1:** 401/403/422/413 đúng error contract; `credit_auth_failures_total` tăng; 4xx **không** kích hoạt
  `HighErrorRate`.
- **Thực tế 1:** 401 `MISSING_API_KEY`, 403 `INVALID_API_KEY`, 422 `VALIDATION_ERROR` (liệt kê từng field, không echo
  giá trị), 413 `BATCH_TOO_LARGE` (max 500); auth failures missing=1, invalid=1; không có alert.
- **Bước 2 (5xx):** `make chaos-model-unloaded` → `make simulate SCENARIO=load SIM_ARGS="--concurrency 4 --duration 240"`
  → chờ alert → `make chaos-restore`.
- **Kỳ vọng 2:** readiness `not_ready` (503), `/predict` 503; `ModelNotLoaded` + `HighErrorRate` firing → resolved sau
  restore.
- **Thực tế 2 (14:52:37–14:56:52):** readiness `not_ready`, reasons `model_not_loaded`, `mlflow_unreachable`; 191 080
  request, 100 % lỗi 503 (latency p95 9.8 ms — trả lỗi nhanh). `ModelNotLoaded` firing 14:53:59 → resolved 14:57:29;
  `HighErrorRate` pending 14:53:19 → firing 14:55:19 → resolved 14:59:09 (webhook 14:55:31 / 14:59:31). Alertmanager
  route cả hai alert tới receiver `telegram` và `webhook`.
- **Evidence:** [TC-009_client-errors-4xx.png](evidence/TC-009_client-errors-4xx.png),
  [TC-009_model-unloaded-5xx-load.png](evidence/TC-009_model-unloaded-5xx-load.png),
  [TC-009_prometheus-modelnotloaded-higherrorrate-firing.png](evidence/TC-009_prometheus-modelnotloaded-higherrorrate-firing.png),
  [TC-009_alertmanager-modelnotloaded-higherrorrate.png](evidence/TC-009_alertmanager-modelnotloaded-higherrorrate.png),
  [TC-009_grafana-error-rate-spike.png](evidence/TC-009_grafana-error-rate-spike.png)
- **Trạng thái:** PASS

## TC-010 — Postgres / MLflow down

- **Bước:** 9a `dc stop postgres` → readiness + `sample_predict.py` → `dc start postgres`; 9b `dc stop mlflow` +
  `dc restart api` → readiness, metrics, predict → giữ > 5 phút → `dc start mlflow` → reload.
- **Kỳ vọng:** 9a readiness `degraded` (`database_unavailable`), predict vẫn 200; 9b `served_by: local_artifact`,
  `credit_model_degraded 1`, `ModelServedFromFallback` firing sau 5 phút; MLflow lên + reload → `ready`, resolved.
- **Thực tế (15:12:35–15:19:46):** 9a `degraded`, database `down` ("predictions are not logged"), predict 200 (10.4 ms).
  9b readiness `degraded` (`model_served_from_local_fallback`, `mlflow_unreachable`), `credit_model_loaded 1`,
  `credit_model_degraded 1`, predict qua Nginx trả `served_by: local_artifact`, `model_version: credit_model_v1`
  (ảnh TC-013). `ModelServedFromFallback` pending 15:13:20 → firing 15:18:21 → resolved 15:20:02 sau reload
  `{"status":"reloaded","previous_version":"credit_model_v1","v":"1","src":"mlflow_registry"}`, readiness `ready`.
- **Ghi chú:** dòng lệnh đầu trong ảnh `TC-010_mlflow-back-reload.png` không có output vì file mẫu
  `examples/sample_request.json` không tồn tại trong repo (lỗi của lệnh kiểm thử, không ảnh hưởng kết quả).
- **Evidence:** [TC-010_postgres-mlflow-down-degraded.png](evidence/TC-010_postgres-mlflow-down-degraded.png),
  [TC-010_prometheus-fallback-firing.png](evidence/TC-010_prometheus-fallback-firing.png),
  [TC-010_grafana-serving-local-fallback.png](evidence/TC-010_grafana-serving-local-fallback.png),
  [TC-010_mlflow-back-reload.png](evidence/TC-010_mlflow-back-reload.png)
- **Trạng thái:** PASS

## TC-011 — Tấn công từ tài khoản nợ quá hạn

- **Bước:** `make simulate SCENARIO=attack` → `POST /analyze` → pause `drift_monitoring` (phản ứng đúng: không retrain
  trên traffic tấn công) → chờ alert → `make simulate SCENARIO=normal SIM_ARGS="--count 600"` → unpause.
- **Kỳ vọng:** DECLINE ≫ 20 %, prediction PSI ≥ 0.25, `PredictionDistributionShift` firing; Business KPIs tăng đột biến;
  traffic normal → resolved.
- **Thực tế (15:06:32):** 600 request, 0 lỗi; DECLINE 83 %, APPROVE 12.2 %, REVIEW 4.8 %; prediction PSI 3.8326, max
  PSI 5.3174 (PAY_0), drift share 0.913. `PredictionDistributionShift` pending 15:07:00 → firing 15:09:00 → resolved
  15:10:30; Grafana Business: decline rate 80.9 %. Sau traffic normal: `is_drifted=false`, max PSI 0.0326;
  `drift_monitoring` unpause.
- **Evidence:** [TC-011_attack-simulation.png](evidence/TC-011_attack-simulation.png),
  [TC-011_prometheus-prediction-shift-firing.png](evidence/TC-011_prometheus-prediction-shift-firing.png),
  [TC-011_alertmanager-drift-and-shift.png](evidence/TC-011_alertmanager-drift-and-shift.png),
  [TC-011_grafana-business-decline-spike.png](evidence/TC-011_grafana-business-decline-spike.png),
  [TC-011_resolve-normal-unpause.png](evidence/TC-011_resolve-normal-unpause.png)
- **Trạng thái:** PASS

## TC-012 — Fairness audit và mitigation

- **Bước:** `make responsible-ai` → `jq '.mitigation | keys' reports/fairness_report.json`.
- **Kỳ vọng:** audit 4 thuộc tính (SEX, age_group, EDUCATION, MARRIAGE) theo ngưỡng DI ≥ 0.80, |DPD| ≤ 0.10,
  |EOD| ≤ 0.10; mitigation cho `SEX` và `age_group`; SHAP/LIME; kết quả tái lập.
- **Thực tế (15:20:10):** SEX DPD 0.0916 / EOD 0.0973, age_group 0.1871 / 0.1614, EDUCATION 0.1147 / 0.1052, MARRIAGE
  0.0357 / 0.1159 → cả 4 WARN (khớp tài liệu); mitigation 5 biến thể trên 5 000 dòng test cho `SEX`, `age_group`;
  SHAP/LIME overlap@k 67 %. Chạy lại chỉ đổi dấu thời gian trong 7 file sinh tự động → kết quả tái lập (đã khôi phục
  file về bản commit).
- **Evidence:** [TC-012_responsible-ai-fairness.png](evidence/TC-012_responsible-ai-fairness.png)
- **Trạng thái:** PASS

## TC-013 — Triển khai Ubuntu 24.04

- **Tiền điều kiện:** không có VM (Multipass/UTM) trên máy test → dùng container `ubuntu:24.04` (aarch64). Bundle
  release là cây file git của working copy (giống `git archive`, không có `.env`, `.venv`).
- **Bước:** `install.sh` (`SKIP_UFW=1`) → kiểm tra user `deploy`, thư mục `/opt/credit-risk`, systemd unit
  (`systemd-analyze verify`), `shared/.env` từ `.env.example` + secret sinh ngẫu nhiên → `bash -n` + `shellcheck` cho
  `install.sh`, `deploy.sh`, `backup.sh` → Nginx site `credit-risk.conf` proxy tới API đang chạy (host network).
- **Kỳ vọng:** install thành công; unit hợp lệ; `.env` quyền 600, không còn `change-me`; qua Nginx: `/health/ready`
  200, `/metrics` 404, `/api/*` thiếu key 401, có key 200, vhost Grafana 200, security header, rate limit trả 429.
- **Thực tế (15:16–15:17):** Ubuntu 24.04.5 LTS; Docker 29.8.1 + Compose v5.5.1 cài từ download.docker.com; user
  `deploy` thuộc nhóm `docker`; `systemd-analyze verify` 3 unit exit 0; `.env` 600, 0 `change-me`; shellcheck (error)
  sạch. Nginx: ready 200, `/metrics` 404, không key 401, có key 200 (`served_by: local_artifact` — đang ở bước 9b của
  TC-010), Grafana 200, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`; 120 request dồn dập →
  56 × 401 + 64 × 429.
- **Giới hạn:** `deploy.sh deploy/smoke/rollback`, `backup.sh backup/restore` **chưa chạy được** trong container:
  Docker-in-Docker lỗi cgroup v2 lồng nhau ("cannot enter cgroupv2 /sys/fs/cgroup/docker … invalid state") và cần
  ~4 GB đĩa trong khi Docker Desktop còn 2.6 GB. Không kiểm thử được UFW, systemd thật (PID 1), reboot, TLS. Chi tiết:
  test report §5, log `reports/qa/ubuntu2404-container-deploy.txt`, `reports/qa/ubuntu2404-dind-attempt.txt`.
- **Evidence:** [TC-013_ubuntu2404-install-nginx-verify.png](evidence/TC-013_ubuntu2404-install-nginx-verify.png)
- **Trạng thái:** PASS\*

## TC-014 — Alert pipeline đủ 11 rule

- **Bước:** gom kết quả firing/resolved của các TC trên; thêm `make chaos-drift-stale` cho `DriftAnalysisStale`; đối
  chiếu Prometheus (poll 10 s), webhook `/alerts` + `/alerts/state`, Alertmanager và Telegram.
- **Kỳ vọng:** mỗi rule firing → Alertmanager gửi `telegram` + `webhook` → resolved khi hết sự cố.
- **Thực tế:** 11/11 rule firing và resolved, bảng timeline ở test report §3. `DriftAnalysisStale`: chaos 15:23:12 →
  pending 15:38:39 → firing 15:43:39 (webhook 15:43:46) → `make chaos-restore` 15:45:05 → resolved 15:45:39 (webhook
  15:45:46); Telegram nhận cả FIRING lẫn RESOLVED. Webhook `/alerts/state` xác nhận `fired=true, resolved=true` cho các rule của phiên test. Phát hiện BUG-02: thông báo
  do Airflow gửi (`RetrainFailed`, `AirflowTaskFailed`, `ServiceHealthCheck`, `DataDriftDetected` từ DAG) không có bản
  resolved nên kẹt `firing` trong `/alerts/state`.
- **Retest sau fix BUG-02 (16:42–16:46):** `docker compose restart alert-webhook` (nạp receiver mới, state in-memory
  reset) → gọi `utils.notify.notify()` trong container `airflow-scheduler` với `TELEGRAM_BOT_TOKEN` rỗng (ép kênh
  webhook): `RetrainFailed` (firing) và `RetrainChampionKept` (resolved) đều trả `webhook`. `GET /alerts` có 2 event
  `receiver=airflow`, `kind=event`, `startsAt == endsAt`; `/alerts/state` **không** có mục `source=airflow`. Đối chứng
  `make alerts-send-test` 16:43:22: `AlertmanagerTest` firing (webhook 16:43:37) → resolved (webhook 16:45:37), state
  `fired=true, resolved=true`; bộ đếm Alertmanager `telegram` 46 → 48, `webhook` 45 → 47, 0 lần gửi lỗi.
- **Evidence:** [TC-014_chaos-drift-stale.png](evidence/TC-014_chaos-drift-stale.png),
  [TC-014_prometheus-driftanalysisstale-firing.png](evidence/TC-014_prometheus-driftanalysisstale-firing.png),
  [TC-014_alertmanager-driftanalysisstale.png](evidence/TC-014_alertmanager-driftanalysisstale.png),
  [TC-014_drift-stale-restore.png](evidence/TC-014_drift-stale-restore.png),
  [TC-014_webhook-alert-state-fired-resolved.png](evidence/TC-014_webhook-alert-state-fired-resolved.png), Telegram:
  [TC-007_telegram-APIDown.png](evidence/TC-007_telegram-APIDown.png),
  [TC-005_telegram-RetrainFailed.png](evidence/TC-005_telegram-RetrainFailed.png),
  [TC-003_telegram-DataDriftDetected.png](evidence/TC-003_telegram-DataDriftDetected.png), retest BUG-02:
  [TC-014_webhook-airflow-event-not-in-state.png](evidence/TC-014_webhook-airflow-event-not-in-state.png)
- **Trạng thái:** PASS (lần đầu PASS\* do BUG-02; đã sửa và retest)

## TC-015 — Test tự động: lint, coverage, e2e

- **Bước:** `make lint`, `make test-ci`, `make alerts-test`, `make test-e2e`.
- **Kỳ vọng:** ruff/black/mypy 0 lỗi; mọi test pass; coverage `credit_risk` ≥ 80 %; rule Prometheus và config
  Alertmanager hợp lệ; e2e pass trên stack thật.
- **Thực tế:** lint 0 lỗi (117 file black, 77 file mypy); `make test-ci` trên checkout sạch của commit đang kiểm thử:
  unit 268 pass + 1 skip, integration 61, data quality 10, model validation 4, coverage 91 %; `make alerts-test` pass
  (11 rule, config Alertmanager hợp lệ); `make test-e2e` 17/17 pass (16:01 UTC). Chi tiết test report §2.
- **Chạy lại trên working tree sau fix (16:46–16:49):** `make lint` 0 lỗi (122 file black, 80 file mypy);
  `make test-ci COV_MIN=80`: unit 296 pass + 2 skip, integration 62, data quality 10, model validation 4 (tổng 372 pass),
  coverage 91.3 %; `docs/openapi.yaml` khớp app nên `test_committed_openapi_document_is_up_to_date` pass.
- **Evidence:** [TC-015_make-lint.png](evidence/TC-015_make-lint.png),
  [TC-015_coverage-html-report.png](evidence/TC-015_coverage-html-report.png),
  [TC-015_alerts-test-e2e.png](evidence/TC-015_alerts-test-e2e.png)
- **Trạng thái:** PASS

## TC-016 — Load test tải danh định (Locust)

- **Bước:** `LOAD_DURATION=45s make test-load` (Locust headless 10 user, spawn 10/s; 20 phần `/predict`, 2 phần batch
  10 chủ thẻ, 1 phần readiness).
- **Kỳ vọng:** 0 lỗi; p95 `/predict` ≤ 100 ms; throughput ≥ số user.
- **Thực tế (14:22:32–14:23:17):** 1 321 request, 0 lỗi, 29.95 rps, p50 17 ms, p95 `/predict` 53 ms, p99
  150 ms; 3/3 test pass. Kết quả `reports/load/locust_summary.json`, `reports/load/locust_report.html`.
- **Chạy lại 15:30:54 (60 s):** máy Mac bị tác vụ nền macOS chiếm CPU (load average 50) → 1 414 request, 0 lỗi,
  23.75 rps nhưng p95 `/predict` 660 ms và `HighLatencyP95` firing 15:34:08. Không dùng làm số liệu danh định; lưu ở
  `reports/load/locust_rerun_host_contention_summary.json` làm bằng chứng API không còn dư địa khi CPU bị tranh chấp
  (bổ sung cho BUG-01).
- **Evidence:** [TC-016_locust-report-10-users.png](evidence/TC-016_locust-report-10-users.png)
- **Trạng thái:** PASS

## TC-017 — Load test tải gấp đôi (Locust 20 user)

- **Bước:** `LOAD_USERS=20 LOAD_DURATION=60s make test-load` (spawn 10/s, không có chaos), 14:21:13–14:22:13 UTC.
  Sau fix: `make test-load-stress` (cùng cấu hình 20 user, 60 s).
- **Kỳ vọng:** p95 `/predict` ≤ 100 ms (SLO), 0 lỗi, không alert latency.
- **Thực tế lần đầu:** 3 305 request theo CSV (report HTML ghi 3 345 vì tính cả giây dừng), 0 lỗi, 55.88 rps; p95
  `/predict` **170 ms**, p99 270 ms → vượt SLO; `HighLatencyP95` firing thật 14:24:01 → resolved 14:25:01 (webhook) dù
  không có chaos. API chạy 1 uvicorn worker (2 CPU) nên bão hoà ở ~56 rps → BUG-01. Kết quả
  `reports/load/locust_stress_20u_summary.json`, `locust_stress_20u_report.html`.
- **Retest sau fix BUG-01 (16:39:19–16:40:19):** stack build lại, API gunicorn 2 worker (ADR 0007), không chạy tác vụ
  nặng khác trên host. 3 556 request theo CSV (HTML 3 594), **0 lỗi**, 60.07 rps; `/predict` 3 079 request, p50 18 ms,
  **p95 72 ms**, p99 290 ms; batch 10 chủ thẻ p95 62 ms; tổng hợp p95 69 ms. 3/3 test pass. Kết quả
  `reports/load/locust_stress_summary.json`, `locust_stress_report.html`.
- **Evidence:** [TC-017_locust-report-20-users.png](evidence/TC-017_locust-report-20-users.png) (lần đầu),
  [TC-017_locust-report-20-users-after-fix.png](evidence/TC-017_locust-report-20-users-after-fix.png) (sau fix)
- **Trạng thái:** PASS (lần đầu FAIL → BUG-01; đã sửa và retest)

## TC-018 — Nghiệm thu đổi framing sang quản lý hạn mức chủ thẻ

- **Tiền điều kiện:** working tree đã đổi câu chuyện nghiệp vụ sang Credit Line Management (behavioral scoring cho chủ
  thẻ đang lưu hành); so sánh với commit gốc `dc95bc1`. Chạy ngày 29/09/2026, 11:59–12:15 UTC.
- **Bước:**
  1. Chạy 2 lệnh `rg` kiểm tra thuật ngữ cũ (danh sách từ khoá thống nhất trong yêu cầu đổi framing; không chép nguyên
     văn vào đây vì chính file này sẽ bị match).
  2. `make lint`, `make test-ci`, `make test-e2e`.
  3. So sánh mọi số trong `reports/{fairness,explainability}_report.{json,md}` và 10 khối `<!-- rai:... -->` của
     `docs/model-card.md`, `docs/data-card.md`, `docs/06-responsible-ai.md` với `dc95bc1` (bỏ qua timestamp); chạy lại
     `make responsible-ai` và so với bản đã stage.
  4. `make up`; mở `/docs`; gọi `POST /api/v1/predict/batch` cùng 2 chủ thẻ mẫu qua field `cardholders`, qua alias cũ
     (deprecated), gửi cả hai field, gửi field lạ.
  5. Tạo traffic `run_scenario.py normal` (600 + 4 × 300 request) + 15 batch + 3 explain; đánh giá mọi truy vấn PromQL
     của dashboard Business và ML Model trên Prometheus; chụp 2 dashboard.
  6. Render lại 7 file `.mmd` bằng `@mermaid-js/mermaid-cli@12` + `mermaid.config.json` vào thư mục tạm, so với SVG
     trong repo.
  7. Đọc `docs/01-problem-statement.md` từ đầu đến cuối.
- **Kỳ vọng:** chỉ còn match được chấp nhận (câu "Ngoài phạm vi" trong problem statement / model card, alias batch cũ
  trong schema / test / API reference / CHANGELOG); lint sạch, test pass, coverage ≥ 80 %; không lệch số nào; Swagger
  dùng "cardholder", alias hiện `deprecated`; 2 cách gọi batch đều 200 và cùng kết quả, gửi cả hai → 422; không panel
  nào "No data" vì đổi tên metric; SVG khớp `.mmd`; problem statement không còn ngụ ý duyệt cho khách chưa có thẻ.
- **Thực tế:**
  - Lệnh `rg` thứ hai: 0 match. Lệnh thứ nhất: 36 dòng, tất cả thuộc nhóm được chấp nhận, cộng key redact cũ giữ lại có
    chủ đích trong `config/logging.py` và 1 false positive trong JS minified của `reports/drift_report.html` (chuỗi
    tiếng Tây Ban Nha của Evidently, file không đổi so với `dc95bc1`). Chi tiết: test report §10.
  - `make lint`: ruff sạch, black 131 file không đổi, mypy 0 lỗi / 88 file. `make test-ci`: unit 311 pass + 2 skip,
    integration 71, data quality 10, model validation 4 (**396 pass**), coverage **91 %**. `make test-e2e`: 18/18 pass.
  - 4 file report + 10 khối rai: số lượng và thứ tự mọi số trùng khớp 100 % với `dc95bc1`; chỉ khác chữ và
    `generated_at`.
  - Swagger: tag `prediction` và summary/description 3 endpoint dùng "cardholder"; ví dụ "Two cardholders",
    "Low-risk cardholder"; schema `BatchPredictRequest` có `cardholders` (bắt buộc) và alias cũ gắn `deprecated`,
    `additionalProperties: false`. Batch: `cardholders` → 200, alias cũ → 200, `predictions` + `decision_summary`
    giống hệt (APPROVE 0.109174, DECLINE 0.993453); gửi cả hai field → 422 `extra_forbidden` tại alias; field lạ → 422.
    Lỗi validation báo đúng tên field đã gửi (`cardholders.1.SEX`, hoặc tiền tố alias cũ khi client gửi alias).
  - `/metrics` có `credit_cardholder_score_distribution` (help "scored cardholders"), tên metric cũ không còn series.
    27 panel có truy vấn: 26 có dữ liệu; "Last promoted version" hiện "none since restart" (metric Airflow không đổi
    tên, chỉ có sau khi promote champion mới).
  - 7/7 SVG render lại **trùng từng byte** với file trong repo.
  - Problem statement: nêu rõ nền tảng quản lý hạn mức cho thẻ đang lưu hành, lý do realtime (chủ thẻ chờ kết quả tăng
    hạn mức trên app, p95 ≤ 100 ms để cả luồng < 1 s) và batch (rà soát toàn danh mục sau kỳ sao kê); application
    scoring chỉ xuất hiện ở mục Ngoài phạm vi kèm lý do.
- **Evidence:** [TC-001_swagger-ui.png](evidence/TC-001_swagger-ui.png),
  [TC-001_swagger-batch-example.png](evidence/TC-001_swagger-batch-example.png),
  [TC-001_swagger-batch-schema-deprecated.png](evidence/TC-001_swagger-batch-schema-deprecated.png),
  [TC-002_grafana-business-kpis-normal.png](evidence/TC-002_grafana-business-kpis-normal.png),
  [TC-018_grafana-ml-model-cardholder-score.png](evidence/TC-018_grafana-ml-model-cardholder-score.png),
  [TC-018_system-context-diagram.png](evidence/TC-018_system-context-diagram.png)
- **Trạng thái:** PASS
