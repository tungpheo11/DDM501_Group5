# 🚀 Đề Án Tốt Nghiệp MLOps: Hệ Thống Giám Sát, Phát Hiện Lệch Dữ Liệu (Drift) & Tự Động Tái Huấn Luyện Khép Kín
> **Môn học**: DDM501 — AI in DevOps, DataOps, MLOps  
> **Tỷ trọng đồ án**: **30% Machine Learning · 70% MLOps & Continuous Operations**  
> **Mục tiêu cốt lõi**: Xây dựng một chu trình MLOps hoàn chỉnh (Closed-Loop Continuous Training & Delivery) với bài toán Machine Learning dạng bảng (Tabular Data) thực tế, có bộ dữ liệu rõ ràng, kịch bản biến động dữ liệu (Drift) trực quan, cơ chế 3 ngưỡng đánh giá chuẩn công nghiệp, kích hoạt tự động Airflow Retraining và triển khai mô hình an toàn (Canary/Blue-Green Deployment).

---

## 🎯 1. Chiến Lược Chọn Chủ Đề & Dữ Liệu Thực Tế

Thầy đã nhấn mạnh: **ML chỉ chiếm 30%** (không cần giải thuật quá phức tạp, quan trọng là có dữ liệu chuẩn, bài toán thực tế), **70% còn lại là toàn bộ tầng vận hành MLOps**.

### Chủ đề chính thức:
> **Hệ Thống Đánh Giá Rủi Ro Tín Dụng & Khả Năng Vỡ Nợ Thời Gian Thực (FinTech Real-time Credit Default Risk Engine)**  
> *(Kịch bản song hành: Dự đoán Khách hàng rời bỏ dịch vụ viễn thông - Telco Churn)*

### Bộ dữ liệu sử dụng:
* **Tên dataset**: **Default of Credit Card Clients Dataset** (từ UCI Machine Learning Repository / Kaggle - 30.000 dòng, 24 đặc trưng).
* **Đặc trưng chính**:
  * *Nhân khẩu học*: `AGE` (Độ tuổi), `SEX` (Giới tính), `EDUCATION` (Trình độ học vấn), `MARRIAGE` (Tình trạng hôn nhân).
  * *Tài chính & Tín dụng*: `LIMIT_BAL` (Hạn mức tín dụng được cấp).
  * *Lịch sử thanh toán qua các tháng*: `PAY_0` đến `PAY_6` (Tình trạng trả đúng hạn hay trễ 1, 2, 3... tháng).
  * *Lịch sử sao kê & số tiền đã thanh toán*: `BILL_AMT1` đến `BILL_AMT6`, `PAY_AMT1` đến `PAY_AMT6`.
  * *Nhãn mục tiêu (`target`)*: `default_payment_next_month` (1: Vỡ nợ / 0: Trả đủ).

---

## 🚦 2. Giải Mã "3 Cái Ngưỡng" Của Giảng Viên (Traffic Light Monitoring System)

Trong giám sát mô hình (Model Monitoring), hệ thống không dùng 1 con số nhị phân cứng nhắc (Đúng / Sai), mà luôn sử dụng **Hệ thống 3 ngưỡng đèn giao thông (Traffic Light Rules)** để quyết định hành động:

```
[Phân Tích Dữ Liệu Mới] ──► So sánh với Baseline qua PSI / p-value
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
  [Ngưỡng 1: XANH]            [Ngưỡng 2: VÀNG]            [Ngưỡng 3: ĐỎ]
     PSI < 0.10               0.10 <= PSI < 0.25            PSI >= 0.25
(An toàn - Hoạt động)      (Cảnh báo - Tăng giám sát)  (Báo động đỏ - Auto Retrain)
```

### Cách 1: Chỉ số Ổn định Dân số — PSI (Population Stability Index) *(Chuẩn FinTech & Ngân hàng)*
Chỉ số PSI đo mức độ phân kỳ phân phối giữa dữ liệu huấn luyện gốc ($P_{ref}$) và dữ liệu production gần nhất ($P_{curr}$):
1. **Ngưỡng 1: $\text{PSI} < 0.10$ (Vùng Xanh - Safe)**:
   * **Hiện trạng**: Không có sự dịch chuyển dữ liệu đáng kể. Dữ liệu thực tế và dữ liệu train gần như trùng khớp.
   * **Hành động**: Hệ thống giữ nguyên trạng thái, phục vụ bình thường.
