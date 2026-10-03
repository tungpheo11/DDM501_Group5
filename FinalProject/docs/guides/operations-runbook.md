# Operations runbook

Sổ tay vận hành hằng ngày cho stack Credit Risk: kiểm tra định kỳ, quy trình xử lý sự cố, troubleshooting theo thành
phần. Xử lý **theo từng alert** (ý nghĩa, cách kích hoạt, cách resolve): [runbooks/alerts.md](../runbooks/alerts.md).
Diễn tập sự cố end-to-end: [scenario-simulation.md](scenario-simulation.md).

Lệnh dưới đây viết cho máy dev (`make …`, cổng `localhost`). Trên server production: chạy trong
`/opt/credit-risk/current` với `ENV_FILE=/opt/credit-risk/shared/.env`, UI nội bộ qua SSH tunnel
([ubuntu-deployment §7](ubuntu-deployment.md#7-tls-với-lets-encrypt)).

## 1. Vai trò

| Vai trò | Trách nhiệm | Kênh |
|---|---|---|
| On-call MLOps | Nhận alert critical, xử lý hạ tầng/serving, quyết định rollback ứng dụng | Telegram / webhook alert |
| Data scientist | Drift, retrain, quality gate, rollback model, fairness | Dashboard *ML Model*, *Data Drift* |
| Risk/business owner | Theo dõi tỉ lệ duyệt, expected loss; phê duyệt thay đổi ngưỡng quyết định | Dashboard *Business KPIs* |

Tên người cụ thể: xem [CONTRIBUTING.md](../../CONTRIBUTING.md#7-vai-trò-thành-viên).

## 2. Kiểm tra định kỳ

### Hằng ngày (~5 phút)

| # | Việc | Lệnh / nơi xem | Kỳ vọng |
|---|---|---|---|
| 1 | Toàn bộ service healthy | `make health` (server: `deploy.sh status`) | 15 service `healthy`/`exited (0)` |
| 2 | API sẵn sàng từ registry | `curl -s localhost:18020/health/ready \| jq .status` | `ready` (không phải `degraded`) |
| 3 | Staff portal sẵn sàng | `curl -s localhost:18030/health/ready \| jq '.status, .checks'` | `ready`; `degraded` = API chấm điểm không phản hồi, HTTP 503 `not_ready` = mất database portal |
| 4 | Alert đang firing | `make alerts`, Grafana *Infra & SLA* → *Firing alerts* | 0 alert |
| 5 | SLA 24h | *Infra & SLA*: uptime, success ratio, p95 | ≥ 99.5 %, ≥ 99 %, < 100 ms |
| 6 | Drift | *Data Drift*: drift share, max PSI, tuổi phân tích | share < 0.5, PSI < 0.10 (vàng 0.10–0.25), phân tích < 2 phút trước |
| 7 | Business | *Business KPIs*: approve/review/decline rate | Lệch < 10 điểm % so với tuần trước |
| 8 | Airflow | UI :18080 — `service_health_check`, `drift_monitoring` | Run gần nhất `success` |
| 9 | Backup đêm qua (server) | `backup.sh list`, `journalctl -u credit-risk-backup -n 20` | Có bản mới, exit 0 |

### Hằng tuần

- `make registry` — xác nhận `@champion`, `@previous_champion`; đọc lý do promote/reject của lần retrain gần nhất.
- Xem `reports/drift_summary.json` / HTML report mới nhất của drift monitor.
- `docker system df` và dung lượng `/var/backups` — dọn image cũ (`docker image prune -f`).
- Thử restore một bản backup lên môi trường thử (mỗi 2 tuần).

### Hằng tháng

- `make responsible-ai` trên dữ liệu có nhãn mới — so DI/DPD/EOD với [06 — Responsible AI](../06-responsible-ai.md).
- `make purge-logs` (xoá `inference_logs` > `RETENTION_DAYS`, mặc định 90) — tuân thủ chính sách lưu trữ.
- `make scan` (Trivy) trên image đang chạy; cập nhật base image nếu có CRITICAL.
- Xoay `API_KEYS` (mục 5).

## 3. Quy trình xử lý sự cố

| Mức | Ví dụ | Phản hồi | Khôi phục mục tiêu |
|---|---|---|---|
| **SEV-1** | `APIDown`, `ModelNotLoaded`, `HighErrorRate` | ≤ 15 phút | ≤ 1 giờ |
| **SEV-2** | `RetrainFailed`, `ModelServedFromFallback`, `HighLatencyP95`, `PredictionDistributionShift` | ≤ 1 giờ | ≤ 1 ngày làm việc |
| **SEV-3** | `DataDriftDetected`, `DriftMonitorDown`, `DriftAnalysisStale`, `AirflowDagImportErrors` | Trong ngày | ≤ 3 ngày |

1. **Xác nhận** — mở alert (Telegram/webhook/Alertmanager), đọc `summary`, `runbook_url`; kiểm tra trên Grafana.
2. **Giảm thiểu trước, điều tra sau** — ưu tiên: rollback ứng dụng (`deploy.sh rollback`), rollback model
   (`make rollback` + `model/reload`), restart service, bật lại dependency.
3. **Silence** alert đã biết trong lúc xử lý: Alertmanager UI → *Silence* (ghi người + lý do, tối đa 2 giờ).
4. **Điều tra** — log JSON theo `request_id`, metric, thay đổi gần nhất (release, model version, cấu hình).
5. **Xác nhận resolve** — alert chuyển `resolved` trên webhook (`make alerts`), dashboard về xanh.
6. **Postmortem** (SEV-1/2) trong 2 ngày: timeline, nguyên nhân gốc, action item; ghi vào `CHANGELOG.md` nếu có fix.

## 4. Troubleshooting theo thành phần

### API

```bash
make logs SERVICE=api                                           # log JSON, 1 dòng/request
docker compose -f deploy/compose/docker-compose.yml logs api | grep '"request_id": "req_…"'
curl -s -H "X-API-Key: $API_KEY" localhost:18020/api/v1/model/info | jq '.model_version, .source, .degraded'
curl -s -X POST -H "X-API-Key: $API_KEY" localhost:18020/api/v1/model/reload | jq .status
```

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| 503 `MODEL_UNAVAILABLE` | Không load được model (registry + artifact local đều lỗi) | Kiểm tra MLflow/MinIO, `model/reload`; `make chaos-restore` nếu đang diễn tập |
| `served_by: local_artifact` | MLflow không tới được lúc load | Bật MLflow → `model/reload` |
| p95 tăng | CPU thiếu, batch lớn, host quá tải | `docker stats`; giảm tải; tăng CPU limit / replica |
| Nhiều 401/403 | Client dùng key cũ | Panel *Auth failures*; thông báo client, kiểm tra `API_KEYS` |

### MLflow / Postgres / MinIO

```bash
curl -s localhost:15040/health                                  # OK
docker exec credit-risk-mlops-postgres-1 pg_isready -U mlops
docker exec credit-risk-mlops-postgres-1 psql -U mlops -d credit_mlops_db -c "select count(*) from inference_logs;"
curl -s localhost:19040/minio/health/live -o /dev/null -w '%{http_code}\n'   # 200
```

- MLflow OOM (1 GB limit): kiểm tra `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`.
- Postgres đầy đĩa: `make purge-logs`, `VACUUM FULL inference_logs`.
- MLflow/Postgres down: API vẫn phục vụ bằng model đang load/fallback, readiness `degraded` — xem
  [Kịch bản 9](scenario-simulation.md#kịch-bản-9--mlflow--postgres-down).

### Drift monitor

```bash
curl -s localhost:18085/health | jq .
curl -s -X POST localhost:18085/analyze | jq '.is_drifted, .drift_share, .max_psi, .prediction_psi, .reasons'
curl -s localhost:18085/reports | jq '.reports[0]'            # HTML report Evidently mới nhất (/reports/<name>)
```

- `current_samples < 50`: chưa đủ traffic, drift không được đánh giá (không phải lỗi).
- Stale: mất kết nối DB → kiểm tra `DATABASE_URL`, Postgres; restart `drift-monitor`.

### Airflow

```bash
make dags-check                                                 # DAG import không lỗi
docker exec credit-risk-mlops-airflow-scheduler-1 airflow dags list-import-errors
docker exec credit-risk-mlops-airflow-scheduler-1 airflow dags list-runs -d model_retrain -o table
```

- Retrain fail: xem log task trong UI (`train_challenger`, `quality_gate`, `promote_champion`, `reload_api`,
  `rollback_champion`); champion không đổi khi fail.
- Trigger tay: `make retrain-dag REASON="manual"`, `make drift-dag`.

### Prometheus / Alertmanager / Grafana

```bash
curl -s localhost:19090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health}'
curl -s localhost:19093/api/v2/alerts | jq '.[].labels.alertname'
curl -s localhost:19095/alerts | jq '.[-5:]'                   # 5 notification gần nhất của webhook
```

- Không nhận Telegram: token/chat id trong `.env`, log `alertmanager`; webhook vẫn phải nhận.
- Dashboard trống: target `down` hoặc chưa có traffic.

## 5. Thao tác thường gặp

| Việc | Lệnh |
|---|---|
| Retrain thủ công | `make retrain` (host) hoặc `make retrain-dag` (Airflow) |
| Promote version cụ thể | `.venv/bin/python scripts/manage_registry.py promote <version> --reason "…"` rồi `model/reload` |
| Rollback model | `make rollback` (hoặc `VERSION=<n>`) chỉ đổi alias → sau đó `POST /api/v1/model/reload` |
| Rollback ứng dụng | `deploy.sh rollback` ([ubuntu-deployment §11](ubuntu-deployment.md#11-rollback)) |
| Đổi ngưỡng quyết định | `REVIEW_THRESHOLD` / `DECLINE_THRESHOLD` trong `.env` → `docker compose up -d api` (cần business owner duyệt) |
| Xoay API key | Thêm key mới vào `API_KEYS=new,old` → `up -d api` → client chuyển → bỏ `old` → `up -d api` |
| Bật Telegram | Điền `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` → `docker compose up -d alertmanager` |
| Xoá log cũ | `make purge-logs RETENTION_DAYS=90` |
| Backup / restore | `deploy/ubuntu/backup.sh backup` / `restore <dir>` ([ubuntu-deployment §9](ubuntu-deployment.md#9-backup--restore)) |
| Reset môi trường dev | `make down-v && make up` |
