# Tài liệu dự án — Credit Default Risk Scoring MLOps

Mục lục toàn bộ tài liệu và bảng đối chiếu **rubric DDM501 → file / bằng chứng**. Mọi con số trích dẫn trong tài liệu
lấy từ file sinh tự động trong [`reports/`](../reports/) (không nhập tay).

## 1. Đọc theo vai trò

| Bạn là… | Bắt đầu từ |
|---|---|
| Giảng viên / reviewer | [Bảng rubric](#3-rubric--file--bằng-chứng) → [01](01-problem-statement.md) → [02](02-architecture.md) |
| Dev mới vào nhóm | [Local quickstart](guides/local-quickstart.md) → [CONTRIBUTING](../CONTRIBUTING.md) → [03](03-ml-pipeline.md) |
| Người tích hợp API | [04 — API reference](04-api-reference.md) · [`openapi.yaml`](openapi.yaml) · Swagger `http://localhost:18020/docs` |
| Vận hành / on-call | [Operations runbook](guides/operations-runbook.md) → [Runbook alert](runbooks/alerts.md) → [05](05-monitoring-alerting.md) |
| Triển khai server | [Ubuntu deployment](guides/ubuntu-deployment.md) → [07 §6](07-testing-cicd.md#6-release-và-rollback) |
| QA | [Scenario simulation](guides/scenario-simulation.md) → [`qa/`](qa/README.md) |

## 2. Mục lục

### Tài liệu chính

| # | Tài liệu | Nội dung |
|---|---|---|
| 01 | [Problem statement](01-problem-statement.md) | Bối cảnh kinh doanh, stakeholder, use case, FR/NFR (MoSCoW), success metrics 3 cấp, phạm vi & ràng buộc |
| 02 | [Architecture](02-architecture.md) | Sơ đồ ngữ cảnh hệ thống, container, component; trách nhiệm thành phần, data flow + edge case, tech stack, trade-off |
| 03 | [ML pipeline](03-ml-pipeline.md) | Validation, versioning, feature engineering, Optuna + CV, MLflow, quality gate, retrain |
| 04 | [API reference](04-api-reference.md) · [`openapi.yaml`](openapi.yaml) | Endpoint, auth, schema, error contract, ví dụ curl/Python |
| 05 | [Monitoring & alerting](05-monitoring-alerting.md) | Metric catalog, 4 dashboard, 11 alert + ngưỡng + routing, drift, Airflow, chaos |
| 06 | [Responsible AI](06-responsible-ai.md) · [Model card](model-card.md) · [Data card](data-card.md) | Fairness + mitigation, SHAP/LIME, privacy, ethics |
| 07 | [Testing & CI/CD](07-testing-cicd.md) | 4 loại test, quality gates, GitHub Actions CI/CD, release & rollback |

### Hướng dẫn (`guides/`)

| Guide | Dùng khi |
|---|---|
| [local-quickstart.md](guides/local-quickstart.md) | Chạy toàn bộ stack trên macOS/Linux |
| [ubuntu-deployment.md](guides/ubuntu-deployment.md) | Triển khai Ubuntu 22.04/24.04: Docker, user, UFW, `.env`, Nginx + TLS, systemd, backup/restore, upgrade/rollback |
| [operations-runbook.md](guides/operations-runbook.md) | Vận hành hằng ngày, quy trình sự cố, troubleshooting |
| [scenario-simulation.md](guides/scenario-simulation.md) | 11 kịch bản: normal, drift → retrain, promote, gate fail, rollback, API down, latency, 4xx/5xx, dependency down, tấn công, fairness |

### Khác

| Mục | Nội dung |
|---|---|
| [`adr/`](adr/) | 7 Architecture Decision Record (bảng bên dưới) |
| [`runbooks/alerts.md`](runbooks/alerts.md) | Runbook từng alert (đích của `runbook_url`) |
| [`assets/`](assets/) | [Diagram](assets/diagrams/README.md) (nguồn Mermaid + SVG), ảnh chụp Grafana/slide |
| [`presentation/`](presentation/README.md) | Slide (`index.html`, PDF, PPTX), [demo script](presentation/demo-script.md) |
| [`qa/`](qa/README.md) | Kế hoạch và kết quả kiểm thử thủ công |
| Root | [README](../README.md) · [ARCHITECTURE](../ARCHITECTURE.md) · [CONTRIBUTING](../CONTRIBUTING.md) · [CHANGELOG](../CHANGELOG.md) · [SECURITY](../SECURITY.md) |

### ADR

| # | Quyết định |
|---|---|
| [0001](adr/0001-serving-with-fastapi.md) | Serving bằng FastAPI |
| [0002](adr/0002-mlflow-minio-postgres.md) | MLflow + PostgreSQL + MinIO |
| [0003](adr/0003-airflow-instead-of-cron.md) | Airflow thay cron |
| [0004](adr/0004-evidently-for-drift.md) | Evidently + PSI cho drift |
| [0005](adr/0005-docker-compose-instead-of-kubernetes.md) | Docker Compose thay Kubernetes |
| [0006](adr/0006-src-layout-package-and-layered-config.md) | Package src layout + cấu hình phân lớp |
| [0007](adr/0007-api-capacity-multi-worker.md) | Capacity API: tối ưu hot path + nhiều worker process |

## 3. Rubric → file / bằng chứng

Rubric: *DDM501 Final Project — Grading Rubrics* (mục 3.1 Development, 3.2 Presentation, 3.3 Individual contribution).
Cột "Bằng chứng" là file sinh tự động hoặc lệnh tái lập được.

### 3.1.1 Problem definition & requirements (10%)

| Tiêu chí (Excellent) | Tài liệu | Bằng chứng |
|---|---|---|
| Problem statement rõ, có bối cảnh kinh doanh | [01 §1–3](01-problem-statement.md#1-bối-cảnh-kinh-doanh) | Cost matrix FN=10/FP=1, LGD 0.45, 3 vùng quyết định, 9 use case |
| FR + NFR đầy đủ, có ưu tiên | [01 §4](01-problem-statement.md#4-yêu-cầu) | 18 FR + 13 NFR, MoSCoW, map tới thành phần |
| Success metrics business/system/model có target | [01 §5](01-problem-statement.md#5-success-metrics-3-cấp) | [`model_comparison.json`](../reports/model_comparison.json), [`latency_benchmark.json`](../reports/latency_benchmark.json), [`reports/simulations/`](../reports/simulations/) |

### 3.1.2 System design & architecture (15%)

| Tiêu chí (Excellent) | Tài liệu | Bằng chứng |
|---|---|---|
| Diagram chuyên nghiệp, tương tác rõ | [02 §2](02-architecture.md#2-sơ-đồ-kiến-trúc), [ARCHITECTURE.md](../ARCHITECTURE.md) | 7 SVG render từ Mermaid ([`assets/diagrams/`](assets/diagrams/README.md), `scripts/render_diagrams.sh`) |
| Data flow đầy đủ + edge case | [02 §4](02-architecture.md#4-data-flow) | Bảng edge case → hành vi → alert → kịch bản kiểm chứng; [scenario-simulation](guides/scenario-simulation.md) |
| Quyết định công nghệ có trade-off | [02 §6–7](02-architecture.md#6-tech-stack--lý-do-chọn), [ADR 0001–0007](adr/) | Bảng lựa chọn vs phương án thay thế; trade-off scalability/cost/complexity/reliability/security |

### 3.1.3 Implementation — ML Pipeline (15%)

| Tiêu chí (Excellent) | Tài liệu | Bằng chứng |
|---|---|---|
| Data pipeline: validation, versioning, error handling | [03 §2](03-ml-pipeline.md#2-data-pipeline), [data card](data-card.md) | [`data_validation.json`](../reports/data_validation.json) (5/5 PASS), `data/manifest.json` SHA256, `make validate` |
| Nhiều thí nghiệm, HPO, cross-validation | [03 §4](03-ml-pipeline.md#4-training) | [`model_comparison.md`](../reports/model_comparison.md): 4 thuật toán × 20 trial Optuna, 5-fold CV; LR CV ROC-AUC 0.7513 ± 0.0152, holdout 0.7700 |
| MLflow: metrics, params, artifacts | [03 §5](03-ml-pipeline.md#5-experiment-tracking-mlflow) | 84 run/lần train, signature + input example, registry alias `@champion`/`@previous_champion`/`@challenger` |

### 3.1.3 Implementation — Deployment (15%)

| Tiêu chí (Excellent) | Tài liệu | Bằng chứng |
|---|---|---|
| API RESTful, tài liệu, error handling, versioning | [04](04-api-reference.md), [`openapi.yaml`](openapi.yaml) | `/api/v1`, `X-API-Key`, error contract thống nhất; `tests/integration/`; p95 20.59 ms ([`latency_benchmark.json`](../reports/latency_benchmark.json)) |
| Dockerfile tối ưu, multi-stage, bảo mật | [`deploy/docker/Dockerfile.api`](../deploy/docker/Dockerfile.api), [SECURITY](../SECURITY.md) | Multi-stage, user non-root, file read-only, healthcheck; Trivy gate CRITICAL trong CI |
| docker-compose đầy đủ service + healthcheck | [05 §1](05-monitoring-alerting.md#1-service-profile-cổng-tài-nguyên), [`deploy/compose/`](../deploy/compose/) | 15 service, 3 profile, healthcheck + giới hạn tài nguyên; overlay prod/image/chaos; `make up` → `make health` |

### 3.1.3 Implementation — Monitoring (10%)

| Tiêu chí (Excellent) | Tài liệu | Bằng chứng |
|---|---|---|
| Metric hệ thống + ML + custom | [05 §3](05-monitoring-alerting.md#3-metric-catalog) | ~40 metric `credit_*` (API, business, drift, retrain) + 8 recording rule |
| Dashboard Grafana có ý nghĩa | [05 §4](05-monitoring-alerting.md#4-dashboards-grafana) | 4 dashboard provision tự động; ảnh [`assets/screenshots/grafana/`](assets/screenshots/grafana/); quy ước hiển thị [05 §4.1](05-monitoring-alerting.md#41-quy-ước-hiển-thị) |
| Alert có ngưỡng hợp lý | [05 §5](05-monitoring-alerting.md#5-alerting), [runbook](runbooks/alerts.md) | 11 alert có lý do ngưỡng + runbook; `make alerts-test` (promtool fire → resolve); bằng chứng fire/resolve thật [05 §5.3](05-monitoring-alerting.md#53-bằng-chứng-fire--resolve-stack-thật-utc-28092026) |

### 3.1.4 Testing & CI/CD (15%)

| Tiêu chí (Excellent) | Tài liệu | Bằng chứng |
|---|---|---|
| Coverage > 80 %, test có ý nghĩa | [07 §2](07-testing-cicd.md#2-quality-gates) | Coverage tổng 91.3 % (gate ≥ 80 %, `make test-ci`; artifact CI `final-project-coverage`) |
| Unit, integration, data quality, model tests | [07](07-testing-cicd.md), [03 §8](03-ml-pipeline.md#8-kiểm-thử-liên-quan) | `tests/unit`, `tests/integration`, `tests/data_quality`, `tests/model_validation` (JUnit từng suite) |
| CI/CD: lint, test, build, deploy | [07 §1, §6](07-testing-cicd.md#1-sơ-đồ-job) | [`final-project-ci.yml`](../../.github/workflows/final-project-ci.yml), [`final-project-cd.yml`](../../.github/workflows/final-project-cd.yml); `make ci` chạy lại pipeline local |

### 3.1.5 Responsible AI (10%)

| Tiêu chí (Excellent) | Tài liệu | Bằng chứng |
|---|---|---|
| Phân tích bias toàn diện + mitigation | [06 §3–4](06-responsible-ai.md#3-fairness) | [`fairness_report.md`](../reports/fairness_report.md): 4 thuộc tính; AGE DI 0.772 → 0.926 (unawareness); [Kịch bản 11](guides/scenario-simulation.md#kịch-bản-11--kiểm-tra-fairness-trước--sau-mitigation) |
| Nhiều phương pháp explainability | [06 §5](06-responsible-ai.md#5-explainability) | [`explainability_report.md`](../reports/explainability_report.md): SHAP + LIME (overlap 67 %); `POST /api/v1/explain` |
| Thảo luận ethics + mitigation | [06 §6–7](06-responsible-ai.md#7-ethics), [model card](model-card.md#7-cân-nhắc-đạo-đức) | Human-in-the-loop vùng REVIEW, giới hạn sử dụng, privacy (HMAC pseudonymization, retention 90 ngày) |

### 3.1.6 Documentation (10%)

| Tiêu chí (Excellent) | Tài liệu | Bằng chứng |
|---|---|---|
| README có badge, ví dụ, troubleshooting | [README](../README.md) | Badge CI/CD/coverage, quickstart, ví dụ curl/Python, bảng troubleshooting |
| OpenAPI đầy đủ kèm ví dụ | [`openapi.yaml`](openapi.yaml), [04](04-api-reference.md) | Sinh từ code (`make openapi`), ví dụ request/response + mọi mã lỗi |
| Code sạch: type hints, docstring, style nhất quán | [CONTRIBUTING](../CONTRIBUTING.md) | `make lint` (ruff + black + mypy) là gate CI |
| Hướng dẫn deploy + vận hành | [guides/](#hướng-dẫn-guides) | Local, Ubuntu, runbook, 11 kịch bản; script [`deploy/ubuntu/`](../deploy/ubuntu/README.md) |

### 3.2 Presentation · 3.3 Individual contribution

| Hạng mục | Tài liệu |
|---|---|
| Slide (problem → solution → deep dive → RAI → demo) | [`presentation/`](presentation/README.md) |
| Live demo (mọi thành viên tham gia) | [demo-script.md](presentation/demo-script.md), [scenario-simulation](guides/scenario-simulation.md) |
| Vai trò từng thành viên | [CONTRIBUTING — Vai trò thành viên](../CONTRIBUTING.md#7-vai-trò-thành-viên) |
| Required files (mục 4.2) | [README](../README.md), [ARCHITECTURE](../ARCHITECTURE.md), [CONTRIBUTING](../CONTRIBUTING.md), [`requirements.txt`](../requirements.txt), [`Dockerfile.api`](../deploy/docker/Dockerfile.api), [`docker-compose.yml`](../deploy/compose/docker-compose.yml), [`.github/workflows/`](../../.github/workflows/) |
