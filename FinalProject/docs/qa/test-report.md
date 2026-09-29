# Test report — Credit Default Risk Scoring

Kết quả kiểm thử ngày 28/09/2026 trên stack chạy thật (Docker Desktop, 12 service) theo [test-plan.md](test-plan.md).
Chi tiết từng test case (bước, kỳ vọng, thực tế): [test-cases.md](test-cases.md). Giờ ghi theo UTC.

## 1. Tóm tắt

| Hạng mục | Kết quả |
|---|---|
| Test case | 17 TC: 16 PASS, 1 PASS\* (TC-013, giới hạn môi trường §5); lần đầu 14 PASS, 2 PASS\*, 1 FAIL — đã retest sau fix (§7) |
| 11 kịch bản vận hành | 11/11 đã chạy trên stack thật, có số liệu và screenshot |
| Test tự động | unit + integration + data quality + model validation pass; e2e 17/17 trên stack thật; load 3/3 ở 10 user và 20 user (sau fix) |
| Coverage `credit_risk` | 91.3 % trên working tree cuối (ngưỡng 80 %), 372 test pass — xem §2 |
| Lint / type check | ruff, black, mypy: 0 lỗi (working tree cuối) |
| Alert | 11/11 rule có evidence firing **và** resolved (ngưỡng ≥ 7) — xem §3 |
| Triển khai Ubuntu 24.04 | Container `ubuntu:24.04`: `install.sh`, systemd unit, `.env`, Nginx thật → đạt; `deploy.sh`/`backup.sh` trong Docker-in-Docker không chạy được (giới hạn môi trường, §5) |
| Lỗi | 3 lỗi tìm được (1 Medium, 2 Low), **cả 3 đã sửa và retest đạt** (§7); không có Critical/High; không còn lỗi mở |

**Verdict:** hệ thống đạt tiêu chí ra của test plan về chức năng, alert, coverage, lint và NFR latency: sau khi API
chuyển sang gunicorn 2 worker, p95 `/predict` ở 20 user là 72 ms (SLO ≤ 100 ms). Phần `deploy.sh`/`backup.sh` trên
Ubuntu cần chạy lại trên VM thật khi có (§5).

## 2. Test tự động

| Bộ test | Lệnh | Kết quả |
|---|---|---|
| Lint + type check | `make lint` | ruff, black, mypy: 0 lỗi |
| Unit, integration, data quality, model validation | `make test-ci` | Xem bảng dưới |
| Alert rule | `make alerts-test` | `promtool check rules` + `promtool test rules` + `amtool check-config` pass |
| E2E trên stack thật | `make test-e2e` | 17/17 pass |
| Load (Locust) | `make test-load`, `make test-load-stress` | 3/3 pass ở 10 user và ở 20 user sau fix BUG-01 (§4) |

Số liệu cuối: `make lint` (16:46) và `make test-ci COV_MIN=80` (16:49) chạy trên **toàn bộ working tree** gồm các
bản sửa BUG-01/02/03 (gunicorn 2 worker, ADR 0007, `notify.py`, `webhook_receiver.py`, `scoring.py`…) và
`docs/openapi.yaml` đã làm mới. Lint: ruff sạch, black 122 file không đổi, mypy 0 lỗi trên 80 file. Tóm tắt coverage
lưu ở `reports/qa/coverage-summary.txt`, report HTML: [TC-015_coverage-html-report](evidence/TC-015_coverage-html-report.png)
(ảnh chụp lần chạy đầu).

| Bộ | Lần đầu (16:23, commit `dbc6cf1`) | Cuối (16:49, working tree sau fix) |
|---|---|---|
| tests/unit | 268 pass, 1 skip | 296 pass, 2 skip |
| tests/integration | 61 pass | 62 pass |
| tests/data_quality | 10 pass | 10 pass |
| tests/model_validation | 4 pass | 4 pass |
| **Tổng coverage** | **91 %** | **91.3 %** (3 586 statement, 534 branch) |

Hai test skip: `test_airflow_dags.py` (cần package `airflow`, chạy trong image bằng `make dags-test`) và một case của
`test_multiworker_serving.py` cần `/proc` của Linux (macOS không có; chạy được trên runner CI).

