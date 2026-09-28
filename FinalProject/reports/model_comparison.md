# Báo cáo so sánh model

> Sinh tự động bởi `make train` (2026-09-28T09:28:59+00:00, session `20260928T092715Z`).
> Không sửa tay — số liệu trong README/docs được render từ `reports/model_comparison.json`.

## Thiết lập

| Mục | Giá trị |
|---|---|
| Dữ liệu train | `reference/train_baseline.csv` — 12000 dòng train + 3000 dòng holdout (stratified 20%) |
| Tập gate champion/challenger | `processed/stream_normal.csv` — 5000 dòng, không dùng để train |
| Data version (manifest fingerprint) | `3df05ace93a33597` (manifest khớp file: True) |
| Cross-validation | StratifiedKFold 5 fold, `random_state=42` |
| HPO | Optuna TPE (seed 42) + MedianPruner, 20 trial/model, objective CV `roc_auc` |
| Decision threshold | 0.5 |
| Cost matrix | FN = 10.0, FP = 1.0 (expected loss = tổng loss / số khách hàng) |
| Feature | 23 feature gốc + 12 feature engineered |

## Kết quả

| Model | CV ROC-AUC (mean ± std) | Holdout ROC-AUC | Holdout PR-AUC | Holdout F1 | Holdout Recall | Holdout expected loss | Normal-stream ROC-AUC | Normal-stream expected loss |
|---|---|---|---|---|---|---|---|---|
| **Logistic Regression** (selected) | 0.7513 ± 0.0152 | 0.7700 | 0.5688 | 0.5314 | 0.6213 | 1.0030 | 0.7519 | 1.0848 |
| Random Forest | 0.7472 ± 0.0114 | 0.7657 | 0.5635 | 0.5312 | 0.5344 | 1.1430 | 0.7474 | 1.2262 |
| XGBoost | 0.7509 ± 0.0127 | 0.7671 | 0.5671 | 0.5318 | 0.5629 | 1.0967 | 0.7556 | 1.1598 |
| LightGBM | 0.7488 ± 0.0123 | 0.7678 | 0.5705 | 0.5226 | 0.5793 | 1.0787 | 0.7549 | 1.1368 |

## Model được chọn: Logistic Regression

Chọn theo CV `roc_auc` cao nhất. Hyper-parameter tốt nhất:

| Param | Giá trị |
|---|---|
| `C` | `0.008433492996539142` |

## Champion/challenger gate — PROMOTE

- no current champion; challenger passes the quality floor

Registry: `credit-risk-model` version **1**; `@champion` = version **1**

## Chi tiết HPO

| Model | Trials | Pruned | Thời gian (s) | Best trial | Cost-optimal threshold (OOF) | MLflow run |
|---|---|---|---|---|---|---|
| Logistic Regression | 20 | 9 | 5.7 | 19 | 0.25 | `c7dffd0d1c3f43ce8376923f46e90cad` |
| Random Forest | 20 | 7 | 44.0 | 15 | 0.26 | `713aa6e2330941cebd49a63d22d569a5` |
| XGBoost | 20 | 8 | 22.4 | 12 | 0.26 | `990f877f3aae4a88af5ffcd810c9bc0d` |
| LightGBM | 20 | 8 | 26.1 | 16 | 0.22 | `9f45b1fa4b4b47adaa53ffac6e208583` |

## Hình minh hoạ

- ROC holdout tất cả model: `reports/figures/roc_comparison.png`
- PR holdout tất cả model: `reports/figures/pr_comparison.png`
- Confusion matrix model được chọn: `reports/figures/confusion_matrix_selected.png`
- Feature importance model được chọn: `reports/figures/feature_importance_selected.png`
