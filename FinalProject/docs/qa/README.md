# QA — kế hoạch và kết quả kiểm thử hệ thống

> Kế hoạch kiểm thử thủ công trên hệ thống chạy thật; cột kết quả được điền khi thực hiện. Tài liệu đầu vào: [local-quickstart](../guides/local-quickstart.md),
> [ubuntu-deployment](../guides/ubuntu-deployment.md), [scenario-simulation](../guides/scenario-simulation.md),
> [operations-runbook](../guides/operations-runbook.md), [API reference](../04-api-reference.md).

## 1. Phạm vi

| Hạng mục | Nguồn kịch bản | Tự động hoá |
|---|---|---|
| Cài đặt local (macOS/Linux) từ máy sạch | local-quickstart §1–4 | — |
| Triển khai Ubuntu 22.04/24.04 (VM) | ubuntu-deployment §2–13 | `deploy.sh smoke` |
| 11 kịch bản vận hành | scenario-simulation | `make simulate`, `make chaos-*` |
| API contract (2xx/4xx/5xx) | API reference §2–4 | `tests/integration/` |
| Load test | Kịch bản 7 | `make simulate SCENARIO=load` |
| End-to-end | drift → retrain → promote → rollback | `make simulate SCENARIO=drift`, `make retrain-dag`, `make rollback` |

## 2. Test case

| ID | Mô tả | Bước | Kết quả mong đợi | Kết quả thực tế | Trạng thái | Người test | Ngày |
|---|---|---|---|---|---|---|---|
| QA-01 | Quickstart trên máy sạch | local-quickstart §2–4 | 15 service healthy, predict 200 | | | | |
| QA-02 | Kịch bản 1 — Ngày bình thường | scenario-simulation §1 | Không alert, PSI < 0.1 | | | | |
| QA-03 | Kịch bản 2 — Drift → retrain | §2 | `DataDriftDetected`, `model_retrain` chạy | | | | |
| QA-04 | Kịch bản 3 — Promote không downtime | §3 | 0 lỗi khi reload | | | | |
| QA-05 | Kịch bản 4 — Retrain trượt gate | §4 | `RetrainFailed`, champion giữ nguyên | | | | |
| QA-06 | Kịch bản 5 — Rollback model | §5 | Về version trước, 0 lỗi | | | | |
| QA-07 | Kịch bản 6 — API down | §6 | `APIDown` → resolved | | | | |
| QA-08 | Kịch bản 7 — Latency spike | §7 | `HighLatencyP95` | | | | |
| QA-09 | Kịch bản 8 — Input sai / thiếu key | §8 | 401/403/413/422 chuẩn; `HighErrorRate` với 5xx | | | | |
| QA-10 | Kịch bản 9 — MLflow/Postgres down | §9 | Readiness `degraded`, vẫn chấm điểm | | | | |
| QA-11 | Kịch bản 10 — Tấn công | §10 | `PredictionDistributionShift` | | | | |
| QA-12 | Kịch bản 11 — Fairness | §11 | DI/DPD/EOD như bảng | | | | |
| QA-13 | Deploy Ubuntu VM | ubuntu-deployment §13 | Checklist nghiệm thu đạt | | | | |
| QA-14 | Backup / restore | ubuntu-deployment §9 | Dữ liệu giữ nguyên, API `ready` | | | | |

## 3. Lỗi phát hiện

| ID | Mức | Mô tả | Bước tái hiện | Owner | Trạng thái |
|---|---|---|---|---|---|
| | | | | | |

## 4. Kết luận

_(Người test điền: tổng số case, pass/fail, rủi ro còn lại, đề xuất go/no-go.)_
