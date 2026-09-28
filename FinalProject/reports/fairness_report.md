# Báo cáo Fairness

> Sinh tự động bởi `make responsible-ai` (2026-09-28T09:53:21+00:00). Không sửa tay — số liệu trong docs được render từ `reports/fairness_report.json`.

## Thiết lập

| Mục | Giá trị |
|---|---|
| Thuật toán | `logistic_regression` (`C=0.008433492996539142`) |
| Registry version | 1 |
| Artifact | `models/credit_model_v1.joblib` (sha256 `9be37814cad4eab6…`) |
| Decision threshold (nhị phân) | 0.50 |
| Policy serving | APPROVE < 0.30 ≤ REVIEW < 0.60 ≤ DECLINE |

- Tập đánh giá: 10,000 hồ sơ chưa từng dùng để train (`stream_normal` 5,000, `stream_drifted+feedback` 5,000); default rate 24.3%, ROC-AUC 0.7513, APPROVE 21.3%.
- Cost matrix: FN = 10.0, FP = 1.0 (expected loss = tổng loss / số hồ sơ).

## Tổng quan theo thuộc tính nhạy cảm

| Thuộc tính | DPD | EOD | ΔTPR | ΔFPR | ΔApproval | DI ratio | Trạng thái |
|---|---|---|---|---|---|---|---|
| Giới tính (SEX) | 0.0916 | 0.0973 | 0.0379 | 0.0973 | 0.0697 | 0.7094 | **WARN** (disparate_impact_ratio) |
| Nhóm tuổi (AGE) | 0.1871 | 0.1614 | 0.1087 | 0.1614 | 0.2442 | 0.4076 | **WARN** (demographic_parity_difference, equalized_odds_difference, disparate_impact_ratio) |
| Học vấn | 0.1147 | 0.1052 | 0.0963 | 0.1052 | 0.1088 | 0.5879 | **WARN** (demographic_parity_difference, equalized_odds_difference, disparate_impact_ratio) |
| Hôn nhân | 0.0357 | 0.1159 | 0.1159 | 0.0202 | 0.0154 | 0.9320 | **WARN** (equalized_odds_difference) |

Ngưỡng cảnh báo: DPD > 0.1, EOD > 0.1, disparate impact ratio (approval) < 0.8 (four-fifths rule). DPD/EOD tính trên quyết định nhị phân tại threshold 0.5; approval theo policy serving (APPROVE khi P(default) < 0.3).

![Group metrics](figures/rai_fairness_group_metrics.png)

## Chi tiết theo nhóm

### Giới tính (SEX)

| Nhóm | n | Default rate | APPROVE | REVIEW | DECLINE | TPR | FPR | ROC-AUC | Expected loss |
|---|---|---|---|---|---|---|---|---|---|
| female | 6,107 | 23.4% | 24.0% | 55.1% | 20.9% | 0.608 | 0.212 | 0.758 | 1.080 |
| male | 3,893 | 25.8% | 17.0% | 57.8% | 25.2% | 0.646 | 0.310 | 0.739 | 1.144 |

### Nhóm tuổi (AGE)

| Nhóm | n | Default rate | APPROVE | REVIEW | DECLINE | TPR | FPR | ROC-AUC | Expected loss |
|---|---|---|---|---|---|---|---|---|---|
| <30 | 5,000 | 25.8% | 16.8% | 58.1% | 25.1% | 0.648 | 0.292 | 0.749 | 1.125 |
| 30-39 | 3,263 | 24.8% | 21.4% | 56.5% | 22.1% | 0.618 | 0.235 | 0.748 | 1.124 |
| 40-49 | 1,310 | 20.4% | 31.5% | 51.5% | 17.0% | 0.539 | 0.174 | 0.753 | 1.077 |
| 50+ | 427 | 15.7% | 41.2% | 45.0% | 13.8% | 0.552 | 0.131 | 0.742 | 0.813 |

### Học vấn

