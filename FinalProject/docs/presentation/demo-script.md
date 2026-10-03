# Kịch bản demo trực tiếp (~4 phút 30 giây)

> Dùng cho phần **08 · Live demo** của [deck](index.html) (slide 17–19). Mọi dữ liệu là dữ liệu mô phỏng (`data/processed/stream_*.csv` từ dataset công khai UCI + persona sinh ngẫu nhiên, danh mục 200 chủ thẻ giả lập của Staff Portal) — không có dữ liệu chủ thẻ thật.
> Tất cả lệnh chạy trong `FinalProject/`. Bí mật (API key, mật khẩu Grafana, mật khẩu 3 tài khoản portal) lấy từ `.env`, **không** gõ hay chiếu lên màn hình.

Câu chuyện demo đi theo một vòng đời hạn mức, thao tác chính trên **Staff Portal** (`http://localhost:18030`): CSKH tiếp nhận yêu cầu tăng hạn mức của chủ thẻ (realtime) → chuyên viên rủi ro quyết định ca REVIEW và rà soát cả danh mục sau kỳ sao kê (batch) → quản trị hệ thống simulate nhóm chủ thẻ dưới 30 tuổi làm dữ liệu lệch (drift) → alert tới Telegram → hệ thống tự retrain nhưng chỉ đưa model lên khi qua quality gate.

## 1. Phân vai

| Vai | Việc | Thành viên |
|---|---|---|
| **Presenter** | Dẫn câu chuyện hạn mức, chỉ vào màn hình portal và dashboard, giữ nhịp thời gian | Thịnh |
| **Driver** | Thao tác 3 cửa sổ Staff Portal, gõ lệnh ở terminal, chuyển tab trình duyệt | Tùng |
| **Observer** | Theo dõi `make alerts`, Airflow và nhóm Telegram ở màn hình phụ/điện thoại; báo "Telegram đã nhận" và báo "fallback" nếu một bước quá 30 giây | Hoa |
| **ML walkthrough** | Giải thích SHAP ở màn hình chuyên viên, trình bày MLflow (runs, registry `@champion`) và quality gate khi retrain/rollback | Hòa |

## 2. Chuẩn bị (T-30 → T-5 phút)

