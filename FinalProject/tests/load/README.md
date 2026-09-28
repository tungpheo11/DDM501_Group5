# Load tests

Thư mục dành cho Locust scenario phân tán cho `/api/v1/predict` (ramp-up, đo p95 latency/throughput), đánh dấu
`@pytest.mark.load` hoặc chạy qua `locust -f`.

Load test một máy hiện chạy bằng `make simulate SCENARIO=load` (32 luồng × 180 s, đo p50/p95/p99 và throughput); báo cáo
JSON lưu ở `reports/simulations/`. Xem Kịch bản 7 trong
[`docs/guides/scenario-simulation.md`](../../docs/guides/scenario-simulation.md).
