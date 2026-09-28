# Data

| Thư mục | File | Vai trò |
|---|---|---|
| `raw/` | `credit_default.csv` (30.000 × 24) | Bản gốc UCI Credit Card Default |
| `reference/` | `train_baseline.csv` (15.000) | Nhóm AGE ≥ 30 — dữ liệu train baseline và reference cho drift |
| `processed/` | `stream_normal.csv` (5.000) | Traffic production không drift (AGE ≥ 30) |
| `processed/` | `stream_drifted.csv` (5.000) | Traffic Gen-Z (AGE < 30), không có label |
| `processed/` | `ground_truth_feedback.csv` (5.000) | Label trễ cho `stream_drifted` (join theo `request_id`) |

- Tái tạo partition (deterministic, `random_state=42`): `make data`.
- `manifest.json` ghi SHA-256, số dòng, cột, nguồn của từng file và `fingerprint` (phiên bản dữ liệu) — cập nhật bằng `make manifest`; `tests/data_quality` fail nếu file lệch hash. Mỗi run training log manifest vào MLflow (tag `data_version` = fingerprint) để truy vết lineage.
- Schema (kiểu, miền giá trị, null, tỷ lệ default 10–40%) kiểm tra bằng pandera: `make validate` → `reports/data_validation.json`; `make train`/retrain dừng ngay nếu dữ liệu vi phạm.
- Data card đầy đủ: [`docs/data-card.md`](../docs/data-card.md).
