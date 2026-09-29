# 04 — API reference

> Rubric **C. Implementation — Deployment (15%)** (API design: RESTful, documented, error handling, versioning) và
> **F. Documentation** (API docs: OpenAPI spec đầy đủ kèm ví dụ).
> Spec máy đọc được: [`openapi.yaml`](openapi.yaml) (sinh bằng `make openapi`, không sửa tay).
> Swagger UI: <http://localhost:18020/docs> · ReDoc: <http://localhost:18020/redoc>.
> Mọi response mẫu dưới đây lấy từ API thật (champion LR, registry version 1).

## 1. Quy ước chung

| Mục | Quy ước |
|---|---|
| Base URL | Local/Compose: `http://localhost:18020` · Production: `https://<API_DOMAIN>` qua Nginx ([Ubuntu guide](guides/ubuntu-deployment.md)) |
| Versioning | Prefix URL `/api/v1`; thay đổi phá vỡ contract ⇒ `/api/v2` chạy song song. Probe `/health/*`, `/metrics` không version |
| Auth | Header `X-API-Key` cho `/api/v1/*`. Server đọc danh sách key từ `API_KEYS` (phân tách dấu phẩy ⇒ xoay key không downtime), so sánh constant-time (`hmac.compare_digest`). Fail closed khi không cấu hình key |
| Content type | `application/json`, UTF-8 |
| Correlation | Gửi `X-Request-ID` để nối log; không gửi thì server sinh `req_<uuid>`. Luôn có trong response header và body |
| Input | Pydantic strict: `extra="forbid"` (field lạ ⇒ 422), miền giá trị UCI (xem §3) |
| Rate limit | Production: Nginx 20 req/s/IP, burst 40 ⇒ `429 TOO_MANY_REQUESTS`. Batch tối đa 500 chủ thẻ |
| Không auth | `/health/live`, `/health/ready`, `/metrics` (cho Docker/Prometheus/Airflow) — Nginx chặn `/metrics` từ Internet |

## 2. Endpoints

| Method | Path | Auth | Mô tả | Mã lỗi |
|---|---|---|---|---|
| `POST` | `/api/v1/predict` | ✔ | Chấm điểm 1 chủ thẻ realtime (yêu cầu tăng hạn mức, rút tiền mặt, chuyển trả góp trên app) | 401, 403, 422, 500, 503 |
| `POST` | `/api/v1/predict/batch` | ✔ | Chấm điểm tối đa 500 chủ thẻ (vectorized) cho rà soát hạn mức sau kỳ sao kê và cảnh báo sớm | 401, 403, 413, 422, 500, 503 |
| `POST` | `/api/v1/explain` | ✔ | Chấm điểm + SHAP top-5 đóng góp, cho chuyên viên rủi ro và adverse action notice | 401, 403, 422, 500, 503 |
| `GET` | `/api/v1/model/info` | ✔ | Metadata model đang phục vụ | 401, 403, 503 |
| `POST` | `/api/v1/model/reload` | ✔ | Hot reload `@champion` từ MLflow, không downtime | 401, 403, 503 |
| `GET` | `/health/live` | — | Liveness: process còn nhận HTTP | — |
| `GET` | `/health/ready` | — | Readiness: `ready` / `degraded` (200) / `not_ready` (503) | 503 |
| `GET` | `/metrics` | — | Prometheus exposition | — |

### 2.1 `POST /api/v1/predict`

```bash
export API_URL=http://localhost:18020
export API_KEY=$(grep -E '^API_KEYS=' .env | cut -d= -f2 | cut -d, -f1)

curl -s "$API_URL/api/v1/predict" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -H "X-Request-ID: doc-demo-1" \
  -d '{"LIMIT_BAL":200000,"SEX":2,"EDUCATION":1,"MARRIAGE":2,"AGE":35,
       "PAY_0":0,"PAY_2":0,"PAY_3":0,"PAY_4":0,"PAY_5":0,"PAY_6":0,
       "BILL_AMT1":50000,"BILL_AMT2":48000,"BILL_AMT3":46000,"BILL_AMT4":44000,"BILL_AMT5":42000,"BILL_AMT6":40000,
       "PAY_AMT1":5000,"PAY_AMT2":5000,"PAY_AMT3":5000,"PAY_AMT4":5000,"PAY_AMT5":5000,"PAY_AMT6":5000}'
```