| Khi nào | Lệnh / thao tác | Kỳ vọng |
|---|---|---|
| T-30 | `make up` (hoặc `make health` nếu stack đã chạy) | Bảng service, tất cả `healthy` (kể cả `staff-portal`); 3 job one-shot `exited (0)` |
| T-28 | `curl -s localhost:18030/health/ready` | `"status":"ready"`, `database` và `scoring_api` đều `up` |
| T-25 | `make simulate SCENARIO=normal SIM_ARGS="--count 1500"` | `0 errors`, `drifted=False`; dashboard có dữ liệu 30 phút gần nhất |
| T-20 | `make registry` | `"champion": "1"` (hoặc version hiện tại) — ghi lại số này |
| T-20 | Airflow → DAG `model_retrain`: kiểm tra **không** có run nào trong 60 phút qua | Nếu có, cảnh 4 dùng `make retrain-dag` thay vì chờ drift trigger (cooldown 60 phút) |
| T-15 | `make alerts` | `Prometheus alerts: none` (nếu còn `DataDriftDetected`/`RetrainFailed` từ lần tập: xem [§5](#5-dọn-dẹp-sau-demo), chờ resolve) |
| T-12 | Mở 3 cửa sổ trình duyệt **tách phiên** (Chrome profile chính, Chrome profile phụ, cửa sổ ẩn danh), mỗi cửa sổ đăng nhập một tài khoản: `cskh`, `chuyenvien`, `admin` | Góc phải hiện đúng tên: Nguyễn Thu Trang · Trần Minh Khoa · Lê Quốc Việt. Cùng một profile chỉ giữ được một phiên |
| T-10 | Cửa sổ `admin` → **Bảng điều khiển hệ thống** | *API chấm điểm* `ready`, *Model đang phục vụ* `@champion · version <n>`, *Drift monitor* **Không drift** |
| T-10 | Cửa sổ `cskh` → **Tra cứu chủ thẻ** → gõ `KH288012` | Thấy Hoàng Văn Trung (chủ thẻ ra REVIEW ở các lần tập với champion version 1) |
| T-10 | Mở các tab công cụ, đăng nhập sẵn | xem danh sách dưới |
| T-5 | Terminal font ≥ 20 pt, nền tối; tắt thông báo hệ điều hành; điện thoại Observer mở nhóm Telegram cảnh báo | |

Cửa sổ và tab (theo thứ tự dùng):

1. Portal `cskh` — `http://localhost:18030/cskh`
2. Portal `chuyenvien` — `http://localhost:18030/analyst`
3. Portal `admin` — `http://localhost:18030/admin`
4. Grafana Drift — `http://localhost:13000/d/credit-drift?orgId=1&from=now-30m&to=now&kiosk`
5. Grafana ML model — `http://localhost:13000/d/credit-ml-model?orgId=1&from=now-30m&to=now&kiosk`
6. Airflow — `http://localhost:18080` (DAGs → `model_retrain`, chế độ Graph)
7. MLflow — `http://localhost:15040` (Models → `credit-risk-model`), dùng ở cảnh 4–5
8. Grafana Infra & SLA — `http://localhost:13000/d/credit-infra-sla?orgId=1&from=now-30m&to=now&kiosk`, dùng ở cảnh 6

> Kiosk mode (`&kiosk`) ẩn sidebar Grafana để tiêu đề stat không bị cắt ở màn hình 1440 px. Grafana, MLflow, Airflow và Alertmanager cũng mở được từ khung **Công cụ vận hành** trên màn hình admin.

## 3. Kịch bản

| # | Thời gian | Cảnh | Ai nói chính |
|---|---|---|---|
| 1 | 0:00–0:40 | CSKH tiếp nhận yêu cầu tăng hạn mức (portal, realtime) | Thịnh |
| 2 | 0:40–1:25 | Chuyên viên rủi ro quyết định ca REVIEW và rà soát theo lô (portal, batch) | Hòa, Thịnh |
| 3 | 1:25–2:20 | Quản trị simulate nhóm chủ thẻ < 30 tuổi → drift → alert Telegram (portal) | Thịnh, Hoa |
| 4 | 2:20–3:15 | Retrain qua quality gate | Hòa |
| 5 | 3:15–3:50 | Quality gate chặn model kém | Hòa |
| 6 | 3:50–4:20 | (tuỳ thời gian) Sự cố API → alert → phục hồi | Thịnh |

### Cảnh 1 — CSKH tiếp nhận yêu cầu tăng hạn mức (0:00–0:40)

**Presenter** (mở cảnh, ~10 s): "Một chủ thẻ đang dùng thẻ gọi tổng đài xin tăng hạn mức. Nhân viên CSKH không cần biết API hay model: chị ấy mở Staff Portal, màn hình **Tra cứu chủ thẻ**."

**Driver** (cửa sổ 1, tài khoản `cskh`, ~20 s)

1. Ô **Từ khoá** đã có `KH288012` → bấm **Hoàng Văn Trung**.
2. Khung **Tạo yêu cầu của chủ thẻ**: giữ **Tăng hạn mức**, *Số tiền khách đề nghị* `300.000`, *Ghi chú* "Khách gọi tổng đài đề nghị tăng hạn mức."
3. Bấm **Gửi chấm điểm**.

**Kỳ vọng** (lần tập với champion version 1)

```text
REVIEW · Chuyển xem xét
Hạn mức đề xuất 45.000 NT$ · Xác suất vỡ nợ 41,0% · Điểm tín dụng 625 Subprime · Thời gian phản hồi ~20 ms
Kiểm tra chính sách: Xác minh tuổi: Đạt · Trần sử dụng hạn mức: Trong ngưỡng · Kiểm soát trễ hạn: Không có
```

**Presenter** (~10 s): "Model trả REVIEW: rủi ro trung bình, nên CSKH không tự quyết mà báo khách sẽ có phản hồi sau thẩm định. Ca này tự chuyển sang chuyên viên rủi ro. Cả vòng gọi API chỉ khoảng 20 mili-giây."

### Cảnh 2 — Chuyên viên rủi ro quyết định và rà soát theo lô (0:40–1:25)

**Driver** (cửa sổ 2, tài khoản `chuyenvien`)

1. (~5 s) **Hàng đợi xem xét** → ca mới nhất của Hoàng Văn Trung → bấm **Xem xét**.
2. (~20 s) Khung **Giải thích quyết định (SHAP)** tự tải từ `/api/v1/explain`; Driver dừng lại cho ML walkthrough nói.
3. (~5 s) Khung **Quyết định cuối**: chọn **Hạ hạn mức**, *Hạn mức mới* `45.000`, ghi chú ngắn → **Lưu quyết định** → hộp xanh "Hạ hạn mức: hạn mức mới 45.000 NT$".
4. (~15 s) Menu **Rà soát theo lô** → *Lô chủ thẻ* "Toàn bộ danh mục demo (200 chủ thẻ)" → **Chấm điểm cả lô** → mở menu **Cảnh báo sớm**.

**Kỳ vọng**

```text
Lô #n · Toàn bộ danh mục demo — 200 chủ thẻ · API ~40 ms · model version 1
Chấp thuận 50 (25%) · Chuyển xem xét 104 (52%) · Từ chối 46 (23%)
Danh sách cảnh báo sớm: 150 chủ thẻ cần theo dõi, xếp theo xác suất vỡ nợ giảm dần
```

**ML walkthrough** (bước 2): "Thanh xanh là yếu tố kéo rủi ro xuống, thanh đỏ là yếu tố đẩy rủi ro lên, tính bằng điểm phần trăm xác suất vỡ nợ. Chuyên viên thấy được *vì sao* model nghi ngờ, rồi mới chọn giữ nguyên, hạ hay tạm khoá hạn mức. Model đề xuất, con người quyết định."

**Presenter** (bước 4): "Sau mỗi kỳ sao kê, chuyên viên chấm lại cả danh mục bằng `/predict/batch`, tối đa 500 chủ thẻ một lô. Phân bố quyết định là con số bộ phận rủi ro đọc đầu tiên; ai REVIEW hoặc DECLINE vào danh sách cảnh báo sớm."

### Cảnh 3 — Simulate nhóm chủ thẻ dưới 30 tuổi → drift → alert Telegram (1:25–2:20)

**Driver** (cửa sổ 3, tài khoản `admin`, màn hình **Bảng điều khiển hệ thống**)

1. (~5 s) Chỉ khung **Trạng thái hệ thống**: API `ready`, model `@champion`, Drift monitor **Không drift**.
2. (~30 s) Khung **Simulate lưu lượng**: chọn **Chủ thẻ dưới 30 tuổi (chiến dịch Gen-Z)**, *Số request* `600` → **Chạy simulate**. Thanh tiến độ chạy ~30 giây (20 request/giây).
3. (~20 s) Khi job xong, chờ khung trạng thái tự làm mới (15 giây/lần): Drift monitor chuyển **DRIFT**. Có thể chuyển tab 4 (Grafana Drift) để thấy *Dataset drift* đỏ.

**Kỳ vọng**

```text
Job #n (Chủ thẻ dưới 30 tuổi (chiến dịch Gen-Z)) đã hoàn tất: 600 request thành công → 600 dòng mới trong inference_logs
Phân bố trong job: khoảng APPROVE 100 · REVIEW 330 · DECLINE 160
Drift monitor: DRIFT · max PSI > 0.25 (lần tập: 13.142) · 500 mẫu · Cột drift: AGE
~2 phút sau: Alertmanager DataDriftDetected firing (receiver telegram + webhook) → tin nhắn trong nhóm Telegram
```

**Presenter** (trong lúc thanh tiến độ chạy): "Ngân hàng mở chiến dịch tăng hạn mức cho khách trẻ. Model được train chỉ với chủ thẻ từ 30 tuổi, nên dòng yêu cầu này lệch hẳn khỏi dữ liệu train. Quản trị hệ thống mô phỏng đúng tình huống đó bằng một cú bấm: 600 yêu cầu thật đi qua API, mỗi yêu cầu thành một dòng trong `inference_logs`."

**Presenter** (khi thấy DRIFT): "Drift monitor đọc 500 dòng mới nhất mỗi phút: PSI của tuổi vượt xa ngưỡng 0.25. Alert DataDriftDetected sẽ tới Telegram sau 2 phút — chúng ta không chờ, đi tiếp sang retrain."

**Observer** (khi tin tới, thường giữa cảnh 4): "Telegram đã nhận DataDriftDetected."

### Cảnh 4 — Retrain qua quality gate (2:20–3:15)

**Driver** (chọn một)

```bash
make drift-dag      # đường chuẩn: drift_monitoring → check_retrain_cooldown → trigger_model_retrain
make retrain-dag    # dùng khi đã có run model_retrain trong 60 phút qua (cooldown)
```

→ **tab 6** (Airflow): DAG `model_retrain` chạy `train_challenger → quality_gate → decide_promotion` (~15 s trung vị trên máy dev).

```bash
make registry
```

**Kỳ vọng:** `"challenger": "<n+1>"`; hoặc

- `"champion": "<n+1>"` — challenger tốt hơn: `promote_champion → reload_api → refresh_drift_reference → notify`, **tab 5** hiện *Last retrain run* **OK** và *Last promoted version* = n+1; hoặc
- `"champion": "<n>"` giữ nguyên — nhánh `keep_champion`: challenger không tốt hơn champion theo `PromotionPolicy`.

**ML walkthrough:** chuyển **tab 7** (MLflow), chỉ alias `@champion` / `@challenger` và run vừa train, rồi nói: "Cả hai kết quả đều đúng thiết kế: hệ thống chỉ promote khi challenger đạt floor ROC-AUC 0.70, không tụt quá 0.005 và expected loss không tệ hơn — tức là không để model mới giữ hạn mức cho nhiều chủ thẻ sắp vỡ nợ hơn. Nếu API không nạp đúng version mới, `rollback_champion` trả alias về bản cũ." Nếu champion đổi, cửa sổ admin hiện version mới ở *Model đang phục vụ*.

### Cảnh 5 — Quality gate chặn model kém (3:15–3:50)

**Driver**

```bash
make retrain-fail   # model_retrain với min_roc_auc = 0.99
```

→ **tab 6**: task `quality_gate` đỏ (`Quality gate failed: ROC-AUC 0.7x < floor 0.9900 … champion unchanged`), các task promote bị skip.

```bash
make alerts
```

**Kỳ vọng:** trong ~30 s `RetrainFailed  firing`; **tab 5** *Last retrain run* = **FAILED**; `DataDriftDetected  firing` từ cảnh 3 cũng đã xuất hiện.

**ML walkthrough:** "Champion không đổi nên CSKH và chuyên viên vẫn chấm điểm bằng model đã kiểm chứng; người vận hành nhận alert kèm runbook. Không có model nào lên production mà chưa qua gate."

### Cảnh 6 — Sự cố và phục hồi (3:50–4:20, bỏ qua nếu trễ giờ)

```bash
make chaos-api-down
```

→ **tab 8**: *Scoring API* **DOWN** trong ≤ 15 s (scrape interval); `APIDown` firing sau 1 phút — **không chờ**, nói tiếp rồi:

```bash
make chaos-restore
```

→ *Scoring API* về **UP**, `/health/ready` = ready. Khung trạng thái ở cửa sổ admin cũng trở lại `ready`.

**Presenter:** "Trong lúc API sập, CSKH bấm **Gửi chấm điểm** sẽ nhận thông báo lỗi chứ không có quyết định giả; portal vẫn đăng nhập được vì health check của nó báo `degraded` chứ không sập theo. Vì vậy APIDown là alert đầu tiên của nhóm Service."

## 4. Dự phòng

| Sự cố | Dấu hiệu | Xử lý tại chỗ (≤ 30 s) |
|---|---|---|
| Portal không vào được | Trang trắng hoặc lỗi kết nối ở `:18030` | `make health`; trong lúc chờ dùng phương án không qua portal bên dưới, hoặc chiếu ảnh [`../assets/screenshots/staff-portal/`](../assets/screenshots/staff-portal/) |
| Bị đẩy về trang **Đăng nhập** / lỗi 403 | Hết phiên, hoặc đăng nhập nhầm tài khoản ở cửa sổ khác cùng profile | Đăng nhập lại đúng tài khoản ở đúng cửa sổ; mỗi cửa sổ phải là một profile/ẩn danh riêng |
| Hoàng Văn Trung không ra REVIEW | Champion đã đổi version sau lần tập | Chọn chủ thẻ khác trong danh sách tới khi ra **Chuyển xem xét**, hoặc chiếu [`03-cskh-review.png`](../assets/screenshots/staff-portal/03-cskh-review.png) |
| Khung SHAP báo lỗi ở cảnh 2 | `/api/v1/explain` chậm | Làm mới trang ca; nếu vẫn lỗi, ML walkthrough giải thích trên [`05-analyst-case.png`](../assets/screenshots/staff-portal/05-analyst-case.png) |
| Grafana chậm / trống | Panel quay vòng > 10 s | Chuyển sang ảnh [`../assets/screenshots/grafana/after/`](../assets/screenshots/grafana/after/); kiểm tra `docker stats` Grafana (giới hạn 768 MiB) sau buổi |
| Drift monitor vẫn **Không drift** ở cảnh 3 | Cửa sổ 500 dòng còn dữ liệu bình thường | Chạy simulate lần nữa với *Số request* `1000`, hoặc chiếu [`08-admin-drift-status.png`](../assets/screenshots/staff-portal/08-admin-drift-status.png) |
| Không thấy tin Telegram | Mất mạng hoặc tin tới chậm | Mở **Alertmanager** từ khung *Công cụ vận hành*: alert hiện ở receiver `telegram`; `make alerts` đọc trực tiếp từ Prometheus và webhook receiver |
| `make drift-dag` không trigger retrain | Task `check_retrain_cooldown` skip | Giải thích cooldown 60 phút (tính năng chống retrain liên tục) rồi chạy `make retrain-dag` |
| DAG kẹt ở `queued` | Airflow scheduler bận | Chuyển cảnh 5 trước; quay lại khi DAG chạy xong |
| API không trả lời | **Gửi chấm điểm** báo lỗi, khung trạng thái admin không `ready` | `make chaos-restore`, rồi `make health`; trong lúc chờ chuyển sang slide Serving |

Quy tắc: không debug trước hội đồng. Quá 30 giây → Observer nói "fallback", Driver mở ảnh/log dự phòng, Presenter (hoặc ML walkthrough ở cảnh 2, 4–5) tiếp tục thuyết minh.

### Phương án không qua portal (cảnh 1–3)

Dùng khi portal không lên; câu nói giữ nguyên, chỉ đổi thao tác.

| Cảnh | Lệnh | Kỳ vọng |
|---|---|---|
| 1 | `set -a; . ./.env; set +a` rồi `.venv/bin/python scripts/sample_predict.py` | Chủ thẻ A `REVIEW` (`default_probability` ≈ 0.36, `recommended_limit_ntd` 100000), chủ thẻ B `DECLINE` (≈ 0.99, 0) |
| 2 | Swagger `http://localhost:18020/docs` (đã **Authorize**) → `POST /api/v1/predict/batch` → ví dụ **Two cardholders** → **Execute** | `"count": 2`, `"decision_summary": {"APPROVE": 1, "REVIEW": 0, "DECLINE": 1}` |
| 3 | `make simulate SCENARIO=drift SIM_ARGS="--count 600"` | `drift analysis: drifted=True … top_psi=[('AGE', …)]`, report trong `reports/simulations/` |

## 5. Dọn dẹp sau demo

1. Cửa sổ `admin` → **Simulate lưu lượng** → **Lưu lượng bình thường**, *Số request* `600` → **Chạy simulate**. Sau ~1 phút Drift monitor về **Không drift**; DataDriftDetected resolve sau ~2 phút (Telegram nhận tin resolved).
2. Terminal:

```bash
make chaos-restore
make retrain-dag    # run thành công đưa RetrainFailed về resolved
make alerts         # Prometheus alerts: none
```

3. (Tuỳ chọn, chỉ khi muốn làm sạch dữ liệu demo) Khung **Xoá dữ liệu log**: gõ `XOA` → **Xoá toàn bộ log**. Thao tác được ghi vào **Nhật ký thao tác quản trị**; drift monitor báo "chưa đủ dữ liệu" cho tới khi có log mới, nên chạy lại bước 1 ngay sau đó. Chức năng này chỉ bật khi `PORTAL_DEMO_MODE=true`.

## 6. Câu hỏi hay gặp khi demo

- **"REVIEW có tự hạ hạn mức không?"** — không. REVIEW chỉ kèm đề xuất hạ hạn mức (`recommended_limit_ntd`); chuyên viên rủi ro quyết định ở **Quyết định cuối** sau khi xem SHAP từ `POST /api/v1/explain`.
- **"Portal có làm đổi API không?"** — không. Portal gọi đúng `/api/v1/predict`, `/predict/batch`, `/explain`; API key nằm ở server portal, trình duyệt chỉ có cookie phiên và CSRF token.
- **"CSKH có xem được màn hình quản trị không?"** — không. Mỗi tài khoản chỉ vào màn hình của vai trò mình; vào sai trả 403.
- **"Xoá log có nguy hiểm không?"** — chỉ bật ở chế độ demo, phải gõ `XOA`, và được ghi nhật ký. Production đặt `PORTAL_DEMO_MODE=false` nên nút bị khoá.
- **"Sao challenger không được promote?"** — dữ liệu retrain gần giống champion nên không vượt `PromotionPolicy`; đó là hành vi mong muốn (nhánh `keep_champion`, có thông báo `RetrainChampionKept`).
- **"Drift xử lý thế nào nếu chỉ lệch output?"** — prediction shift (PSI output ≥ 0.25) chỉ alert `PredictionDistributionShift`, không retrain tự động, vì có thể là thay đổi hợp lệ trong tập chủ thẻ.
- **"Latency có bị retrain ảnh hưởng?"** — retrain chạy trong Airflow (container riêng); API chỉ hot-reload model qua `POST /api/v1/model/reload`.
- **"Stack này đã chạy trên production thật chưa hay chỉ local compose?"** — hệ thống đã có pipeline CD hoàn chỉnh: push tag `v1.0.0` kích hoạt workflow GitHub Actions, build và scan Trivy, publish GHCR, rồi deploy qua SSH Deploy Key vào VPS Ubuntu `148.113.255.63`. Stack production chạy 12 containers (`/opt/credit-risk/current`), sau Nginx, smoke test pass và tự động rollback nếu lỗi.