E2E và load **không** nằm trong `make test` (marker `e2e`, `load` bị loại trong `addopts`) vì cần stack đang chạy:
`make test-e2e`, `make test-load`, `make test-load-stress`.

**Lưu ý môi trường:** `make test-ci` phải chạy trong shell **không** export biến từ `.env`. Nếu đã `set -a; . ./.env`
(ví dụ để lấy API key), `test_settings.py::test_environment_overlays_differ` fail vì `POSTGRES_PORT=15434` của máy dev
ghi đè giá trị mặc định. CI không có các biến này; lần chạy cuối dùng `env -i` và pass.

## 3. Alert: firing → resolved

Nguồn: poll `GET /api/v1/alerts` của Prometheus mỗi 10 s (lưu `reports/qa/alert-timeline.jsonl`) và lịch sử
`alert-webhook` (`/alerts`, `/alerts/state`). Mỗi alert được Alertmanager route tới cả `telegram` và `webhook`.

| # | Rule | Severity | Tác nhân (TC) | Firing | Resolved | Webhook firing / resolved |
|---|---|---|---|---|---|---|
| 1 | `APIDown` | critical | outage (TC-007) | 14:43:08 | 14:43:48 | 14:43:16 / 14:44:16 |
| 2 | `HighErrorRate` | critical | model unloaded + load (TC-009) | 14:55:19 | 14:59:09 | 14:55:31 / 14:59:31 |
| 3 | `HighLatencyP95` | warning | 0.5 CPU + load (TC-008) | 14:48:08 | 14:50:38 | 14:48:16 / 14:51:16 |
| 4 | `DataDriftDetected` | warning | drift (TC-003) | 15:01:19 | 15:10:50 | 15:01:16 / 15:11:16 |
| 5 | `DriftMonitorDown` | critical | `chaos-drift-down` (TC-005) | 14:35:18 | 14:41:18 | 14:35:31 / 14:41:31 |
| 6 | `DriftAnalysisStale` | warning | `chaos-drift-stale` (TC-014) | 15:43:39 | 15:45:39 | 15:43:46 / 15:45:46 |
| 7 | `ModelNotLoaded` | critical | `chaos-model-unloaded` (TC-009) | 14:53:59 | 14:57:29 | 14:54:11 / 14:58:11 |
| 8 | `ModelServedFromFallback` | warning | MLflow down + restart API (TC-010) | 15:18:21 | 15:20:02 | 15:18:26 / 15:20:26 |
| 9 | `PredictionDistributionShift` | warning | attack (TC-011) | 15:09:00 | 15:10:30 | 15:09:11 / 15:11:11 |
| 10 | `RetrainFailed` | critical | `retrain-fail` (TC-005) | 14:33:27 | 14:41:18 | 14:33:41 / 14:41:41 |
| 11 | `AirflowDagImportErrors` | warning | `chaos-dag-import-error` (TC-005) | 14:38:28 | 14:40:58 | 14:38:41 / 14:41:41 |

Ngoài ra `HighLatencyP95`, `DataDriftDetected` và `PredictionDistributionShift` còn firing/resolved thêm một lần lúc
14:24–14:27 do lần load 20 user (TC-017) với dữ liệu Locust ngẫu nhiên; `HighLatencyP95` firing 15:34:08 → resolved
15:34:38 khi máy test bị tranh chấp CPU (TC-016, lần chạy lại).

Lần chạy lại để lấy tin Telegram (15:46–16:00): `DataDriftDetected` firing 15:48:09 → resolved 15:59:10,
`PredictionDistributionShift` firing 15:47:59 → resolved 15:59:00 (TC-003); `ModelNotLoaded` firing 15:53:50 → resolved
15:58:50, `HighErrorRate` pending 15:53:10 → firing 15:55:10 → resolved 16:00:20 (TC-009, `make chaos-model-unloaded` +
load 330 s, khôi phục 15:58:08). Khi API khởi động lại, `APIDown` chỉ pending 10 s (15:58:40–15:58:50), không firing.

