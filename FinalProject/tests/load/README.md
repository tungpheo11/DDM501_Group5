# Load tests

Kịch bản Locust ([`locustfile.py`](locustfile.py)) cho API chấm điểm: 20 phần `POST /api/v1/predict`, 2 phần
`POST /api/v1/predict/batch` (10 hồ sơ), 1 phần `GET /health/ready`; mỗi user nghỉ 0.1–0.5 s giữa hai request. Hồ sơ
được sinh ngẫu nhiên trong miền giá trị của tập UCI.

```bash
make test-load                                         # 10 user, 60 s, kiểm tra 0 lỗi + p95 /predict <= 100 ms
LOAD_USERS=20 LOAD_DURATION=120s make test-load        # stress
locust -f tests/load/locustfile.py --host http://localhost:18020   # web UI http://localhost:8089
```

`make test` bỏ qua nhóm này. Locust chạy trong subprocess (Locust monkey-patch thư viện chuẩn bằng gevent khi import).
Kết quả ghi vào `reports/load/`: `locust_report.html`, `locust_stats.csv`, `locust_summary.json`, `locust_output.txt`.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LOAD_USERS` | 10 | Số user đồng thời |
| `LOAD_SPAWN_RATE` | 10 | User khởi tạo mỗi giây |
| `LOAD_DURATION` | 60s | Thời gian chạy |
| `LOAD_P95_MS` | 100 | SLO p95 của `/api/v1/predict` |
| `E2E_API_URL` | `http://localhost:$API_PORT` | API đích |

Load test tăng dần để kích hoạt `HighLatencyP95` (32 luồng × 180 s, kết hợp `make chaos-latency`) vẫn chạy bằng
`make simulate SCENARIO=load`, xem Kịch bản 7 trong
[`docs/guides/scenario-simulation.md`](../../docs/guides/scenario-simulation.md).