2. **Ngưỡng 2: $0.10 \le \text{PSI} < 0.25$ (Vùng Vàng - Moderate Drift / Warning)**:
   * **Hiện trạng**: Bắt đầu có sự dịch chuyển hành vi (ví dụ: nhóm khách hàng trẻ tuổi bắt đầu xuất hiện rải rác, hoặc có biến động nhẹ theo chu kỳ tuần/tháng).
   * **Hành động**: **Chưa kích hoạt Retrain ngay** (để tránh lãng phí tài nguyên và retrain vội vàng khi chưa đủ mẫu), nhưng hệ thống sẽ:
     * Gửi tin nhắn cảnh báo lên Slack/Discord và bật cờ Warning trên Grafana.
     * Tăng tần suất quét dữ liệu (ví dụ từ 24h/lần &rarr; 4h/lần).
3. **Ngưỡng 3: $\text{PSI} \ge 0.25$ (Vùng Đỏ - Significant Drift / Critical Alert)**:
   * **Hiện trạng**: Dữ liệu đã lệch nghiêm trọng. Mô hình hiện tại đang dự đoán trong vùng "mù" (Out of Distribution).
   * **Hành động**: **Kích hoạt Vòng lặp Khẩn cấp (Emergency Retraining Loop)**: Bắn Webhook sang Apache Airflow để tự động kích hoạt pipeline huấn luyện lại ngay lập tức!

---

### Cách 2: Ngưỡng Kiểm Định Thống Kê (p-value & Share of Drifted Features trong Evidently AI)
Khi sử dụng thư viện **Evidently AI**, hệ thống thực hiện kiểm định Kolmogorov-Smirnov (KS-test) tính $p$-value cho từng cột liên tục (`AGE`, `LIMIT_BAL`...) và Chi-Square/PSI cho cột phân loại (`PAY_0`...):
* **Từng cột**: Nếu $p\text{-value} < 0.05$ &rarr; Cột đó bị xác nhận là có Drift.
* **Tổng thể mô hình (3 Ngưỡng)**:
  * **Xanh (Safe)**: Tỷ lệ cột bị drift $< 20\%$ &rarr; An toàn.
  * **Vàng (Warning)**: Tỷ lệ cột bị drift từ $20\% - 40\%$ &rarr; Bắn cảnh báo lên Grafana.
  * **Đỏ (Critical)**: Tỷ lệ cột bị drift $> 40\%$ (hoặc một cột trọng yếu như `AGE` hoặc `LIMIT_BAL` bị drift với $p < 0.001$) &rarr; Gửi Webhook sang Airflow kích hoạt Retraining.

---

## 📊 3. Chiến Lược Phân Tách Dữ Liệu Tạo "Kịch Bản Đời Thực"

Để chứng minh hệ thống hoạt động thực thụ cho thầy thấy, chúng ta chia 30,000 dòng dữ liệu thành **4 tệp phân vùng thời gian/hành vi**:

```
[30,000 Records UCI Credit Default Dataset]
        │
        ├── 1. [15,000 records]  train_baseline.csv  ───> Huấn luyện Model V1.0 ban đầu (Nhóm khách hàng truyền thống: Tuổi 30-50, hạn mức cao)
        │
        ├── 2. [5,000 records]   stream_normal.csv   ───> Giả lập User traffic tháng 1 (Phân phối tương đồng baseline, F1 ~ 0.78, PSI < 0.1)
        │
        ├── 3. [5,000 records]   stream_drifted.csv  ───> GIẢ LẬP SỰ CỐ: Chiến dịch Marketing hút nhóm Gen-Z (18-24 tuổi)
        │                                                 --> Lệch phân phối AGE, LIMIT_BAL và độ trễ thanh toán PAY_0 (PSI >= 0.25)
        │
        └── 4. [5,000 records]   ground_truth_feedback.csv ─> Dữ liệu dán nhãn thực tế sau 30 ngày dùng để GHÉP NHÃN và RETRAINING
```

---

## 🔄 4. Chi Tiết Toàn Bộ Vòng Lặp Khép Kín 6 Giai Đoạn

```
[Phase 1: Baseline Data] ──► [Phase 2: Train Model V1] ──► [Phase 3: Deploy FastAPI & Log DB]
                                                                        │
                                                                        ▼ (Inference Traffic)
[Phase 6: Canary Rollout] ◄── [Phase 5: Airflow Retrain] ◄── [Phase 4: Evidently & Prometheus Monitor]
```

