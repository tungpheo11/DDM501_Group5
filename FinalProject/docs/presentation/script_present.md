
# DDM501 GROUP 5 — SCRIPT THUYẾT TRÌNH ~16 PHÚT

**Chủ đề:** Credit Default Risk Scoring — Từ bài toán nghiệp vụ đến Production MLOps

### Phân chia

- **Thịnh:** Slide 1–4 — Problem → ML Setup → Ops Foundation — ~2 phút
- **Tùng:** Slide 5–9 — Requirements → Lifecycle → Architecture → Staff Portal → CI/CD — ~4 phút 15 giây
- **Hoa:** Slide 10–14 — Serving → Monitoring → Incident → Drift → Retraining — ~4 phút
- **Hòa:** Slide 15–20 — Failure → RAI → Staff Portal (3 vai trò, drift) → Demo → Lessons — ~4 phút 30 giây
- **Slide 21:** Q&A

Mục tiêu hoàn thành khoảng **15:00–15:45**, để dành thời gian cho phần demo trực tiếp và trả lời câu hỏi của hội đồng. Nếu cần rút về 15 phút, cắt theo mục *Nếu bị quá giờ* ở cuối.

---

# NGƯỜI 1 — THỊNH
## Slide 1–4
### 0:00 → ~2:00

## SLIDE 1 — MỞ ĐẦU
### ~20 giây

“Kính chào thầy cô và các bạn.

Nhóm 5 xin báo cáo đồ án cuối môn với đề tài **Credit Default Risk Scoring — Từ bài toán nghiệp vụ đến Production MLOps**.

Bám sát định hướng của môn học: phần Machine Learning chiếm 30% để chuẩn bị scoring artifact, và **70% trọng tâm là toàn bộ kiến trúc vận hành MLOps**.

Mục tiêu cốt lõi của đồ án không phải chạy đua thuật toán phức tạp trong notebook, mà là:

**sau khi có model, làm thế nào để release, serve, monitor, bắt drift và tự động retrain/recover an toàn trên môi trường production.**”

**[Slide 2]**

---

## SLIDE 2 — BÀI TOÁN & RÀNG BUỘC NGHIỆP VỤ
### ~35 giây

“Về bài toán, hệ thống giải quyết bài toán **Behavioral Scoring** — quản lý hạn mức cho danh mục 30.000 chủ thẻ hiện hữu dựa trên 6 tháng lịch sử sao kê và thanh toán.

Hệ thống phục vụ hai use case chính: **Realtime** khi chủ thẻ yêu cầu tăng hạn mức trên app, và **Batch** khi ngân hàng rà soát toàn bộ danh mục sau mỗi kỳ sao kê.

Điểm then chốt định hình toàn bộ thiết kế Ops phía sau là **ma trận chi phí bất đối xứng: False Negative đắt gấp 10 lần False Positive**.

Cấp hạn mức cho một chủ thẻ mất khả năng thanh toán (FN) gây rủi ro nợ xấu lớn hơn nhiều so với việc thận trọng rà soát lại một chủ thẻ tốt (FP).

Vì vậy, bài toán không thể chỉ tối ưu accuracy, mà đòi hỏi thiết lập ngưỡng quyết định rõ ràng phục vụ cho tầng serving và policy gate.”

**[Slide 3]**

---

## SLIDE 3 — THIẾT LẬP ML PHỤC VỤ TẦNG OPS
### ~40 giây

“Để chuẩn bị artifact cho tầng vận hành, nhóm đóng gói ML pipeline chuẩn: validate schema bằng Pandera, trích xuất 12 features đặc trưng như tỷ lệ sử dụng hạn mức (utilization) và xu hướng trễ hạn.

Sau khi benchmark 4 thuật toán qua cross-validation, nhóm chọn **Logistic Regression** với holdout ROC-AUC đạt **0.770**.

