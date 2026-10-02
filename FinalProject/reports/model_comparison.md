# Báo cáo so sánh model

> Sinh tự động bởi `make train` (2026-10-01T08:27:41+00:00, session `20261001T082709Z`).
> Không sửa tay — số liệu trong README/docs được render từ `reports/model_comparison.json`.

## Thiết lập

| Mục | Giá trị |
|---|---|
| Dữ liệu train | `reference/train_baseline.csv` — 12000 dòng train + 3000 dòng holdout (stratified 20%) |
| Tập gate champion/challenger | `processed/stream_normal.csv` — 5000 dòng, không dùng để train |
| Data version (manifest fingerprint) | `3df05ace93a33597` (manifest khớp file: True) |
| Cross-validation | StratifiedKFold 5 fold, `random_state=42` |
| HPO | Optuna TPE (seed 42) + MedianPruner, 5 trial/model, objective CV `roc_auc` |
| Decision threshold | 0.5 |
| Cost matrix | FN = 10.0, FP = 1.0 (expected loss = tổng loss / số khách hàng) |
| Feature | 23 feature gốc + 12 feature engineered |

## Kết quả

| Model | CV ROC-AUC (mean ± std) | Holdout ROC-AUC | Holdout PR-AUC | Holdout F1 | Holdout Recall | Holdout expected loss | Normal-stream ROC-AUC | Normal-stream expected loss |
|---|---|---|---|---|---|---|---|---|
| **XGBoost** (selected) | 0.7505 ± 0.0130 | 0.7676 | 0.5666 | 0.5319 | 0.5554 | 1.1087 | 0.7545 | 1.1734 |
| LightGBM | 0.7486 ± 0.0138 | 0.7689 | 0.5704 | 0.5309 | 0.5778 | 1.0733 | 0.7543 | 1.1502 |

## Model được chọn: XGBoost

Chọn theo CV `roc_auc` cao nhất. Hyper-parameter tốt nhất:

| Param | Giá trị |
|---|---|
| `colsample_bytree` | `0.7159725093210578` |
| `learning_rate` | `0.02279379523765072` |
| `max_depth` | `2` |
| `min_child_weight` | `2` |
| `n_estimators` | `200` |
| `reg_lambda` | `1.0465133152078552` |
| `scale_pos_weight` | `3.4893` |
| `subsample` | `0.8099025726528951` |

## Champion/challenger gate — GIỮ CHAMPION HIỆN TẠI

- ROC-AUC 0.7545 vs 0.7519 (delta +0.0026)
- expected loss 1.1734 vs 1.0848 (delta +0.0886)
- rejected: expected financial loss is higher than the champion's

Registry: `credit-risk-model` version **20**; `@champion` = version **1**

## Chi tiết HPO

| Model | Trials | Pruned | Thời gian (s) | Best trial | Cost-optimal threshold (OOF) | MLflow run |
|---|---|---|---|---|---|---|
| XGBoost | 5 | 0 | 9.4 | 2 | 0.28 | `389fed620fe9471990b949d33b45c77d` |
| LightGBM | 5 | 0 | 12.2 | 2 | 0.23 | `c2c7f66db3e049fea38a7c4a89d721b8` |

## Hình minh hoạ

- ROC holdout tất cả model: `reports/figures/roc_comparison.png`
- PR holdout tất cả model: `reports/figures/pr_comparison.png`
- Confusion matrix model được chọn: `reports/figures/confusion_matrix_selected.png`
- Feature importance model được chọn: `reports/figures/feature_importance_selected.png`
