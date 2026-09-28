# Model Card — Credit Default Risk Scoring

> Theo khung *Model Cards for Model Reporting* (Mitchell et al., 2019). Khối số liệu `<!-- rai:… -->` được render từ
> `reports/model_comparison.json` (`make train`) và `reports/fairness_report.json` / `reports/explainability_report.json`
> (`make responsible-ai`) — không sửa tay. Chi tiết phân tích: [06 — Responsible AI](06-responsible-ai.md).

## 1. Thông tin model

<!-- rai:model-details:start -->
| Mục | Giá trị |
|---|---|
| Thuật toán | `logistic_regression` (`C=0.008433492996539142`) |
| Registry version | 1 |
| Artifact | `models/credit_model_v1.joblib` (sha256 `9be37814cad4eab6…`) |
| Decision threshold (nhị phân) | 0.50 |
| Policy serving | APPROVE < 0.30 ≤ REVIEW < 0.60 ≤ DECLINE |

_Sinh tự động bởi `make responsible-ai` (2026-09-28T09:53:21+00:00) — không sửa tay._
<!-- rai:model-details:end -->

- **Kiến trúc:** một `sklearn.Pipeline` duy nhất `FeatureEngineer` (12 feature domain: utilization, payment ratio,
  delinquency…) → `ColumnTransformer` (StandardScaler cho số, OneHotEncoder cho `SEX/EDUCATION/MARRIAGE`, passthrough
  `PAY_*`) → classifier. Cùng object được train, đăng ký MLflow và phục vụ → không có train/serve skew.
- **Chọn model:** 4 ứng viên (Logistic Regression, Random Forest, XGBoost, LightGBM), Optuna TPE + StratifiedKFold 5 fold,
  chọn theo CV ROC-AUC, qua champion/challenger gate trước khi gắn alias `@champion`
  ([báo cáo so sánh](../reports/model_comparison.md)).
- **Class imbalance:** class weighting (`class_weight="balanced"` / `scale_pos_weight`).
- **Đầu ra:** `P(default tháng tới)` → điểm 300–850, hạng (PRIME…HIGH_RISK), quyết định APPROVE/REVIEW/DECLINE, hạn mức
  đề xuất, lý do (SHAP qua `/api/v1/explain`).
- **Chủ sở hữu:** DDM501 Group 5 · **License code:** theo repo · **Liên hệ:** xem `CONTRIBUTING.md`.

## 2. Mục đích sử dụng

| | |
|---|---|
| **Mục đích chính** | Hỗ trợ đánh giá rủi ro vỡ nợ tháng tới của chủ thẻ tín dụng cá nhân để quyết định giữ/tăng/giảm hạn mức |
| **Người dùng** | Chuyên viên tín dụng (duyệt vùng REVIEW), hệ thống phê duyệt tự động cho APPROVE, bộ phận quản trị rủi ro |
| **Chế độ vận hành** | Decision support: REVIEW luôn do người quyết định; DECLINE tự động phải kèm lý do + kênh khiếu nại |

**Ngoài phạm vi (không được dùng):** tuyển dụng, bảo hiểm, nhà ở, marketing nhắm mục tiêu, thu hồi nợ; khách hàng doanh
nghiệp; thị trường/giai đoạn khác Đài Loan 2005 khi chưa validate lại; làm căn cứ *duy nhất* để từ chối tín dụng;
người dưới 18 tuổi (guardrail `age_verification`).

## 3. Factors (yếu tố đánh giá)

- **Nhóm nhạy cảm:** `SEX`, nhóm tuổi (`<30`, `30-39`, `40-49`, `50+`), `EDUCATION`, `MARRIAGE`.
- **Môi trường:** phân phối train chỉ gồm khách hàng ≥ 30 tuổi; lưu lượng production có thể chứa nhóm < 30
  (mô phỏng bởi `stream_drifted`) → drift + disparity theo tuổi.

## 4. Metrics

- **Model:** ROC-AUC (xếp hạng, không phụ thuộc ngưỡng), PR-AUC (lớp dương hiếm), F1/Recall/Precision tại ngưỡng 0.5,
  Brier (calibration).
- **Business:** expected loss / hồ sơ với cost FN = 10, FP = 1 (bỏ sót một người vỡ nợ đắt gấp 10 lần từ chối oan).
- **Fairness:** DPD, EOD, ΔTPR/ΔFPR, approval-rate gap, disparate impact ratio (four-fifths rule).

## 5. Dữ liệu

- **Train:** `data/reference/train_baseline.csv` — 15,000 hồ sơ ≥ 30 tuổi; 80% train / 20% holdout (stratified).
- **Gate/đánh giá:** `data/processed/stream_normal.csv` (5,000, ≥ 30 tuổi, không dùng để train).
- **Đánh giá fairness:** `stream_normal` + `stream_drifted` ghép nhãn trễ (5,000, < 30 tuổi).
- Chi tiết nguồn, license, phân bố, bias đã biết: [Data card](data-card.md).

## 6. Kết quả định lượng

### 6.1 Hiệu năng