Mô hình này có hiệu năng tương đương các boosting model nhưng mang 3 lợi thế quyết định cho Ops: **inference cực nhẹ (p95 dưới 25ms), dễ giải thích qua SHAP/LIME, và tối ưu chi phí theo ma trận rủi ro**.

Đầu ra xác suất được ánh xạ trực tiếp thành **Decision Engine 3 vùng**:
- **APPROVE** (xác suất vỡ nợ dưới 0.30: duyệt tự động)
- **REVIEW** (0.30 đến 0.60: chuyển thẩm định viên rủi ro kèm reason codes)
- **DECLINE** (từ 0.60 trở lên: từ chối tự động).

Toàn bộ tham số và model artifact được version hóa, đăng ký lên **MLflow Registry** với alias **`@champion`**.”

**[Slide 4]**

---

## SLIDE 4 — TỪ ML SANG MLOPS
### ~25 giây

“Mô hình và metrics vừa rồi mới chỉ là bước chuẩn bị đầu tiên.

Khi đưa vào production thực tế, hệ thống phải trả lời hàng loạt bài toán kỹ thuật: Model version nào đang phục vụ? Deploy thế nào để không gián đoạn? Dữ liệu drift thì đo lường ra sao? Quy trình retrain tự động và rollback an toàn khi có sự cố được kiểm soát thế nào?

Để giải quyết trọn vẹn chu trình này, nhóm đã hiện thực hóa hạ tầng gồm **4 dashboard Grafana, 11 alert rules Prometheus, 3 nhóm workflow Airflow**, cùng pipeline CI/CD kiểm thử và deploy tự động lên cloud VPS.

Tiếp theo, bạn Tùng sẽ trình bày cách nhóm chuyển đổi các ràng buộc nghiệp vụ này thành hệ sinh thái kiến trúc và quy trình release an toàn.”


---

# NGƯỜI 2 — TÙNG
## Slide 5–9
### ~3:00 → 7:15

## SLIDE 5 — BUSINESS REQUIREMENT → SLO
### ~50 giây

“Cảm ơn Thịnh.

Khi chuyển từ ML sang production, yêu cầu nghiệp vụ cần trở thành những tiêu chí có thể **đo và enforce được**.

Với realtime prediction, người dùng đang chờ kết quả, nên nhóm đặt **p95 latency dưới 100 milliseconds**.

Với service health, nhóm đặt ngưỡng **5xx error rate dưới 5%** và mọi lỗi quan trọng phải observable.

Với dữ liệu, PSI từ **0.25 trở lên** được xem là tín hiệu drift đáng chú ý.

Và với model update, nguyên tắc là:

**không được promote một challenger kém hơn champion đang chạy.**

Các quyết định APPROVE, REVIEW và DECLINE vẫn giữ từ business layer; riêng REVIEW luôn có human-in-the-loop.

Như vậy chúng em không chỉ có một model metric mà có một tập **operational contract** cho cả hệ thống.”

**[Slide 6]**

---

## SLIDE 6 — END-TO-END LIFECYCLE
### ~55 giây

“Slide này là bản đồ của phần còn lại.

Một thay đổi bắt đầu từ **code và data**.

Đầu tiên đi qua CI để lint, test và kiểm tra coverage.

Sau đó Docker image được build và scan security.

Application artifact được lưu ở GHCR, còn ML model được version bằng MLflow Registry.

Release tiếp tục được deploy lên Ubuntu và phải vượt smoke test trước khi thành công.

Khi đi vào production, FastAPI serve model và xuất metrics.

Prometheus, Grafana và Alertmanager đảm nhiệm observability.

Evidently và PSI theo dõi drift.

Nếu đủ điều kiện, Airflow trigger retraining để tạo challenger mới.

Challenger lại phải đi qua quality gate trước khi được promote hoặc bị giữ lại.

Điểm quan trọng nhất là:

