# 03 — ML pipeline

> Rubric **C. Implementation — ML Pipeline (15%)**: data pipeline (validation, versioning, error handling), model training (nhiều
> thí nghiệm, HPO, cross-validation), experiment tracking (MLflow metrics, params, artifacts). Số liệu trong tài liệu
> này trích từ [`reports/model_comparison.md`](../reports/model_comparison.md) (sinh bởi `make train`).

![Sơ đồ component — ML pipeline](assets/diagrams/04-component-ml-pipeline.svg)

## 1. Tổng quan lệnh

```bash
make data        # chia data/raw → reference/ + processed/ theo tuổi (random_state=42), rồi make manifest
make manifest    # tính lại SHA256 + fingerprint → data/manifest.json
make validate    # pandera trên mọi partition + đối chiếu manifest → reports/data_validation.json (fail fast)
make train       # validate → Optuna 4 thuật toán × 20 trial, 5-fold CV → gate → registry @champion → reports/
make registry    # xem version + alias (@champion, @previous_champion, @challenger)
make retrain     # champion vs challenger trên feedback mới → promote + hot reload API
make rollback    # @champion → @previous_champion (hoặc VERSION=<n>)
make mlflow-ui   # xem store fallback local (mlruns/) khi không chạy stack
```

Với stack Compose đang chạy, `make train` log vào MLflow server (`http://localhost:15040`); không có server thì tự
fallback sang SQLite `mlruns/` (`MLFLOW_LOCAL_FALLBACK`). `N_TRIALS=5 make train` để chạy nhanh khi demo.

## 2. Data pipeline

### 2.1 Nguồn và partition

UCI *Default of Credit Card Clients* — 30.000 chủ thẻ đang lưu hành × 24 cột, không có ô thiếu (chi tiết: [data card](data-card.md)).
`scripts/split_data.py` chia **có chủ đích theo tuổi** để tạo drift thật cho vòng lặp MLOps:

| Partition (`data/…`) | Dòng | Dùng cho |
|---|---|---|
| `raw/credit_default.csv` | 30.000 | Nguồn gốc (read-only) |
| `reference/train_baseline.csv` | 15.000 (tuổi ≥ 30) | Train (12.000) + holdout stratified (3.000); reference của drift monitor |
| `processed/stream_normal.csv` | 5.000 (tuổi ≥ 30) | Tập gate champion/challenger (không dùng train); traffic "bình thường" |
| `processed/stream_drifted.csv` | 5.000 (tuổi < 30), không nhãn | Traffic chiến dịch Gen-Z |
| `processed/ground_truth_feedback.csv` | 5.000 | Nhãn trễ của `stream_drifted` — dùng cho retrain + audit fairness |

### 2.2 Validation (pandera)

`credit_risk.data.validation` kiểm tra trước **mọi** lần train/retrain (fail fast, exit ≠ 0):

- kiểu dữ liệu, cột bắt buộc, không null;
- miền giá trị UCI: `SEX ∈ {1,2}`, `EDUCATION ∈ 0..6`, `MARRIAGE ∈ 0..3`, `AGE 18–100`, `PAY_* ∈ -2..9`, số tiền hữu hạn;
- tỷ lệ default trong khoảng 10–40 % (phát hiện nhãn hỏng);
- `request_id` duy nhất; feature engineered hữu hạn (không `inf`/`NaN` sau khi chia).

Kết quả: [`reports/data_validation.json`](../reports/data_validation.json) — 5/5 dataset PASS, 0 failure, `manifest_hash_match: true`
(target rate: raw 23.3 %, baseline 22.3 %, normal 22.9 %, feedback 25.8 %).

### 2.3 Versioning & lineage

- `data/manifest.json` (v2): SHA256, số dòng, `source`, thời điểm tạo cho từng file + `fingerprint` tổng
  (`3df05ace93a33597` hiện tại).
- `make train` đối chiếu hash thực tế với manifest; lệch ⇒ dừng cho tới khi review và chạy `make manifest`.
- Mỗi MLflow run có tag `data_version` và `data.<file>.sha256`, log manifest + dataset input → từ một model version truy
  ngược được chính xác dữ liệu đã train.

