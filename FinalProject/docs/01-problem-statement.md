# 01 — Problem statement & requirements

> Rubric **A. Problem Definition & Requirements (10%)**. Số liệu "hiện tại" trích từ file sinh tự động trong
> [`reports/`](../reports/) (cột *Nguồn*); khi chạy lại `make train` / `make responsible-ai` / `make bench` /
> `make simulate`, đối chiếu lại bảng mục 5.

## 1. Bối cảnh kinh doanh

Ngân hàng đang có hàng trăm nghìn thẻ tín dụng lưu hành. Việc quản lý hạn mức cho danh mục này hiện gặp hai vấn đề:

- **Rà soát hạn mức thủ công theo quý.** Chậm, và không phát hiện sớm những chủ thẻ đang xấu đi giữa hai lần rà soát.
- **Yêu cầu tăng hạn mức qua app mất 1–3 ngày.** Quyết định không nhất quán giữa các chuyên viên và không giải thích
  được bằng số liệu.

Hệ thống này là nền tảng **Credit Line Management (quản lý hạn mức thẻ)** cho chủ thẻ đang lưu hành. Sau mỗi kỳ sao kê,
hệ thống dự báo xác suất vỡ nợ `P(default)` của từng chủ thẻ ở kỳ thanh toán kế tiếp — ví dụ dùng sao kê tháng 04–09 để
dự báo vỡ nợ tháng 10 — rồi dùng xác suất đó để quyết định giữ, tăng, hạ hay tạm khoá hạn mức.

Quyết định sai có **chi phí bất đối xứng**:

| | Thực tế: trả nợ tốt | Thực tế: vỡ nợ |
|---|---|---|
| **Giữ / tăng hạn mức** | Đúng — thu lãi + phí interchange | **False Negative** — mất dư nợ + phần hạn mức vừa tăng (≈ hạn mức × LGD) |
| **Hạ / khoá hạn mức** | **False Positive** — mất doanh thu, khách khó chịu, có thể rời bỏ | Đúng — giảm exposure trước khi vỡ nợ |

Hệ thống dùng cost matrix **FN = 10, FP = 1** (bỏ sót một chủ thẻ sắp vỡ nợ tốn ngang 10 lần hạ hạn mức nhầm một khách
tốt) và LGD 0.45 (Basel II foundation IRB, `configs/serving.yaml`) cho metric tiền tệ. Vì vậy mục tiêu không phải
*accuracy* mà là **giảm expected financial loss** trong khi vẫn giữ recall lớp vỡ nợ cao.

**Bài toán ML:** phân loại nhị phân có xác suất — dự báo `P(default)` của chủ thẻ ở kỳ thanh toán kế tiếp từ hạn mức
hiện tại, nhân khẩu học, 6 tháng lịch sử trả nợ / dư nợ sao kê / số tiền đã trả (UCI *Default of Credit Card Clients*,
30.000 chủ thẻ, xem [data card](data-card.md)). Đây là bài toán *behavioral scoring*: mọi feature đều là hành vi của
người đã có thẻ. Xác suất được chuyển thành quyết định 3 vùng:

```text
P(default) < 0.30          → APPROVE  (tự động chấp thuận / giữ hạn mức)
0.30 ≤ P(default) < 0.60   → REVIEW   (chuyển chuyên viên rủi ro — human-in-the-loop)
P(default) ≥ 0.60          → DECLINE  (tự động từ chối tăng / tạm khoá hạn mức, kèm lý do)
```

Mỗi vùng đi kèm một hạn mức đề xuất (`recommended_limit_ntd` trong response):

