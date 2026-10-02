# 02 — System design & architecture

> Rubric **B. System Design & Architecture (15%)**. Diagram render từ nguồn Mermaid trong
> [`assets/diagrams/src/`](assets/diagrams/src/) (`bash scripts/render_diagrams.sh`); quyết định kiến trúc ghi ở
> [`adr/`](adr/). Tóm tắt một trang: [`ARCHITECTURE.md`](../ARCHITECTURE.md).

## 1. Nguyên tắc kiến trúc

| Nguyên tắc | Áp dụng |
|---|---|
| **Một package, nhiều entrypoint** | Toàn bộ logic ở `src/credit_risk`; API, script `make`, Airflow task và drift monitor chỉ là lớp mỏng gọi cùng hàm ([ADR 0006](adr/0006-src-layout-package-and-layered-config.md)) |
| **Registry là nguồn sự thật của model** | API nạp `models:/credit-risk-model@champion`; promote/rollback = đổi alias, không build lại image |
| **Degrade chứ không chết** | Mất MLflow → artifact local (`degraded`); mất PostgreSQL → vẫn chấm điểm, bỏ ghi log; reload lỗi → giữ model cũ |
| **Một quality gate** | `evaluation.model_validation` dùng chung cho `make train`, `make retrain`, DAG `model_retrain` |
| **Quan sát trước khi vận hành** | Mọi service có healthcheck + `/metrics`; alert có runbook; log JSON có `request_id` |
| **Security by default** | API key, non-root container, secret chỉ qua `.env`, port prod bind `127.0.0.1`, không log PII thô |
| **Reversibility** | Release thư mục + symlink `current` (rollback tức thì), `@previous_champion`, compose profiles bật/tắt theo nhóm |

## 2. Sơ đồ kiến trúc

Ba mức chi tiết, từ ngoài vào trong: hệ thống và các bên liên quan → các container chạy trong Compose → component bên
trong API và ML pipeline.

### 2.1 Sơ đồ ngữ cảnh hệ thống

Card Management System / mobile app backend gọi `/predict` realtime khi chủ thẻ gửi yêu cầu tăng hạn mức; batch job rà
soát hạn mức gọi `/predict/batch` sau mỗi kỳ sao kê (trong demo cả hai là persona simulator). Chuyên viên rủi ro tín dụng
và risk manager dùng Grafana và kết quả explain; MLOps engineer vận hành qua SSH, Airflow, MLflow; thông báo ra Telegram.

![Sơ đồ ngữ cảnh hệ thống](assets/diagrams/01-system-context.svg)

### 2.2 Sơ đồ container

Project Compose `credit-risk-mlops`: 15 service (12 long-running + 3 job one-shot), chia 3 profile để bật tách.

![Sơ đồ container](assets/diagrams/02-container.svg)

### 2.3 Sơ đồ component

![Sơ đồ component — Scoring API](assets/diagrams/03-component-api.svg)

![Sơ đồ component — ML pipeline](assets/diagrams/04-component-ml-pipeline.svg)

## 3. Trách nhiệm thành phần

### 3.1 Container

| Container | Profile | Trách nhiệm | Phụ thuộc | Trạng thái lưu |
|---|---|---|---|---|
| `api` | core | Chấm điểm, explain, reload model, ghi inference log, `/metrics` | mlflow (tuỳ chọn), postgres (tuỳ chọn) | Không (stateless) |
| `mlflow` | core | Tracking server + model registry (alias `@champion`, `@previous_champion`, `@challenger`) | postgres, minio | — |
| `postgres` | core | MLflow metadata, `inference_logs`, Airflow metadata (DB `airflow`) | — | volume `pgdata` |
| `minio` (+`minio-init`) | core | Artifact store S3 cho MLflow (model, plot, report) | — | volume `miniodata` |
| `model-bootstrap` | core | One-shot: đăng ký model baseline vào registry nếu registry trống | mlflow | — |
| `drift-monitor` | monitoring | Mỗi 60 s so 500 inference log gần nhất với reference: PSI + Evidently + prediction PSI; HTML report | postgres, `data/reference` | volume `drift-reports` |
| `prometheus` | monitoring | Scrape API, drift monitor, statsd-exporter, MinIO, Grafana, Alertmanager; recording + alert rules | — | volume `prometheus-data` (15 ngày) |
| `alertmanager` | monitoring | Route, group, inhibit; gửi Telegram (khi có token) và `alert-webhook` | — | volume `alertmanager-data` |
| `alert-webhook` | monitoring | Receiver nội bộ luôn nhận alert, lưu trạng thái firing/resolved (`/alerts/state`) | — | bộ nhớ |
| `grafana` | monitoring | 4 dashboard auto-provision: Business, ML model, Drift, Infra & SLA | prometheus | volume `grafana-data` |
| `statsd-exporter` | monitoring, orchestration | Chuyển metric StatsD của Airflow + gauge retrain sang Prometheus | — | — |
| `airflow-webserver` / `-scheduler` (+`airflow-init`) | orchestration | DAG `service_health_check`, `drift_monitoring`, `model_retrain` | postgres, api, mlflow, drift-monitor | volume `airflow-logs` |

