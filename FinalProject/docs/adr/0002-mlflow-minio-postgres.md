# ADR-0002: MLflow Tracking + Model Registry với PostgreSQL (backend store) và MinIO (artifact store)

## Context

Rubric yêu cầu experiment tracking, model versioning, lineage và cơ chế champion/challenger. Vòng lặp khép kín (drift → retrain → promote → hot reload) cần một **registry có alias** để API luôn load "model đang được phép phục vụ" mà không hard-code version. Ràng buộc:

- Chạy hoàn toàn self-hosted trên laptop và Ubuntu VM (không phụ thuộc cloud trả phí).
- Nhiều process ghi đồng thời (training script, Airflow task, API đọc) → file store local không an toàn.
- Artifact (model pickle, report) cần storage kiểu object store để mô phỏng production (S3).

## Decision

- **MLflow server** (container dùng chung image API) với `--backend-store-uri postgresql://…` và `--default-artifact-root s3://mlflow/`.
- **PostgreSQL 16** làm backend store (đồng thời chứa bảng `inference_logs` của API — có thể tách database/schema riêng khi tải tăng).
- **MinIO** làm S3-compatible artifact store; bucket tạo bởi job `minio-init`.
- Registry dùng **alias `@champion`** (không dùng stage đã deprecated). Code: `credit_risk.training.registry.log_model_run()` log params/metrics/signature, register version và chuyển alias khi thắng quality gate.
- Training vẫn chạy được **offline**: nếu tracking server không reachable, model vẫn lưu `models/*.joblib` và API fallback về artifact local.

## Consequences

- **Tích cực:** lineage đầy đủ (run → version → alias); rollback model = đổi alias; UI so sánh run cho báo cáo; kiến trúc giống production (DB + object store).
- **Tiêu cực:** thêm 3 service (Postgres, MinIO, MLflow) → tốn RAM; credential MinIO/Postgres phải quản lý qua `.env` (xem `SECURITY.md`).
- **Vận hành:** backup = `pg_dump` + mirror bucket MinIO (script `deploy/ubuntu/backup.sh`); healthcheck `/health` của MLflow và `mc ready`; nếu MLflow down, API vẫn phục vụ bằng fallback local (readiness phản ánh nguồn model).
- **Khả năng đảo ngược:** khó đảo ngược một phần — dữ liệu run và registry nằm trong Postgres + MinIO, nên chuyển sang nền tảng tracking khác sẽ tốn công migrate.

## Alternatives considered

| Phương án | Ưu điểm | Nhược điểm | Lý do không chọn |
|---|---|---|---|
| MLflow file store + local artifacts | Zero setup | Không an toàn khi ghi đồng thời, không mô phỏng production | Không đạt mức "production-grade" |
| SQLite backend | Đơn giản | Lock khi nhiều writer (Airflow + API) | Rủi ro concurrency |
| Weights & Biases / Neptune | UI mạnh | SaaS, cần tài khoản/Internet, dữ liệu ra ngoài | Vi phạm yêu cầu self-hosted |
| DVC + Git tags cho model | Versioning tốt | Không có registry/alias runtime cho API | Không hỗ trợ hot reload theo alias |
| AWS S3 thật | Production thật | Chi phí + credential cloud | MinIO tương thích API S3, đổi endpoint là chuyển được |
