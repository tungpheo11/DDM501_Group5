# Credit Default Risk Scoring — End-to-End MLOps

[![Final Project CI](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-ci.yml/badge.svg?branch=main)](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-ci.yml)
[![Final Project CD](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-cd.yml/badge.svg)](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-cd.yml)
![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/API-FastAPI%20v1-009688)
![MLflow](https://img.shields.io/badge/tracking-MLflow-0194E2)
![Docker Compose](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED)
![Code style](https://img.shields.io/badge/code%20style-ruff%20%2B%20black-000000)

Hệ thống MLOps vòng lặp khép kín chấm điểm **rủi ro vỡ nợ thẻ tín dụng** (UCI *Default of Credit Card Clients*,
30.000 khách hàng): mỗi hồ sơ nhận xác suất default, quyết định **APPROVE / REVIEW / DECLINE**, credit score và hạn mức
đề xuất. Model được huấn luyện với Optuna + MLflow, phục vụ qua FastAPI, giám sát bằng Prometheus/Grafana, phát hiện
drift bằng Evidently + PSI và tự retrain qua Airflow với quality gate champion/challenger.

| Chỉ số | Giá trị | Nguồn |
|---|---|---|
| Model production | Logistic Regression — holdout ROC-AUC **0.7700**, recall 0.62 | [`model_comparison.md`](reports/model_comparison.md) |
| Latency `POST /api/v1/predict` | p95 **18.79 ms**, p99 24.17 ms (1000 request, 0 lỗi) | [`latency_benchmark.json`](reports/latency_benchmark.json) |
| Test | 4 loại test, coverage **92.1 %** (gate ≥ 80 %) | [07 — Testing & CI/CD](docs/07-testing-cicd.md) |
| Monitoring | 4 dashboard, 11 alert, mỗi alert đã fire → resolve trên stack thật | [05 — Monitoring](docs/05-monitoring-alerting.md) |
| Fairness (nhóm tuổi) | DI 0.772 → 0.926 sau mitigation, ROC-AUC gần như không đổi | [`fairness_report.md`](reports/fairness_report.md) |

![Container view](docs/assets/diagrams/02-container.svg)

## Mục lục

- [Quickstart](#quickstart)
- [Ví dụ sử dụng](#ví-dụ-sử-dụng)
- [Lệnh thường dùng](#lệnh-thường-dùng)
- [Kết quả mô hình](#kết-quả-mô-hình)
- [Cấu trúc repo](#cấu-trúc-repo)
- [Xử lý sự cố](#xử-lý-sự-cố)
- [Tài liệu](#tài-liệu)

## Quickstart

Yêu cầu: macOS/Linux, Docker (Compose ≥ 2.24.4, cấp ≥ 6 GB RAM), Python 3.11, `make`. Chi tiết:
[local quickstart](docs/guides/local-quickstart.md).

```bash
git clone https://github.com/tungpheo11/DDM501_Group5.git && cd DDM501_Group5/FinalProject
make setup                # .venv + dependencies + .env (từ .env.example)
make up                   # build + chạy 15 service, chờ tới khi tất cả healthy
curl -s localhost:18020/health/ready     # {"status":"ready", ...}
```

| Giao diện | URL |
|---|---|
| Swagger UI (API) | <http://localhost:18020/docs> |
| Grafana (`admin` / `GRAFANA_ADMIN_PASSWORD`) | <http://localhost:13000> |
| MLflow | <http://localhost:15040> |
| Airflow (`admin` / `AIRFLOW_ADMIN_PASSWORD`) | <http://localhost:18080> |
| Prometheus · Alertmanager | <http://localhost:19090> · <http://localhost:19093> |

Triển khai production trên Ubuntu (Nginx + TLS, systemd, backup): [ubuntu-deployment](docs/guides/ubuntu-deployment.md).

## Ví dụ sử dụng

```bash
export API_KEY=$(grep -E '^API_KEYS=' .env | cut -d= -f2 | cut -d, -f1)
curl -s http://localhost:18020/api/v1/predict \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"LIMIT_BAL":200000,"SEX":2,"EDUCATION":1,"MARRIAGE":2,"AGE":35,
       "PAY_0":0,"PAY_2":0,"PAY_3":0,"PAY_4":0,"PAY_5":0,"PAY_6":0,
       "BILL_AMT1":50000,"BILL_AMT2":48000,"BILL_AMT3":46000,"BILL_AMT4":44000,"BILL_AMT5":42000,"BILL_AMT6":40000,
       "PAY_AMT1":5000,"PAY_AMT2":5000,"PAY_AMT3":5000,"PAY_AMT4":5000,"PAY_AMT5":5000,"PAY_AMT6":5000}'
```

```json
{"model_version": "1", "served_by": "mlflow_registry", "default_prediction": 0, "default_probability": 0.463411,
 "credit_score": 595, "credit_tier": "SUBPRIME", "risk_decision": "REVIEW", "recommended_limit_ntd": 100000.0,
 "top_risk_factors": ["Repayment Discipline: Timely and structured monthly repayments", "…"],
 "policy_guardrails": {"age_verification": "PASS", "utilization_ceiling_check": "ACCEPTABLE", "delinquency_guardrail": "CLEAR"},
 "request_id": "req_d4ee54a614ca4e959ba491d4733aef57", "latency_ms": 46.53}
```

```python
import os
import requests

response = requests.post(
    "http://localhost:18020/api/v1/explain",
    headers={"X-API-Key": os.environ["API_KEY"]},
    json=applicant,  # cùng 23 field như trên
    timeout=5,
)
for item in response.json()["contributions"]:
    print(f"{item['feature']:<10} {item['contribution']:+.3f} {item['direction']}")
```

Endpoint khác: `POST /api/v1/predict/batch` (≤ 500 hồ sơ), `GET /api/v1/model/info`, `POST /api/v1/model/reload`,
`GET /health/live|ready`, `GET /metrics`. Error contract, schema và mã lỗi: [API reference](docs/04-api-reference.md).

## Lệnh thường dùng

| Mục đích | Lệnh |
|---|---|
| Chất lượng code | `make lint` (ruff + black + mypy) · `make test` · `make test-cov` · `make ci` (pipeline CI local) |
| Dữ liệu & model | `make validate` · `make train` (`N_TRIALS=5` để nhanh) · `make registry` · `make retrain` · `make rollback` |
| Stack | `make up` · `make up-core` · `make health` · `make logs SERVICE=api` · `make down` · `make down-v` |
| Kịch bản | `make simulate SCENARIO=normal\|drift\|attack\|load\|outage` · `make chaos-*` · `make chaos-restore` |
| Monitoring | `make alerts` · `make alerts-test` · `make drift` |
| Airflow | `make retrain-dag` · `make retrain-fail` · `make drift-dag` · `make dags-check` |
| Responsible AI | `make responsible-ai` (fairness + SHAP/LIME → `reports/`) |
| API / image | `make serve` · `make openapi` · `make bench` · `make docker-build` · `make scan` · `make smoke` |
| Tất cả | `make help` |

11 kịch bản vận hành (drift → retrain, promote không downtime, rollback, API down, latency, tấn công, fairness…):
[scenario simulation](docs/guides/scenario-simulation.md).

## Kết quả mô hình

Bảng dưới được `make train` sinh tự động từ [`reports/model_comparison.json`](reports/model_comparison.json) — không sửa tay; số liệu trong tài liệu khác phải trích từ file này.

<!-- model-comparison:start -->
_Sinh tự động từ `reports/model_comparison.json` (session `20260928T092715Z`)._

| Model | CV ROC-AUC (mean ± std) | Holdout ROC-AUC | Holdout PR-AUC | Holdout F1 | Holdout Recall | Holdout expected loss | Normal-stream ROC-AUC | Normal-stream expected loss |
|---|---|---|---|---|---|---|---|---|
| **Logistic Regression** (selected) | 0.7513 ± 0.0152 | 0.7700 | 0.5688 | 0.5314 | 0.6213 | 1.0030 | 0.7519 | 1.0848 |
| Random Forest | 0.7472 ± 0.0114 | 0.7657 | 0.5635 | 0.5312 | 0.5344 | 1.1430 | 0.7474 | 1.2262 |
| XGBoost | 0.7509 ± 0.0127 | 0.7671 | 0.5671 | 0.5318 | 0.5629 | 1.0967 | 0.7556 | 1.1598 |
| LightGBM | 0.7488 ± 0.0123 | 0.7678 | 0.5705 | 0.5226 | 0.5793 | 1.0787 | 0.7549 | 1.1368 |

Model được chọn: **Logistic Regression** — gate: **promote**. Chi tiết: [`reports/model_comparison.md`](reports/model_comparison.md).
<!-- model-comparison:end -->

## Cấu trúc repo

```text
FinalProject/
├── README.md  ARCHITECTURE.md  CONTRIBUTING.md  CHANGELOG.md  SECURITY.md
├── Makefile  pyproject.toml  uv.lock  requirements.txt  requirements-dev.txt  .env.example
├── configs/                 # training / serving / drift / responsible_ai / logging + environments/{local,docker,test}
├── data/                    # raw/ reference/ processed/ + manifest.json (SHA256)
├── models/                  # artifact fallback cho API khi MLflow không tới được
├── src/credit_risk/         # config data features training evaluation responsible_ai monitoring serving utils
├── services/drift_monitor/  # Evidently + PSI, xuất metric Prometheus
├── orchestration/airflow/   # 3 DAG: service_health_check, drift_monitoring, model_retrain
├── deploy/                  # docker/ compose/ (base, prod, image, chaos) ubuntu/ (install, deploy, backup, nginx, systemd)
├── monitoring/              # prometheus/ (rules + tests) alertmanager/ grafana/ statsd/
├── simulations/  scripts/  notebooks/
├── tests/                   # unit/ integration/ data_quality/ model_validation/ e2e/ load/
├── reports/                 # output sinh tự động: model, fairness, explainability, latency, simulations
└── docs/                    # 01–07, guides/, runbooks/, adr/, assets/, presentation/, qa/
```

CI/CD nằm ở root repo: [`.github/workflows/final-project-ci.yml`](../.github/workflows/final-project-ci.yml),
[`final-project-cd.yml`](../.github/workflows/final-project-cd.yml).

## Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| `port is already allocated` khi `make up` | Đổi `*_PORT` tương ứng trong `.env` |
| Service `OOMKilled`, `make health` timeout | Tăng RAM cho Docker ≥ 6 GB hoặc chạy `make up-core` |
| `unknown tag !reset` | Nâng Docker Compose ≥ 2.24.4 |
| `/health/ready` = `degraded`, `served_by: local_artifact` | MLflow chưa sẵn sàng lúc API khởi động → `curl -X POST -H "X-API-Key: $API_KEY" localhost:18020/api/v1/model/reload` |
| 401 / 403 | Thiếu hoặc sai header `X-API-Key` (giá trị trong `API_KEYS` của `.env`) |
| Dashboard Grafana trống | Chưa có traffic → `make simulate SCENARIO=normal` |
| Có alert firing sau khi diễn tập | `make chaos-restore` rồi `make simulate SCENARIO=normal` |
| Muốn làm lại từ đầu | `make down-v && make up` |

Thêm: [local quickstart §6](docs/guides/local-quickstart.md#6-xử-lý-sự-cố),
[operations runbook](docs/guides/operations-runbook.md), [runbook theo alert](docs/runbooks/alerts.md).

## Tài liệu

| Tài liệu | Nội dung |
|---|---|
| [docs/README.md](docs/README.md) | Mục lục + **bảng rubric → file / bằng chứng** |
| [ARCHITECTURE.md](ARCHITECTURE.md) · [02 — Architecture](docs/02-architecture.md) | Sơ đồ kiến trúc, data flow, tech stack, trade-off |
| [01 — Problem statement](docs/01-problem-statement.md) | Bối cảnh, yêu cầu, success metrics |
| [03 — ML pipeline](docs/03-ml-pipeline.md) · [04 — API](docs/04-api-reference.md) · [05 — Monitoring](docs/05-monitoring-alerting.md) | Implementation |
| [06 — Responsible AI](docs/06-responsible-ai.md) · [Model card](docs/model-card.md) · [Data card](docs/data-card.md) | Fairness, explainability, privacy, ethics |
| [07 — Testing & CI/CD](docs/07-testing-cicd.md) | Test, quality gates, release & rollback |
| [Guides](docs/guides/) | [Local](docs/guides/local-quickstart.md), [Ubuntu](docs/guides/ubuntu-deployment.md), [Vận hành](docs/guides/operations-runbook.md), [11 kịch bản](docs/guides/scenario-simulation.md) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Quy ước code, vai trò thành viên |
| [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) | Bảo mật · lịch sử thay đổi |
| [Presentation](docs/presentation/README.md) | Slide + demo script |