---

### 🟢 Giai đoạn 1: Chuẩn bị & Tiền xử lý Dữ liệu gốc (Day 0)
1. **Lấy 15.000 dòng đầu tiên** lưu thành `train_baseline.csv` làm tập tham chiếu chuẩn (Reference Dataset), đẩy lên MinIO S3.
2. **Tiền xử lý (Preprocessing Pipeline)**:
   * Số thực (`LIMIT_BAL`, `BILL_AMT`, `PAY_AMT`): Chuẩn hóa bằng `StandardScaler()`.
   * Phân loại (`EDUCATION`, `MARRIAGE`): Mã hóa bằng `OneHotEncoder(handle_unknown='ignore')`.
   * Thứ bậc (`PAY_0` đến `PAY_6`): Giữ nguyên thứ tự trễ hạn.

### 🏋️ Giai đoạn 2: Huấn luyện, Gán nhãn Model V1.0 & Đăng ký MLflow
1. **Huấn luyện**: Chạy LightGBM / XGBoost trên 15.000 dòng `train_baseline.csv`.
2. **Đánh giá ban đầu**: Đạt $ROC\text{-}AUC = 0.82$, $F1 = 0.78$.
3. **MLflow Registry**:
   * Log hyperparameters, metrics, model signature.
   * Lưu artifact `model.pkl` lên MinIO S3.
   * Đăng ký vào Model Registry với alias: **`@champion` (Version 1)**.

### 🚀 Giai đoạn 3: Triển khai Serving & Cơ Chế Ghi Nhận Logs (Cội nguồn của Monitoring)
* **Vấn đề cốt lõi**: *"Không có log thì không thể đo drift!"*.
1. FastAPI khởi động, tự động kéo model `@champion` từ MLflow/S3 về RAM.
2. Khi Client gọi `POST /predict` với thông tin khách hàng:
   * Model tính toán và trả về kết quả dự đoán (0: An toàn / 1: Vỡ nợ) kèm xác suất (`probability`).
   * **Cơ chế ghi nhận log tức thì**: FastAPI lưu ngay một dòng vào bảng `inference_logs` trong PostgreSQL:
     ```sql
     INSERT INTO inference_logs (request_id, timestamp, features_json, prediction, probability)
     VALUES ('req_123', NOW(), '{"age": 22, "limit_bal": 20000, ...}', 1, 0.88);
     ```
   * Đồng thời gửi metric RPS và Latency sang **Prometheus**.

### 🕵️ Giai đoạn 4: Giám Sát & Bắt Độ Lệch Khi Có Độ Trễ Nhãn (Ground-Truth Delay)
* **Vấn đề thực tế**: Khi khách hàng quẹt thẻ hôm nay, **30 ngày sau** ta mới biết họ có trả nợ hay không (độ trễ nhãn). Trong 30 ngày đó, làm sao biết model đang suy giảm chất lượng?
* **Giải pháp 2 tầng giám sát**:
  1. **Tầng 1 - Giám sát sớm (Early Drift Detection)**: Đo **Data Drift** (Input) và **Prediction Drift** (Output). Nếu tỷ lệ model dự đoán vỡ nợ tăng vọt bất thường hoặc tuổi khách hàng giảm mạnh &rarr; Chắc chắn có vấn đề!
  2. **Tầng 2 - Giám sát muộn (Performance Drift)**: Khi đã có nhãn thực tế sau 30 ngày &rarr; Tính lại F1 và Accuracy.
* **Kịch bản bắt Drift**:
  1. Chạy script `simulate_genz_drift.py` đẩy 5.000 requests khách hàng trẻ tuổi vào FastAPI.
  2. Service **Evidently AI** định kỳ quét 1.000 bản ghi mới nhất từ `inference_logs` và so sánh với `train_baseline.csv`.
  3. Evidently phát hiện `AGE` rớt từ 38 xuống 21 ($p < 0.001$), `LIMIT_BAL` giảm mạnh ($p < 0.001$).
  4. Chỉ số **$\text{PSI} = 0.32 > 0.25$ (Vượt ngưỡng ĐỎ!)**.
  5. Evidently xuất báo cáo `drift_report.html` lên S3, đẩy metric `data_drift_alert=1` sang Prometheus, và bắn HTTP Webhook kích hoạt **Airflow DAG**.

