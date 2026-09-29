# QA — kiểm thử hệ thống

Tài liệu kiểm thử trên hệ thống chạy thật. Đầu vào: [local-quickstart](../guides/local-quickstart.md),
[ubuntu-deployment](../guides/ubuntu-deployment.md), [scenario-simulation](../guides/scenario-simulation.md),
[operations-runbook](../guides/operations-runbook.md), [API reference](../04-api-reference.md).

| Tài liệu | Nội dung |
|---|---|
| [test-plan.md](test-plan.md) | Phạm vi, chiến lược theo tầng (unit → load), môi trường, tiêu chí vào/ra, rủi ro |
| [test-cases.md](test-cases.md) | 17 test case `TC-001`…`TC-017`: tiền điều kiện, bước, kỳ vọng, kết quả thực tế, trạng thái, evidence |
| [test-report.md](test-report.md) | Kết quả tổng hợp, coverage, timeline alert firing → resolved, load test, triển khai Ubuntu, lỗi tìm được, verdict |
| [`evidence/`](evidence/) | Screenshot thật, tên `<TC-ID>_<mô-tả>.png` |

Báo cáo máy sinh: `reports/qa/` (coverage, timeline alert, log triển khai Ubuntu), `reports/load/` (Locust),
`reports/simulations/` (kết quả từng kịch bản).

Chạy lại bộ test tự động:

```bash
make lint          # ruff + black + mypy
make test-ci       # unit + integration + data quality + model validation, gate coverage 80 %
make alerts-test   # promtool + amtool
make test-e2e      # cần stack đang chạy (make up)
make test-load     # Locust headless, cần stack đang chạy
```
