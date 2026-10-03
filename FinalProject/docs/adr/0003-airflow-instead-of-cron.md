# ADR-0003: Apache Airflow thay cho cron để điều phối pipeline

## Context

Vòng lặp MLOps có nhiều bước phụ thuộc nhau: kiểm tra sức khoẻ service → phân tích drift → nếu drift vượt ngưỡng thì retrain → quality gate (champion vs challenger theo ROC-AUC + financial loss) → promote hoặc giữ champion/rollback → hot reload API → báo cáo/alert. Yêu cầu:

- Nhánh điều kiện (drift / không drift, pass / fail gate) và retry có kiểm soát.
- Lịch chạy định kỳ **và** trigger theo sự kiện (alert `DataDriftDetected`).
- Quan sát được lịch sử chạy, log từng task, trạng thái thất bại → alert `RetrainFailed`.
- Self-hosted trong cùng Docker Compose với phần còn lại của stack, không phụ thuộc dịch vụ cloud bên ngoài.

## Decision

Dùng **Apache Airflow** (image riêng trong `orchestration/airflow/`, không cài Airflow vào `requirements.txt` để tránh xung đột dependency) với 3 DAG:

1. `service_health_check` — ping API/MLflow/Postgres/MinIO định kỳ.
2. `drift_monitoring` — chạy `credit_risk.monitoring.drift.run_drift_analysis()`, `BranchPythonOperator` quyết định trigger retrain.
3. `model_retrain` — `credit_risk.training.retrain.run_retraining_pipeline()` + quality gate + promote/rollback + gọi `POST /api/v1/model/reload`.

DAG chỉ là lớp điều phối mỏng; mọi logic nằm trong package `credit_risk` để test được bằng pytest mà không cần Airflow.

## Consequences

- **Tích cực:** DAG graph + UI giúp demo và chấm điểm; retry/timeout/SLA có sẵn; lịch sử chạy là evidence; branch logic rõ ràng.
- **Tiêu cực:** Airflow nặng (webserver, scheduler, metadata DB) → đặt trong compose **profile `orchestration`** để có thể tắt trên máy yếu; thêm một image cần build.
- **Vận hành:** DAG phải parse không lỗi (`airflow dags list-import-errors`) — kiểm tra trong CI; task failure → callback alert; metadata DB dùng Postgres chung (database riêng).
- **Khả năng đảo ngược:** dễ đảo ngược — task chỉ gọi hàm thuần trong `credit_risk.*`, đổi orchestrator không phải viết lại logic.

## Alternatives considered

| Phương án | Ưu điểm | Nhược điểm | Lý do không chọn |
|---|---|---|---|
| cron + shell script | Nhẹ, có sẵn trên Ubuntu | Không có dependency/branching, retry, UI, lịch sử; lỗi im lặng | Không quan sát được, khó chứng minh vòng lặp khép kín |
| Prefect | API Python hiện đại, nhẹ hơn Airflow | Self-hosted cần chạy Prefect server riêng, một số tính năng (automation, RBAC) gắn với Prefect Cloud; hệ sinh thái operator/provider nhỏ hơn | Airflow đã đáp ứng đủ branching/retry/lịch/UI và chạy hoàn toàn self-hosted; đổi sang Prefect không thêm năng lực cần thiết |
| Dagster | Asset-based lineage tốt | Mô hình asset khác với luồng task tuần tự của pipeline | 3 DAG dạng task tuần tự không cần lineage theo asset; lợi ích không bù chi phí chuyển đổi |
| Kubeflow Pipelines | Chuẩn ML trên K8s | Bắt buộc Kubernetes (xem ADR-0005) | Over-engineering |
| APScheduler trong API | Không thêm service | Trộn orchestration vào serving, khó scale/observe | Vi phạm tách trách nhiệm |
