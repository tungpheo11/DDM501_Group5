# E2E tests

Test end-to-end chạy trên stack Compose thật (`make up`), đánh dấu `@pytest.mark.e2e`. `make test` bỏ qua nhóm này;
chạy riêng bằng:

```bash
make test-e2e          # = pytest tests/e2e -m e2e
```

Endpoint và credential đọc từ `.env` (biến `API_PORT`, `API_KEYS`, `GRAFANA_ADMIN_*`, `AIRFLOW_ADMIN_*`…), có thể ghi
đè bằng tiền tố `E2E_` (ví dụ `E2E_API_URL=https://api.example.com`). API không truy cập được thì cả nhóm tự skip; một
service tuỳ chọn (profile chưa bật) không chạy thì test tương ứng skip.

| Nhóm | Kiểm tra |
|---|---|
| Serving API | readiness đủ 3 check, contract `/predict` và `/predict/batch`, hồ sơ rủi ro cao bị `DECLINE`, lỗi 401/403/422/413 theo error contract, 422 không echo giá trị input, `/metrics` |
| Model registry | API phục vụ đúng version đang gắn alias `@champion` trong MLflow |
| Drift monitor | reference đã nạp, `POST /analyze` trả kết quả hợp lệ, report HTML Evidently truy cập được |
| Monitoring | Prometheus scrape `credit-risk-api` và `drift-monitor`, nạp đủ 11 alert rule; Alertmanager `ready` và có receiver webhook; Grafana có 4 dashboard |
| Orchestration | Airflow có 3 DAG, không có import error |

Luồng drift → retrain → promote → rollback được kiểm chứng bằng các kịch bản trong
[`docs/guides/scenario-simulation.md`](../../docs/guides/scenario-simulation.md) (kết quả trong `reports/simulations/`)
và bảng test case [`docs/qa/test-cases.md`](../../docs/qa/test-cases.md).