| Nhóm | n | Default rate | APPROVE | REVIEW | DECLINE | TPR | FPR | ROC-AUC | Expected loss |
|---|---|---|---|---|---|---|---|---|---|
| graduate_school | 3,504 | 23.1% | 26.4% | 53.8% | 19.8% | 0.590 | 0.206 | 0.756 | 1.103 |
| high_school | 1,598 | 26.2% | 15.5% | 58.7% | 25.8% | 0.687 | 0.311 | 0.765 | 1.049 |
| others | 162 | 26.5% | 19.8% | 58.0% | 22.2% | 0.674 | 0.252 | 0.800 | 1.049 |
| university | 4,736 | 24.6% | 19.4% | 57.0% | 23.5% | 0.622 | 0.262 | 0.741 | 1.126 |

### Hôn nhân

| Nhóm | n | Default rate | APPROVE | REVIEW | DECLINE | TPR | FPR | ROC-AUC | Expected loss |
|---|---|---|---|---|---|---|---|---|---|
| married | 4,595 | 24.7% | 21.1% | 56.1% | 22.8% | 0.623 | 0.253 | 0.747 | 1.122 |
| others | 137 | 27.7% | 22.6% | 51.1% | 26.3% | 0.737 | 0.232 | 0.791 | 0.898 |
| single | 5,268 | 23.9% | 21.4% | 56.4% | 22.2% | 0.621 | 0.247 | 0.754 | 1.095 |

![Decisions by age group](figures/rai_decisions_by_age_group.png)

## Mitigation — trước / sau

Tất cả biến thể được đánh giá trên cùng test split (50% tập đánh giá, stratified theo nhóm × nhãn). `retrained`/`reweighing`/`unawareness` fit lại cùng thuật toán + hyper-parameter của champion trên train split baseline + fit split; `threshold_optimizer` hậu xử lý champion với ngưỡng theo nhóm (equalized_odds, balanced_accuracy_score) fit trên fit split. ROC-AUC của ThresholdOptimizer tính trên xác suất trộn ngẫu nhiên nên thấp hơn tự nhiên.

**Nhóm tuổi (AGE)** — test split 5,000 dòng (fit split 5,000 dòng)

| Biến thể | ROC-AUC | Expected loss | Recall | DPD | EOD | DI ratio (nhị phân) |
|---|---|---|---|---|---|---|
| Champion (không mitigation) | 0.7599 | 1.0734 | 0.635 | 0.1817 | 0.1461 | 0.772 |
| Retrained (đối chứng) | 0.7599 | 1.0906 | 0.624 | 0.1784 | 0.1420 | 0.778 |
| Reweighing | 0.7593 | 1.1302 | 0.600 | 0.0672 | 0.0694 | 0.911 |
| Unawareness | 0.7585 | 1.1346 | 0.597 | 0.0549 | 0.0477 | 0.926 |
| ThresholdOptimizer | 0.7137 | 1.1288 | 0.611 | 0.0253 | 0.0835 | 0.963 |

**Giới tính (SEX)** — test split 5,000 dòng (fit split 5,000 dòng)

| Biến thể | ROC-AUC | Expected loss | Recall | DPD | EOD | DI ratio (nhị phân) |
|---|---|---|---|---|---|---|
| Champion (không mitigation) | 0.7401 | 1.1456 | 0.606 | 0.0766 | 0.0885 | 0.890 |
| Retrained (đối chứng) | 0.7392 | 1.1502 | 0.601 | 0.0638 | 0.0707 | 0.909 |
| Reweighing | 0.7379 | 1.1622 | 0.596 | 0.0041 | 0.0451 | 0.994 |
| Unawareness | 0.7364 | 1.1884 | 0.577 | 0.0249 | 0.0257 | 0.965 |
| ThresholdOptimizer | 0.7010 | 1.1604 | 0.594 | 0.0122 | 0.0681 | 0.982 |

DI ratio ở bảng này tính trên quyết định nhị phân (không bị gắn cờ default tại threshold) để so sánh được với ThresholdOptimizer (chỉ cho ra nhãn nhị phân); bảng audit dùng tỷ lệ APPROVE của policy 3 mức.

![Mitigation trade-off](figures/rai_mitigation_tradeoff.png)

Phân tích trade-off và khuyến nghị: xem `docs/06-responsible-ai.md`.
