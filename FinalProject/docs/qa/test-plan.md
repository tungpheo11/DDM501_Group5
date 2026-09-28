# Test plan — Credit Default Risk Scoring

Kế hoạch kiểm thử cho toàn hệ thống: ML pipeline, API chấm điểm, drift monitor, monitoring/alerting, Airflow và triển
khai Ubuntu. Danh sách test case: [test-cases.md](test-cases.md). Kết quả, số liệu và bảng evidence:
[test-report.md](test-report.md).

## 1. Phạm vi

**Trong phạm vi**

| Hạng mục | Thành phần | Nguồn yêu cầu |
|---|---|---|
| Data & ML pipeline | Validation (pandera + manifest hash), feature engineering, tuning, quality gate, MLflow registry | [03-ml-pipeline](../03-ml-pipeline.md), [model card](../model-card.md) |
| Serving API | `/api/v1/predict`, `/predict/batch`, `/explain`, `/model/*`, health, metrics; API key; error contract | [04-api-reference](../04-api-reference.md) |
| Drift & retrain | Drift monitor (PSI + Evidently), DAG `drift_monitoring`, `model_retrain`, `service_health_check` | [05-monitoring-alerting](../05-monitoring-alerting.md) |
| Monitoring & alerting | 11 alert rule Prometheus, Alertmanager → webhook + Telegram, 4 dashboard Grafana | [05-monitoring-alerting](../05-monitoring-alerting.md), [runbook](../runbooks/alerts.md) |
| Responsible AI | Fairness audit + mitigation, SHAP/LIME, privacy (pseudonymization, retention) | [06-responsible-ai](../06-responsible-ai.md) |
| Vận hành | 11 kịch bản trong [scenario-simulation](../guides/scenario-simulation.md) | |
| Triển khai | [ubuntu-deployment](../guides/ubuntu-deployment.md): `install.sh`, `deploy.sh`, Nginx, systemd, backup | |
| CI | `make lint`, `make test-ci`, `make alerts-test`, workflow GitHub Actions | [07-testing-cicd](../07-testing-cicd.md) |

**Ngoài phạm vi:** TLS Let's Encrypt thật (cần domain public), multi-host / Kubernetes, pen-test chuyên sâu, kiểm thử
trên dữ liệu khách hàng thật.

## 2. Chiến lược

Kiểm thử theo kim tự tháp, tầng dưới tự động hoàn toàn và chạy trong CI; tầng trên chạy trên stack thật và lưu evidence.

| Tầng | Thư mục / công cụ | Chạy bằng | Trong CI | Mục tiêu |
|---|---|---|---|---|
| Unit | `tests/unit` (pytest) | `make test-unit` | Có | Logic từng module: features, training, registry, drift, fairness, privacy, serving components, link tài liệu |
| Integration | `tests/integration` (FastAPI `TestClient`) | `make test-integration` | Có | API contract 2xx/4xx/5xx, auth, readiness, reload, logging |
| Data quality | `tests/data_quality` | `pytest tests/data_quality` | Có | Schema pandera, hash manifest, phân phối nhãn, không rò rỉ giữa các split |
| Model validation | `tests/model_validation` | `pytest tests/model_validation` | Có | Champion đạt ngưỡng ROC-AUC / expected loss, ổn định theo nhóm |
| E2E | `tests/e2e` (pytest + requests) | `make test-e2e` | Không (cần stack) | API ↔ MLflow ↔ drift monitor ↔ Prometheus/Alertmanager/Grafana ↔ Airflow |
| Load | `tests/load` (Locust) | `make test-load` | Không (cần stack) | 0 lỗi, p95 `/predict` ≤ 100 ms ở tải danh định, throughput |
| Kịch bản vận hành | `make simulate`, `make chaos-*`, Airflow | Thủ công theo guide | Không | Alert firing → thông báo → resolved; retrain, promote, rollback |
| Triển khai | `deploy/ubuntu/*.sh` | Thủ công theo guide | Không | Bootstrap host, deploy, smoke, rollback, backup/restore |