| Vùng | Yêu cầu tăng hạn mức (realtime) | Rà soát định kỳ (batch) | Hạn mức đề xuất |
|---|---|---|---|
| `APPROVE` | Chấp thuận | Giữ hoặc đề xuất tăng | min(`LIMIT_BAL` × 1.25, 500.000) |
| `REVIEW` | Chuyển chuyên viên rủi ro xem xét | Đề xuất hạ hạn mức, chuyên viên quyết định | min(`LIMIT_BAL` × 0.5, 100.000) |
| `DECLINE` | Từ chối, bắt buộc kèm reason codes (SHAP) | Tạm khoá hạn mức khả dụng: không cho chi tiêu thêm, dư nợ hiện tại vẫn phải trả | 0 |

Theo luật tín dụng (ECOA / Regulation B), từ chối yêu cầu tăng hạn mức hoặc thay đổi bất lợi điều khoản tài khoản (hạ,
tạm khoá hạn mức) đều là *adverse action*, nên mọi quyết định `DECLINE` và mọi lần hạ hạn mức phải gửi được thông báo kèm
lý do cho chủ thẻ.

Ngưỡng nằm trong `configs/serving.yaml` (override bằng `REVIEW_THRESHOLD`, `DECLINE_THRESHOLD`).

**Vì sao cần MLOps chứ không chỉ một model:** tập chủ thẻ thay đổi theo chiến dịch marketing (ví dụ chiến dịch Gen-Z
đưa nhiều chủ thẻ < 30 tuổi vào danh mục — nhóm model chưa từng thấy khi train, xem
[data card §4](data-card.md#4-partition-và-mục-đích)). Không có giám sát drift và retrain có kiểm soát, model âm thầm
xuống cấp và có thể phân biệt đối xử theo tuổi.

## 2. Stakeholder & người dùng

| Stakeholder | Nhu cầu | Tương tác với hệ thống |
|---|---|---|
| Card Management System (CMS) + mobile app backend | Trả kết quả yêu cầu tăng hạn mức ngay trong phiên app của chủ thẻ | `POST /api/v1/predict` realtime với `X-API-Key` |
| Batch job rà soát hạn mức | Chấm điểm toàn danh mục sau mỗi kỳ sao kê, lập danh sách cảnh báo sớm | `POST /api/v1/predict/batch` (lô ≤ 500 chủ thẻ) |
| Chuyên viên rủi ro tín dụng / quản lý hạn mức (Credit Risk Analyst) | Xử lý tài khoản vùng REVIEW, theo dõi danh sách cảnh báo sớm, biết vì sao | `POST /api/v1/explain` (top risk factors, SHAP) |
| Risk manager / Model risk | Biết model có còn đúng, có công bằng | Grafana *Business*, *ML model*, *Drift*; [fairness report](../reports/fairness_report.md) |
| MLOps / SRE | Vận hành, xử lý sự cố, release | Grafana *Infra & SLA*, Alertmanager/Telegram, Airflow, runbook |
| Compliance / kiểm toán | Truy vết model, dữ liệu, quyết định; adverse action notice | MLflow registry + lineage, `data/manifest.json`, inference log (pseudonymized), [model card](model-card.md) |

## 3. Use case

Use case nghiệp vụ và chế độ gọi API:

| Use case nghiệp vụ | Kích hoạt | Chế độ | Endpoint |
|---|---|---|---|
| Duyệt yêu cầu tăng hạn mức (tạm thời / vĩnh viễn), yêu cầu rút tiền mặt / chuyển trả góp | Chủ thẻ gửi yêu cầu trên mobile app / Internet banking, chờ kết quả ngay trong phiên | Realtime | `POST /api/v1/predict` |
| Rà soát hạn mức định kỳ toàn danh mục (giữ / tăng / giảm / tạm khoá hạn mức khả dụng), gia hạn thẻ | Job chạy sau mỗi kỳ sao kê, chia lô ≤ 500 | Batch | `POST /api/v1/predict/batch` |
| Danh sách cảnh báo sớm cho chuyên viên rủi ro (chỉ theo dõi và liên hệ nhắc nợ mềm; **không** tự động chuyển thu hồi nợ) | Job chạy sau kỳ sao kê | Batch | `/predict/batch` + `/explain` |
| Giải thích quyết định cho chuyên viên / adverse action notice | Tài khoản rơi vào vùng REVIEW hoặc DECLINE | On-demand | `POST /api/v1/explain` |

**Realtime và batch.** Luồng realtime phục vụ chủ thẻ đang chờ kết quả yêu cầu tăng hạn mức ngay trên app: cả luồng app
phải phản hồi dưới 1 giây, nên riêng phần chấm điểm được ngân sách **p95 ≤ 100 ms** (NFR-01), phần còn lại dành cho
CMS, xác thực và mạng. Luồng batch phục vụ rà soát định kỳ toàn danh mục sau mỗi kỳ sao kê; ở đây throughput quan trọng
hơn latency của từng request, nên API chấm vector hoá tối đa 500 chủ thẻ mỗi lần gọi.

Use case hệ thống:

| ID | Use case | Actor | Luồng chính | Kết quả |
|---|---|---|---|---|
| UC-01 | Chấm điểm một chủ thẻ (yêu cầu tăng hạn mức) | CMS / mobile app backend | Gửi 23 feature → validate → model `@champion` → quyết định | `default_probability`, `credit_score` 300–850, `risk_decision`, `recommended_limit_ntd`, `model_version`, `request_id` |
| UC-02 | Chấm điểm theo lô (rà soát hạn mức) | Batch job rà soát hạn mức | ≤ 500 chủ thẻ/lần, giữ thứ tự | Danh sách kết quả + `decision_summary`; > 500 → `413` |
| UC-03 | Giải thích quyết định | Credit Risk Analyst | Gửi dữ liệu tài khoản → SHAP permutation so với chủ thẻ tham chiếu | Top-k yếu tố tăng/giảm rủi ro (reason codes) |
| UC-04 | Giám sát sức khoẻ & drift | Risk manager, MLOps | Prometheus scrape API + drift monitor mỗi 60 s | Dashboard, alert `DataDriftDetected`, `PredictionDistributionShift`, … |
| UC-05 | Retrain có kiểm soát | Airflow (tự động) / MLOps | Drift → `model_retrain`: train challenger → quality gate → promote → hot reload | `@champion` mới, không downtime; hoặc giữ champion |
| UC-06 | Rollback model | MLOps | `make rollback` → alias `@champion` về version trước → reload | API phục vụ version cũ trong vài giây |
| UC-07 | Audit fairness & giải thích | Model risk | `make responsible-ai` | Báo cáo DPD/EOD/DI trước–sau mitigation, SHAP + LIME |
| UC-08 | Cảnh báo sự cố | Hệ thống → MLOps | Rule Prometheus → Alertmanager → Telegram / webhook | Thông báo firing + resolved, kèm runbook |
| UC-09 | Release & rollback hạ tầng | MLOps | Tag `v*` → CI → GHCR → deploy Ubuntu → smoke | Release mới, tự rollback khi smoke fail |

## 4. Yêu cầu

Ưu tiên theo **MoSCoW**: **M** = Must (thiếu thì không release), **S** = Should, **C** = Could, **W** = Won't (lần này).

### 4.1 Functional requirements

| ID | Yêu cầu | Ưu tiên | Hiện thực / bằng chứng |
|---|---|---|---|
| FR-01 | API REST versioned chấm điểm một chủ thẻ, trả xác suất + score + quyết định 3 vùng + hạn mức đề xuất | M | `POST /api/v1/predict` — [04 — API](04-api-reference.md) |
| FR-02 | Validate input theo miền giá trị UCI, từ chối field lạ, lỗi có schema chuẩn | M | `serving/schemas.py`, `422 VALIDATION_ERROR` |
| FR-03 | Xác thực bằng API key, hỗ trợ nhiều key để rotate | M | `X-API-Key`, env `API_KEYS`, `401`/`403` |
| FR-04 | Pipeline train tái lập: validate dữ liệu → feature engineering → HPO + CV → so sánh ≥ 3 thuật toán | M | `make train` — [03 — ML pipeline](03-ml-pipeline.md) |
| FR-05 | Experiment tracking + model registry có alias `@champion` | M | MLflow + PostgreSQL + MinIO |
| FR-06 | Model được nạp từ registry, hot reload không downtime, fallback artifact local khi registry down | M | `POST /api/v1/model/reload`, readiness `degraded` |
| FR-07 | Ghi inference log để giám sát và retrain | M | bảng `inference_logs` (PostgreSQL) |
| FR-08 | Metric Prometheus cho HTTP, model, nghiệp vụ và drift; 4 dashboard Grafana | M | [05 — Monitoring](05-monitoring-alerting.md) |
| FR-09 | Alert rule có ngưỡng + runbook, gửi Telegram (fallback webhook nội bộ) | M | 11 alert — [runbook](runbooks/alerts.md) |
| FR-10 | Phát hiện data drift (PSI + Evidently) và prediction drift | M | `services/drift_monitor`, `make drift` |
| FR-11 | Retrain tự động khi drift, quality gate champion/challenger, rollback | M | Airflow `drift_monitoring`, `model_retrain` |
| FR-12 | Giải thích quyết định cho từng chủ thẻ (reason codes cho adverse action notice) | S | `POST /api/v1/explain` (SHAP) |
| FR-13 | Chấm điểm theo lô cho rà soát hạn mức sau kỳ sao kê | S | `POST /api/v1/predict/batch` |
| FR-14 | Audit fairness + mitigation, SHAP + LIME | M | `make responsible-ai` — [06](06-responsible-ai.md) |
| FR-15 | Pseudonymize định danh, retention inference log 90 ngày | S | `responsible_ai.privacy`, `make purge-logs` |
| FR-16 | Giả lập traffic thực tế (normal, drift, attack, load, outage) | S | `make simulate SCENARIO=…` — [kịch bản](guides/scenario-simulation.md) |
| FR-17 | Canary / A-B test nhiều model đồng thời | C | Chưa làm — champion/challenger offline thay thế |
| FR-18 | UI web cho chuyên viên rủi ro | W | Ngoài phạm vi (CMS có sẵn UI) |

### 4.2 Non-functional requirements

| ID | Loại | Yêu cầu | Target | Ưu tiên | Kiểm chứng |
|---|---|---|---|---|---|
| NFR-01 | Hiệu năng | Latency `POST /api/v1/predict` (để luồng tăng hạn mức trên app phản hồi < 1 s) | p95 ≤ 100 ms | M | `make bench`, alert `HighLatencyP95` |
| NFR-02 | Khả dụng | Uptime API | ≥ 99.5 %/tháng; mọi service có healthcheck, `restart` policy | M | `up{job="credit-risk-api"}`, `APIDown` |
| NFR-03 | Tin cậy | Tỷ lệ 5xx trên `/api/v1/*` | < 5 % (cửa sổ 2 phút) | M | `HighErrorRate` |
| NFR-04 | Tin cậy | Registry/DB down không làm API ngừng chấm điểm | degraded nhưng vẫn phục vụ | M | kịch bản 9 |
| NFR-05 | Bảo mật | Không secret trong git/image; container non-root; image không có CVE CRITICAL | 0 CRITICAL | M | `make scan`, `.env.example`, [SECURITY.md](../SECURITY.md) |
| NFR-06 | Bảo mật | Chỉ API + Grafana ra Internet, qua TLS | UFW 22/80/443, port container bind `127.0.0.1` | M | [ubuntu-deployment](guides/ubuntu-deployment.md) |
| NFR-07 | Tái lập | Train lại từ store trống cho metrics giống hệt | seed cố định, data manifest hash | M | `make train` 2 lần |
| NFR-08 | Quan sát | Log JSON có `request_id`, không log PII thô | 0 feature thô trong log | M | `LOG_FORMAT=json` |
| NFR-09 | Chất lượng | Test coverage, 4 loại test + e2e/load | ≥ 80 % | M | `make test-ci` |
| NFR-10 | Triển khai | Dựng toàn bộ stack bằng 1 lệnh; release có rollback | `make up`; `deploy.sh rollback` | M | [local-quickstart](guides/local-quickstart.md) |
| NFR-11 | Tài nguyên | Chạy trên laptop / VPS nhỏ | Docker ≥ 6 GB RAM, idle ≈ 3.0 GB | S | [05 §1](05-monitoring-alerting.md#1-service-profile-cổng-tài-nguyên) |
| NFR-12 | Công bằng | Disparate impact (approval) theo nhóm tuổi sau mitigation | ≥ 0.80 (four-fifths rule) | S | [fairness report](../reports/fairness_report.md) |
| NFR-13 | Mở rộng | Scale ngang API | stateless, scale bằng replica sau reverse proxy | C | [02 §7](02-architecture.md#7-trade-off) |

## 5. Success metrics (3 cấp)

| Cấp | Metric | Target | Hiện tại | Nguồn |
|---|---|---|---|---|
| **Business** | Expected financial loss / chủ thẻ (FN=10, FP=1), normal stream | ≤ 1.10 và không tăng qua mỗi lần promote | **1.0848** | [`model_comparison.json`](../reports/model_comparison.json) |
| Business | Recall lớp vỡ nợ (tỷ lệ phát hiện được chủ thẻ sắp vỡ nợ) | ≥ 0.60 | **0.6213** (holdout) | [`model_comparison.md`](../reports/model_comparison.md) |
| Business | Tỷ lệ tự động hoá (APPROVE + DECLINE, không cần người) | ≥ 40 % | **45.4 %** (REVIEW 54.6 %, 2.500 request normal) | [`reports/simulations/normal_*.json`](../reports/simulations/) |
| Business | Disparate impact (approval) nhóm tuổi sau mitigation | ≥ 0.80 | **0.911** (reweighing), baseline 0.772 | [`fairness_report.md`](../reports/fairness_report.md) |
| **Model** | ROC-AUC holdout / normal stream | ≥ 0.75 / sàn gate ≥ 0.70 | **0.7700 / 0.7519** | [`model_comparison.json`](../reports/model_comparison.json) |
| Model | PR-AUC holdout (lớp dương ~23 %) | ≥ 0.50 | **0.5688** | idem |
| Model | Độ ổn định CV (std ROC-AUC 5 fold) | ≤ 0.02 | **0.0152** | idem |
| Model | Quality gate challenger | ROC-AUC không giảm > 0.005 **và** expected loss không tăng, cải thiện ít nhất một | áp dụng ở `make train`, `make retrain`, DAG `model_retrain` | [`evaluation/model_validation.py`](../src/credit_risk/evaluation/model_validation.py) |
| Model | Drift: PSI feature chính | < 0.10 bình thường; ≥ 0.25 ⇒ drift | normal **0.0226**; Gen-Z **3.34** | [`reports/simulations/`](../reports/simulations/) |
| **System** | Latency p95 `/api/v1/predict` | ≤ 100 ms | **20.59 ms** (500 request, 0 lỗi); 72 ms ở 20 user đồng thời | [`latency_benchmark.json`](../reports/latency_benchmark.json) |
| System | Tỷ lệ lỗi 5xx | < 5 % | 0 % ở traffic normal/drift/attack | [`reports/simulations/`](../reports/simulations/) |
| System | Thời gian phục hồi API sau khi bật lại | ≤ 60 s | **7.1 s** | `reports/simulations/outage_*.json` |
| System | Phát hiện drift (từ lúc traffic lệch tới alert firing) | ≤ 5 phút | ~2–3 phút (phân tích 60 s + `for: 2m`) | [runbook](runbooks/alerts.md#datadriftdetected) |
| System | Test coverage | ≥ 80 % | **91.3 %** (372 pass, 2 skip — JUnit trong `reports/coverage/`) | `reports/coverage/coverage.xml` |
| System | CVE CRITICAL trong image API | 0 | **0** | `make scan` → `reports/security/trivy-report.json` |

## 6. Phạm vi & ràng buộc

**Trong phạm vi:** vòng đời đầy đủ của một model chấm điểm — dữ liệu có version, train + HPO + registry, serving API,
container/orchestration, monitoring/alerting, drift → retrain → promote/rollback, Responsible AI, test + CI/CD,
triển khai một host Ubuntu.

**Ngoài phạm vi:**

- **Duyệt mở thẻ mới / application scoring.** Khách chưa có thẻ thì chưa có hạn mức, sao kê hay 6 tháng lịch sử trả nợ
  mà model cần (18/23 feature không tồn tại lúc đó), và "vỡ nợ kỳ tới" chỉ có nghĩa với người đang có dư nợ.
- **Thu hồi nợ tự động.** Danh sách cảnh báo sớm chỉ để chuyên viên theo dõi và nhắc nợ mềm; hệ thống không tự chuyển
  tài khoản sang thu hồi nợ.
- **Khách hàng doanh nghiệp** (thẻ công ty): dữ liệu chỉ gồm chủ thẻ cá nhân.
- UI cho chuyên viên; tích hợp core banking / credit bureau thật; streaming (Kafka); Kubernetes / multi-host HA; canary
  traffic splitting; quản lý consent khách hàng.

| Ràng buộc | Ảnh hưởng tới thiết kế |
|---|---|
| Dữ liệu công khai UCI (Đài Loan, 2005), không có dữ liệu khách hàng thật | Traffic "production" là replay + persona simulator; nhãn trễ mô phỏng bằng `ground_truth_feedback.csv` |
| Dữ liệu chia theo tuổi (train ≥ 30, drift < 30) để có drift thật | Nhóm < 30 vừa là drift vừa là rủi ro fairness — được audit riêng |
| Nhóm 3–4 người, 4 tuần | Chọn công cụ quen thuộc, boring tech; Docker Compose thay Kubernetes ([ADR 0005](adr/0005-docker-compose-instead-of-kubernetes.md)) |
| Một host (laptop 8 GB hoặc VPS nhỏ) | Compose profiles `core` / `monitoring` / `orchestration`, giới hạn RAM từng service |
| Không có sẵn Telegram token / VPS thật | Webhook receiver nội bộ luôn nhận alert; kiểm chứng Ubuntu bằng VM/container |
| Quy định tín dụng (không phân biệt đối xử, phải giải thích được) | SHAP reason codes, vùng REVIEW có người quyết định, audit fairness trước khi promote |

## 7. Giả định & rủi ro

| Giả định / rủi ro | Giảm thiểu |
|---|---|
| Nhãn trễ: chỉ biết chủ thẻ có vỡ nợ hay không sau 1 kỳ thanh toán kể từ lúc chấm điểm | Retrain dùng feedback đã có nhãn; gate trên tập không dùng để train |
| Drift covariate (tuổi) làm model kém trên nhóm mới | Drift monitor + retrain có gate; theo dõi fairness theo nhóm tuổi |
| Tấn công có tổ chức (dồn dập yêu cầu tăng hạn mức từ tài khoản đang nợ quá hạn) | Alert `PredictionDistributionShift`, dashboard tỷ lệ DECLINE |
| Registry / DB gián đoạn | Fallback artifact local, readiness `degraded`, alert `ModelServedFromFallback` |
| Model mới tệ hơn lọt ra production | Quality gate + `@previous_champion` + `make rollback` |
