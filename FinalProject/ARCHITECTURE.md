# Kiến trúc hệ thống

Tóm tắt một trang. Tài liệu đầy đủ (sơ đồ ngữ cảnh hệ thống, container, component, data flow + edge case, deployment view, tech stack, trade-off):
[`docs/02-architecture.md`](docs/02-architecture.md). Quyết định kiến trúc: [`docs/adr/`](docs/adr/).

## 1. Container view

![Sơ đồ container](docs/assets/diagrams/02-container.svg)

| Container | Công nghệ | Trách nhiệm | Cổng (host) |
|---|---|---|---|
| Scoring API | FastAPI + scikit-learn | `/api/v1` predict/batch/explain/model, auth `X-API-Key`, inference log, `/metrics` | 18020 |
| Model registry | MLflow + PostgreSQL + MinIO | Tracking thí nghiệm, registry alias `@champion` / `@previous_champion` / `@challenger`, artifact | 15040, 15434, 19040 |
| Drift monitor | FastAPI + Evidently + PSI | So cửa sổ 500 inference log với reference mỗi 60 s, xuất metric drift | 18085 |
| Orchestration | Airflow 2.10 (+ statsd-exporter) | `service_health_check`, `drift_monitoring` → `model_retrain` (gate → promote → reload → rollback) | 18080 |
| Observability | Prometheus, Alertmanager, Grafana, alert-webhook | Scrape + 8 recording rule + 11 alert, routing webhook/Telegram, 4 dashboard | 19090, 19093, 13000, 19095 |

15 service Docker Compose, 3 profile (`core`, `monitoring`, `orchestration`); production chạy sau Nginx + TLS trên
Ubuntu, mọi cổng bind `127.0.0.1` ([Ubuntu deployment](docs/guides/ubuntu-deployment.md)).

## 2. Vòng lặp MLOps

```mermaid
flowchart LR
    client[Client] -->|POST /api/v1/predict + X-API-Key| api[Scoring API]
    api -->|models:/credit-risk-model@champion| mlflow[MLflow registry]
    api -->|inference_logs| pg[(PostgreSQL)]
    drift[Drift monitor] -->|cửa sổ 500 log| pg
    prom[Prometheus] -->|scrape| api & drift
    prom -->|alert| am[Alertmanager] --> hook[Webhook / Telegram]
    airflow[Airflow drift_monitoring] -->|drift| retrain[model_retrain]
    retrain -->|train challenger → gate| mlflow
    retrain -->|promote → POST /api/v1/model/reload| api
    grafana[Grafana] --> prom
```

Chi tiết từng bước và nhánh lỗi: [sequence retrain](docs/assets/diagrams/06-retrain-sequence.svg),
[data flow](docs/02-architecture.md#4-data-flow).

## 3. Package `credit_risk`

| Sub-package | Trách nhiệm |
|---|---|
| `config` | Cấu hình phân lớp YAML + env (`get_settings()`), logging JSON |
| `data` | Schema, load/split, pandera validation, manifest SHA256 |
| `features` | `FeatureEngineer` (12 feature) + preprocessing — nằm trong pipeline model |
| `training` | Model zoo 4 thuật toán, Optuna + CV, MLflow tracking/registry, retrain replay |
| `evaluation` | Metrics, business cost (FN=10, FP=1), quality gate champion/challenger |
| `serving` | FastAPI app, routers, auth, error contract, model loader (fallback local), readiness, decision engine |
| `monitoring` | Prometheus metrics, drift (PSI + Evidently) |
| `responsible_ai` | Fairness + mitigation, SHAP/LIME, privacy (HMAC pseudonymization, retention) |
| `utils` | Request context, network helper |

## 4. Môi trường

| `APP_ENV` | Dùng khi | MLflow | Database |
|---|---|---|---|
| `local` | Script trên host, stack Compose chạy nền | `http://localhost:15040` | Postgres `localhost:15434` |
| `docker` | Process trong mạng Compose | `http://mlflow:5000` | Postgres `postgres:5432` |
| `test` | pytest / CI | port đóng → fallback local | SQLite in-memory |

## 5. Quyết định chính

| Quyết định | Lý do ngắn | ADR |
|---|---|---|
| FastAPI cho serving | Async, Pydantic validation, OpenAPI tự sinh | [0001](docs/adr/0001-serving-with-fastapi.md) |
| MLflow + Postgres + MinIO | Registry có alias, artifact S3-compatible, self-host | [0002](docs/adr/0002-mlflow-minio-postgres.md) |
| Airflow thay cron | DAG có retry, branch, lịch sử run, UI | [0003](docs/adr/0003-airflow-instead-of-cron.md) |
| Evidently + PSI | PSI chuẩn ngành tín dụng + stattest từng cột | [0004](docs/adr/0004-evidently-for-drift.md) |
| Docker Compose thay Kubernetes | 1 VPS, nhóm nhỏ, chi phí thấp; đổi lại không auto-scale | [0005](docs/adr/0005-docker-compose-instead-of-kubernetes.md) |
| src layout + config phân lớp | Package cài đặt được, không hard-code, test hermetic | [0006](docs/adr/0006-src-layout-package-and-layered-config.md) |
| Nhiều worker process trong container API | GIL giới hạn 1 process ~50 rps; 2 worker giữ p95 ≤ 100 ms tới ~85 rps | [0007](docs/adr/0007-api-capacity-multi-worker.md) |

Trade-off scalability / cost / complexity / reliability / security: [02 §7](docs/02-architecture.md#7-trade-off).
