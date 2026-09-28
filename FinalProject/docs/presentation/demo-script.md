# Kịch bản demo trực tiếp (~4 phút)

> Dùng cho slide **08 · Live demo** của [deck](index.html). Mọi dữ liệu là dữ liệu mô phỏng (`data/processed/stream_*.csv` từ dataset công khai UCI + persona sinh ngẫu nhiên) — không có dữ liệu khách hàng thật.
> Tất cả lệnh chạy trong `FinalProject/`. Bí mật (API key, mật khẩu Grafana) lấy từ `.env`, **không** gõ hay chiếu lên màn hình.

## 1. Phân vai

| Vai | Việc | Thành viên |
|---|---|---|
| **Presenter** | Nói, chỉ vào dashboard, giữ nhịp thời gian | Thịnh |
| **Driver** | Gõ lệnh ở terminal, chuyển tab trình duyệt | Tùng |
| **Observer** | Theo dõi `make alerts` và Airflow ở màn hình phụ; báo "fallback" nếu một bước quá 30 giây | Hoa |
| **ML walkthrough** | Trình bày MLflow (runs, registry `@champion`), giải thích quality gate khi retrain/rollback | Hòa |

## 2. Chuẩn bị (T-30 → T-5 phút)

| Khi nào | Lệnh / thao tác | Kỳ vọng |
|---|---|---|
| T-30 | `make up` (hoặc `make health` nếu stack đã chạy) | Bảng service, tất cả `healthy`; 3 job one-shot `exited (0)` |
| T-25 | `make simulate SCENARIO=normal SIM_ARGS="--count 1500"` | `0 errors`, `drifted=False`; dashboard có dữ liệu 30 phút gần nhất |
| T-20 | `make registry` | `"champion": "1"` (hoặc version hiện tại) — ghi lại số này |
| T-20 | Airflow → DAG `model_retrain`: kiểm tra **không** có run nào trong 60 phút qua | Nếu có, bước 4 dùng `make retrain-dag` thay vì chờ drift trigger (cooldown 60 phút) |
| T-15 | `make alerts` | `Prometheus alerts: none` (nếu còn `DataDriftDetected`/`RetrainFailed` từ lần tập: chạy `make simulate SCENARIO=normal` và `make retrain-dag`, chờ resolve) |
| T-10 | Mở 6 tab, đăng nhập sẵn | xem danh sách dưới |
| T-5 | Terminal font ≥ 20 pt, nền tối; tắt thông báo hệ điều hành | |

Tab trình duyệt (theo thứ tự):

1. Grafana Infra & SLA — `http://localhost:13000/d/credit-infra-sla?orgId=1&from=now-30m&to=now&kiosk`
2. Grafana Drift — `http://localhost:13000/d/credit-drift?orgId=1&from=now-30m&to=now&kiosk`
3. Grafana ML model — `http://localhost:13000/d/credit-ml-model?orgId=1&from=now-30m&to=now&kiosk`
4. Airflow — `http://localhost:18080` (DAGs → `model_retrain`, chế độ Graph)
5. Swagger — `http://localhost:18020/docs` (đã bấm **Authorize** với API key)
6. MLflow — `http://localhost:15040` (Models → `credit-risk-model`), dùng ở cảnh 3–4

> Kiosk mode (`&kiosk`) ẩn sidebar Grafana để tiêu đề stat không bị cắt ở màn hình 1440 px.

## 3. Kịch bản

| # | Thời gian | Cảnh |
|---|---|---|
| 1 | 0:00–0:35 | Hệ thống sống + một lần chấm điểm |
| 2 | 0:35–1:40 | Dữ liệu lệch → drift |
| 3 | 1:40–2:50 | Retrain qua quality gate |
| 4 | 2:50–3:30 | Quality gate chặn model kém |
| 5 | 3:30–4:00 | (tuỳ thời gian) Sự cố API → alert → phục hồi |

### Cảnh 1 — Hệ thống sống (0:00–0:35)

**Driver**

```bash
.venv/bin/python scripts/sample_predict.py
```

Script tự đọc API key từ biến môi trường; chạy sau `set -a; . ./.env; set +a` ở terminal đã chuẩn bị.

**Kỳ vọng**

```text
Readiness: 200            "status": "ready"
--- Sending Low Risk Customer Request ---
Status: 200  "served_by": "mlflow_registry"  "default_probability": 0.36268  "risk_decision": "REVIEW"
--- Sending High Risk Customer Request ---
Status: 200  "default_probability": 0.993469  "credit_score": 304  "risk_decision": "DECLINE"
```

**Presenter:** "API phục vụ model từ MLflow registry, trả xác suất, điểm 300–850 và quyết định 3 mức. Hồ sơ rủi ro trung bình rơi vào REVIEW để người duyệt xem." → chuyển **tab 1** (Infra & SLA): Scoring API UP, p95 vài chục ms, 0 alert firing.

### Cảnh 2 — Dữ liệu lệch (0:35–1:40)

**Driver**

```bash
make simulate SCENARIO=drift SIM_ARGS="--count 600"
```

**Kỳ vọng** (~20–30 s)

```text
==> Gen-Z campaign (stream_drifted.csv + campaign personas): 600 requests, concurrency …
    …/600 sent
==> drift analysis: drifted=True share=… prediction_psi=… top_psi=[('AGE', …), …]
Report: reports/simulations/drift_<timestamp>.json
Next: DataDriftDetected fires after ~2 min (make alerts); `make drift-dag` triggers model_retrain. Resolve with `make simulate SCENARIO=normal`.
```