```json
{
  "model_version": "1",
  "served_by": "mlflow_registry",
  "default_prediction": 0,
  "default_probability": 0.463411,
  "credit_score": 595,
  "credit_tier": "SUBPRIME",
  "risk_decision": "REVIEW",
  "recommended_limit_ntd": 100000.0,
  "top_risk_factors": [
    "Repayment Discipline: Timely and structured monthly repayments",
    "Conservative Debt Ratio: Low credit utilization of 25.0%"
  ],
  "policy_guardrails": {
    "age_verification": "PASS",
    "utilization_ceiling_check": "ACCEPTABLE",
    "delinquency_guardrail": "CLEAR"
  },
  "request_id": "doc-demo-1",
  "latency_ms": 29.78
}
```

| Field | Ý nghĩa |
|---|---|
| `default_probability` | PD của model (0–1) |
| `default_prediction` | `1` nếu PD > 0.5 (nhãn nhị phân của model class-weighted) |
| `risk_decision` | `APPROVE` (PD < 0.30) · `REVIEW` (0.30 ≤ PD < 0.60) · `DECLINE` (PD ≥ 0.60) — `configs/serving.yaml` |
| `credit_score` | `round(850 − PD × 550)`, kẹp trong 300–850 |
| `credit_tier` | `PRIME` ≥ 740 · `NEAR_PRIME` ≥ 670 · `SUBPRIME` ≥ 580 · `HIGH_RISK` |
| `recommended_limit_ntd` | Hạn mức đề xuất. APPROVE: `min(LIMIT_BAL × 1.25, 500 000)` (chấp thuận tăng / giữ) · REVIEW: `min(LIMIT_BAL × 0.5, 100 000)` (đề xuất hạ, chuyên viên quyết định) · DECLINE: 0 (tạm khoá hạn mức khả dụng; dư nợ hiện tại vẫn phải trả) |
| `top_risk_factors` | Lý do dạng rule-based dễ đọc cho chủ thẻ / chuyên viên rủi ro |
| `policy_guardrails` | Kiểm tra tuân thủ tất định: tuổi ≥ 18, utilization < 95 %, `PAY_0 ≤ 1` |
| `served_by` | `mlflow_registry` hoặc `local_artifact` (fallback khi MLflow down — readiness `degraded`) |

Mọi request thành công được ghi vào bảng `inference_logs` (Postgres) — nguồn dữ liệu cho drift monitor.

### 2.2 `POST /api/v1/predict/batch`

Body `{"cardholders": [<cardholder>, ...]}` (1–500 phần tử, mỗi phần tử là 23 field như §3). Thứ tự kết quả giữ
nguyên; mỗi item có id `<request_id>-<index>` trong inference log.

```bash
curl -s "$API_URL/api/v1/predict/batch" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"cardholders": [
        {"LIMIT_BAL":200000,"SEX":2,"EDUCATION":1,"MARRIAGE":2,"AGE":35,
         "PAY_0":0,"PAY_2":0,"PAY_3":0,"PAY_4":0,"PAY_5":0,"PAY_6":0,
         "BILL_AMT1":50000,"BILL_AMT2":48000,"BILL_AMT3":46000,"BILL_AMT4":44000,"BILL_AMT5":42000,"BILL_AMT6":40000,
         "PAY_AMT1":5000,"PAY_AMT2":5000,"PAY_AMT3":5000,"PAY_AMT4":5000,"PAY_AMT5":5000,"PAY_AMT6":5000},
        {"LIMIT_BAL":200000,"SEX":2,"EDUCATION":1,"MARRIAGE":2,"AGE":35,
         "PAY_0":0,"PAY_2":0,"PAY_3":0,"PAY_4":0,"PAY_5":0,"PAY_6":0,
         "BILL_AMT1":50000,"BILL_AMT2":48000,"BILL_AMT3":46000,"BILL_AMT4":44000,"BILL_AMT5":42000,"BILL_AMT6":40000,
         "PAY_AMT1":5000,"PAY_AMT2":5000,"PAY_AMT3":5000,"PAY_AMT4":5000,"PAY_AMT5":5000,"PAY_AMT6":5000}
      ]}'
```

> **Deprecated — field `applicants`.** Tên cũ `applicants` vẫn được nhận như alias của `cardholders` để client cũ không
> bị vỡ, cho cùng kết quả, và được đánh dấu `deprecated: true` trong [`openapi.yaml`](openapi.yaml). Client mới dùng
> `cardholders`. Chỉ gửi **một** trong hai field: request chứa cả `cardholders` lẫn `applicants` (hoặc thêm field lạ
> khác) bị `422 VALIDATION_ERROR`. Alias sẽ bị gỡ ở phiên bản API chính kế tiếp (`/api/v2`).

