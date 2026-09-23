# 💳 Credit Default Risk Scoring — End-to-End MLOps Platform
> **Course**: DDM501 — AI in DevOps, DataOps, MLOps · FSB  
> **Group 5 Final Project**: Closed-Loop Continuous ML Training, Drift Detection & Canary Delivery

[![CI Pipeline](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-ci.yml/badge.svg)](https://github.com/tungpheo11/DDM501_Group5/actions/workflows/final-project-ci.yml)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![MLflow](https://img.shields.io/badge/MLflow-2.19-0194E2?logo=mlflow&logoColor=white)](https://mlflow.org/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

---

## 📖 1. Giới Thiệu Dự Án (Project Overview)

Trong các bài toán tài chính tín dụng (Credit Default Risk Scoring), việc xây dựng mô hình chỉ chiếm **30%**. Trọng tâm **70% còn lại là tầng vận hành MLOps**: giám sát độ trôi dạt dữ liệu theo thời gian thực (Data Drift & Concept Drift), cơ chế ghi nhận log suy luận (Inference Logging), tự động tái huấn luyện (Retraining Loop) và triển khai an toàn không gián đoạn (Canary/Blue-Green Deployment).

Dự án này sử dụng tập dữ liệu thực tế **Default of Credit Card Clients Dataset (UCI / Kaggle)** gồm **30.000 dòng dữ liệu và 24 đặc trưng** để xây dựng một chu trình MLOps hoàn chỉnh.

### Kịch bản 4 phân vùng dữ liệu:
1. `train_baseline.csv` (**15.000 dòng**): Khách hàng truyền thống (Tuổi trung bình: 38.8) dùng huấn luyện **Model V1.0 (Baseline)**.
2. `stream_normal.csv` (**5.000 dòng**): Dữ liệu sản xuất bình thường tháng đầu (Tuổi trung bình: 38.5, phân phối ổn định, PSI < 0.10).
3. `stream_drifted.csv` (**5.000 dòng**): Giả lập sự cố chiến dịch Marketing thu hút giới trẻ Gen-Z (Tuổi trung bình: 26.4, hạn mức thấp hơn & thói quen chi tiêu khác biệt, PSI $\ge 0.25$).
4. `ground_truth_feedback.csv` (**5.000 dòng**): Dữ liệu nhãn thực tế sau 30 ngày phục vụ tự động Retraining.

---

## 🏗️ 2. Bảng Cổng Dịch Vụ & Endpoints (Service Ports)

Mọi dịch vụ được cô lập tuyệt đối trong Docker với cổng chuyên biệt, không gây xung đột hệ thống:

| Dịch vụ | Cổng Host | Đường dẫn truy cập | Mô tả & Tài khoản mặc định |
| :--- | :--- | :--- | :--- |
| **FastAPI Serving** | `18020` | `http://localhost:18020` | Phục vụ dự đoán rủi ro tín dụng thời gian thực |
| **FastAPI Swagger** | `18020` | `http://localhost:18020/docs` | Tài liệu API tương tác OpenAPI |
| **Prometheus Telemetry** | `18020` | `http://localhost:18020/metrics` | Endpoint trích xuất metrics cho Prometheus |
| **MLflow Registry UI** | `15040` | `http://localhost:15040` | Giao diện quản lý thử nghiệm & Model Registry |
| **MinIO Console** | `19041` | `http://localhost:19041` | S3 Object Browser (`minioadmin` / `miniopassword`) |
| **MinIO API S3** | `19040` | `http://localhost:19040` | Endpoint S3 cho MLflow và artifacts |
| **PostgreSQL Database** | `15434` | `localhost:15434` | Lưu trữ `inference_logs` & MLflow metadata |
| **Prometheus Server** | `19090` | `http://localhost:19090` | Thu thập metrics hệ thống & tỷ lệ dự đoán |
| **Grafana Dashboard** | `13000` | `http://localhost:13000` | Bảng điều khiển trực quan (`admin` / `admin`) |

---

## 🚀 3. Hướng Dẫn Khởi Động Nhanh (Quickstart)

### Bước 1: Khởi động toàn bộ hạ tầng bằng Docker Compose
```bash
cd FinalProject
docker compose up -d
```

Kiểm tra trạng thái các container:
```bash
docker compose ps
```
> Đợi khoảng 15–20 giây để PostgreSQL và MinIO tự khởi tạo hoàn tất. Khi các container báo `healthy`, toàn bộ hệ thống đã sẵn sàng.

### Bước 2: Kiểm tra Healthcheck
```bash
curl -s http://localhost:18020/health | jq .
```
Kết quả kỳ vọng:
```json
{
  "status": "ok",
  "model_loaded": true,
  "model_name": "credit-risk-model",
  "model_source": "local_artifact:.../models/credit_model_v1.joblib",
  "database_connected": true
}
```

### Bước 3: Gửi dự đoán thử nghiệm
Chạy script kiểm tra mẫu:
```bash
python scripts/sample_predict.py
```

Hoặc gửi HTTP POST qua `curl`:
```bash
curl -s -X POST http://localhost:18020/predict \
  -H "Content-Type: application/json" \
  -d '{
    "LIMIT_BAL": 200000.0,
    "SEX": 2,
    "EDUCATION": 1,
    "MARRIAGE": 2,
    "AGE": 38,
    "PAY_0": 0, "PAY_2": 0, "PAY_3": 0, "PAY_4": 0, "PAY_5": 0, "PAY_6": 0,
    "BILL_AMT1": 15000.0, "BILL_AMT2": 14000.0, "BILL_AMT3": 13000.0,
    "BILL_AMT4": 12000.0, "BILL_AMT5": 11000.0, "BILL_AMT6": 10000.0,
    "PAY_AMT1": 5000.0, "PAY_AMT2": 5000.0, "PAY_AMT3": 5000.0,
    "PAY_AMT4": 5000.0, "PAY_AMT5": 5000.0, "PAY_AMT6": 5000.0
  }' | jq .
```

Phản hồi mẫu:
```json
{
  "request_id": "req_a1b2c3d4e5f6",
  "default_prediction": 0,
  "default_probability": 0.12,
  "risk_decision": "APPROVE",
  "served_by": "local_artifact:.../credit_model_v1.joblib",
  "latency_ms": 12.4
}
```
Mỗi lượt dự đoán thành công sẽ tự động được lưu trữ vào bảng `inference_logs` trong PostgreSQL để phục vụ phân tích độ lệch dữ liệu (Drift Detection) bởi Evidently AI!

---

## 🧪 4. Kiểm Thử & CI/CD Pipeline

Dự án được bảo vệ bởi **GitHub Actions CI** với chuẩn chất lượng nghiêm ngặt:
- **Linting & Code Style**: Tuân thủ chuẩn PEP 8 với `flake8` (0 lỗi).
- **Unit Tests**: Kiểm thử toàn diện pipeline, model inference, và FastAPI contract với `pytest` và `coverage`.
- **Docker Validation**: Kiểm tra khả năng build container độc lập trên runner Ubuntu.

Chạy kiểm thử cục bộ:
```bash
# Cài đặt môi trường cực nhanh bằng uv
uv sync --dev

# Chạy test suite
PYTHONPATH=. uv run pytest -v tests/ --cov=src --cov=app

# Kiểm tra lint
uv run flake8 src app tests
```

---

## 👥 Nhóm Tác Giả (Group 5)
* **Khóa học**: DDM501 — AI in DevOps, DataOps, MLOps
* **Học viện**: FSB, FPT University