<!-- rai:model-performance:start -->
| Tập | ROC-AUC | PR-AUC | F1 | Recall | Precision | Brier | Expected loss |
|---|---|---|---|---|---|---|---|
| Holdout (15k baseline, 20%) | 0.7700 | 0.5688 | 0.5314 | 0.6213 | 0.4642 | 0.1885 | 1.0030 |
| Gate set `stream_normal` | 0.7519 | 0.5447 | 0.5183 | 0.5958 | 0.4586 | 0.1914 | 1.0848 |

CV 5-fold ROC-AUC: 0.7513 ± 0.0152 · session `20260928T092715Z` · nguồn: `reports/model_comparison.json`.

_Sinh tự động bởi `make responsible-ai` (2026-09-28T09:53:21+00:00) — không sửa tay._
<!-- rai:model-performance:end -->

### 6.2 Fairness

<!-- rai:fairness-summary:start -->
| Thuộc tính | DPD | EOD | ΔTPR | ΔFPR | ΔApproval | DI ratio | Trạng thái |
|---|---|---|---|---|---|---|---|
| Giới tính (SEX) | 0.0916 | 0.0973 | 0.0379 | 0.0973 | 0.0697 | 0.7094 | **WARN** (disparate_impact_ratio) |
| Nhóm tuổi (AGE) | 0.1871 | 0.1614 | 0.1087 | 0.1614 | 0.2442 | 0.4076 | **WARN** (demographic_parity_difference, equalized_odds_difference, disparate_impact_ratio) |
| Học vấn | 0.1147 | 0.1052 | 0.0963 | 0.1052 | 0.1088 | 0.5879 | **WARN** (demographic_parity_difference, equalized_odds_difference, disparate_impact_ratio) |
| Hôn nhân | 0.0357 | 0.1159 | 0.1159 | 0.0202 | 0.0154 | 0.9320 | **WARN** (equalized_odds_difference) |

Ngưỡng cảnh báo: DPD > 0.1, EOD > 0.1, disparate impact ratio (approval) < 0.8 (four-fifths rule). DPD/EOD tính trên quyết định nhị phân tại threshold 0.5; approval theo policy serving (APPROVE khi P(default) < 0.3).

_Sinh tự động bởi `make responsible-ai` (2026-09-28T09:53:21+00:00) — không sửa tay._
<!-- rai:fairness-summary:end -->

Mitigation (reweighing, unawareness, ThresholdOptimizer) và trade-off: [06 — mục 4](06-responsible-ai.md#4-mitigation-và-trade-off).

### 6.3 Explainability — feature quan trọng nhất (SHAP)

<!-- rai:explainability-global:start -->
| # | Feature | mean \|SHAP\| (xác suất) | Tỷ trọng |
|---|---|---|---|
| 1 | `PAY_0` | 0.0973 | 17.6% |
| 2 | `PAY_AMT1` | 0.0937 | 16.9% |
| 3 | `LIMIT_BAL` | 0.0563 | 10.2% |
| 4 | `BILL_AMT2` | 0.0467 | 8.4% |
| 5 | `BILL_AMT5` | 0.0355 | 6.4% |
| 6 | `BILL_AMT6` | 0.0344 | 6.2% |
| 7 | `AGE` | 0.0275 | 5.0% |
| 8 | `PAY_2` | 0.0257 | 4.6% |

_Sinh tự động bởi `make responsible-ai` (2026-09-28T09:53:21+00:00) — không sửa tay._
<!-- rai:explainability-global:end -->

Giải thích từng hồ sơ: `POST /api/v1/explain` (SHAP, cộng dồn chính xác về `default_probability`); so sánh SHAP↔LIME
trên 3 hồ sơ mẫu trong [báo cáo explainability](../reports/explainability_report.md).

## 7. Cân nhắc đạo đức

- Model **dùng trực tiếp** `SEX`, `AGE`, `EDUCATION`, `MARRIAGE` làm feature; audit cho thấy disparity vượt ngưỡng, rõ nhất
  theo tuổi. Khuyến nghị challenger "unawareness + reweighing" (xem mục 4 của tài liệu 06).
- Nhãn phản ánh chính sách tín dụng quá khứ; khách bị từ chối không có nhãn (feedback loop).
- Human-in-the-loop bắt buộc cho REVIEW; DECLINE cần adverse action notice dựa trên SHAP; kênh khiếu nại.
- Privacy: không định danh trực tiếp, log redact, HMAC pseudonymization, inference log giữ 90 ngày.

## 8. Lưu ý và khuyến nghị

- Model là Logistic Regression với regularization mạnh → ổn định, dễ giải thích, nhưng trần ROC-AUC ~0.75–0.77 trên
  dataset này (các model cây không tốt hơn đáng kể).
- Ngưỡng 0.5 không phải ngưỡng tối ưu chi phí (cost-optimal OOF thấp hơn, xem báo cáo so sánh); policy serving dùng
  0.30/0.60 cho 3 mức.
- Mỗi lần retrain/đổi ngưỡng: chạy `make responsible-ai` để cập nhật card này (khối số liệu tự refresh) và rà soát
  trạng thái fairness trước khi promote.