**vòng đời không dừng ở deploy. Nó quay ngược trở lại serving và tạo thành một closed loop.**”

**[Slide 7]**

---

## SLIDE 7 — PRODUCTION ARCHITECTURE
### ~55 giây

“Về architecture, toàn bộ hệ thống có 16 service, nhưng được chia thành ba operational profile.

**Core profile** gồm FastAPI, Staff Portal, MLflow, PostgreSQL và MinIO.

Đây là phần tối thiểu để serving và model registry hoạt động.

**Orchestration profile** là Airflow, phụ trách drift monitoring workflow, model retraining và service health check.

**Monitoring profile** gồm Prometheus, Grafana, Alertmanager, Evidently và các exporter.

Phía ngoài có GitHub Actions và GHCR cho CI/CD, Ubuntu làm production host và Telegram làm alert destination.

Nhóm chọn **Docker Compose thay vì Kubernetes** vì deployment target hiện tại chỉ là một Ubuntu VM.

Trade-off là chúng em giảm đáng kể operational overhead, nhưng chấp nhận hiện tại chưa có high availability và autoscaling.

Nếu hệ thống cần mở rộng sau này, đây sẽ là một trong những điểm cần nâng cấp.”

**[Slide 8]**

---

## SLIDE 8 — STAFF PORTAL TRONG KIẾN TRÚC
### ~35 giây

“Model chỉ có giá trị khi người làm nghiệp vụ dùng được nó, nên nhóm thêm service thứ 16: **Staff Portal**, cổng nghiệp vụ cho nhân viên ngân hàng.

Portal có ba vai trò: CSKH tiếp nhận yêu cầu, chuyên viên rủi ro tín dụng và quản trị hệ thống. Mỗi tài khoản chỉ vào được màn hình của vai trò mình.

Portal gọi đúng ba endpoint đã có — `/predict`, `/predict/batch` và `/explain` — nên **API contract không đổi**. API key nằm ở server portal, trình duyệt chỉ giữ cookie phiên.

Mỗi lần chấm điểm vẫn ghi một dòng vào `inference_logs`, nên mọi thao tác trên portal đi thẳng vào vòng monitoring, drift và retrain mà các phần sau sẽ trình bày.

Portal cũng có `/health/live` và `/health/ready` như API, để Docker và smoke test biết khi nào nó thật sự phục vụ được.”

**[Slide 9]**

---

## SLIDE 9 — RELEASE SAFETY / CI-CD
### ~1 phút

“Tiếp theo là release process.

Nhóm coi một release không đơn giản là chạy `docker compose up`.

Nó phải vượt qua nhiều gate.

Đầu tiên là static validation với Ruff, Black, Mypy và data/model tests.

Sau đó là quality gate với **396 tests** và coverage floor ít nhất **80%**.

Docker image được build theo multi-stage process.

Trivy scan image và nếu có vulnerability mức CRITICAL thì pipeline bị chặn.

Khi tạo tag release, image được publish lên GHCR rồi deploy qua SSH vào thư mục `releases/<tag>` trên Ubuntu.

Đặc biệt, pipeline này đã được kiểm chứng thực tế: nhóm đã chạy thành công khi push tag `v1.0.0`, toàn bộ chu trình CI/CD tự động build, scan Trivy, publish GHCR và deploy lên VPS Ubuntu `148.113.255.63` qua SSH Deploy Key, smoke test pass và 12 container healthy mà không cần bất kỳ can thiệp thủ công nào.

Sau deploy, hệ thống chưa được coi là thành công ngay.

Nó phải gọi `/health/ready` và chạy một prediction thật.

Nếu smoke test fail, symlink `current` được đưa về `previous_release`, tức là rollback tự động về bản trước.

Runtime secrets cũng không nằm trong image mà được giữ ngoài host environment.

Mục tiêu của toàn bộ pipeline là:

**mỗi gate loại bỏ một lớp rủi ro trước khi release mới gặp traffic thật.**

