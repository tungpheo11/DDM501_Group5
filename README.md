# 🛠️ DDM501: AI in DevOps, DataOps & MLOps — Group 5 Capstone Repository

[![Final Project CI](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-ci.yml/badge.svg?branch=main)](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-ci.yml)
[![Final Project CD](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-cd.yml/badge.svg)](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-cd.yml)
![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/API-FastAPI%20v1-009688)
![MLflow](https://img.shields.io/badge/tracking-MLflow-0194E2)
![Docker Compose](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED)
![Code style](https://img.shields.io/badge/code%20style-ruff%20%2B%20black-000000)

> *"Machine learning code is only 5–10% of the system. The rest is plumbing, infrastructure, and operational discipline."*  
> — Inspired by Sculley et al. (NeurIPS 2015) & Google's Rules of ML

Repository trung tâm lưu trữ toàn bộ hành trình nghiên cứu, bài tập thực hành (Labs 1–4) và **Đồ Án Tốt Nghiệp MLOps Hoàn Chỉnh (Final Project Capstone)** thuộc học phần **DDM501 — AI in DevOps, DataOps, MLOps** tại **FPT School of Business & Technology (FSB)**.

---

## 🏆 Cấu Trúc Repository

```text
DDM501_Group5/
├── FinalProject/                  # 🌟 ĐỒ ÁN TỐT NGHIỆP MLOPS (TRỌNG SỐ 40%)
│   ├── src/credit_risk/           # Mã nguồn lõi (Training, Serving, Responsible AI, Governance)
│   ├── deploy/                    # Hạ tầng Docker Compose & Triển khai Ubuntu Linux VM
│   ├── monitoring/                # Prometheus (11 Alert Rules), Alertmanager, Grafana (4 Dashboards)
│   ├── orchestration/airflow/     # Apache Airflow DAGs tự động hoá closed-loop retraining
│   ├── simulations/               # Bộ kịch bản traffic & data drift shock phục vụ Live Demo
│   ├── docs/                      # Tài liệu kỹ thuật, Model Card, Data Card, ADRs, Slides
│   ├── PROPOSAL.md                # Bản đề án tốt nghiệp, bài toán tài chính & giải mã 3 ngưỡng
│   ├── ARCHITECTURE.md            # Sơ đồ C4, luồng dữ liệu, phân tích trade-offs kỹ thuật
│   └── CONTRIBUTING.md            # Bảng phân vai nhiệm vụ 4 thành viên theo Rubric 3.3
├── Lab1/                          # Lab 01: Version Control, Data Versioning & ML Baseline
├── Lab2/                          # Lab 02: Experiment Tracking với MLflow & Model Registry
├── Lab3/                          # Lab 03: Automated Testing & GitHub Actions CI/CD Pipeline
├── Lab4/                          # Lab 04: Observability, Drift Detection & Model Monitoring
└── INDIVIDUAL_ASSIGNMENTS_CONTEXT.md # Ngữ cảnh chưng cất bài tập cá nhân 1 & 2
```

---

## 🌟 Đồ Án Tốt Nghiệp: Credit Default Risk Scoring Platform

Hệ thống MLOps vòng lặp khép kín (Closed-Loop Continuous Training & Delivery) tự động chấm điểm **rủi ro vỡ nợ tín dụng** trong thời gian thực, phục vụ quyết định phê duyệt khoản vay (**APPROVE / REVIEW / DECLINE**):

* **Mã nguồn & Hướng dẫn chi tiết**: 👉 **[`FinalProject/README.md`](FinalProject/README.md)**
* **Bản Đề Án Chi Tiết (Proposal)**: 👉 **[`FinalProject/PROPOSAL.md`](FinalProject/PROPOSAL.md)**
* **Kiến Trúc Kỹ Thuật (Architecture)**: 👉 **[`FinalProject/ARCHITECTURE.md`](FinalProject/ARCHITECTURE.md)**
* **Slide Thuyết Trình & Kịch Bản Demo**: 👉 **[`FinalProject/docs/presentation/`](FinalProject/docs/presentation/)** ([`slides.pdf`](FinalProject/docs/presentation/slides.pdf) · [`slides.pptx`](FinalProject/docs/presentation/slides.pptx))
* **Báo Cáo Nghiệm Thu & Evidence**: 👉 **[`FinalProject/docs/qa/test-report.md`](FinalProject/docs/qa/test-report.md)**

### Bảng Kết Quả Nghiệm Thu Trọng Yếu

| Hạng Mục | Kết Quả Đạt Được | Bằng Chứng & Tài Liệu Đối Chiếu |
|---|---|---|
| **Mô hình phục vụ (Champion)** | Logistic Regression — holdout ROC-AUC **0.7700**, recall 0.62 | [`FinalProject/reports/model_comparison.md`](FinalProject/reports/model_comparison.md) |
| **Độ trễ suy luận (SLO)** | p95 **18.79 ms**, p99 24.17 ms (1.000 requests, 0 lỗi) | [`FinalProject/reports/latency_benchmark.json`](FinalProject/reports/latency_benchmark.json) |
| **Kiểm thử tự động** | **354 tests PASS tuyệt đối**, coverage **92.1%** (vượt gate 80%) | [`FinalProject/docs/07-testing-cicd.md`](FinalProject/docs/07-testing-cicd.md) |
| **Hạ tầng giám sát** | 4 Dashboard Grafana, 11 Prometheus alert rules đã verify fire/resolve | [`FinalProject/docs/05-monitoring-alerting.md`](FinalProject/docs/05-monitoring-alerting.md) |
| **Công bằng (Responsible AI)** | Disparate Impact nhóm tuổi: **0.772 $\to$ 0.926** sau mitigation | [`FinalProject/reports/fairness_report.md`](FinalProject/reports/fairness_report.md) |
| **Triển khai Production** | Docker Compose 15 services, Nginx reverse proxy, Systemd trên Ubuntu VM | [`FinalProject/docs/guides/ubuntu-deployment.md`](FinalProject/docs/guides/ubuntu-deployment.md) |

---

## 🚀 Khởi Chạy Nhanh Đồ Án (Quickstart)

Hệ thống hỗ trợ chạy cả trên **máy cá nhân (macOS/Linux/Windows)** lẫn **SSH vào Ubuntu Linux VM**:

```bash
# 1. Di chuyển vào thư mục FinalProject
cd FinalProject

# 2. Tạo cấu hình môi trường từ mẫu
cp .env.example .env

# 3. Khởi chạy toàn bộ cụm 15 microservices
make up

# 4. Kiểm tra sức khoẻ toàn hệ thống
make health
```

### Các Cổng Dịch Vụ Chính

* 🌐 **FastAPI Swagger Docs**: <http://localhost:18020/docs>
* 📊 **Grafana Dashboards**: <http://localhost:13000> (`admin` / `admin`)
* 🧪 **MLflow Tracking & Registry**: <http://localhost:15040>
* 🔄 **Airflow Orchestrator**: <http://localhost:18080> (`admin` / `admin`)
* 🪣 **MinIO S3 Storage Console**: <http://localhost:19041> (`minioadmin` / `miniopassword`)
* 🚨 **Prometheus & Alertmanager**: <http://localhost:19090> & <http://localhost:19093>

---

## 👥 Đội Ngũ Thực Hiện & Phân Vai (Rubric 3.3)

| Thành Viên | Vai Trò Chính | Phạm Vi Đóng Góp Kỹ Thuật | Sản Phẩm Giao Nộp |
|:---|:---|:---|:---|
| **Hòa (hoapn)** | Data & ML Pipeline Lead | Ingestion, Pandera validation, Feature Engineering, Optuna tuning, MLflow Registry | [03 — Pipeline](FinalProject/docs/03-ml-pipeline.md), MLflow Model Registry |
| **Tùng (tungpheo11)** | Serving, Infrastructure & CI/CD Lead | FastAPI REST v1, Docker multi-stage, Docker Compose, Nginx, CI/CD Actions, Ubuntu VM CD | [04 — API](FinalProject/docs/04-api-reference.md), [07 — CI/CD](FinalProject/docs/07-testing-cicd.md), Deploy Scripts |
| **Hoa (hoant)** | Monitoring & Orchestration Lead | Prometheus exporter, 11 Alert rules, Alertmanager Telegram Bot, 4 Grafana Dashboards, Airflow Retrain DAG | [05 — Monitoring](FinalProject/docs/05-monitoring-alerting.md), Airflow DAGs |
| **Thịnh (zgsnat)** | Responsible AI, Simulation & QA Lead | Fairness Audit (4/5 Rule), SHAP Explainability, Simulation Suite (Drift Shock), QA Test Plan & Reports | [06 — Responsible AI](FinalProject/docs/06-responsible-ai.md), [Slide Deck](FinalProject/docs/presentation/README.md), [QA Report](FinalProject/docs/qa/test-report.md) |

---

## 📚 Tổng Quan Các Bài Lab Trong Học Phần

1. **[Lab 1: Version Control & Data Management](Lab1/)**: Thiết lập Git branching, quản lý dữ liệu lớn bằng DVC/Git LFS, xây dựng baseline model.
2. **[Lab 2: Experiment Tracking & Model Registry](Lab2/)**: Tích hợp MLflow theo dõi tham số, metrics, artifacts và quản lý vòng đời mô hình Staging/Production.
3. **[Lab 3: Automated Testing & CI/CD](Lab3/)**: Xây dựng test suite đa tầng (Unit, Integration, Data Quality) kết hợp GitHub Actions kiểm thử tự động.
4. **[Lab 4: Monitoring, Drift Detection & Alerting](Lab4/)**: Triển khai Prometheus, Grafana và Evidently AI giám sát độ trôi dữ liệu và cảnh báo thời gian thực.
