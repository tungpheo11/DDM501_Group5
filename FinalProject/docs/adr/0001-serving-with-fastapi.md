# ADR-0001: Serving model bằng FastAPI

## Context

Hệ thống cần một online scoring service cho bài toán Credit Default Risk: nhận dữ liệu hành vi của một chủ thẻ (23 feature của UCI dataset) khi chủ thẻ gửi yêu cầu tăng hạn mức trên app hoặc khi batch rà soát hạn mức chạy, trả về xác suất vỡ nợ, quyết định `APPROVE/REVIEW/DECLINE`, credit score, giải thích và guardrail. Yêu cầu phi chức năng:

- p95 latency < 100 ms cho một request (model RandomForest sklearn, in-process).
- Validation input chặt chẽ, trả lỗi 4xx rõ ràng; OpenAPI tự sinh để làm tài liệu + contract test.
- Export metrics cho Prometheus, health/readiness cho Docker healthcheck và Airflow `service_health_check`.
- Hot-reload model khi `@champion` đổi trên MLflow registry, không downtime.
- Team đã quen FastAPI từ lab/tutorial của môn học.

## Decision

Dùng **FastAPI + Uvicorn** làm serving layer, model sklearn load **in-process** (MLflow registry `models:/<name>@<alias>`, fallback artifact local `models/*.joblib`).

- App factory `credit_risk.serving.app.create_app()`; routes mỏng, logic nằm ở `decision_engine`, `responsible_ai.explanations`, `monitoring.metrics`, `serving.database`.
- Pydantic v2 schema (`serving/schemas.py`) là contract request/response; tên field giữ nguyên cột UCI (`LIMIT_BAL`, `PAY_0`…).
- `/metrics` dùng `prometheus_client` (không auth, chỉ mở trong mạng nội bộ).
- **API v1:** routers tách riêng trong `serving/routers/` — `POST /api/v1/predict`, `POST /api/v1/predict/batch`, `POST /api/v1/explain`, `GET /api/v1/model/info`, `POST /api/v1/model/reload`, `GET /health/live`, `GET /health/ready`. Endpoint cũ không version (`/predict`, `/reload-model`, `/health`) bị gỡ; mọi client trong repo đã chuyển sang v1. Thay đổi phá vỡ contract sau này đi qua `/api/v2`.
- **Error contract:** mọi response non-2xx có body `{code, message, details, request_id}`; lỗi validation không echo lại giá trị input (tránh lộ PII); lỗi 500 không lộ exception.
- **Request id:** middleware ASGI nhận `X-Request-ID` hợp lệ từ client hoặc sinh mới, trả lại trong header + body, gắn vào mọi log line.
- **Auth:** header `X-API-Key`, danh sách key trong `API_KEYS` (nhiều key để rotate không downtime), so sánh constant-time, fail closed khi bật auth mà không có key. Health và metrics không cần key.
- **Model state:** snapshot bất biến swap nguyên tử dưới lock; reload thất bại giữ model cũ (`unchanged_on_failure`). Nguồn local fallback ⇒ readiness `degraded` (200); không có model ⇒ `not_ready` (503).
- **Explain:** attribution kiểu *reference substitution* (thay từng feature bằng giá trị trung vị của tập train, 1 lần `predict_proba` vectorized). Về sau endpoint chuyển sang SHAP permutation và giữ reference substitution làm fallback — xem [06 — Responsible AI](../06-responsible-ai.md).
- **Observability:** log JSON một dòng (`LOG_FORMAT=json`), trường PII của UCI bị redact; metrics `credit_api_requests_total{method,endpoint,status}`, `credit_api_request_duration_seconds`, `credit_model_info`, `credit_model_loaded`, `credit_model_degraded`, `credit_model_reloads_total`, `credit_prediction_default_probability` cùng các metric nghiệp vụ có sẵn.

## Consequences

- **Tích cực:** OpenAPI + Swagger UI miễn phí; validation bằng type hints; async lifespan để init DB/model; test dễ bằng `TestClient` (không cần Docker).
- **Tiêu cực:** model chạy chung process với API → scale bằng nhân bản container (stateless), không tách GPU/inference server riêng; RandomForest predict là CPU-bound nên endpoint để sync (FastAPI chạy trong threadpool).
- **Vận hành:** image `deploy/docker/Dockerfile.api` (multi-stage, base pin version + digest, user non-root UID 10001, không có compiler/curl), HEALTHCHECK gọi `/health/ready` bằng Python stdlib; rollback model = chuyển alias MLflow về version cũ rồi gọi `POST /api/v1/model/reload`; rollback code = redeploy image tag trước.
- **Khả năng đảo ngược:** dễ đảo ngược — API contract được giữ ổn định, framework có thể thay mà không ảnh hưởng client vì mọi thứ nằm sau lớp `credit_risk.serving`.

## Alternatives considered

| Phương án | Ưu điểm | Nhược điểm | Lý do không chọn |
|---|---|---|---|
| Flask | Đơn giản, phổ biến | Không có validation/OpenAPI built-in, phải thêm marshmallow/flasgger | Tốn công hơn cho cùng kết quả |
| MLflow `models serve` | Không cần viết code serving | Không có business logic (decision, score, explain), khó thêm metrics/logging tuỳ biến | Không đáp ứng yêu cầu sản phẩm |
| BentoML / Seldon / KServe | Chuẩn hoá model serving, adaptive batching | Thêm một hệ sinh thái lớn; KServe cần Kubernetes (xem ADR-0005) | Over-engineering cho 1 model sklearn |
| TorchServe / Triton | Hiệu năng cao cho DL/GPU | Không phù hợp sklearn | Sai công cụ |