Sau deployment, câu hỏi tiếp theo là làm sao service biết khi nào mình thực sự healthy. Phần đó bạn Hoa sẽ trình bày.”

---

# NGƯỜI 3 — HOA
## Slide 10–14
### ~7:15 → 11:15

## SLIDE 10 — SERVING RELIABILITY
### ~50 giây

“Ở serving layer, nhóm thiết kế ba trạng thái rõ ràng.

Trạng thái đầu tiên là **READY**.

API load alias `champion` từ MLflow Registry và response luôn chứa `model_version`, để operator biết chính xác version nào đang chạy.

Trạng thái thứ hai là **DEGRADED**.

Ví dụ khi cold start mà MLflow tạm thời unavailable, hệ thống có thể sử dụng local joblib fallback.

Nhưng fallback không được diễn ra âm thầm.

Nó bật metric và alert ngay lập tức.

Trạng thái cuối cùng là **NOT READY**.

Nếu không còn model hợp lệ, API trả `503 MODEL_UNAVAILABLE` thay vì trả một kết quả không đáng tin cậy.

Nhóm cũng tách `/live` và `/ready`.

`live` cho biết process còn sống.

`ready` cho biết service có thật sự đủ điều kiện nhận traffic hay không.

Đây cũng là endpoint được dùng cho Docker healthcheck và deployment smoke test.”

**[Slide 11]**

---

## SLIDE 11 — OBSERVABILITY
### ~45 giây

“Sau khi service chạy, chúng em chia observability thành **4 dashboard tương ứng với 4 câu hỏi**.

Business dashboard trả lời hệ thống đang APPROVE, REVIEW hay DECLINE bao nhiêu trường hợp.

Model dashboard trả lời champion version nào đang chạy và score distribution có thay đổi không.

Drift dashboard theo dõi PSI, drift share và freshness của lần phân tích gần nhất.

Cuối cùng, Infra/SLA dashboard theo dõi service UP/DOWN, p95 latency, 5xx, request rate và Airflow health.

Các dashboard được provision từ code, và threshold hiển thị được đồng bộ với alert threshold.

Nguyên tắc của nhóm là:

**không để một failure quan trọng chỉ tồn tại trong log mà operator không nhìn thấy.**”

**[Slide 12]**

---

## SLIDE 12 — INCIDENT RESPONSE
### ~50 giây

“Tuy nhiên dashboard mới chỉ là quan sát.

Alert chỉ thật sự có giá trị khi dẫn tới **action và recovery**.

Ví dụ nhóm inject một latency spike.

Prometheus phát hiện metric vượt threshold.

Alertmanager nhận alert, group và deduplicate.

Sau đó webhook gửi notification tới Telegram cùng thông tin liên quan.

Engineer mở runbook để kiểm tra symptom và thực hiện mitigation.

Khi metric trở lại bình thường, alert chuyển sang RESOLVED.

Project hiện có tổng cộng **11 alert rules** cho service, model, drift và pipeline.

Các rule còn được kiểm tra bằng `promtool`.

Ngoài ra nhóm có chaos target như `api-down`, `model-unloaded`, `latency` và `drift-down`.

Mục đích là chứng minh alert thực sự fire và resolve, chứ không chỉ tồn tại dưới dạng YAML.”

**[Slide 13]**

---

## SLIDE 13 — DRIFT KHÔNG ĐỒNG NGHĨA RETRAIN NGAY
### ~50 giây

“Với ML system, một failure có thể xảy ra ngay cả khi API vẫn trả HTTP 200.

Production data có thể dần khác với training data.

Ở đây nhóm tách ba cadence.

**Background drift analysis khoảng 60 giây.**

**Airflow orchestration khoảng 30 phút.**

Và **retraining có cooldown 60 phút.**

Lý do là phát hiện drift sớm không có nghĩa chúng ta phải retrain liên tục.