→ **tab 2** (Drift): *Dataset drift* chuyển **DRIFT** (đỏ), *Max key-feature PSI* vượt 0.25, bảng *Drifted features* liệt kê các cột (AGE đứng đầu).

**Presenter:** "Chiến dịch hướng tới khách hàng trẻ làm phân phối tuổi lệch khỏi dữ liệu train (train chỉ có khách ≥ 30 tuổi). PSI ≥ 0.25 là ngưỡng drift nặng. Alert DataDriftDetected sẽ firing sau 2 phút — chúng ta quay lại xem."

### Cảnh 3 — Retrain qua quality gate (1:40–2:50)

**Driver** (chọn một)

```bash
make drift-dag      # đường chuẩn: drift_monitoring → check_retrain_cooldown → trigger_model_retrain
make retrain-dag    # dùng khi đã có run model_retrain trong 60 phút qua (cooldown)
```

→ **tab 4** (Airflow): DAG `model_retrain` chạy `train_challenger → quality_gate → decide_promotion` (~15 s trung vị trên máy dev).

```bash
make registry
```

**Kỳ vọng:** `"challenger": "<n+1>"`; hoặc

- `"champion": "<n+1>"` — challenger tốt hơn: `promote_champion → reload_api → refresh_drift_reference → notify`, **tab 3** hiện *Last retrain run* **OK** và *Last promoted version* = n+1; hoặc
- `"champion": "<n>"` giữ nguyên — nhánh `keep_champion`: challenger không tốt hơn champion theo `PromotionPolicy`.

**ML walkthrough:** chuyển **tab 6** (MLflow), chỉ alias `@champion` / `@challenger` và run vừa train, rồi nói: "Cả hai kết quả đều đúng thiết kế: hệ thống chỉ promote khi challenger đạt floor ROC-AUC 0.70, không tụt quá 0.005 và expected loss không tệ hơn. Nếu API không nạp đúng version mới, `rollback_champion` trả alias về bản cũ."

### Cảnh 4 — Quality gate chặn model kém (2:50–3:30)

**Driver**

```bash
make retrain-fail   # model_retrain với min_roc_auc = 0.99
```

→ **tab 4**: task `quality_gate` đỏ (`Quality gate failed: ROC-AUC 0.7x < floor 0.9900 … champion unchanged`), các task promote bị skip.

```bash
make alerts
```

**Kỳ vọng:** trong ~30 s `RetrainFailed  firing`; **tab 3** *Last retrain run* = **FAILED**; `DataDriftDetected  firing` từ cảnh 2 cũng đã xuất hiện.

**ML walkthrough:** "Champion không đổi, người vận hành nhận alert kèm runbook. Không có model nào lên production mà chưa qua gate."

### Cảnh 5 — Sự cố và phục hồi (3:30–4:00, bỏ qua nếu trễ giờ)

```bash
make chaos-api-down
```

→ **tab 1**: *Scoring API* **DOWN** trong ≤ 15 s (scrape interval); `APIDown` firing sau 1 phút — **không chờ**, nói tiếp rồi:

```bash
make chaos-restore
```

→ *Scoring API* về **UP**, `/health/ready` = ready.

## 4. Dự phòng

| Sự cố | Dấu hiệu | Xử lý tại chỗ (≤ 30 s) |
|---|---|---|
| Grafana chậm / trống | Panel quay vòng > 10 s | Chuyển sang ảnh [`../assets/screenshots/grafana/after/`](../assets/screenshots/grafana/after/); kiểm tra `docker stats` Grafana (giới hạn 768 MiB) sau buổi |
| `drifted=False` ở cảnh 2 | Window còn nhiều dữ liệu normal | Chạy lại với `SIM_ARGS="--count 1000"` hoặc chiếu `reports/simulations/drift_*.json` gần nhất |
| `make drift-dag` không trigger retrain | Task `check_retrain_cooldown` skip | Giải thích cooldown 60 phút (tính năng chống retrain liên tục) rồi chạy `make retrain-dag` |
| DAG kẹt ở `queued` | Airflow scheduler bận | Chuyển cảnh 4 trước; quay lại khi DAG chạy xong |
| API không trả lời | `sample_predict` timeout | `make chaos-restore`, rồi `make health`; trong lúc chờ chuyển sang slide Serving |
| Mất mạng Telegram | Không có tin nhắn | Không ảnh hưởng — `make alerts` đọc trực tiếp từ Prometheus và webhook receiver |

Quy tắc: không debug trước hội đồng. Quá 30 giây → Observer nói "fallback", Driver mở ảnh/log dự phòng, Presenter (hoặc ML walkthrough ở cảnh 3–4) tiếp tục thuyết minh.

## 5. Dọn dẹp sau demo

```bash
make chaos-restore
make simulate SCENARIO=normal SIM_ARGS="--count 1500"   # DataDriftDetected resolve sau ~2 phút
make retrain-dag                                        # run thành công đưa RetrainFailed về resolved
make alerts                                             # Prometheus alerts: none
```

## 6. Câu hỏi hay gặp khi demo

- **"Sao challenger không được promote?"** — dữ liệu retrain gần giống champion nên không vượt `PromotionPolicy`; đó là hành vi mong muốn (nhánh `keep_champion`, có thông báo `RetrainChampionKept`).
- **"Drift xử lý thế nào nếu chỉ lệch output?"** — prediction shift (PSI output ≥ 0.25) chỉ alert `PredictionDistributionShift`, không retrain tự động, vì có thể là thay đổi tập khách hàng hợp lệ.
- **"Latency có bị retrain ảnh hưởng?"** — retrain chạy trong Airflow (container riêng); API chỉ hot-reload model qua `POST /api/v1/model/reload`.
