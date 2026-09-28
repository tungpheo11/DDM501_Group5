# ADR-0006: Package `src/credit_risk` (src layout) và cấu hình phân lớp theo môi trường

## Context

Code ban đầu chia thành `src/` (training), `app/` (serving) và `scripts/` (retrain, drift, simulator) với import dạng `from src.config import …`, cần `PYTHONPATH=.` và `sys.path` hack; cấu hình là hằng số module đọc env với default rải rác, tạo thư mục và set biến môi trường S3 ngay khi import. Hệ quả: khó tái sử dụng logic từ Airflow/drift service, test phụ thuộc thư mục chạy, không tách được cấu hình local / docker / test.

## Decision

1. **Một package cài đặt được** `credit_risk` theo src layout (`pip install -e .` / `uv sync`), chia theo domain: `config/`, `data/`, `features/`, `training/`, `evaluation/`, `responsible_ai/`, `monitoring/`, `serving/`, `utils/`.
2. `scripts/` chỉ là **entrypoint mỏng** (parse args → `setup_logging()` → gọi 1 hàm); `simulations/` chứa công cụ sinh traffic.
3. **Cấu hình phân lớp** (`credit_risk.config.settings`): default trong code → `configs/{training,serving,drift}.yaml` → `configs/environments/<APP_ENV>.yaml` (`local`/`docker`/`test`) → biến môi trường (giữ nguyên tên cũ trong `.env.example`). Settings là dataclass bất biến, lấy qua `get_settings()` (cache) hoặc `load_settings()` (mới), truyền tường minh vào hàm để test dễ.
4. **Logging** cấu hình duy nhất qua `configs/logging.yaml` (`setup_logging()`), thay toàn bộ `print` trong library code.
5. **Chất lượng code:** ruff (pycodestyle, pyflakes, isort, pep8-naming, pyupgrade, bugbear, pydocstyle Google), black (line 120), mypy (`disallow_untyped_defs`) — cấu hình trong `pyproject.toml`, chạy qua `make lint` và pre-commit.

## Consequences

- **Tích cực:** import ổn định ở mọi nơi (API container, Airflow, test); test hermetic với `APP_ENV=test` (SQLite in-memory, MLflow unreachable → fallback local) chạy ~10 giây không cần Docker; đổi ngưỡng/hyperparameter không cần sửa code.
- **Tiêu cực:** container phải đặt `PYTHONPATH=/app/src` (hoặc cài package) và `CREDIT_RISK_HOME` khi package không nằm trong cây repo; người đóng góp phải chạy `make setup` trước.
- **Tương thích:** hành vi được chứng minh không đổi bằng snapshot trước/sau (metrics, PSI, response `/predict`, hash dữ liệu) — xem CHANGELOG 1.1.0. Tên metric Prometheus và contract API giữ nguyên.

## Alternatives considered

| Phương án | Ưu điểm | Nhược điểm | Lý do không chọn |
|---|---|---|---|
| Giữ `src/` + `app/` phẳng | Không phải di chuyển | Import mơ hồ (`src` là tên package), sys.path hack | Nợ kỹ thuật cản trở việc dùng lại logic từ Airflow, drift monitor và test |
| Pydantic Settings / Hydra | Validation/override mạnh | Thêm dependency, Hydra thay đổi working dir | Dataclass + YAML đủ dùng, ít phép thuật |
| Chỉ biến môi trường (12-factor thuần) | Đơn giản | Hyperparameter/ngưỡng dài dòng trong `.env`, không review được | YAML cho cấu hình domain, env cho endpoint/secret |