### 3.2 Package `credit_risk`

| Sub-package | Trách nhiệm chính | Dùng bởi |
|---|---|---|
| `config` | Settings phân lớp YAML → `environments/<APP_ENV>.yaml` → env; logging JSON có redact PII | mọi entrypoint |
| `data` | Schema cột, load, split theo partition, pandera validation, manifest SHA256 (data versioning) | train, retrain, drift, test |
| `features` | `FeatureEngineer` — 12 feature (utilization, payment ratio, delinquency trend…) nằm trong pipeline model | train + serving (cùng code) |
| `training` | Model zoo 4 thuật toán, Optuna HPO + stratified CV, MLflow log/register, `promote_model_version`, `rollback_champion`, retrain | `make train/retrain`, Airflow |
| `evaluation` | ROC-AUC, PR-AUC, F1, recall, expected financial loss, quality gate champion/challenger, report | train, retrain, test |
| `responsible_ai` | Fairlearn audit + mitigation, SHAP/LIME, reason codes, pseudonymization, retention | `make responsible-ai`, `/explain` |
| `monitoring` | Prometheus metrics của API, PSI + Evidently | API, drift monitor, `make drift` |
| `serving` | FastAPI app factory, routers v1, schemas, auth, middleware request-id, error model, `ModelManager`, readiness, decision engine, inference log DB | container `api` |

## 4. Data flow

### 4.1 Bốn luồng chính

![Data flow end-to-end + edge cases](assets/diagrams/05-data-flow.svg)

| Luồng | Các bước | Output |
|---|---|---|
| **Offline training** | `data/raw` → `make data` (split theo tuổi) → `make manifest` (SHA256) → `make validate` (pandera, fail fast) → `FeatureEngineer` → Optuna 20 trial × 4 thuật toán, 5-fold CV → holdout + gate trên `stream_normal` → MLflow run + register → alias `@champion` → `models/*.joblib` fallback | Registry version, `reports/model_comparison.*`, `reports/figures/` |
| **Model loading** | API startup/reload → probe MLflow (0.5 s) → nạp `@champion` → swap snapshot atomic; lỗi → artifact local (`degraded`) hoặc giữ model cũ | `credit_model_info`, `credit_model_degraded` |
| **Online scoring** | CMS / mobile app backend (realtime) hoặc batch job rà soát hạn mức → (Nginx) → middleware request-id → auth `X-API-Key` → Pydantic validate → pipeline model → decision engine (APPROVE/REVIEW/DECLINE, score 300–850) → metric → ghi `inference_logs` (pseudonymized) → response | JSON response, metric, inference log |
| **Monitoring feedback loop** | Prometheus scrape 10 s (drift monitor 15 s), đánh giá rule 15 s → rules → Alertmanager → Telegram/webhook; drift monitor đọc `inference_logs` mỗi 60 s → gauge drift; Airflow `drift_monitoring` (30 phút) → drift ⇒ trigger `model_retrain` (cooldown 60 phút) | Alert, dashboard, retrain run |

### 4.2 Edge case