### 🔄 Giai đoạn 5: Xử Lý Dữ Liệu Vòng 2 Cho Tái Huấn Luyện (Data Processing for Retraining)
Khi Airflow nhận lệnh, pipeline tự động xử lý dữ liệu như sau:
1. **Ghép nhãn (Label Joining)**:
   * Airflow truy vấn 5.000 bản ghi trong `inference_logs`.
   * Đọc tệp `ground_truth_feedback.csv` (kết quả thanh toán sau 30 ngày).
   * Thực hiện phép **JOIN** theo `request_id` để tạo tập dữ liệu hoàn chỉnh gồm đủ Features + Ground-truth Label.
2. **Làm giàu dữ liệu (Data Augmentation / Sliding Window)**:
   * Hợp nhất: **15.000 dòng cũ (`train_baseline`) + 5.000 dòng mới vừa ghép nhãn = 20.000 dòng**.
   * Nhờ đó, mô hình mới vừa giữ được tri thức về khách hàng truyền thống, vừa học được hành vi của nhóm khách hàng trẻ Gen-Z.
3. **Thẩm định chất lượng dữ liệu (Data Quality Gate)**:
   * Kiểm tra schema, tỷ lệ missing values ($< 5\%$), không có giá trị ngoại lai vô lý trước khi đưa vào huấn luyện.

### 🏆 Giai đoạn 6: Airflow Huấn Luyện, Quality Gate & Triển Khai Canary An Toàn
1. **Huấn luyện Model V2.0**: Chạy huấn luyện trên 20.000 dòng dữ liệu mới.
2. **Quality Gate (Cánh cổng chất lượng)**:
   * Đánh giá mô hình cũ (V1.0) và mô hình mới (V2.0) trên cùng tập dữ liệu mới:
     * $F1_{V1.0}$: tụt còn **0.58** (do bị drift).
     * $F1_{V2.0}$: đạt **0.82** (đã thích ứng).
   * **Điều kiện thông qua**: $F1_{V2.0} > F1_{V1.0} + 0.05$.
3. **Đăng ký MLflow**: Đăng ký Model V2.0 với nhãn **`@challenger`**.
4. **Triển khai Canary (90/10 Traffic Split)**:
   * API Gateway phân luồng: **90% traffic vào Model V1 (`@champion`)**, **10% traffic vào Model V2 (`@challenger`)**.
   * Màn hình Grafana A/B Testing theo dõi song song latency và tỷ lệ lỗi 5xx.
5. **Thăng cấp hoàn tất (Promote to Champion)**:
   * Sau khi kiểm chứng an toàn, thăng cấp Version 2 thành `@champion`. Toàn bộ 100% traffic chuyển sang dùng Model mới mà không hề có 1 giây gián đoạn (Zero Downtime).

---

## 🏛️ 5. Sơ Đồ Kiến Trúc Hệ Thống (End-to-End MLOps Architecture)

