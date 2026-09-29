# ADR-0007: Capacity API — tối ưu hot path + nhiều worker process trong 1 container

## Context

NFR-01 yêu cầu p95 `POST /api/v1/predict` ≤ 100 ms (alert `HighLatencyP95`). Cấu hình ban đầu chạy **1 process uvicorn** trong
container giới hạn 2 CPU / 1 GB. Load test Locust (`tests/load/locustfile.py`, mix predict : batch(10) : readiness = 20 : 2 : 1)
cho thấy SLO bị vi phạm ở tải vừa phải, không cần chaos:

| Cấu hình (container 2 CPU, host 10 CPU arm64) | Locust user | rps (tổng) | p50 / p95 / p99 `/predict` (ms) |
|---|---|---|---|
| 1 worker, code ban đầu | 10 | ~30 | — / 53 / — |
| 1 worker, code ban đầu | 20 | 53.4 | 53 / **180** / 280 |
| 1 worker, feature engineering tối ưu | 20 | 56.6 | 34 / **140** / 240 |
| 2 worker, feature engineering tối ưu | 20 | 60.2 | 21 / **71** / 120 |
| 2 worker, feature engineering tối ưu | 30 | 88.4 | 22 / **86** / 180 |
| 2 worker, feature engineering tối ưu | 40 | 106.4 | 38 / 200 / 440 |
| 2 worker, bản triển khai (gunicorn + multiprocess metrics, `make test-load-stress`) | 20 | 61.8 | 14 / **31** / 54 |

Nguyên nhân gốc:

- Một request `/predict` tốn **~12 ms CPU** phía server (đo bằng `process_cpu_seconds_total` qua 400 request tuần tự).
  Khoảng 80 % nằm trong `Pipeline.predict_proba` cho **1 dòng**: overhead pandas của `FeatureEngineer` (5 lần `Series.clip`,
  dựng DataFrame, `concat`) và việc chọn cột / kiểm tra input của `ColumnTransformer`. Ghi inference log, logging JSON và
  Prometheus chỉ chiếm phần nhỏ.
- Toàn bộ chạy trong **1 process Python**: GIL khiến threadpool của FastAPI không dùng được CPU thứ hai. Ở ~56 rps process đó
  bận ~80 % thời gian; theo lý thuyết hàng đợi, p95 tăng theo `1 / (1 − ρ)` nên vượt 100 ms dù p50 vẫn thấp. Khi host bị tranh
  chấp CPU, cùng mức tải 10 user cũng đẩy p95 lên 660 ms.

Ràng buộc: model và các gauge Prometheus (`credit_model_loaded`, `credit_model_info`, rolling stats) là **trạng thái trong
process**; `POST /api/v1/model/reload` chỉ reload process nhận request. Mọi phương án nhiều process phải giữ đúng hai điều này.

## Decision

1. **Giảm CPU/request trên hot path, không đổi kết quả.** `engineer_features` clip bằng numpy và dựng DataFrame một lần.
   Kết quả giống hệt từng bit (đã so trên 15 000 dòng `train_baseline.csv`, các ca biên và `predict_proba` của cả hai model);
   `predict_proba` 1 dòng của champion LogisticRegression giảm từ ~5.6 ms xuống ~3.5–4 ms.
2. **Chạy N worker process trong container `api`** (gunicorn + `uvicorn_worker.UvicornWorker` từ gói `uvicorn-worker`, vì
   `uvicorn.workers` đã deprecated; `API_WORKERS`, mặc định 2 = giới hạn CPU), nâng giới hạn RAM của `api` lên **1.5 GB**
   (đo được ~705 MiB với 2 worker lúc vừa khởi động, ~890 MiB sau load 20 user; 1 worker ~370 MiB; cần chỗ cho reload/SHAP).
   Đi kèm:
   - **Prometheus multiprocess mode** (`PROMETHEUS_MULTIPROC_DIR` trên thư mục tạm, dọn khi container khởi động; `/metrics` dùng
     `MultiProcessCollector`; hook `child_exit` gọi `mark_process_dead`). Counter/histogram được cộng tự động nên recording rule
     và alert giữ nguyên. Gauge chọn chế độ gộp theo ý nghĩa: `credit_model_loaded` = `livemin` (1 worker mất model là alert),
     `credit_model_degraded` = `livemax`, `credit_model_info` = `livemax` (đặt series version cũ về 0 trước khi đổi, vì `clear()`
     không xoá giá trị trong file mmap), rolling gauges = `livemostrecent`.
   - **`process_cpu_seconds_total` / `process_resident_memory_bytes`** của job API là tổng master + worker (collector đọc `/proc`),
     để dashboard *Infra & SLA* không đổi query.
   - **Hội tụ version model giữa các worker:** reload thành công ghi một marker "generation" (ghi nguyên tử) vào thư mục dùng
     chung; worker khác thấy generation mới thì tự `load_champion()` ở nền. Reload thất bại không ghi marker, nên ngữ nghĩa
     `unchanged_on_failure` và "không hạ cấp registry → fallback" giữ nguyên trên từng worker.
   - **Pool DB theo worker** giảm để tổng kết nối không vượt quá bản 1 worker hiện tại (vd. `pool_size=5`, `max_overflow=5`).