Nếu chỉ prediction distribution thay đổi, hệ thống alert để theo dõi nhưng không tự retrain.

Nếu dataset drift thực sự vượt threshold, pipeline còn kiểm tra sample size, cooldown và các điều kiện khác trước khi trigger retraining.

Việc tách ba cadence giúp tránh một feedback loop mà chỉ cần dữ liệu dao động nhẹ cũng liên tục tạo model mới.”

**[Slide 14]**

---

## SLIDE 14 — CHAMPION / CHALLENGER
### ~55 giây

“Khi retraining được trigger, model mới được gọi là **challenger** và model production hiện tại là **champion**.

Điểm quan trọng là:

**auto-retrain không đồng nghĩa auto-promote.**

Challenger phải đạt ROC-AUC tối thiểu **0.70**.

Performance không được giảm quá **0.005** so với champion.

Expected loss cũng không được tệ hơn champion.

Nếu không tốt hơn, challenger bị giữ lại và champion tiếp tục phục vụ.

Nếu pass, model được promote và API reload model mới.

Nhưng pipeline vẫn chưa kết thúc.

Sau reload, hệ thống kiểm tra xem API có thật sự đang serve đúng version vừa promote hay không.

Nếu không, alias được rollback về version cũ.

Như vậy pipeline có ba kết quả rõ ràng:

**promote, keep hoặc rollback.**

Đây là lớp bảo vệ chính của closed-loop MLOps.

Và bạn Hòa sẽ nói tiếp về cách hệ thống xử lý failure, governance và demo end-to-end.”

---

# NGƯỜI 4 — HÒA
## Slide 15–20
### ~11:15 → 15:45

## SLIDE 15 — DESIGN FOR FAILURE
### ~45 giây

“Cảm ơn Hoa.

Một nguyên tắc xuyên suốt project là:

**mỗi failure mode phải có response, signal và recovery path.**

Nếu input sai schema, Pydantic chặn request bằng 422 trước khi request chạm vào model.

Nếu model chưa load được, readiness chuyển sang NOT READY và API trả 503.

Nếu MLflow unavailable nhưng fallback còn hợp lệ, service chuyển sang DEGRADED và bật `ModelServedFromFallback`.

Nếu challenger fail quality gate, champion vẫn tiếp tục serving và pipeline phát `RetrainFailed` hoặc giữ champion.

Điểm chúng em muốn nhấn mạnh là failure không phải một exception bất ngờ.

**Failure là một phần của system design.**”

**[Slide 16]**

---

## SLIDE 16 — RESPONSIBLE AI
### ~45 giây

“Ngoài reliability, model còn cần governance guardrail.

Nhóm đánh giá fairness bằng các metric như Disparate Impact, DPD và EOD.

Hiện tại AGE vẫn là nhóm có rủi ro fairness rõ nhất, với Disparate Impact khoảng **0.41** trước mitigation.

Nhóm không che kết quả này mà coi đây là một issue cần quản lý.

Các trường hợp REVIEW luôn được đưa qua Credit Risk Analyst.

SHAP được sử dụng để tạo reason code cho REVIEW và DECLINE.

Về privacy, inference log được redact, identifier được pseudonymize và secret chỉ tồn tại ở runtime environment.

Nhóm cũng thử mitigation như reweighing.

Tuy nhiên quyết định có áp dụng mitigation hay không phải là quyết định của business và compliance, chứ không nên để pipeline tự động lựa chọn.”

**[Slide 17]**

---

## SLIDE 17 — STAFF PORTAL · LUỒNG 3 VAI TRÒ
### ~30 giây

“Human-in-the-loop vừa nói ở trên giờ có giao diện thật. Ảnh trên slide chụp từ portal đang chạy.

Đầu tiên, nhân viên **CSKH** tìm chủ thẻ, chọn *Tăng hạn mức* và bấm *Gửi chấm điểm*. Model trả REVIEW, xác suất vỡ nợ 41%, nên CSKH không tự quyết.