```mermaid
flowchart TD
    subgraph ServingAndGateway ["1. Lớp Phục Vụ & Phân Luồng Traffic (Canary Delivery)"]
        ClientReq([Client Traffic / User Requests]) --> Gateway{API Gateway / NGINX / Traefik<br/>Canary Traffic Splitter}
        Gateway -->|90% Traffic| ChampionAPI["FastAPI: Champion Model (@champion - V1.0)"]
        Gateway -->|10% Traffic| ChallengerAPI["FastAPI: Challenger Model (@challenger - V2.0)"]
        ChampionAPI --> InferenceDB[(Production Inference Logs DB<br/>PostgreSQL)]
        ChallengerAPI --> InferenceDB
    end

    subgraph ObservabilityLayer ["2. Lớp Giám Sát Hệ Thống & Đo Lường Drift (70% Trọng Tâm)"]
        ChampionAPI -.->|Expose /metrics| Prometheus["Prometheus Server"]
        ChallengerAPI -.->|Expose /metrics| Prometheus
        Prometheus --> Grafana["Grafana Unified Dashboard<br/>(RPS, Latency, Data Drift, Drift Alerts)"]
        
        InferenceDB -->|Periodic Batch Scan| Evidently["Evidently AI Drift Monitoring Service<br/>(KS-Test, Wasserstein, PSI, Data Quality)"]
        Evidently -->|Push 3-Threshold Gauges| Prometheus
        Evidently -->|Sinh Báo Cáo HTML Trực Quan| S3[(MinIO S3 Artifacts)]
    end

    subgraph RetrainingLoop ["3. Vòng Lặp Tự Động Phục Hồi (Continuous Training Loop)"]
        Evidently -->|Webhook Trigger khi PSI >= 0.25 (ĐỎ)| Airflow["Apache Airflow 3.x Orchestrator"]
        Airflow --> T1["Task 1: Ingest Logs & Join Ground-Truth Labels"]
        T1 --> T2["Task 2: Data Quality & Schema Gate"]
        T2 --> T3["Task 3: Retrain Model V2.0 trên 20,000 records"]
        T3 --> T4{"Task 4: Quality Gate<br/>F1_v2 > F1_v1 + 5%?"}
        T4 -->|Passed| T5["Task 5: Register Model to MLflow as @challenger"]
        T5 --> Gateway
    end

    subgraph GovernanceLayer ["4. Quản Lý Phiên Bản & Lưu Trữ (MLflow + S3)"]
        T3 -.->|Log Parameters, Metrics & Artifacts| MLflow["MLflow 3.x Model Registry"]
        MLflow --> MetaDB[(Postgres Metadata)]
        MLflow --> S3
    end

    subgraph CICDLayer ["5. Tích Hợp & Triển Khai Liên Tục (GitHub Actions)"]
        GitHub[Push Code to GitHub] --> Actions["GitHub Actions CI Pipeline"]
        Actions --> Lint[Linting: flake8]
        Actions --> Test[Unit & Drift Tests: pytest]
        Actions --> DockerBuild[Build Unified Docker Images]
    end
```

---

## 🎬 6. Kịch Bản Trình Bày Live Demo Cho Giảng Viên (15 Phút "Gây Choáng Ngợp")

| Thời gian | Nhóm trình chiếu / Thao tác | Hiện tượng diễn ra trên hệ thống | Giá trị chứng minh với Thầy |
| :---: | :--- | :--- | :--- |
| **00:00 - 03:00** | Bật terminal: `docker compose up -d`. Mở `docker compose ps` cho thầy thấy 8 services đang chạy trơn tru. | Toàn bộ stack khởi động: API, Postgres, MinIO, MLflow, Airflow, Prometheus, Grafana, Evidently. | Kỹ năng đóng gói hạ tầng DevOps/MLOps hoàn hảo, 1-click deployment. |
| **03:00 - 06:00** | Chạy script: `python scripts/simulate_normal_traffic.py`. Mở Grafana Dashboard. | Requests tăng đều, Latency < 40ms, PSI < 0.1, Evidently hiển thị trạng thái `Drift Status: OK (Green)`. | Hệ thống phục vụ thời gian thực ổn định ở điều kiện bình thường. |
| **06:00 - 09:00** | **Tạo sự cố (The Shock)**: Chạy `python scripts/simulate_genz_marketing_drift.py`. | **Bảng điều khiển Grafana đổi màu**: Biểu đồ phân phối tuổi lệch hẳn; PSI nhảy lên 0.32; Evidently cắm cờ đỏ; Prometheus kích hoạt alert `ALERT: CriticalDataDriftDetected`. | Khả năng quan sát (Observability) và áp dụng đúng hệ thống 3 ngưỡng phát hiện sự cố. |
| **09:00 - 12:00** | Không thao tác gì cả, bảo thầy nhìn vào Airflow UI. | **DAG Retraining tự động được bật chạy** do nhận Webhook từ Evidently. Các task chạy xanh lần lượt: Ghép nhãn &rarr; Quality Gate &rarr; Train V2 &rarr; So sánh F1 &rarr; Đăng ký MLflow `@challenger`. | Chu trình khép kín tự phục hồi (Self-healing Loop), đúng chuẩn triết lý MLOps. |
| **12:00 - 15:00** | Mở MLflow xem Model Version 2. Kiểm tra API Gateway đang chia luồng Canary 90/10. Gửi 1 sample khách hàng trẻ tuổi để thấy Model V2 dự đoán chuẩn xác. | Khách hàng trẻ tuổi được chấm điểm đúng rủi ro, hệ thống sẵn sàng thăng cấp Model V2 lên 100% traffic không gián đoạn. | Triển khai an toàn chuẩn doanh nghiệp (Safe Deployment / Zero Downtime). |