3. **Capacity chính thức cho 1 container `api` (2 CPU, 2 worker): ~85 rps** với mix Locust ở trên và p95 ≤ 100 ms. Lập kế hoạch
   ở **≤ 70 rps** (giữ ~20 % headroom). `make test-load` có thêm mức stress 20 user làm regression gate.

## Consequences

- **Tích cực:** đạt SLO ở 20 user (~60 rps, p95 71 ms) mà không cần thêm hạ tầng; cổng API, target scrape Prometheus, alert và
  dashboard giữ nguyên; tối ưu feature engineering cũng làm training/batch nhanh hơn.
- **Tiêu cực / chi phí:** RAM `api` tăng ~350 MB mỗi worker; code metrics phức tạp hơn (multiprocess mode, chế độ gộp gauge);
  sau `POST /model/reload` có một cửa sổ ngắn (đo được ≤ 1.5 s) các worker phục vụ version khác nhau; khi một worker bị thay
  thế, `credit_model_loaded` = 0 khoảng 3 s trong lúc worker mới nạp model (ngắn hơn nhiều so với `for` của `ModelNotLoaded`);
  rolling gauges là xấp xỉ theo worker gần nhất thay vì cửa sổ toàn cục.
- **Vận hành:** scale dọc bằng `API_WORKERS` + `deploy.resources.limits.cpus` (giữ worker = CPU; nhiều worker hơn CPU chỉ tăng
  tranh chấp). Vượt 1 container thì scale ngang nhiều replica sau Nginx `upstream` (NFR-13): Prometheus scrape từng replica,
  và marker reload phải thay bằng poll alias MLflow định kỳ vì không có thư mục dùng chung giữa container. Rollback: đặt
  `API_WORKERS=1` (hành vi cũ, không cần build lại image).
- **Khả năng đảo ngược:** dễ. Bước 1 là refactor không đổi output; bước 2 bật/tắt bằng biến môi trường.

## Alternatives considered

| Phương án | Ưu điểm | Nhược điểm | Lý do không chọn |
|---|---|---|---|
| Chỉ tối ưu hot path, giữ 1 worker | Không đổi kiến trúc | Vẫn p95 140 ms ở ~56 rps; giới hạn bởi GIL | Không đạt SLO |
| `uvicorn --workers N` (không gunicorn) | Ít phụ thuộc | Không có hook `child_exit` để dọn file mmap của worker chết, gauge `live*` sai | Thiếu vòng đời worker |
| Nhiều replica `api` sau Nginx ngay bây giờ | Metric theo instance chuẩn Prometheus, không cần multiprocess mode | Thêm service Nginx, đổi cổng/scrape/dashboard/smoke test; blast radius lớn trên 1 host | Để dành cho bước scale ngang |
| Process pool chỉ cho inference | Metric/reload giữ trong 1 process | IPC mỗi request, phải dựng lại pool khi reload, process chính vẫn là nút thắt | Phức tạp hơn mà lợi ích thấp hơn |
| SIGHUP gunicorn khi reload | Mọi worker nạp lại đồng thời | Worker mới nạp từ đầu: MLflow lỗi thì hạ cấp xuống fallback, mất warm-up | Phá ngữ nghĩa reload an toàn |
| Đổi model sang ONNX / viết lại pipeline bằng numpy | Nhanh hơn nhiều | Artifact và quy trình train/registry thay đổi lớn | Không tương xứng với mức độ lỗi |
