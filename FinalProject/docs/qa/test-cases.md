# Danh Sách Test Cases — Hệ Thống Credit Default Risk Scoring

Tài liệu chi tiết các ca kiểm thử theo kế hoạch kiểm thử [test-plan.md](test-plan.md). Báo cáo thực thi và bằng chứng kết quả xem tại [test-report.md](test-report.md).

---

## Danh Mục Test Cases Nghiệm Thu

| Test ID | Tên Ca Kiểm Thử | Tầng Kiểm Thử | Mục Tiêu & Mô Tả | Điều Kiện & Dữ Liệu | Kết Quả Kỳ Vọng |
|---|---|---|---|---|---|
| **TC-001** | API Contract & Swagger UI Verification | Integration / API | Kiểm tra toàn bộ endpoint Swagger, docs OpenAPI, schema validation | Stack chạy, gọi `/docs` và `/api/v1/predict` | HTTP 200, hiển thị đầy đủ OpenAPI 3.1, schema Pydantic v2 đúng định dạng |
| **TC-002** | Normal Traffic Steady-State Baseline | E2E / Simulation | Chạy luồng giao dịch bình thường không drift trong 5 phút | `stream_normal.csv`, 100 req/s | PSI < 0.1, p95 latency < 50ms, 0 alerts firing, Grafana hiển thị xanh |
| **TC-003** | Data Drift Detection (GenZ Campaign) | Drift Monitor | Mô phỏng chiến dịch marketing GenZ làm lệch phân phối tuổi và hạn mức | `stream_drifted.csv`, chạy `simulate SCENARIO=drift` | PSI > 0.25 trên trường AGE/LIMIT_BAL, cảnh báo `DataDriftDetected` phát sinh |
| **TC-004** | MLflow Model Registry Aliases & Lineage | Model Registry | Xác minh mô hình Champion, Challenger, versioning và metadata | MLflow tracking server port 15040 | Gắn đúng alias `@champion`, lưu đủ run metrics, parameters và artifact lineage |
| **TC-005** | Airflow Closed-Loop Retraining & Quality Gate | Orchestration | Kích hoạt DAG retrain tự động; xác minh cơ chế chặn mô hình kém | DAG `model_retrain`, ngưỡng ROC-AUC > 0.76 | Nếu mô hình mới vượt gate: gán `@champion` mới; nếu trượt gate: báo động `RetrainFailed` |
| **TC-006** | Zero-Downtime Hot Reload & Promotion | Serving Engine | Kiểm tra khả năng tải lại model weights không gián đoạn dịch vụ | Endpoint `/api/v1/model/reload` | HTTP 200, 0 request bị rớt khi chuyển đổi giữa model versions |
| **TC-007** | Model Version Instant Rollback | Governance | Kiểm tra quy trình phục hồi về model phiên bản trước khi gặp sự cố | Script `make rollback` | Rollback thành công về model cũ, API serving cập nhật alias lập tức |
| **TC-008** | API Outage & Health Probes (Chaos Engineering) | Resilience | Giả lập tắt container API để kiểm tra alert và self-healing | Dừng container API hoặc chặn port | `APIDown` firing sau 1m, gửi tin nhắn Telegram, resolved khi bật lại |
| **TC-009** | Latency Spike & Concurrency Saturation | Performance | Đẩy tải đồng thời 50 workers kiểm tra cơ chế phân luồng | Locust load test 50-100 users | API chịu tải ổn định, p95 <= 100ms, không xuất hiện crash rò rỉ bộ nhớ |
| **TC-010** | Error Contract & Input Boundary Validation | Security / Validation | Kiểm tra bắt lỗi 401 (thiếu API Key), 422 (dữ liệu sai kiểu), 413 (batch quá lớn) | Gửi payload thiếu auth, sai AGE < 18 hoặc batch > 500 | Trả đúng JSON RFC 7807, không lộ thông tin nhạy cảm (PII) trong log |
| **TC-011** | Responsible AI Audit (Fairness & SHAP) | Responsible AI | Kiểm định công bằng theo nhóm nhân khẩu (Sex, Age, Education) | Chạy suite `make responsible-ai` | Disparate Impact > 0.80, tính năng SHAP waterfall giải thích tường minh từng hồ sơ |
| **TC-012** | Full Linux Ubuntu VM Deployment & Systemd | Infrastructure | Triển khai trên môi trường Ubuntu VM thông qua script cài đặt | Host Ubuntu 22.04 / 24.04, Nginx reverse proxy | Cài đặt tự động không lỗi, systemd quản lý dịch vụ, Nginx proxy an toàn |
| **TC-013** | Database & MinIO Automated Backup & Restore | Disaster Recovery | Kiểm tra script backup và restore toàn bộ dữ liệu database & S3 | `deploy/ubuntu/backup.sh` | Tạo file backup nén hợp lệ, restore toàn vẹn không mất mát trạng thái |