**Ghi chú `DriftAnalysisStale`:** chaos bật lúc 15:23:12 (drift monitor khởi động lại, mất database, chưa phân tích
thành công lần nào nên `last_analysis_timestamp = 0`). Rule chuyển pending 15:38:39, firing 15:43:39 (sau `for: 5m`);
`make chaos-restore` lúc 15:45:05, phân tích thành công 15:45:29 → resolved 15:45:39. Tin Telegram RESOLVED hiện trong
[TC-003_telegram-DataDriftDetected](evidence/TC-003_telegram-DataDriftDetected.png).

**Telegram (nhóm "Test MLOps"):**

- [APIDown FIRING + RESOLVED](evidence/TC-007_telegram-APIDown.png) (kèm RESOLVED của `RetrainFailed`,
  `AirflowDagImportErrors`).
- [RetrainFailed + DriftMonitorDown + AirflowDagImportErrors FIRING và tin retrain từ Airflow](evidence/TC-005_telegram-RetrainFailed.png).
- [DataDriftDetected FIRING, tin `[DRIFT]` và `[RETRAIN] challenger v9 rejected` từ Airflow, DriftAnalysisStale
  RESOLVED](evidence/TC-003_telegram-DataDriftDetected.png).
- [HighErrorRate FIRING (kèm ModelNotLoaded FIRING, `[HEALTH]` từ Airflow)](evidence/TC-009_telegram-HighErrorRate.png),
  [HighErrorRate RESOLVED (kèm ModelNotLoaded, DataDriftDetected, PredictionDistributionShift
  RESOLVED)](evidence/TC-009_telegram-HighErrorRate-resolved.png).

## 4. Load test

| Lần chạy | Cấu hình | Request | Lỗi | RPS | p50 | p95 `/predict` | p99 | Kết luận |
|---|---|---|---|---|---|---|---|---|
| Danh định (14:22:32) | Locust 10 user, 45 s | 1 321 | 0 | 29.95 | 17 ms | 53 ms | 150 ms | Đạt SLO 100 ms |
| Tải gấp đôi (14:21:13) | Locust 20 user, 60 s | 3 305 | 0 | 55.88 | 36 ms | **170 ms** | 270 ms | Vượt SLO → BUG-01 |
| Tải gấp đôi sau fix (16:39:19) | `make test-load-stress`: 20 user, 60 s, gunicorn 2 worker | 3 556 | 0 | 60.07 | 18 ms | **72 ms** | 290 ms | Đạt SLO, BUG-01 đã sửa |
| Chaos latency (14:45:21) | simulator 32 luồng × 180 s, API 0.5 CPU | 4 035 | 0 | 22.4 | 1 397 ms | 2 084 ms | 2 807 ms | Alert đúng (TC-008) |
| Baseline `make bench` | 500 request tuần tự | 500 | 0 | — | — | 20.59 ms | 29.49 ms | Model p95 11.55 ms |
| Lỗi 5xx (14:52:52) | simulator 4 luồng × 240 s, model unloaded | 191 080 | 100 % 503 | 796 | 4.1 ms | 9.8 ms | 24.5 ms | Fail-fast đúng (TC-009) |
| Lỗi 5xx lần 2 (15:52:22) | simulator × 330 s, model unloaded | 337 675 | 100 % 503 | 1 023 | 28.2 ms | 54.9 ms | 89.3 ms | Fail-fast đúng, lấy tin Telegram (TC-009) |
| Chạy lại khi máy bận (15:30:54) | Locust 10 user, 60 s, load average host 50 | 1 414 | 0 | 23.75 | 29 ms | 660 ms | 1 200 ms | Không dùng làm số danh định |

Kết quả: `reports/load/` (CSV, HTML, `locust_summary.json`, `locust_stress_20u_*` lần đầu, `locust_stress_*` sau fix,
`locust_rerun_host_contention_summary.json`), `reports/simulations/*.json`, `reports/latency_benchmark.json`.

## 5. Triển khai Ubuntu 24.04

Máy test không có Multipass/UTM nên dùng container `ubuntu:24.04` (aarch64). Bundle release là cây file git của
working copy (không `.env`, không `.venv`), giống `git archive` trong CD.

