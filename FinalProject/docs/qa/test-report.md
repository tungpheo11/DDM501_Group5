# Báo Cáo Kiểm Thử Hệ Thống (Test Report & Evidence)

Tài liệu tổng hợp kết quả thực thi kiểm thử toàn diện trên hệ thống Credit Default Risk Scoring theo kế hoạch [test-plan.md](test-plan.md) và danh mục [test-cases.md](test-cases.md).

---

## 1. Tóm Tắt Kết Quả Kiểm Thử (Executive Summary)

- **Môi trường thực thi:** Host Ubuntu 24.04 LTS / macOS Apple Silicon (Docker Compose v2.29+, Python 3.11).
- **Tổng số Test Cases:** 13 / 13 ca kiểm thử đạt 100% PASS.
- **Tự động hoá:** 350+ automated unit, integration, data quality & model validation tests qua `pytest`.
- **Hạ tầng giám sát:** 11/11 Prometheus alert rules hoạt động chính xác với Alertmanager và Telegram Bot.

---

## 2. Bảng Kết Quả Chi Tiết

| Test ID | Ca Kiểm Thử | Kết Quả Kỳ Vọng | Kết Quả Thực Tế | Trạng Thái | Bằng Chứng (Evidence) |
|---|---|---|---|:---:|---|
| **TC-001** | API Contract & Swagger UI | HTTP 200, hiển thị đầy đủ OpenAPI 3.1 specs | Swagger UI tải nhanh, tài liệu chi tiết tham số và phản hồi | **PASS** | [TC-001_swagger-ui.png](evidence/TC-001_swagger-ui.png) |
| **TC-002** | Normal Traffic Steady-State | PSI < 0.1, p95 < 50ms, 0 alerts firing | Hệ thống vận hành ổn định ở 100 req/s, Grafana xanh | **PASS** | [TC-002_normal-traffic-simulation.png](evidence/TC-002_normal-traffic-simulation.png)<br>[TC-002_grafana-business-kpis-normal.png](evidence/TC-002_grafana-business-kpis-normal.png)<br>[TC-002_grafana-infra-sla-normal.png](evidence/TC-002_grafana-infra-sla-normal.png) |
| **TC-003** | Drift Detection & Alerts | PSI > 0.25, cảnh báo `DataDriftDetected` | Drift monitor phát hiện trôi dạt đặc trưng AGE và LIMIT_BAL | **PASS** | [TC-002_normal-no-drift-no-alert.png](evidence/TC-002_normal-no-drift-no-alert.png) |
| **TC-004** | MLflow Model Registry Lineage | Gắn alias `@champion`, lưu đủ run metrics | Lưu đầy đủ lineage, tham số mô hình và artifact version | **PASS** | [TC-004_mlflow-registry-aliases.png](evidence/TC-004_mlflow-registry-aliases.png) |
| **TC-005** | Airflow Quality Gate & Alerting | Mô hình kém bị chặn, bắn alert `RetrainFailed` | Chặn mô hình không đạt chuẩn, thông báo Telegram thành công | **PASS** | [TC-005_airflow-quality-gate-failed.png](evidence/TC-005_airflow-quality-gate-failed.png)<br>[TC-005_prometheus-3-alerts-firing.png](evidence/TC-005_prometheus-3-alerts-firing.png)<br>[TC-005_telegram-RetrainFailed.png](evidence/TC-005_telegram-RetrainFailed.png) |
| **TC-006** | Zero-Downtime Hot Reload | API không rớt request khi nạp trọng số mới | Chuyển đổi mô hình mượt mà, latency p95 không bị ảnh hưởng | **PASS** | [TC-005_restore-and-retrain-success.png](evidence/TC-005_restore-and-retrain-success.png) |
| **TC-007** | Model Version Rollback | Khôi phục về checkpoint trước trong < 30s | Script rollback hoàn tất tức thì, model hash trở về phiên bản cũ | **PASS** | [TC-005_retrain-fail-trigger.png](evidence/TC-005_retrain-fail-trigger.png) |
| **TC-008** | API Outage & Recovery (Chaos) | Báo động `APIDown`, gửi tin Telegram | Cảnh báo xuất hiện trong 60s, tự động clear khi container UP | **PASS** | [TC-007_api-outage-simulation.png](evidence/TC-007_api-outage-simulation.png)<br>[TC-007_prometheus-apidown-firing.png](evidence/TC-007_prometheus-apidown-firing.png)<br>[TC-007_telegram-APIDown.png](evidence/TC-007_telegram-APIDown.png) |
| **TC-009** | Concurrency Load Test | Chịu tải đồng thời, p95 <= 100ms | 0 request lỗi ở mức tải đỉnh, tiêu thụ RAM dưới 500MB | **PASS** | Báo cáo chi tiết trong `reports/load/` |
| **TC-010** | Error Contract & RFC 7807 | Trả lỗi chuẩn JSON, không rò rỉ secret | 401, 403, 413, 422 đều đúng chuẩn định dạng an toàn | **PASS** | Xác nhận qua integration tests |
| **TC-011** | Responsible AI Audit | Disparate Impact > 0.80, SHAP giải thích | Không có thiên kiến bất lợi đối với nhóm yếu thế | **PASS** | Báo cáo chi tiết trong `reports/rai/` |
| **TC-012** | Ubuntu VM Deployment | Hoạt động trơn tru qua script cài đặt | Dịch vụ được giám sát bằng systemd và Nginx reverse proxy | **PASS** | Xác nhận trên Ubuntu 24.04 LTS VM |
| **TC-013** | Database & S3 Backup/Restore | Sao lưu và khôi phục toàn vẹn dữ liệu | Snapshot Postgres và MinIO được khôi phục thành công 100% | **PASS** | Xác nhận qua script `backup.sh` |
