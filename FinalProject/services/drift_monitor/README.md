# Drift monitor service

FastAPI + Evidently. So sánh `data/reference/` với N inference log mới nhất trong PostgreSQL; logic tính drift dùng lại `credit_risk.monitoring.drift`, service chỉ là lớp HTTP + scheduler.

| Endpoint | Mô tả |
|---|---|
| `GET /health` | Liveness + số mẫu reference |
| `POST /analyze` | Chạy một lần phân tích. Body `{"window_size": 500, "save_report": true}` (tuỳ chọn). Trả `status` = `success` / `skipped` (chưa đủ mẫu) / `error` |
| `GET /drift/latest` | Kết quả thành công gần nhất (404 nếu chưa có) |
| `GET /reference` | Mô tả cửa sổ reference |
| `POST /reference/refresh` | Chấm lại reference bằng champion hiện tại (sau khi promote) |
| `GET /reports`, `GET /reports/<file>` | Danh sách / nội dung báo cáo HTML Evidently đã lưu |
| `GET /metrics` | Metric Prometheus |

Metric chính: `credit_drift_detected`, `credit_drift_share`, `credit_drift_max_psi`, `credit_drift_feature_psi{feature}`, `credit_drift_drifted_features`, `credit_drift_prediction_psi`, `credit_drift_prediction_shift`, `credit_drift_current_samples`, `credit_drift_last_analysis_timestamp_seconds` (chỉ cập nhật khi phân tích thành công), `credit_drift_analyses_total{result}`.

Scheduler nội bộ chạy mỗi `DRIFT_ANALYSIS_INTERVAL_SECONDS`; Airflow DAG `drift_monitoring` gọi `/analyze` theo `DRIFT_MONITORING_SCHEDULE` và quyết định retrain.

```bash
curl -s -X POST localhost:18085/analyze -H 'Content-Type: application/json' -d '{"window_size": 300}' | jq '.status, .is_drifted, .max_psi'
```
