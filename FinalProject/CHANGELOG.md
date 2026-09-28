# Changelog

Định dạng theo [Keep a Changelog](https://keepachangelog.com/vi/1.1.0/), phiên bản theo [SemVer](https://semver.org/).

## [Unreleased]

### Added

**ML pipeline**
- Data validation bằng pandera (`credit_risk.data.validation`, `make validate`): kiểu, miền giá trị UCI, null, cân bằng target, `request_id` duy nhất; fail fast trước khi train/retrain. Báo cáo `reports/data_validation.json`.
- Data versioning: `data/manifest.json` v2 thêm `source`, `fingerprint`, metadata dataset; manifest + dataset input được log vào MLflow (tag `data_version`, `data.<file>.sha256`) để truy vết lineage.
- `credit_risk.features.feature_engineering`: 12 feature (credit utilization, payment ratio, delay trend, …) qua transformer `FeatureEngineer` dùng chung cho train và serving (nằm trong pipeline model).
- 4 thuật toán (Logistic Regression, Random Forest, XGBoost, LightGBM), Optuna TPE + stratified 5-fold CV, `random_state` cố định; mỗi trial là một nested run MLflow.
- MLflow: params, metrics (ROC-AUC, PR-AUC, F1, recall, expected financial loss theo cost matrix), artifacts (confusion matrix, ROC/PR curve, feature importance, trials.csv), signature + input example; tự fallback sang sqlite `mlruns/` khi không có tracking server (môi trường local).
- Champion/challenger gate dùng chung cho train và retrain (`credit_risk.evaluation.model_validation`), alias `@champion` / `@previous_champion` / `@challenger`, `promote_model_version` + `rollback_champion` (`make registry`, `make rollback`).
- `reports/model_comparison.{json,md}` + `reports/figures/` sinh tự động; README đồng bộ bảng kết quả từ file JSON.

**Serving API v1**
- API versioned `/api/v1`: `predict`, `predict/batch` (tối đa `batch_max_size`=500, 413 khi vượt), `explain` (reference substitution), `model/info`, `model/reload`; probes `GET /health/live`, `GET /health/ready` (`ready` / `degraded` / `not_ready`).
- Error schema chuẩn `{code, message, details, request_id}`, middleware `X-Request-ID`, API-key auth (`X-API-Key`, env `API_KEYS`), validation Pydantic giới hạn miền giá trị UCI + từ chối field lạ.
- Structured JSON logging (`LOG_FORMAT`), redact PII; Prometheus metrics HTTP theo endpoint/status, trạng thái + version model, phân phối xác suất.
- `docs/openapi.yaml` (xuất bằng `make openapi`, có test chống lệch contract), `scripts/benchmark_latency.py` (`make bench`), `make docker-build`, `make scan` (Trivy).

**Monitoring & orchestration**
- Drift monitor service (`services/drift_monitor`): Evidently + PSI trên cửa sổ 500 inference log mới nhất, chạy mỗi 60 s so với reference 5000 dòng; endpoint `/analyze`, `/drift/latest`, `/reference/refresh`, `/reports`; xuất metric Prometheus.
- Prometheus: 8 recording rule + 11 alert (`APIDown`, `HighErrorRate`, `HighLatencyP95`, `ModelNotLoaded`, `ModelServedFromFallback`, `DataDriftDetected`, `PredictionDistributionShift`, `RetrainFailed`, `DriftMonitorDown`, `DriftAnalysisStale`, `AirflowDagImportErrors`) kèm unit test `promtool` (`make alerts-test`).
- Alertmanager: group/inhibit rules, receiver webhook luôn bật (`alert-webhook`, `make alerts`), Telegram tuỳ chọn khi có token.
- Grafana provisioning 4 dashboard: Business, ML Model, Drift, Infra & SLA.
- Airflow 2.10: `service_health_check` (5 phút), `drift_monitoring` (30 phút, trigger retrain có cooldown 60 phút), `model_retrain` (train challenger → quality gate → promote → reload API → rollback nếu reload lỗi → refresh drift reference); statsd-exporter cho metric Airflow.
- Chaos targets `make chaos-*` / `make chaos-restore` và runbook cho từng alert (`docs/runbooks/alerts.md`).

**Responsible AI**
- `credit_risk.responsible_ai.fairness`: audit Fairlearn (DPD, EOD, TPR/FPR, approval rate, disparate impact) theo `SEX`, nhóm tuổi, `EDUCATION`, `MARRIAGE`; mitigation reweighing, unawareness, `ThresholdOptimizer` + bảng trade-off fairness ↔ ROC-AUC ↔ expected loss.
- `credit_risk.responsible_ai.explainability`: SHAP global (summary, bar) + local (waterfall), LIME cho cùng hồ sơ, đo đồng thuận SHAP↔LIME; thông điệp `risk_factors` sinh từ SHAP.
- `credit_risk.responsible_ai.privacy`: PII inventory, pseudonymization HMAC (`PSEUDONYMIZATION_KEY`), generalization, retention 90 ngày (`make purge-logs`).
- `make responsible-ai`: sinh `reports/{fairness,explainability}_report.{json,md}`, `reports/figures/rai_*.png` và đồng bộ khối số liệu trong `docs/06-responsible-ai.md`, `docs/model-card.md`, `docs/data-card.md` (có test chống lệch); notebook `notebooks/02_fairness_explainability.ipynb` (`make notebook-rai`).

**CI/CD**
- Workflow `final-project-ci.yml`: lint → test (coverage gate 80 %) → build image + Trivy gate (fail khi CRITICAL) → smoke test Compose; `make ci` chạy cùng thứ tự ở local.
- Workflow `final-project-cd.yml`: CI gate → publish GHCR (SBOM + provenance, image reference bất biến theo digest) → deploy Ubuntu qua SSH (host key pin) → smoke test sau deploy → tự rollback về release trước → thông báo Telegram.
- Overlay `docker-compose.prod.yml` (bind `127.0.0.1`, bắt buộc secret, log rotation) và `docker-compose.image.yml` (chạy image đã publish); `deploy/ubuntu/deploy.sh` quản lý `releases/<tag>` + symlink `current`.
- Mọi action pin theo commit SHA.

**Sơ đồ kiến trúc & thuyết trình**
- 7 sơ đồ Mermaid (ngữ cảnh hệ thống, container, 2 sơ đồ component, data flow, retrain sequence, deployment Ubuntu) xuất SVG + PNG trong `docs/assets/diagrams/`, nguồn trong `src/`.
- Slide thuyết trình (`docs/presentation/`: HTML, PDF, PPTX) và demo script.

**Tài liệu & triển khai production**
- `docs/` đầy đủ: 01–07 (problem, architecture, ML pipeline, API reference + `openapi.yaml`, monitoring & alerting, Responsible AI, testing & CI/CD), model card, data card, ADR, bảng rubric → bằng chứng trong `docs/README.md`.
- `docs/guides/`: local quickstart, Ubuntu deployment, operations runbook, 11 kịch bản vận hành (drift → retrain, promote không downtime, rollback, API down, latency, input sai, MLflow/Postgres down, tấn công, fairness) với số liệu từ `reports/simulations/`.
- `docs/qa/`: kế hoạch và test case kiểm thử thủ công.
- `deploy/ubuntu/`: `install.sh` (Docker, Nginx, certbot, UFW, user deploy, systemd), vhost Nginx (TLS, rate limit, chặn `/metrics`), unit systemd cho stack và backup timer, `backup.sh` (pg_dump + mirror MinIO, retention, restore); `deploy.sh start|stop`.
- Root `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md` (quy ước code + vai trò thành viên), `SECURITY.md` viết lại đầy đủ.
- Test kiểm tra link và anchor nội bộ của mọi file Markdown.

### Changed
- `/api/v1/explain` dùng SHAP permutation so với hồ sơ tham chiếu (`method="shap_permutation"`, cộng dồn chính xác về xác suất, deterministic), tự fallback về reference substitution khi lỗi; cấu hình `explain.method` trong `configs/serving.yaml`.
- **Breaking:** gỡ `/predict`, `/reload-model`, `/health`; simulator, `scripts/sample_predict.py`, retrain hot reload và healthcheck Compose đã chuyển sang v1 + API key.
- `deploy/docker/Dockerfile.api`: multi-stage, `python:3.11.16-slim-trixie` pin digest, non-root, không còn `build-essential`/`curl`/`data/` trong image; `.dockerignore` thu hẹp build context.
- `docs/08-monitoring-alerting.md` → `docs/05-monitoring-alerting.md` (metric catalog, dashboard, ngưỡng alert, bằng chứng fire → resolve).
- `reports/simulations/` được track trong git làm bằng chứng cho các kịch bản.
- Quy ước hiển thị dashboard Grafana gộp vào `docs/05-monitoring-alerting.md` §4.1; ADR bỏ khối metadata, lý do dễ/khó đảo ngược chuyển vào mục Consequences.

### Fixed
- Reload model thất bại không còn làm mất model đang phục vụ.

### Removed
- `docs/legacy/` (README và ảnh chụp v1.0) — nội dung v1.0 vẫn tra được trong lịch sử git.

## [1.1.0] — 2026-09-28 — Tái cấu trúc repo

### Changed
- Gom code `src/` + `app/` + logic trong `scripts/` vào package cài đặt được `src/credit_risk/` (src layout); `scripts/` chỉ còn entrypoint mỏng.
- Cấu hình phân lớp: `configs/{training,serving,drift,logging}.yaml` + `configs/environments/{local,docker,test}.yaml` + biến môi trường (tên biến cũ giữ nguyên).
- Logging qua `configs/logging.yaml` thay cho `print` trong library code.
- Dữ liệu chia `data/raw` (bản gốc 30k, trước đây đọc từ `../Lab2`), `data/reference` (baseline), `data/processed` (streams + ground truth); thêm `data/manifest.json`.
- `Dockerfile` → `deploy/docker/Dockerfile.api`; `docker-compose.yml` → `deploy/compose/docker-compose.yml`; `monitoring/prometheus.yml` → `monitoring/prometheus/prometheus.yml`.
- Lint: flake8 → ruff + black + mypy; thêm pre-commit; CI workflow cập nhật tương ứng.
- URL API trong `retrain` và `persona_simulator` đọc từ cấu hình/`--api-url` thay vì hard-code.
- Test: tái tổ chức thành `tests/{unit,integration,data_quality,model_validation}` (6 → 90 test, hermetic với `APP_ENV=test`).

### Fixed
- `evaluate_model` trả ROC-AUC 0.5 như tài liệu mô tả khi target chỉ có một lớp (trước đó scikit-learn mới trả `nan`).
- Ghi inference log dùng timestamp UTC không phụ thuộc `datetime.utcnow()` (deprecated).

### Removed
- `scripts/generate_extra_screenshots.py` và 2 template HTML (`reports/screenshot_*.html`) dùng để render screenshot giả; 2 ảnh render giả (`01b_…`, `08_…`) bị xoá. Evidence được chụp từ hệ thống chạy thật.

### Verified
- Hành vi không đổi: metrics model V1 trên normal stream (ROC-AUC 0.7425, financial loss 6111), PSI 4 feature, response `/predict` cho 3 payload mẫu và hash 4 file dữ liệu **giống hệt** trước/sau tái cấu trúc.

## [1.0.0] — Lab 4 / Final Project v1
- Phiên bản ban đầu.