Ca đó tự vào **Hàng đợi xem xét** của **chuyên viên rủi ro**. Chuyên viên đọc giải thích SHAP rồi chọn giữ nguyên, hạ hay tạm khoá hạn mức — ở đây là hạ xuống 45.000.

Cuối cùng, **quản trị hệ thống** chỉ nhìn sức khoẻ: API, model `@champion`, drift monitor và bảng `inference_logs`.”

**[Slide 18]**

---

## SLIDE 18 — STAFF PORTAL · SIMULATE → DRIFT → ALERT → RETRAIN
### ~30 giây

“Quản trị cũng là người kích hoạt kịch bản drift, chỉ bằng một cú bấm *Chạy simulate* với nguồn *Chủ thẻ dưới 30 tuổi*.

600 yêu cầu thật đi qua API. Trong khoảng một phút, drift monitor báo **DRIFT**, PSI của tuổi vượt xa ngưỡng 0.25, vì model chỉ được train với chủ thẻ từ 30 tuổi.

Hai phút sau, Alertmanager gửi `DataDriftDetected` tới **Telegram**, và Airflow chạy `model_retrain`: train challenger, qua quality gate, rồi promote hoặc giữ champion.

Giờ chúng em làm đúng vòng này trên hệ thống thật.”

**[Slide 19]**

---

# SLIDE 19 — LIVE DEMO
### ~1 phút 10 giây

> **Khuyến nghị:** Hòa nói, Tùng thao tác Staff Portal/terminal/Grafana theo [demo-script.md](demo-script.md).  
> Đừng giải thích command. Chỉ kể production story.

### Bước 1 — Healthy

“Phần demo của nhóm không tập trung vào việc chứng minh API có thể predict, vì đó chỉ là bước đầu.

Chúng em demo theo câu chuyện:

**Healthy → Incident → Detection → Recovery.**

Đầu tiên, API đang ở trạng thái READY, champion version đang được serve và monitoring stack ở trạng thái bình thường.”

**[Chỉ health/Grafana khoảng 5–8 giây.]**

---

### Bước 2 — Inject drift

“Tiếp theo chúng em chủ động đưa vào một data distribution bị lệch.”

**[Tùng, cửa sổ portal `admin`: Simulate lưu lượng → *Chủ thẻ dưới 30 tuổi (chiến dịch Gen-Z)* → 600 → *Chạy simulate*. Dự phòng: `make simulate SCENARIO=drift`.]**

“Service vẫn sống.

Điều thay đổi ở đây là data, không phải application.”

---

### Bước 3 — Detect

“Drift monitor phân tích dữ liệu mới.

Khi threshold bị vượt, Drift dashboard thay đổi và `DataDriftDetected` chuyển sang firing.”

**[Chỉ dashboard / alert.]**

---

### Bước 4 — Airflow

“Airflow tiếp nhận phần orchestration.

DAG không retrain ngay lập tức mà kiểm tra drift condition và cooldown trước.”

**[Mở DAG hoặc output `make drift-dag`.]**

---

### Bước 5 — Quality gate

“Nếu đủ điều kiện, challenger được train và đi qua quality gate.

Nếu challenger đạt yêu cầu, nó có thể được promote.

Nếu không, champion vẫn giữ nguyên.”

**[Cho nhanh `make retrain-fail` hoặc evidence đã chuẩn bị.]**

“Ở failure path này, retraining thất bại nhưng production service không bị thay thế bởi model kém hơn.

Đây chính là điều quality gate bảo vệ.”

---

### Bước 6 — Close loop

“Như vậy chúng ta vừa đi qua toàn bộ vòng:

**production data thay đổi → drift detection → alert → orchestration → retrain → quality gate → promote hoặc giữ champion → verify serving state.**

Đây là phần quan trọng nhất của project dưới góc nhìn MLOps.”