```json
{
  "model_version": "1",
  "served_by": "mlflow_registry",
  "request_id": "req_19d79380517a42d596801d03b9825600",
  "count": 2,
  "decision_summary": {"APPROVE": 0, "REVIEW": 2, "DECLINE": 0},
  "predictions": [
    {"index": 0, "request_id": "req_19d79380517a42d596801d03b9825600-0",
     "default_probability": 0.463411, "risk_decision": "REVIEW", "...": "các field như /predict"}
  ],
  "latency_ms": 9.04
}
```

### 2.3 `POST /api/v1/explain`

Cùng body với `/predict`. Trả thêm `method` (`shap_permutation`, degrade sang `reference_substitution` nếu SHAP lỗi),
`reference_probability` (PD của chủ thẻ trung vị tập train) và `contributions` top-5 theo độ lớn; tổng contributions ≈
`default_probability − reference_probability`. Không ghi vào inference log.

```json
{
  "method": "shap_permutation",
  "default_probability": 0.463411,
  "reference_probability": 0.438187,
  "contributions": [
    {"feature": "LIMIT_BAL", "value": 200000.0, "reference_value": 100000.0, "contribution": -0.060569, "direction": "decreases_risk"},
    {"feature": "PAY_AMT1", "value": 5000.0, "reference_value": 10823.0, "contribution": 0.036879, "direction": "increases_risk"},
    {"feature": "BILL_AMT5", "value": 42000.0, "reference_value": 25580.5, "contribution": 0.02229, "direction": "increases_risk"}
  ]
}
```

Chi phí: ~40 ms/request khi đã warm (240 model evaluations); request đầu sau khi load model chậm hơn (~0.8 s).

### 2.4 `GET /api/v1/model/info` và `POST /api/v1/model/reload`

```json
{
  "model_name": "credit-risk-model",
  "model_alias": "champion",
  "model_version": "1",
  "source": "mlflow_registry",
  "uri": "models:/credit-risk-model@champion",
  "run_id": "8e1790ed7fd649dc9c8b5d87297652df",
  "model_type": "LogisticRegression",
  "loaded_at": "2026-09-28T13:21:07.857115Z",
  "degraded": false,
  "feature_names": ["LIMIT_BAL", "AGE", "BILL_AMT1", "..."],
  "thresholds": {"review": 0.3, "decline": 0.6}
}
```

`/reload` idempotent, trả `{status, message, previous_version, model}`: `status=reloaded` khi thành công,
`unchanged_on_failure` khi load lỗi (model cũ tiếp tục phục vụ); chỉ 503 nếu không có model nào. Được gọi tự động
bởi `make retrain` và DAG `model_retrain` sau khi promote; sau `make rollback` (chỉ đổi alias) cần gọi tay.

### 2.5 Health probes

| Trạng thái `/health/ready` | HTTP | Khi nào |
|---|---|---|
| `ready` | 200 | Champion từ MLflow registry, MLflow + Postgres đều up |
| `degraded` | 200 | Đang phục vụ model fallback local, hoặc MLflow/Postgres down (vẫn chấm điểm được) |
| `not_ready` | 503 | Không có model nào được load |

```json
{"status":"ready","reasons":[],"checks":{"model":{"status":"ok","detail":"mlflow_registry version 1"},
 "mlflow":{"status":"ok","detail":null},"database":{"status":"ok","detail":null}}}
```

Kết quả probe dependency cache 10 s (`readiness_cache_seconds`). `/health/live` luôn trả
`{"status":"alive","version":"1.1.0"}` khi process chạy.

## 3. Schema input (`CreditPredictRequest`)

Một chủ thẻ sau kỳ sao kê gần nhất: 23 feature UCI, tất cả bắt buộc, không nhận field lạ:

| Field | Kiểu | Ràng buộc |
|---|---|---|
| `LIMIT_BAL` | float | Hạn mức hiện tại của thẻ; > 0, ≤ 10 000 000 (NT$) |
| `SEX` | int | 1 = nam, 2 = nữ |
| `EDUCATION` | int | 0–6 (1 sau đại học, 2 đại học, 3 THPT, 4 khác, 0/5/6 không rõ) |
| `MARRIAGE` | int | 0–3 (1 kết hôn, 2 độc thân, 3 khác, 0 không rõ) |
| `AGE` | int | 18–100 |
| `PAY_0`, `PAY_2`…`PAY_6` | int | −2…9 (−2 không dùng thẻ, −1 trả đủ, 0 revolving, n = trễ n tháng) |
| `BILL_AMT1`…`BILL_AMT6` | float | −10 000 000 … 10 000 000 (có thể âm) |
| `PAY_AMT1`…`PAY_AMT6` | float | 0 … 10 000 000 |