**Kỹ thuật thiết kế test:** phân vùng tương đương và giá trị biên cho input API (tuổi, hạn mức, batch 500/501), bảng
quyết định cho quality gate (ROC-AUC, expected loss), kiểm thử dựa trên trạng thái cho alert (inactive → pending →
firing → resolved), fault injection (dừng container, bóp CPU, mất model, mất DB/MLflow), kiểm thử hồi quy qua CI.

## 3. Môi trường

| Thành phần | Giá trị |
|---|---|
| Máy chạy | macOS 26 (Apple Silicon), Docker Desktop 10 CPU / 7.7 GB RAM |
| Stack | `make up`, `COMPOSE_PROFILES=core,monitoring,orchestration`, 12 service (postgres, minio, mlflow, api, drift-monitor, prometheus, alertmanager, alert-webhook, grafana, statsd-exporter, airflow-webserver, airflow-scheduler) |
| Python | 3.11 (`.venv` từ `uv sync --dev`) |
| Kênh thông báo | Webhook nội bộ `alert-webhook` + nhóm Telegram "Test MLOps" (bot đọc từ `.env`) |
| Triển khai Ubuntu | Container `ubuntu:24.04` privileged chạy Docker Engine bên trong (không có Multipass/UTM trên máy test) |
| Dữ liệu | UCI Credit Default 30k (`data/`), stream mô phỏng `simulations/data/` |

URL: API <http://localhost:18020/docs>, MLflow <http://localhost:15040>, Grafana <http://localhost:13000>, Prometheus
<http://localhost:19090>, Alertmanager <http://localhost:19093>, webhook <http://localhost:19095/alerts>, Airflow
<http://localhost:18080>, drift monitor <http://localhost:18085>.

## 4. Tiêu chí vào / ra

**Tiêu chí vào**

- `make up` → mọi service `healthy`; `make alerts` không có alert firing.
- `make lint` sạch; `make test` pass.
- Registry có `@champion`; API `/health/ready` = `ready`.

**Tiêu chí ra**

| Tiêu chí | Ngưỡng |
|---|---|
| Test tự động | 100 % pass (skip có lý do rõ ràng) |
| Coverage `credit_risk` | ≥ 80 % (`make test-ci`) |
| Lint / type check | ruff, black, mypy: 0 lỗi |
| Test case thủ công | 100 % có kết quả thực tế + screenshot |
| Alert | ≥ 7 alert rule có evidence firing **và** resolved |
| Lỗi | Không còn lỗi mức Critical/High mở; lỗi còn lại có issue theo dõi |

## 5. Mức độ lỗi

| Mức | Định nghĩa | Ví dụ |
|---|---|---|
| Critical | Mất dịch vụ chấm điểm hoặc sai quyết định tín dụng hàng loạt, lộ secret/PII | API trả 5xx liên tục, token bot trong log |
| High | Tính năng chính hỏng, không có workaround | Alert không bao giờ firing, rollback không đổi model |
| Medium | Vi phạm SLO/NFR hoặc có workaround | p95 vượt SLO ở tải vừa phải |
| Low | Sai lệch hiển thị, tài liệu, trạng thái phụ | Trạng thái thông báo không tự resolve |

## 6. Rủi ro kiểm thử

| Rủi ro | Giảm thiểu |
|---|---|
| Alert có `for:` dài (5–20 phút) làm chậm vòng kiểm thử | Chạy song song các sự cố độc lập (drift monitor down, DAG lỗi, retrain fail) |
| Traffic của load test làm lệch cửa sổ drift | Sau mỗi kịch bản chạy lại `simulate SCENARIO=normal` trước khi đo tiếp |
| Tài nguyên Docker Desktop hạn chế khi chạy thêm môi trường Ubuntu lồng nhau | Triển khai Ubuntu với profile `core`, chạy sau các kịch bản nhạy latency |
| Evidence lộ secret | Chỉ chụp UI và output lệnh; không chụp `.env`, log container hay URL `api.telegram.org` |