| Bước guide | Cách chạy | Kết quả |
|---|---|---|
| §1 OS | `ubuntu:24.04` | Ubuntu 24.04.5 LTS (aarch64) |
| §3 `install.sh` | `SKIP_UFW=1` | Docker 29.8.1 + Compose v5.5.1 từ download.docker.com, Nginx, user `deploy` (nhóm `docker`), `/opt/credit-risk/{releases,shared}`, `/var/backups/credit-risk` quyền 700 |
| §4 `shared/.env` | từ `.env.example` + `openssl rand` | quyền 600, owner `deploy`, 0 giá trị `change-me` |
| §8 systemd | `systemd-analyze verify` 3 unit | exit 0 |
| Script | `bash -n`, `shellcheck -S error` | sạch |
| §7 Nginx | site `credit-risk.conf`, host network tới API đang chạy | `/health/ready` 200, `/metrics` 404, `/api/*` không key 401, có key 200, vhost Grafana 200, 3 security header, 120 request dồn dập → 56 × 401 + 64 × 429 |
| §6 `deploy.sh deploy/smoke`, §9 backup/restore, §10 upgrade, §11 rollback | Docker-in-Docker (container privileged) | **Không chạy được** — xem giới hạn |

**Giới hạn:**

- Docker-in-Docker lần 1: overlayfs lồng nhau không giải nén được image (`failed to convert whiteout file`). Lần 2 (volume
  riêng cho `/var/lib/docker`): `runc` lỗi cgroup v2 lồng nhau ("cannot enter cgroupv2 /sys/fs/cgroup/docker with domain
  controllers -- it is in an invalid state"), đồng thời Docker Desktop hết đĩa (DinD cần ~4 GB, VM chỉ còn 2.6 GB).
  Log: `reports/qa/ubuntu2404-dind-attempt.txt`.
- Không kiểm thử được: UFW (container không điều khiển netfilter), systemd thật làm PID 1 (`enable --now`, timer backup
  chạy thật), reboot, TLS Let's Encrypt.
- CI có dựng compose stack và smoke test (job *Build image, Trivy scan & compose smoke test* pass) nhưng không chạy
  `deploy.sh`/`backup.sh`; cần chạy lại §6–§11 trên VM Ubuntu 24.04 thật trước khi release.

Log đầy đủ lần chạy đạt: `reports/qa/ubuntu2404-container-deploy.txt`.

## 6. Sự cố môi trường trong lúc test

| Thời điểm | Sự cố | Ảnh hưởng | Xử lý |
|---|---|---|---|
| ~15:00 | Lần thử Docker-in-Docker làm đầy đĩa VM Docker Desktop (100 %) | `airflow-scheduler` ghi log lỗi `No space left on device`, treo (health 503, CPU 210 %), run `drift_monitoring` 14:59:52 chờ ~4 phút | Xoá container + volume DinD (còn 2.6 GB), `docker compose restart airflow-scheduler` lúc 15:03; run chạy tiếp và success |
| 15:30–15:36 | Tác vụ nền macOS (`mobileassetd`, `modelcatalogd`, `fseventsd`) đẩy load average host lên 50–180 | Lần chạy lại load test p95 660 ms, `HighLatencyP95` firing 15:34:08 | Không dùng số liệu lần này làm danh định |

Không có dữ liệu nào bị mất; mọi service `healthy` sau xử lý.

## 7. Lỗi tìm được

| Mã | Mức | Tiêu đề | Tái hiện | Trạng thái |
|---|---|---|---|---|
| BUG-01 | Medium | API không đạt SLO p95 ≤ 100 ms ở ~56 rps (Locust 20 user) — p95 170 ms, `HighLatencyP95` firing không cần chaos | `LOAD_USERS=20 LOAD_DURATION=60s make test-load` trên stack mặc định (API 1 uvicorn worker, 2 CPU) | **Đã sửa, retest đạt:** API chạy gunicorn 2 worker (ADR 0007); `make test-load-stress` 16:39 → 0 lỗi, p95 `/predict` 72 ms |
| BUG-02 | Low | Thông báo Airflow gửi qua webhook (`RetrainFailed`, `AirflowTaskFailed`, `ServiceHealthCheck`, `DataDriftDetected`) không bao giờ resolved → `/alerts/state` kẹt `firing` | Tắt Telegram (hoặc Telegram lỗi) → `make retrain-fail` → `curl localhost:19095/alerts/state`: mục `source=airflow` có `status=firing`, `endsAt=0001-01-01` mãi mãi. Nguyên nhân: `orchestration/airflow/utils/notify.py::send_webhook` gửi sự kiện one-shot với `status="firing"` | **Đã sửa, retest đạt:** event Airflow mang `kind=event`, `endsAt = startsAt`; receiver lưu ở `/alerts`, không đưa vào `/alerts/state` (16:43, TC-014) |
| BUG-03 | Low | Histogram `credit_prediction_duration_seconds` khai báo nhưng không bao giờ `.observe()` → panel "Model inference latency" (ML Model) luôn "no observations" | Gửi bất kỳ request `/predict` → `curl localhost:18020/metrics \| grep credit_prediction_duration_seconds_count` = 0; `rg PREDICTION_LATENCY src` chỉ có định nghĩa | **Đã sửa, retest đạt:** `ScoringService.score()` đo thời gian gọi model; count 0 → 14 sau 7 lần `sample_predict.py`; panel có p50 ~7 ms, p95 ~30 ms (TC-004) |

### 7.1 Retest sau fix và hồi quy (16:38–16:50)

Stack build lại bằng `make up` lúc 16:38 (15/15 service healthy; API chạy `gunicorn` 1 master + 2 worker). Không chạy
tác vụ nặng khác trên host trong lúc load test.

| Hạng mục | Cách kiểm | Kết quả |
|---|---|---|
| BUG-01 / TC-017 | `make test-load-stress` (20 user, 60 s) | 3 556 request, 0 lỗi, 60.07 rps; p95 `/predict` 72 ms, batch 62 ms, tổng hợp 69 ms → **PASS** |
| BUG-02 / TC-014 | restart `alert-webhook`; `notify()` trong `airflow-scheduler` với Telegram rỗng | 2 event `kind=event` trong `GET /alerts`; `/alerts/state` 0 mục `source=airflow` → **PASS** |
| BUG-03 / TC-004 | `sample_predict.py` + load; `/metrics`; Prometheus; Grafana ML Model | `credit_prediction_duration_seconds_count` > 0; panel "Model inference latency" có p50/p95 → **PASS** |
| `/health/live`, `/health/ready` | `curl` | 200 `alive`; 200 `ready`, không có reason |
| `/api/v1/predict` | hồ sơ rủi ro thấp / cao; thiếu API key | 200 (PD 0.363, `REVIEW`) / 200 (PD 0.993); thiếu key 401 `MISSING_API_KEY` |
| `/api/v1/predict/batch` | 3 hồ sơ | 200, `count` 3 |
| Reload model | `POST /api/v1/model/reload` rồi 30 × `GET /model/info` | `reloaded` v1 → v1; 2 mốc `loaded_at` khác nhau 0.4 s → cả 2 worker đã nạp lại |
| Alert → Telegram | `make alerts-send-test` 16:43:22 | FIRING webhook 16:43:37, RESOLVED 16:45:37; bộ đếm Alertmanager `telegram` 46 → 48, `webhook` 45 → 47, 0 lỗi gửi |
| OpenAPI | `make openapi` | `docs/openapi.yaml` sinh lại trùng bản trong working tree (8 path) |

Quan sát không tạo lỗi: ở lần chạy drift đầu (15:00) `trigger_model_retrain` bị bỏ qua do cooldown 60 phút (retrain
gần nhất 14:40:48) — đúng thiết kế. Chạy lại lúc 15:46 (đã qua cooldown): `drift_monitoring` gọi `trigger_model_retrain`,
run `model_retrain` 15:46:28 success, challenger v9 bị gate loại (expected loss cao hơn champion), giữ champion v1.

## 8. Bảng test case → evidence

| TC | Screenshot |
|---|---|
| TC-001 | [swagger-ui](evidence/TC-001_swagger-ui.png) |
| TC-002 | [normal-traffic-simulation](evidence/TC-002_normal-traffic-simulation.png), [normal-no-drift-no-alert](evidence/TC-002_normal-no-drift-no-alert.png), [grafana-infra-sla-normal](evidence/TC-002_grafana-infra-sla-normal.png), [grafana-business-kpis-normal](evidence/TC-002_grafana-business-kpis-normal.png) |
| TC-003 | [drift-simulation-analyze](evidence/TC-003_drift-simulation-analyze.png), [prometheus-datadrift-firing](evidence/TC-003_prometheus-datadrift-firing.png), [drift-dag-trigger](evidence/TC-003_drift-dag-trigger.png), [airflow-drift-monitoring-run](evidence/TC-003_airflow-drift-monitoring-run.png), [evidently-drift-report](evidence/TC-003_evidently-drift-report.png), [grafana-drift-dashboard](evidence/TC-003_grafana-drift-dashboard.png), [drift-rerun-retrain-trigger](evidence/TC-003_drift-rerun-retrain-trigger.png), [airflow-drift-rerun-trigger-retrain](evidence/TC-003_airflow-drift-rerun-trigger-retrain.png), [airflow-model-retrain-from-drift](evidence/TC-003_airflow-model-retrain-from-drift.png), [telegram-DataDriftDetected](evidence/TC-003_telegram-DataDriftDetected.png) |
| TC-004 | [promote-hot-reload-under-traffic](evidence/TC-004_promote-hot-reload-under-traffic.png), [mlflow-champion-v5](evidence/TC-004_mlflow-champion-v5.png), [grafana-ml-model-version-5](evidence/TC-004_grafana-ml-model-version-5.png), [mlflow-registry-aliases](evidence/TC-004_mlflow-registry-aliases.png), [grafana-model-inference-latency](evidence/TC-004_grafana-model-inference-latency.png) (sau fix BUG-03) |
| TC-005 | [retrain-fail-trigger](evidence/TC-005_retrain-fail-trigger.png), [airflow-quality-gate-failed](evidence/TC-005_airflow-quality-gate-failed.png), [prometheus-3-alerts-firing](evidence/TC-005_prometheus-3-alerts-firing.png), [alertmanager-3-alerts-firing](evidence/TC-005_alertmanager-3-alerts-firing.png), [telegram-RetrainFailed](evidence/TC-005_telegram-RetrainFailed.png), [restore-and-retrain-success](evidence/TC-005_restore-and-retrain-success.png), [airflow-model-retrain-success-graph](evidence/TC-005_airflow-model-retrain-success-graph.png), [mlflow-experiment-runs](evidence/TC-005_mlflow-experiment-runs.png) |
| TC-006 | [rollback-under-traffic](evidence/TC-006_rollback-under-traffic.png) |
| TC-007 | [api-outage-simulation](evidence/TC-007_api-outage-simulation.png), [prometheus-apidown-firing](evidence/TC-007_prometheus-apidown-firing.png), [telegram-APIDown](evidence/TC-007_telegram-APIDown.png) |
| TC-008 | [latency-bench-chaos-load](evidence/TC-008_latency-bench-chaos-load.png), [prometheus-highlatency-firing](evidence/TC-008_prometheus-highlatency-firing.png), [grafana-latency-spike](evidence/TC-008_grafana-latency-spike.png) |
| TC-009 | [client-errors-4xx](evidence/TC-009_client-errors-4xx.png), [model-unloaded-5xx-load](evidence/TC-009_model-unloaded-5xx-load.png), [prometheus-modelnotloaded-higherrorrate-firing](evidence/TC-009_prometheus-modelnotloaded-higherrorrate-firing.png), [alertmanager-modelnotloaded-higherrorrate](evidence/TC-009_alertmanager-modelnotloaded-higherrorrate.png), [grafana-error-rate-spike](evidence/TC-009_grafana-error-rate-spike.png), [telegram-HighErrorRate](evidence/TC-009_telegram-HighErrorRate.png), [telegram-HighErrorRate-resolved](evidence/TC-009_telegram-HighErrorRate-resolved.png) |
| TC-010 | [postgres-mlflow-down-degraded](evidence/TC-010_postgres-mlflow-down-degraded.png), [prometheus-fallback-firing](evidence/TC-010_prometheus-fallback-firing.png), [grafana-serving-local-fallback](evidence/TC-010_grafana-serving-local-fallback.png), [mlflow-back-reload](evidence/TC-010_mlflow-back-reload.png) |
| TC-011 | [attack-simulation](evidence/TC-011_attack-simulation.png), [prometheus-prediction-shift-firing](evidence/TC-011_prometheus-prediction-shift-firing.png), [alertmanager-drift-and-shift](evidence/TC-011_alertmanager-drift-and-shift.png), [grafana-business-decline-spike](evidence/TC-011_grafana-business-decline-spike.png), [resolve-normal-unpause](evidence/TC-011_resolve-normal-unpause.png) |
| TC-012 | [responsible-ai-fairness](evidence/TC-012_responsible-ai-fairness.png) |
| TC-013 | [ubuntu2404-install-nginx-verify](evidence/TC-013_ubuntu2404-install-nginx-verify.png) |
| TC-014 | [chaos-drift-stale](evidence/TC-014_chaos-drift-stale.png), [prometheus-driftanalysisstale-firing](evidence/TC-014_prometheus-driftanalysisstale-firing.png), [alertmanager-driftanalysisstale](evidence/TC-014_alertmanager-driftanalysisstale.png), [drift-stale-restore](evidence/TC-014_drift-stale-restore.png), [webhook-alert-state-fired-resolved](evidence/TC-014_webhook-alert-state-fired-resolved.png), [webhook-airflow-event-not-in-state](evidence/TC-014_webhook-airflow-event-not-in-state.png) (sau fix BUG-02) |
| TC-015 | [make-lint](evidence/TC-015_make-lint.png), [coverage-html-report](evidence/TC-015_coverage-html-report.png), [alerts-test-e2e](evidence/TC-015_alerts-test-e2e.png) |
| TC-016 | [locust-report-10-users](evidence/TC-016_locust-report-10-users.png) |
| TC-017 | [locust-report-20-users](evidence/TC-017_locust-report-20-users.png) (lần đầu), [locust-report-20-users-after-fix](evidence/TC-017_locust-report-20-users-after-fix.png) (sau fix BUG-01) |

## 9. Kiểm chứng traceability

Chạy tại thư mục gốc repo (`DDM501_Group5/`) hai lệnh `rg` kiểm chứng traceability đã thống nhất (lệnh 1: nhãn tiến
độ nội bộ, mã ticket, thuật ngữ ADR/kiến trúc và tên vai trò; lệnh 2: dấu vết phân công thành viên và tên tài khoản).
Lệnh không được chép nguyên văn vào đây vì chính các từ khoá trong lệnh sẽ khiến file này bị match.

- **Lệnh 1:** 11 dòng, **tất cả** trong `FinalProject/reports/drift_report.html` (report Evidently minified: base64 font
  và JavaScript, dòng 14, 101, 140, 639, 640, 644, 651, 652, 784, 829, 849) — khớp kỳ vọng.
- **Lệnh 2:** 33 match, **tất cả** là URL repo thật của dự án: badge CI/CD và `git clone` trong `README.md` (3),
  `runbook_url` trong 3 file rule Prometheus (11) và `alerts_test.yml` (12), nhãn `org.opencontainers.image.source`
  trong 3 Dockerfile (3), `Makefile` (1), `docs/guides/local-quickstart.md` (1), `docs/guides/ubuntu-deployment.md` (2:
  `git clone` và đường dẫn image GHCR của repo) — giữ cố ý, khớp kỳ vọng.

Lần chạy cuối: 16:34 UTC, sau khi hoàn thiện `test-cases.md`, `test-report.md`, `README.md` của `docs/qa/`.

Kiểm lại sau retest (16:52 UTC), trong `FinalProject/` trên `docs`, `README.md`, `CONTRIBUTING.md` với mẫu nhãn tiến độ
nội bộ, mã ticket và tên công cụ: 0 match. Trước đó cột "Rubric" của `docs/assets/diagrams/README.md` dùng mã mục viết
tắt (3 dòng match); đã đổi sang số mục rubric `3.1.x` giống [docs/README.md](../README.md#3-rubric--file--bằng-chứng).