`SEX`/`AGE`/`MARRIAGE` chỉ dùng cho audit fairness; xem [Responsible AI](06-responsible-ai.md) về mitigation.

## 4. Error contract

Mọi response non-2xx có cùng schema `ErrorResponse`:

```json
{"code": "INVALID_API_KEY", "message": "The provided API key is not valid.", "details": null,
 "request_id": "req_4396e73f9bea4230994d48c6be32487c"}
```

| HTTP | `code` | Nguyên nhân | Client nên |
|---|---|---|---|
| 401 | `MISSING_API_KEY` | Thiếu header `X-API-Key` (kèm `WWW-Authenticate: ApiKey`) | Thêm key |
| 403 | `INVALID_API_KEY` | Key sai / đã thu hồi | Xin key mới |
| 404 | `NOT_FOUND` | Sai path | Kiểm tra `/api/v1` |
| 405 | `METHOD_NOT_ALLOWED` | Sai method | — |
| 413 | `BATCH_TOO_LARGE` | Batch > 500 (`details: {max_size, received}`) | Chia nhỏ batch |
| 422 | `VALIDATION_ERROR` | Sai kiểu/miền giá trị, thiếu field, field lạ | Sửa theo `details[]` |
| 429 | — (Nginx) | Vượt rate limit production | Retry với backoff |
| 500 | `INTERNAL_ERROR` | Lỗi không lường trước | Retry; báo kèm `request_id` |
| 503 | `MODEL_UNAVAILABLE` | Chưa có model nào được load | Retry sau; kiểm tra `/health/ready` |

`details[]` của 422 liệt kê từng field lỗi — **cố ý không echo lại giá trị input** để không rò dữ liệu chủ thẻ vào log:

```json
{"code": "VALIDATION_ERROR", "message": "Request validation failed.",
 "details": [
   {"field": "LIMIT_BAL", "message": "Input should be greater than 0", "type": "greater_than", "constraint": {"gt": "0.0"}},
   {"field": "SEX", "message": "Field required", "type": "missing"},
   {"field": "foo", "message": "Extra inputs are not permitted", "type": "extra_forbidden"}
 ],
 "request_id": "req_31fb6f30c5554876ab64d112acef4b32"}
```

Với `/predict/batch`, `field` là đường dẫn tới phần tử lỗi và **dùng đúng tên field client đã gửi**:
`cardholders.<index>.<FIELD>` khi gửi `cardholders`, `applicants.<index>.<FIELD>` khi còn dùng alias cũ. Ví dụ phần tử
thứ hai thiếu `AGE`:

```json
{"code": "VALIDATION_ERROR", "message": "Request validation failed.",
 "details": [{"field": "cardholders.1.AGE", "message": "Field required", "type": "missing"}],
 "request_id": "req_…"}
```

Gửi cả hai field trong cùng request: field thứ hai bị coi là field lạ, ví dụ
`{"field": "applicants", "message": "Extra inputs are not permitted", "type": "extra_forbidden"}`.

Mỗi lần auth thất bại tăng `credit_api_auth_failures_total{reason="missing"|"invalid"}`; tỉ lệ 5xx cao kích hoạt alert
`HighErrorRate` ([monitoring](05-monitoring-alerting.md)).

## 5. Client mẫu

```bash
.venv/bin/python scripts/sample_predict.py   # 1 chủ thẻ tốt + 1 chủ thẻ xấu (API_URL, API_KEY từ env)
make bench                                   # scripts/benchmark_latency.py: p95 /predict (fail nếu > 100 ms)
```

```python
import os
import requests

response = requests.post(
    f"{os.environ['API_URL']}/api/v1/predict",
    headers={"X-API-Key": os.environ["API_KEY"], "X-Request-ID": "limit-increase-42"},
    json=cardholder,  # dict 23 field như §3
    timeout=5,
)
if response.status_code == 422:
    for problem in response.json()["details"]:
        print(problem["field"], problem["message"])
response.raise_for_status()
print(response.json()["risk_decision"])
```

## 6. Hiệu năng

[`reports/latency_benchmark.json`](../reports/latency_benchmark.json): 1000 request tuần tự tới `/api/v1/predict` —
**p95 18.79 ms**, p99 24.17 ms, 0 lỗi; thời gian model phía server p95 8.77 ms. Mục tiêu NFR p95 < 100 ms
([problem statement](01-problem-statement.md)). Load test và giới hạn tài nguyên:
[scenario-simulation — Kịch bản 7](guides/scenario-simulation.md#kịch-bản-7--latency-spike--load-test).