### 2.4 Error handling

| Lỗi | Xử lý |
|---|---|
| Schema / miền giá trị sai | `SchemaErrors` → log từng dòng lỗi, ghi report, exit 1 |
| Manifest lệch | Dừng, thông báo file lệch |
| MLflow không tới được | Log vào `mlruns/` local, vẫn ghi `models/*.joblib` (API dùng làm fallback) |
| Một thuật toán lỗi trong HPO | Trial bị đánh dấu fail/pruned, không làm hỏng các thuật toán khác |
| Challenger kém | Gate từ chối, champion giữ nguyên (không phải lỗi) |

## 3. Feature engineering

`credit_risk.features.FeatureEngineer` là transformer scikit-learn stateless, **nằm trong pipeline model** nên serving
dùng đúng code lúc train (không training/serving skew). 23 feature gốc + 12 feature engineered:

| Nhóm | Feature | Ý nghĩa nghiệp vụ |
|---|---|---|
| Capacity | `utilization_latest`, `utilization_mean`, `utilization_max`, `utilization_trend` | Dư nợ / hạn mức — mức cạn kiệt thẻ và xu hướng |
| Character | `payment_ratio_latest`, `payment_ratio_mean`, `pay_to_limit_ratio`, `zero_payment_months` | Khả năng/thói quen trả nợ so với dư nợ |
| Delinquency | `delay_max`, `delay_recent_mean`, `delay_months`, `delay_trend` | Mức độ và xu hướng trễ hạn (`PAY_*`) |

Sau đó `preprocessing`: StandardScaler cho số, one-hot cho `SEX`/`EDUCATION`/`MARRIAGE`, fit trên train split.

## 4. Training

| Thiết lập | Giá trị (`configs/training.yaml`) |
|---|---|
| Thuật toán | Logistic Regression, Random Forest, XGBoost, LightGBM (class-weighted) |
| HPO | Optuna TPE (seed 42) + MedianPruner, 20 trial/thuật toán (`OPTUNA_N_TRIALS`), objective CV `roc_auc` |
| Cross-validation | StratifiedKFold 5 fold, `shuffle=True`, `random_state=42` |
| Holdout | 20 % stratified từ `train_baseline` |
| Decision threshold | 0.5 (model class-weighted); ngưỡng tối ưu chi phí (OOF) cũng được báo cáo |
| Cost matrix | FN = 10, FP = 1 → expected loss = tổng loss / số chủ thẻ |

Không gian tìm kiếm (`credit_risk.training.models`): LR `C ∈ [1e-3, 10]` log; RF `n_estimators 100–400`,
`max_depth 4–14`, `min_samples_leaf 1–50`, `max_features`, `class_weight`; XGBoost/LightGBM `n_estimators 100–600`,
`learning_rate 0.01–0.15`, độ sâu/`num_leaves`, `subsample`, `colsample_bytree`, `min_child_*`, `reg_lambda`.

### 4.1 Kết quả

Bảng dưới đồng bộ với [`reports/model_comparison.md`](../reports/model_comparison.md) (session `20260928T092715Z`):

| Model | CV ROC-AUC (mean ± std) | Holdout ROC-AUC | Holdout PR-AUC | Holdout F1 | Holdout Recall | Holdout expected loss | Normal-stream ROC-AUC | Normal-stream expected loss |
|---|---|---|---|---|---|---|---|---|
| **Logistic Regression** (selected) | 0.7513 ± 0.0152 | 0.7700 | 0.5688 | 0.5314 | 0.6213 | 1.0030 | 0.7519 | 1.0848 |
| Random Forest | 0.7472 ± 0.0114 | 0.7657 | 0.5635 | 0.5312 | 0.5344 | 1.1430 | 0.7474 | 1.2262 |
| XGBoost | 0.7509 ± 0.0127 | 0.7671 | 0.5671 | 0.5318 | 0.5629 | 1.0967 | 0.7556 | 1.1598 |
| LightGBM | 0.7488 ± 0.0123 | 0.7678 | 0.5705 | 0.5226 | 0.5793 | 1.0787 | 0.7549 | 1.1368 |