**[Slide 20]**

---

## SLIDE 20 — LESSONS LEARNED
### ~45 giây

“Sau khi thực sự vận hành stack này, nhóm rút ra bốn bài học.

Thứ nhất, evidence nên được sinh từ pipeline để report và model card không lệch khỏi artifact thật.

Thứ hai, fallback chỉ có ý nghĩa khi observable.

Nếu service đang degraded mà không có metric và alert, fallback chỉ đang che giấu lỗi.

Thứ ba, bản thân observability stack cũng cần capacity planning.

Trong quá trình vận hành, Grafana từng chạm memory limit và dashboard không thể mở cho tới khi nhóm tăng resource budget và giảm plugin không cần thiết.

Và cuối cùng, automation luôn phải có guardrail.

Drift không nên nối thẳng với auto-promotion.

Chúng ta cần cooldown, champion/challenger, quality gate và rollback verification.

Nếu phát triển tiếp, nhóm muốn bổ sung shadow deployment, high availability cho serving và scheduled fairness/privacy checks.”

**[Slide 21]**

---

# SLIDE 21 — KẾT LUẬN / Q&A
### ~15–20 giây

“Nhóm xin kết thúc bằng một ý chính:

**Một model chưa trở thành sản phẩm chỉ vì nó predict tốt.**

Nó chỉ thực sự trở thành một production ML system khi chúng ta có thể **deploy, observe, update và recover nó một cách có kiểm soát**.

Nhóm xin cảm ơn thầy/cô và các bạn đã lắng nghe.

Nhóm xin nhận câu hỏi.”

---

# PHÂN BỔ THỜI GIAN KHI TẬP

| Người | Slide | Mốc nên chuyển |
|---|---|---:|
| Thịnh | 1–4 | **03:00** |
| Tùng | 5–9 | **07:15** |
| Hoa | 10–14 | **11:15** |
| Hòa | 15–20 | **15:45** |
| Kết | 21 | **≤16:00** |

# NẾU BỊ QUÁ GIỜ

Ưu tiên cắt ở những chỗ này, **không cắt demo và closed-loop retraining**:

1. Slide 7 Architecture: bỏ mô tả từng component, chỉ nói 3 profile + Compose vs K8s.
2. Slide 8 Staff Portal: chỉ nói "service thứ 16, gọi đúng API cũ, API key ở server".
3. Slide 11 Monitoring: nói 4 dashboard trong một câu.
4. Slide 15 Failure modes: chỉ lấy 2 case `503` và `DEGRADED`.
5. Slide 16 RAI: chỉ giữ fairness warning + human-in-the-loop + SHAP.
6. Slide 17–18 Staff Portal: nếu sắp demo trực tiếp, chỉ lướt 10 giây mỗi slide.
7. Slide 20 Lessons: chỉ nói lesson 2 và lesson 3.

# 4 CÂU CHUYỂN NGƯỜI NÊN HỌC THUỘC

**Thịnh → Tùng**

“ML đã tạo ra được scoring artifact. Phần còn lại của bài là làm thế nào để artifact đó tồn tại an toàn trong production, và bạn Tùng sẽ bắt đầu từ operational requirement và release pipeline.”

**Tùng → Hoa**

“Đến đây model đã được deploy an toàn. Nhưng deploy thành công không có nghĩa hệ thống sẽ luôn khỏe, nên bạn Hoa sẽ trình bày phần serving, observability và closed-loop retraining.”

**Hoa → Hòa**

“Như vậy hệ thống đã có vòng monitor–retrain–verify hoàn chỉnh. Bạn Hòa sẽ trình bày cách nhóm thiết kế cho failure, Responsible AI và sau đó demo vòng đời này trên hệ thống.”

**Hòa → Q&A**

“Model tốt là điều kiện cần; khả năng vận hành và phục hồi có kiểm soát mới biến model đó thành production system.”