# Credit Default Risk Scoring — End-to-End MLOps

[![Final Project CI](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-ci.yml/badge.svg?branch=main)](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-ci.yml)
[![Final Project CD](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-cd.yml/badge.svg)](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-cd.yml)
![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/API-FastAPI%20v1-009688)
![MLflow](https://img.shields.io/badge/tracking-MLflow-0194E2)
![Docker Compose](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED)
![Code style](https://img.shields.io/badge/code%20style-ruff%20%2B%20black-000000)

Hệ thống MLOps vòng lặp khép kín **quản lý hạn mức cho chủ thẻ tín dụng đang lưu hành** (Credit Line Management, UCI *Default of Credit Card Clients*, 30.000 chủ thẻ): sau mỗi kỳ sao kê, mỗi chủ thẻ được dự báo xác suất vỡ nợ ở kỳ thanh toán kế tiếp và nhận quyết định **APPROVE / REVIEW / DECLINE**, credit score và hạn mức đề xuất. API phục vụ hai luồng: duyệt yêu cầu tăng hạn mức realtime trên app (`/predict`, p95 ≤ 100 ms) và rà soát hạn mức theo lô sau kỳ sao kê (`/predict/batch`), kèm giải thích quyết định (`/explain`). Model được huấn luyện với Optuna + MLflow, phục vụ qua FastAPI, giám sát bằng Prometheus/Grafana, phát hiện drift bằng Evidently + PSI và tự retrain qua Airflow với quality gate champion/challenger.

| Chỉ số | Giá trị | Nguồn |
|---|---|---|
| Model production | XGBoost (Model Zoo 4 ứng viên: LR, RF, LightGBM, XGBoost) — holdout ROC-AUC **0.7676**, CV 0.7505 | [`model_comparison.md`](reports/model_comparison.md) |
| Latency `POST /api/v1/predict` | p95 **20.59 ms**, p99 29.49 ms (500 request tuần tự, 0 lỗi); 20 user đồng thời: p95 72 ms, 0 lỗi | [`latency_benchmark.json`](reports/latency_benchmark.json), [`locust_stress_summary.json`](reports/load/locust_stress_summary.json) |
| Test | 4 loại test, coverage **91.3 %** (gate ≥ 80 %) | [07 — Testing & CI/CD](docs/07-testing-cicd.md) |
| Monitoring | 4 dashboard, 11 alert, mỗi alert đã fire → resolve trên stack thật | [05 — Monitoring](docs/05-monitoring-alerting.md) |
| Fairness (nhóm tuổi) | DI 0.772 → 0.926 sau mitigation, ROC-AUC gần như không đổi | [`fairness_report.md`](reports/fairness_report.md) |

![Container view](docs/assets/diagrams/02-container.svg)

---

## 📑 Mục lục

1. [Quickstart (Khởi Chạy Nhanh)](#1-quickstart-khởi-chạy-nhanh)
2. [Kịch Bản Live Demo 15 Phút & Mô Phỏng Lưu Lượng](#2-kịch-bản-live-demo-15-phút--mô-phỏng-lưu-lượng)
3. [Bản Chất Bài Toán Tài Chính & Ma Trận Chi Phí](#3-bản-chất-bài-toán-tài-chính--ma-trận-chi-phí)
4. [Kiến Trúc Hệ Thống & Cổng Dịch Vụ](#4-kiến-trúc-hệ-thống--cổng-dịch-vụ)
5. [Kết Quả Huấn Luyện & Tuyển Chọn Mô Hình](#5-kết-quả-huấn-luyện--tuyển-chọn-mô-hình)
6. [Trí Tuệ Nhân Tạo Có Trách Nhiệm (Responsible AI)](#6-trí-tuệ-nhân-tạo-có-trách-nhiệm-responsible-ai)
7. [Kiểm Thử & CI/CD Triển Khai Production (Ubuntu VM)](#7-kiểm-thử--cicd-triển-khai-production-ubuntu-vm)
8. [Tài Liệu Chuyên Sâu & Phân Vai Thành Viên](#8-tài-liệu-chuyên-sâu--phân-vai-thành-viên)

---

## 1. Quickstart (Khởi Chạy Nhanh)

Yêu cầu: Docker (Compose ≥ 2.24.4, cấp ≥ 6 GB RAM), Python 3.11, `make`. Chi tiết: [local quickstart](docs/guides/local-quickstart.md).

```bash
# 1. Clone và chuẩn bị môi trường
git clone git@github.com:tungpheo11/DDM501_Group5.git
cd DDM501_Group5/FinalProject
cp .env.example .env

# 2. Khởi động toàn bộ stack 15 containers
make up

# 3. Kiểm tra trạng thái sẵn sàng (ready)
make health
```

*Các cổng dịch vụ chính*:
- **Scoring API Swagger**: `http://localhost:18020/docs` (hoặc `http://<VM_IP>:18020/docs`)
- **Grafana Dashboards**: `http://localhost:13000` (user/pass: `admin/admin`)
- **MLflow Tracking**: `http://localhost:15040`
- **Airflow Orchestrator**: `http://localhost:18080` (user/pass: `admin/admin`)
- **MinIO S3 Portal**: `http://localhost:19041` (user/pass: `minioadmin/miniopassword`)

---

## 2. Kịch Bản Live Demo 15 Phút & Mô Phỏng Lưu Lượng

Hệ thống cung cấp trọn bộ script mô phỏng phục vụ buổi trình diễn trực tiếp (Live Demo) trước Giảng viên và Hội đồng:

### 🚀 Bảng Điều Khiển Live Demo (Theo Từng Mốc Thời Gian)

| Mốc Thời Gian | Thao Tác Trình Diễn | Câu Lệnh Thực Thi | Hiện Tượng Quan Sát Trên Hệ Thống |
| :---: | :--- | :--- | :--- |
| **00:00 – 03:00** | Khởi động stack & kiểm tra 15 dịch vụ | `make health`<br>`docker compose ps` | Toàn bộ 15 containers xanh `healthy`. MLflow, Postgres, MinIO, API, Prometheus, Grafana sẵn sàng. |
| **03:00 – 06:00** | **Demo Lưu lượng Bình thường** | `python scripts/simulate_normal_traffic.py --count 50` | Grafana chuyển động: Requests tăng đều, p95 Latency $< 20\text{ms}$, FICO TB $\sim 710$, Approve $> 75\%$, Trạng thái Xanh. |
| **06:00 – 09:00** | **Tạo Sự Cố (The Shock: Gen-Z Drift)** | `python scripts/simulate_genz_marketing_drift.py --count 60` | Độ tuổi tụt từ 39 về 22, trễ hạn lương gig. **Grafana đổi màu đỏ**, $\text{PSI} \ge 0.25$, Prometheus bắn alert `CriticalDataDriftDetected`. |
| **09:00 – 12:00** | Tự động hóa phục hồi (Self-Healing) | *(Quan sát Airflow UI)* | Webhook kích hoạt Airflow DAG `model_retrain`: Ghép nhãn $\to$ Quality Gate $\to$ Train Challenger $\to$ Đăng ký MLflow $\to$ Hot-reload API. |
| **12:00 – 15:00** | Kiểm chứng Zero-Downtime & Q&A | `curl -H "X-API-Key: ..." http://localhost:18020/api/v1/model/info` | API phục vụ model mới `@champion` mượt mà không downtime. Chủ thẻ trẻ được chấm điểm công bằng hơn. |

### Chuỗi 4 Giai Đoạn Đa Tác Nhân (Staged Progression)
```bash
python simulations/run_simulation.py --scenario all --count 40
# Hoặc chạy giả lập 5 Persona hành vi:
python simulations/persona_simulator.py --mode staged_progression --count 35
```

---

## 3. Bản Chất Bài Toán Tài Chính & Ma Trận Chi Phí

### Mô hình 3 Chữ C trong Tín Dụng (The 3 Cs of Credit)
- **Capacity (Năng lực trả nợ)**: `LIMIT_BAL` (Hạn mức thẻ), `BILL_AMT1..6` (Dư nợ sao kê hàng tháng), Tỷ lệ sử dụng hạn mức (Credit Utilization).
- **Character (Uy tín & Hành vi)**: `PAY_0..6` (Lịch sử trả nợ các tháng qua), `PAY_AMT1..6` (Số tiền thực trả). `PAY_0` chiếm hơn **35% Feature Importance**.
- **Conditions (Nhân khẩu & Điều kiện)**: `AGE`, `EDUCATION`, `MARRIAGE`, `SEX`.

### Ma Trận Chi Phí Bất Đối Xứng (Asymmetric Cost Matrix)

$$ \text{Tỷ lệ thiệt hại: } \frac{Cost(FN)}{Cost(FP)} \approx 10 \times \text{ đến } 20 \times $$

Chi phí của **False Negative (giữ hoặc tăng hạn mức cho chủ thẻ sắp vỡ nợ: mất dư nợ cộng phần hạn mức vừa tăng)** lớn gấp 10-20 lần so với **False Positive (hạ hoặc khoá hạn mức oan một chủ thẻ tốt: mất doanh thu, khách rời bỏ)**. Hệ thống áp dụng cơ chế **Ra quyết định đa ngưỡng (Multi-Threshold Decision)**:
- **$P < 0.30$**: `APPROVE` (Chấp thuận yêu cầu tăng hạn mức; trong rà soát định kỳ thì giữ hoặc đề xuất tăng hạn mức).
- **$0.30 \le P < 0.60$**: `REVIEW` (Chuyển chuyên viên rủi ro xem xét tài khoản, đề xuất hạ hạn mức).
- **$P \ge 0.60$**: `DECLINE` (Từ chối yêu cầu tăng hạn mức; trong rà soát định kỳ thì tạm khoá hạn mức khả dụng; kèm Adverse Action reason codes).

---

## 4. Kiến Trúc Hệ Thống & Cổng Dịch Vụ

Tóm tắt kiến trúc một trang (Chi tiết xem tại [`ARCHITECTURE.md`](ARCHITECTURE.md) và [`docs/02-architecture.md`](docs/02-architecture.md)):

```mermaid
flowchart LR
    client[Client / Mobile App] -->|POST /api/v1/predict + X-API-Key| api[Scoring API :18020]
    api -->|models:/credit-risk-model@champion| mlflow[MLflow Registry :15040]
    api -->|sync insert inference_logs| pg[(PostgreSQL :15434)]
    drift[Drift Monitor :18085] -->|scan 500 logs| pg
    prom[Prometheus :19090] -->|scrape| api & drift
    prom -->|alerts| am[Alertmanager :19093] --> hook[Webhook / Telegram]
    airflow[Airflow 2.10 :18080] -->|trigger retrain| retrain[model_retrain DAG]
    retrain -->|train challenger -> quality gate| mlflow
    retrain -->|promote -> POST /api/v1/model/reload| api
    grafana[Grafana :13000] --> prom
```

### Cấu Trúc Repo Chuẩn Enterprise

```text
FinalProject/
├── README.md  ARCHITECTURE.md  CONTRIBUTING.md  CHANGELOG.md  SECURITY.md
├── Makefile  pyproject.toml  uv.lock  requirements.txt  requirements-dev.txt  .env.example
├── configs/                 # training / serving / drift / responsible_ai / logging + environments/
├── data/                    # raw/ reference/ processed/ + manifest.json (SHA256 fingerprint)
├── models/                  # local fallback artifacts khi MLflow không tới được
├── src/credit_risk/         # package chính: config, data, features, training, evaluation, serving, monitoring, responsible_ai, utils
├── services/drift_monitor/  # Microservice Evidently + PSI độc lập, xuất metrics
├── orchestration/airflow/   # 3 DAG: service_health_check, drift_monitoring, model_retrain
├── deploy/                  # compose/ (base, prod, image) + ubuntu/ (install, deploy, backup, nginx, systemd)
├── monitoring/              # prometheus/ (8 recording rules + 11 alert rules) alertmanager/ grafana/ statsd/
├── simulations/             # Bộ kịch bản giả lập lưu lượng & trôi dạt dữ liệu chuẩn
├── scripts/                 # Entrypoints chạy nhanh: simulate, retrain, benchmark, audit
├── tests/                   # unit/ integration/ data_quality/ model_validation/ e2e/ load/
├── reports/                 # Artifacts xuất tự động: model, fairness, explainability, latency
└── docs/                    # 01–07, guides/, runbooks/, adr/, assets/, presentation/, qa/
```

---

## 5. Kết Quả Huấn Luyện & Tuyển Chọn Mô Hình

<!-- model-comparison:start -->
_Sinh tự động từ `reports/model_comparison.json` (session `20261001T082709Z`)._

| Model | CV ROC-AUC (mean ± std) | Holdout ROC-AUC | Holdout PR-AUC | Holdout F1 | Holdout Recall | Holdout expected loss | Normal-stream ROC-AUC | Normal-stream expected loss |
|---|---|---|---|---|---|---|---|---|
| **XGBoost** (selected) | 0.7505 ± 0.0130 | 0.7676 | 0.5666 | 0.5319 | 0.5554 | 1.1087 | 0.7545 | 1.1734 |
| LightGBM | 0.7486 ± 0.0138 | 0.7689 | 0.5704 | 0.5309 | 0.5778 | 1.0733 | 0.7543 | 1.1502 |

Model được chọn: **XGBoost** — gate: **giữ champion hiện tại**. Chi tiết: [`reports/model_comparison.md`](reports/model_comparison.md).
<!-- model-comparison:end -->

---

## 6. Trí Tuệ Nhân Tạo Có Trách Nhiệm (Responsible AI)

1. **Kiểm Định Định Kiến (Fairness & Bias Audit)**:
   - Sử dụng **Fairlearn** đánh giá Disparate Impact (DI), Demographic Parity Difference (DPD), và Equal Opportunity Difference (EOD) trên các nhóm nhạy cảm (`SEX`, `AGE`, `EDUCATION`, `MARRIAGE`).
   - Áp dụng kỹ thuật giảm thiểu thiên vị (**Mitigation via `ThresholdOptimizer`**): Cải thiện chỉ số Disparate Impact của nhóm tuổi trẻ từ **0.772 lên 0.926** (đáp ứng trọn vẹn Four-Fifths Rule $\ge 0.80$).
2. **Khả Năng Giải Thích (Explainability)**:
   - Tích hợp **SHAP** (Tree/Permutation) và **LIME** với chỉ số đồng thuận (consensus score).
   - Tự động sinh **Adverse Action Reason Codes** khi chủ thẻ bị từ chối yêu cầu tăng hạn mức hoặc bị hạ / tạm khoá hạn mức — các trường hợp mà đạo luật tín dụng công bằng (ECOA / Reg B, FCRA) coi là adverse action.
3. **Bảo Mật & Quyền Riêng Tư (Privacy & PII)**:
   - Cơ chế băm HMAC (`PSEUDONYMIZATION_KEY`) mã hóa định danh cá nhân; chính sách tự động xóa log suy luận sau 90 ngày (`make purge-logs`).

---

## 7. Kiểm Thử & CI/CD Triển Khai Production (Ubuntu VM)

### Bộ Kiểm Thử Đa Tầng (Coverage 92.1% · Gate ≥ 80%)
- **Unit Tests**: Kiểm tra tiền xử lý, tính toán chỉ số tài chính, trôi dạt dữ liệu, logic nghiệp vụ.
- **Integration Tests**: Kiểm thử hợp đồng API `/api/v1/predict`, `/batch`, `/explain`, SQLite in-memory.
- **Data Quality Tests**: Kiểm tra schema Pandera, chặn missing values, giới hạn biên UCI.
- **Model Validation Tests**: Kiểm định tính đơn điệu của rủi ro (Monotonicity), ROC-AUC $\ge 0.70$, SLA Latency p95 $< 50\text{ms}$.

```bash
# Chạy toàn bộ test suite
make test
# Xem báo cáo coverage chi tiết
make test-cov
```

### Triển Khai Tự Động (Continuous Deployment - CD) — ĐÃ VERIFIED trên Production

Pipeline CD được kích hoạt hoàn toàn tự động khi push tag `v*` lên `main`, đã triển khai thành công **v1.0.0** lên VM production `148.113.255.63`:

```text
git tag v1.0.0 && git push origin v1.0.0
   │
   ▼
CI Gate (lint + 394 tests + coverage ≥ 80% + image build + Trivy + smoke)
   │  ✓ 2m13s
   ▼
Publish Image → GHCR (ghcr.io/tungpheo11/credit-risk-api@sha256:...)
   │  ✓ 3m14s – immutable digest, SBOM + provenance attestations
   ▼
Deploy to Ubuntu VM (SSH → upload release → docker compose up → smoke test)
   │  ✓ 1m47s – 12 containers healthy, automatic rollback nếu smoke fail
   ▼
Notify Telegram (deployment status)
```

- **Trigger**: Push tag `v*` (e.g. `git tag v1.2.0 && git push origin v1.2.0`)
- **CI gate**: Lint (ruff, black, mypy) + Test suite (394 tests, coverage ≥ 80%) + Docker build + Trivy security scan (block CRITICAL)
- **Publish**: Build multi-stage Docker image → push lên GitHub Container Registry (GHCR) với immutable digest
- **Deploy**: SSH key-only auth → upload release bundle → `deploy.sh deploy` → zero-downtime rolling update
- **Safety**: Smoke test tự động sau deploy; **automatic rollback** về release trước nếu smoke fail; symlink-based release management (`/opt/credit-risk/current → releases/<tag>`)
- **Secrets**: `DEPLOY_SSH_KEY`, `DEPLOY_SSH_HOST`, `DEPLOY_SSH_USER`, `DEPLOY_SSH_KNOWN_HOSTS` được quản lý qua GitHub Actions Secrets


---

## 8. Tài Liệu Chuyên Sâu & Phân Vai Thành Viên

### Bảng Phân Vai Đóng Góp Nhóm 5 (Rubric 3.3)

| Mảng Việc | Thành Viên Phụ Trách | Reviewer | Phạm Vi Công Việc | Sản Phẩm Giao Nộp Chính |
| :--- | :--- | :--- | :--- | :--- |
| **M1: Data & ML Pipeline** | **Hòa** | Tùng | `data/`, `src/credit_risk/training`, `evaluation`, `features` | [03 — Pipeline](docs/03-ml-pipeline.md), MLflow Registry |
| **M2: Serving, Docker & CI/CD** | **Tùng** | Hoa | `src/credit_risk/serving`, `deploy/`, `Makefile`, CI/CD Workflows | [04 — API](docs/04-api-reference.md), [07 — CI/CD](docs/07-testing-cicd.md), CD Script |
| **M3: Monitoring & Orchestration** | **Hoa** | Thịnh | `monitoring/`, `services/drift_monitor`, Airflow DAGs, `simulations/` | [05 — Monitoring](docs/05-monitoring-alerting.md), Grafana Dashboards |
| **M4: Responsible AI & Presentation**| **Thịnh** | Hòa | `responsible_ai/`, `docs/presentation/`, Slide Deck, QA | [06 — Responsible AI](docs/06-responsible-ai.md), [Slide Deck](docs/presentation/README.md) |

### Danh Mục Tài Liệu Kỹ Thuật

| Tài Liệu | Nội Dung Chuyên Sâu |
| :--- | :--- |
| [`docs/README.md`](docs/README.md) | **Bảng đối chiếu Rubric Thầy $\to$ Bằng chứng & File tương ứng** |
| [`PROPOSAL.md`](PROPOSAL.md) | **Đề án tốt nghiệp MLOps, bài toán kinh doanh & giải mã 3 ngưỡng** |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`docs/02-architecture.md`](docs/02-architecture.md) | Sơ đồ kiến trúc C4, data flow, tech stack, trade-offs |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Phân vai trách nhiệm 4 thành viên & quy chuẩn đóng góp |
| [`docs/qa/test-report.md`](docs/qa/test-report.md) · [`docs/qa/test-cases.md`](docs/qa/test-cases.md) | Báo cáo kiểm thử hệ thống & thư viện bằng chứng (Evidence) |
| [`docs/01-problem-statement.md`](docs/01-problem-statement.md) | Định nghĩa bài toán, bối cảnh kinh doanh, mục tiêu và chỉ số |
| [`docs/04-api-reference.md`](docs/04-api-reference.md) · [`docs/openapi.yaml`](docs/openapi.yaml) | Đặc tả OpenAPI v3, hợp đồng dữ liệu, mã lỗi chuẩn |
| [`docs/05-monitoring-alerting.md`](docs/05-monitoring-alerting.md) | Catalog metrics, 4 Dashboards, 11 Alert rules & bằng chứng fire/resolve |
| [`docs/06-responsible-ai.md`](docs/06-responsible-ai.md) | Báo cáo Fairness, SHAP/LIME, chính sách quyền riêng tư |
| [`docs/guides/ubuntu-deployment.md`](docs/guides/ubuntu-deployment.md) | Hướng dẫn triển khai máy chủ Ubuntu thực tế qua SSH |
| [`docs/presentation/`](docs/presentation/) | **Slide thuyết trình (HTML) & Kịch bản demo** |
| [`INDIVIDUAL_ASSIGNMENTS_CONTEXT.md`](../INDIVIDUAL_ASSIGNMENTS_CONTEXT.md) | **Ngữ cảnh chưng cất dùng cho Bài Tập Cá Nhân 1 & 2** |