**Chọn Logistic Regression** (`C ≈ 0.0084`): CV ROC-AUC cao nhất, expected loss thấp nhất, recall cao nhất; đồng thời
dễ giải thích nhất cho bài toán tín dụng. Các GBM không vượt được LR trên cohort ≥ 30 tuổi (trần ROC-AUC ~0.75–0.77 của
dataset). Hình: [ROC](../reports/figures/roc_comparison.png), [PR](../reports/figures/pr_comparison.png),
[confusion matrix](../reports/figures/confusion_matrix_selected.png),
[feature importance](../reports/figures/feature_importance_selected.png).

**Tái lập:** hai lần `make train` từ store trống cho metrics giống hệt (seed cố định ở split, CV, Optuna, model).

## 5. Experiment tracking (MLflow)

| Loại | Nội dung được log |
|---|---|
| Cấu trúc run | 1 run cha / thuật toán + 1 nested run / trial Optuna (84 run cho một lần `make train` 20 trial) |
| Params | Hyper-parameter, thuật toán, số trial, CV folds, threshold, cost matrix, `random_state` |
| Metrics | CV ROC-AUC mean/std, holdout + normal-stream ROC-AUC, PR-AUC, F1, recall, precision, expected financial loss |
| Artifacts | Model (sklearn pipeline, **signature + input example**), confusion matrix, ROC/PR curve, feature importance, `trials.csv`, `gate/decision.json`, data manifest |
| Tags | `data_version`, `data.<file>.sha256`, `data.<file>.rows` (run); `promotion_reason`, `rolled_back` (model version) |
| Registry | Model `credit-risk-model`; alias `@champion` (đang phục vụ), `@previous_champion` (đích rollback), `@challenger` (ứng viên bị từ chối gần nhất) |

UI: <http://localhost:15040> (stack) hoặc `make mlflow-ui` → <http://localhost:5001> (store local).

## 6. Quality gate champion/challenger

`credit_risk.evaluation.model_validation.compare_champion_challenger` — dùng chung cho `make train`, `make retrain`, DAG
`model_retrain`:

1. Challenger phải đạt sàn **ROC-AUC ≥ 0.70** (`promotion.min_roc_auc`, DAG override `RETRAIN_MIN_ROC_AUC`).
2. ROC-AUC không giảm quá **0.005** so với champion (`max_roc_auc_drop`) **và** expected loss không tăng.
3. Phải cải thiện ít nhất một trong hai (ROC-AUC hoặc expected loss).
4. Đạt ⇒ register version mới, `@previous_champion` ← champion cũ, `@champion` ← challenger, API hot reload.
   Không đạt ⇒ version mới gắn `@challenger`, champion giữ nguyên.

Tập so sánh: `stream_normal` cho `make train`; **phần feedback drifted được giữ lại** (challenger chưa từng thấy) cho
retrain — tránh đánh giá lạc quan.

## 7. Retrain liên tục

`credit_risk.training.retrain.run_retraining_pipeline` (gọi bởi `make retrain` và task `train_challenger` của Airflow):

1. **Replay strategy** chống catastrophic forgetting: 15.000 dòng baseline + feedback có nhãn của stream drifted, validate.
2. Refit đúng thuật toán + hyper-parameter của champion (`models/model_spec.json` do `make train` ghi).
3. Chấm champion và challenger trên phần feedback giữ lại → quality gate (mục 6).
4. Promote + `POST /api/v1/model/reload`; DAG kiểm tra API thực sự phục vụ version mới, sai ⇒ `rollback_champion`.

Kịch bản thực hành: [scenario-simulation §2–§5](guides/scenario-simulation.md). Sequence:
[06-retrain-sequence](assets/diagrams/06-retrain-sequence.svg).

## 8. Kiểm thử liên quan

| Suite | Kiểm tra |
|---|---|
| `tests/data_quality/` | Schema, miền giá trị, manifest hash, cân bằng nhãn |
| `tests/model_validation/` | Champion đạt ngưỡng ROC-AUC / recall / business cost; gate từ chối model kém |
| `tests/unit/` | Validation, feature engineering, tuning, metrics, registry promote/rollback, reporting, train idempotent |

Chi tiết: [07 — Testing & CI/CD](07-testing-cicd.md).