| Edge case | Hành vi | Tín hiệu quan sát | Kiểm chứng |
|---|---|---|---|
| Dữ liệu train sai schema / ngoài miền | `make validate` dừng, exit ≠ 0, không train | `reports/data_validation.json` | `tests/data_quality/` |
| File dữ liệu đổi mà manifest chưa cập nhật | Train dừng tới khi review + `make manifest` | log + exit code | `tests/data_quality/` |
| Request thiếu field / sai kiểu / ngoài miền / field lạ | `422 VALIDATION_ERROR`, `details` theo field, không echo giá trị | `credit_api_requests_total{status="422"}` | kịch bản 8 |
| JSON hỏng | `422` | idem | `tests/integration/test_api.py` |
| Thiếu / sai API key | `401 MISSING_API_KEY` (+`WWW-Authenticate`) / `403 INVALID_API_KEY` | `credit_api_auth_failures_total` | kịch bản 8 |
| Batch > 500 chủ thẻ | `413 BATCH_TOO_LARGE` | response body | integration test |
| MLflow down lúc API khởi động | Phục vụ artifact local, readiness `degraded` (200) | `ModelServedFromFallback` | kịch bản 9 |
| MLflow down lúc reload | Giữ model registry đang phục vụ (không hạ cấp) | `credit_model_reloads_total{result="failure"}` | integration test |
| Không nạp được model nào | `503 MODEL_UNAVAILABLE`, readiness `not_ready` (503) | `ModelNotLoaded` (+`HighErrorRate` nếu có traffic) | `make chaos-model-unloaded` |
| PostgreSQL down | Vẫn chấm điểm, bỏ ghi log, readiness `degraded` | `/health/ready` reasons | kịch bản 9 |
| Drift monitor thiếu mẫu (< 50) / DB lỗi | `status=skipped`, DAG không fail | `DriftAnalysisStale` nếu kéo dài > 15 phút | `make chaos-drift-stale` |
| Challenger tệ hơn champion | Gate từ chối, giữ champion, DAG vẫn success | log `keep_champion` | kịch bản 4 |
| Retrain lỗi thật (train lỗi, dưới sàn ROC-AUC, reload sai version) | DAG failed, `rollback_champion`, gauge = 1 | `RetrainFailed` | kịch bản 4 |
| Dồn dập yêu cầu tăng hạn mức từ tài khoản nợ quá hạn | Tỷ lệ DECLINE tăng, prediction PSI ≥ 0.25 | `PredictionDistributionShift` | kịch bản 10 |
| Không có Telegram token | Alertmanager chỉ gửi `alert-webhook` | `make alerts` | kịch bản 6 |
| Deploy/smoke fail trên server | `deploy.sh rollback` về release trước (image digest cũ) | job CD failed + Telegram | [07 §6](07-testing-cicd.md#6-release-và-rollback) |

### 4.3 Vòng lặp retrain

![Sequence drift → retrain → gate → promote / rollback](assets/diagrams/06-retrain-sequence.svg)

## 5. Deployment view

![Deployment trên Ubuntu 24.04](assets/diagrams/07-deployment-ubuntu.svg)

| Môi trường | `APP_ENV` | Cách chạy | MLflow | Database |
|---|---|---|---|---|
| Test / CI | `test` | `make test-ci` (hermetic) | port đóng → fallback local | SQLite in-memory |
| Dev local | `local` / `docker` | `make up` (stack đủ) — script trên host dùng `local` | `localhost:15040` / `mlflow:5000` | Postgres `localhost:15434` / `postgres:5432` |
| Smoke CI | `docker` | `make smoke` (project `credit-risk-smoke`, image đã scan) | `mlflow:5000` | `postgres:5432` |
| Production (1 host) | `docker` | `deploy.sh` + overlay `docker-compose.prod.yml` + image GHCR theo digest, Nginx + TLS, systemd | nội bộ | nội bộ |

Chi tiết: [guide Ubuntu](guides/ubuntu-deployment.md), [CI/CD](07-testing-cicd.md).

## 6. Tech stack & lý do chọn

| Lớp | Chọn | Lý do | Phương án đã cân nhắc | ADR |
|---|---|---|---|---|
| Ngôn ngữ / packaging | Python 3.11, src layout, `uv` + `uv.lock`, `requirements*.txt` sinh tự động | Hệ sinh thái ML; lock tái lập; pip vẫn dùng được | Poetry, conda | [0006](adr/0006-src-layout-package-and-layered-config.md) |
| Validation dữ liệu | pandera | Schema khai báo trên DataFrame, lỗi theo dòng/cột, nhẹ | Great Expectations (nặng, nhiều config) | — |
| ML | scikit-learn pipeline, XGBoost, LightGBM, Optuna | 4 thuật toán cùng interface; TPE + pruning hiệu quả với 20 trial | Grid search (tốn), AutoML (khó giải thích) | — |
| Tracking / registry | MLflow + PostgreSQL + MinIO | Alias registry cho hot reload; self-hosted; giống kiến trúc S3 thật | W&B (SaaS), DVC (không registry runtime) | [0002](adr/0002-mlflow-minio-postgres.md) |
| Serving | FastAPI + Uvicorn, model in-process | OpenAPI tự sinh, Pydantic validate, p95 18.79 ms | Flask, BentoML, Triton | [0001](adr/0001-serving-with-fastapi.md) |
| Drift | Evidently + PSI tự cài | PSI dễ giải thích cho tín dụng; Evidently cho test thống kê + HTML | Alibi Detect, NannyML, SaaS | [0004](adr/0004-evidently-for-drift.md) |
| Orchestration | Apache Airflow 2.10 | Branching, retry, lịch + trigger, UI/lịch sử làm evidence | cron, Prefect, Dagster, Kubeflow | [0003](adr/0003-airflow-instead-of-cron.md) |
| Monitoring | Prometheus + Alertmanager + Grafana (provisioning as code), statsd-exporter | Chuẩn de facto, pull-based, rule có unit test (`promtool`) | ELK, Datadog (SaaS) | — |
| Runtime | Docker Compose v2 + profiles; Ubuntu + Nginx + systemd | 1 lệnh dựng stack; giống nhau laptop ↔ VM; đủ cho 1 node | Kubernetes, Swarm | [0005](adr/0005-docker-compose-instead-of-kubernetes.md) |
| Responsible AI | Fairlearn, SHAP, LIME | Metric fairness + mitigation chuẩn; 2 phương pháp XAI để đối chiếu | AIF360 (nặng hơn), chỉ feature importance | — |
| CI/CD | GitHub Actions, GHCR, Trivy, SSH deploy | Tích hợp repo; action pin SHA; image theo digest; rollback tự động | GitLab CI, Jenkins | [07](07-testing-cicd.md) |

## 7. Trade-off

| Khía cạnh | Lựa chọn hiện tại | Được | Mất / giới hạn | Hướng mở rộng |
|---|---|---|---|---|
| **Scalability** | 1 container API chạy `API_WORKERS` (mặc định 2 = giới hạn CPU) worker gunicorn, model in-process mỗi worker, 1 host ([ADR-0007](adr/0007-api-capacity-multi-worker.md)) | Latency thấp (không hop mạng); ~85 rps với p95 ≤ 100 ms trên 2 CPU mà không thêm hạ tầng | Không auto-scale; model, gauge Prometheus và cửa sổ rolling là **trạng thái theo process** (multiprocess metrics + marker reload chỉ hoạt động trong 1 container); bão hoà ở ~25 req/s khi bị giới hạn 0.5 CPU ([kịch bản 7](guides/scenario-simulation.md#kịch-bản-7--latency-spike--load-test)) | Scale dọc: tăng `API_WORKERS` cùng `cpus` của service `api`. Scale ngang: nhiều replica sau Nginx `upstream`, Prometheus scrape từng replica và thay marker reload bằng poll alias MLflow định kỳ (API **không** stateless nên không dùng thẳng `--scale api=N`); K8s + HPA khi cần multi-host |
| Scalability | Drift chạy cửa sổ 500 log mỗi 60 s | Nhẹ (< 1 s/lần), phản ứng nhanh | Cửa sổ nhỏ nhạy với nhiễu | Tăng `DRIFT_WINDOW_SIZE`, hoặc phân tích theo batch hằng ngày |
| **Cost** | Self-hosted toàn bộ, 1 VPS ~8 GB RAM | ~0 chi phí license; dữ liệu không ra ngoài | Tự vận hành backup, cập nhật bảo mật | Chuyển MinIO → S3, Postgres → RDS khi có ngân sách (chỉ đổi endpoint) |
| Cost | Airflow trong profile riêng | Tắt được trên máy yếu (`make up-core`) | Airflow chiếm ~4 GB giới hạn RAM | Prefect/cron nếu chỉ cần lịch đơn giản |
| **Complexity** | 15 service Compose | Bao phủ đủ vòng đời MLOps, demo được | Nhiều thành phần cần hiểu; khởi động lần đầu ~5–10 phút (build image) | Profiles, `make up`/`make health`, runbook |
| Complexity | Logistic Regression thắng GBM | Dễ giải thích, ổn định, nhanh | Trần ROC-AUC ~0.77 | Monotonic GBM + calibration nếu cần hiệu năng cao hơn |
| **Reliability** | Single host | Đơn giản | SPOF: host chết = ngừng dịch vụ | Backup hằng ngày + restore đã kiểm chứng; multi-host/HA ngoài phạm vi |
| Reliability | Retrain tự động có gate + rollback | Không promote model kém | Nhãn trễ → retrain dựa trên feedback mô phỏng | Đánh giá lại khi đủ nhãn thật; human approval cho promote |
| **Security** | API key tĩnh, rotate qua danh sách | Đơn giản, không cần IdP | Không có danh tính người dùng / scope | OAuth2 client credentials / mTLS giữa CMS và API |

## 8. Cross-cutting concerns

- **Bảo mật:** [SECURITY.md](../SECURITY.md) — API key constant-time, container non-root UID 10001, image pin digest,
  Trivy gate, secret qua `.env` (chmod 600 trên server), UFW + Nginx, port container `127.0.0.1`.
- **Quan sát:** [05 — Monitoring & alerting](05-monitoring-alerting.md) — metric catalog, 4 dashboard, 11 alert có runbook.
- **Cấu hình:** YAML domain trong `configs/`, endpoint/secret qua env — [ADR 0006](adr/0006-src-layout-package-and-layered-config.md).
- **Tái lập & lineage:** manifest SHA256 + tag `data_version` trên MLflow run; seed cố định; `uv.lock`.
- **Responsible AI:** [06](06-responsible-ai.md), [model card](model-card.md), [data card](data-card.md).
