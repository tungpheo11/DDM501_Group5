# Hướng dẫn đóng góp (CONTRIBUTING)

> Quy ước kỹ thuật bắt buộc cho mọi thành viên và vai trò từng người ([mục 7](#7-vai-trò-thành-viên)).

## 1. Thiết lập môi trường

```bash
cd FinalProject
make setup          # tạo .venv (uv nếu có, ngược lại venv + pip), cài package editable + dev tools, copy .env
source .venv/bin/activate
make lint test      # phải xanh trước khi mở PR
```

- Python **3.11** (xem `.python-version`); dependency khai báo trong `pyproject.toml`, khoá trong `uv.lock`; `requirements.txt` / `requirements-dev.txt` được **sinh tự động** bằng `make lock` — không sửa tay.
- Pre-commit (chạy từ thư mục gốc git `DDM501_Group5/`):
  `pre-commit install --config FinalProject/.pre-commit-config.yaml`

## 2. Bố cục thư mục

| Thư mục | Nội dung | Quy tắc |
|---|---|---|
| `src/credit_risk/` | Toàn bộ logic Python (package cài đặt được) | Mọi logic tái sử dụng **phải** nằm ở đây |
| `configs/` | YAML cấu hình domain + `environments/<APP_ENV>.yaml` + `logging.yaml` | Không đặt secret trong YAML |
| `scripts/` | Entrypoint mỏng cho `make` | Chỉ: parse args → `setup_logging()` → gọi 1 hàm trong `credit_risk` |
| `simulations/` | Công cụ sinh traffic (persona simulator, kịch bản) | Chỉ gọi API qua HTTP |
| `services/` | Microservice phụ trợ (drift monitor) | Lớp HTTP mỏng, logic dùng lại `credit_risk.*` |
| `orchestration/airflow/` | Dockerfile, DAGs, utils | DAG chỉ điều phối, gọi hàm `credit_risk.*` |
| `deploy/` | `docker/` (Dockerfile), `compose/`, `ubuntu/` | Path trong compose tương đối với file compose |
| `monitoring/` | Prometheus (+rules), Alertmanager, Grafana | Tên metric là contract — đổi phải cập nhật dashboard/rules |
| `data/` | `raw/`, `reference/`, `processed/`, `manifest.json` | Đổi dữ liệu ⇒ `make manifest` |
| `models/` | Artifact `.joblib` fallback cho API khi MLflow down | Chỉ ghi bởi `make train` / `make retrain` |
| `tests/` | `unit/`, `integration/`, `data_quality/`, `model_validation/`, `e2e/`, `load/` | Xem mục 5 |
| `reports/` | Output sinh tự động (drift, coverage, fairness) | Không sửa tay |
| `docs/` | Tài liệu, ADR, guides, QA evidence | Tiếng Việt, thuật ngữ kỹ thuật giữ tiếng Anh |

Sub-package của `credit_risk`:

| Package | Trách nhiệm |
|---|---|
| `config` | `get_settings()` / `load_settings()`, `setup_logging()`, `configure_mlflow_environment()` |
| `data` | schema cột, load/split, chia partition, manifest (data versioning) |
| `features` | preprocessing / feature engineering |
| `training` | pipeline model, train, retrain (champion/challenger), MLflow registry |
| `evaluation` | metrics thống kê, business cost, model validation |
| `responsible_ai` | giải thích, guardrail, fairness, privacy |
| `monitoring` | Prometheus metrics, drift (PSI + Evidently) |
| `serving` | FastAPI app, schemas, model loader, decision engine, inference log DB |
| `utils` | helper không chứa logic domain |

## 3. Quy ước code

- **Ngôn ngữ:** code, tên hàm/biến/file, docstring, comment bằng **tiếng Anh**; tài liệu trong `docs/` bằng tiếng Việt.
- **Naming (PEP 8):** module/hàm/biến `snake_case`, class `PascalCase`, hằng số `UPPER_SNAKE_CASE`. Ngoại lệ duy nhất: tên cột UCI (`LIMIT_BAL`, `PAY_0`…) giữ nguyên vì là contract dữ liệu/API.
- **Type hints** bắt buộc cho mọi hàm trong `src/` (mypy `disallow_untyped_defs`). Dùng cú pháp hiện đại: `list[str]`, `X | None`, `from __future__ import annotations`.
- **Docstring** Google style cho module, class và hàm public: một dòng tóm tắt, sau đó `Args/Returns/Raises` khi không hiển nhiên.
- **Comment** chỉ giải thích ràng buộc/ý đồ không thể hiện được bằng code. **Không** ghi mã ticket/issue vào code, docstring, tên test.
- **Logging:** `logger = get_logger(__name__)`; dùng `%s` placeholder (`logger.info("x=%s", x)`), không f-string trong log call; không `print` trong `src/` (được phép trong `simulations/` và script CLI in kết quả cho người dùng).
- **Cấu hình:** không hard-code URL, ngưỡng, hyperparameter, đường dẫn. Thêm key mới vào YAML tương ứng + dataclass trong `config/settings.py` (+ env override nếu là endpoint/secret) + test trong `tests/unit/test_settings.py`.
- **Hàm nhận `settings: Settings | None = None`** và dùng `settings or get_settings()` để test truyền cấu hình riêng.
- **Exception:** bắt exception cụ thể; `except Exception` chỉ ở ranh giới hệ thống (kết nối DB/MLflow, endpoint API) và phải log lý do.
- **Secret:** chỉ đọc từ biến môi trường; thêm biến mới vào `.env.example` với giá trị giả. Xem `SECURITY.md`.
- Format/lint: `make format` (ruff --fix + black), line length 120.

## 4. Thêm module mới

1. Chọn đúng sub-package theo bảng ở mục 2 (tạo sub-package mới chỉ khi trách nhiệm không khớp — cần ADR nếu ảnh hưởng kiến trúc).
2. Tạo `src/credit_risk/<package>/<module>.py` với module docstring, type hints, không side-effect khi import (không tạo thư mục, không kết nối mạng, không set env ở top-level).
3. Tham số cấu hình → `configs/*.yaml` + `Settings`.
4. Viết test tương ứng trong `tests/unit/test_<module>.py` (và `tests/integration/` nếu chạm API/DB).
5. Cần chạy từ CLI → thêm `scripts/<verb>.py` mỏng + target trong `Makefile` (kèm `## mô tả` để hiện trong `make help`).
6. Quyết định kiến trúc mới/không dễ đảo ngược → thêm ADR `docs/adr/NNNN-<slug>.md` theo `0000-template.md`.
7. Cập nhật `CHANGELOG.md` mục `Unreleased`.

## 5. Kiểm thử

| Suite | Marker | Chạy khi | Ghi chú |
|---|---|---|---|
| `tests/unit/` | — | Mọi lần | Nhanh, không mạng |
| `tests/integration/` | `integration` | Mọi lần | FastAPI `TestClient`, SQLite in-memory |
| `tests/data_quality/` | `data_quality` | Mọi lần | Schema, domain giá trị, manifest hash |
| `tests/model_validation/` | `model_validation` | Mọi lần | Ngưỡng ROC-AUC/recall/business cost của champion |
| `tests/e2e/` | `e2e` | Khi stack Compose chạy | Skip nếu stack không có |
| `tests/load/` | `load` | Thủ công / CI định kỳ | Locust |

- `tests/conftest.py` ép `APP_ENV=test` (hermetic: MLflow trỏ port đóng → fallback model local, DB SQLite in-memory). Không test nào được phụ thuộc service thật trừ `e2e`/`load`.
- Fixture dùng chung: `settings`, `champion_model`, `client`, `valid_payload`.
- Tên file test không cần duy nhất giữa các thư mục (pytest `--import-mode=importlib`).
- Coverage: `make test-cov` (report ở `reports/coverage/`); gate ≥ 80% được áp trong CI.

## 6. Git workflow

- Branch: `feature/<slug>`, `fix/<slug>`, `docs/<slug>` từ `main`; branch tích hợp hiện tại: `feature/final-project-productionize`.
- Commit message dạng Conventional Commits: `feat(serving): add batch endpoint`, `fix(drift): …`, `docs(adr): …`, `test: …`, `chore: …`.
- Không commit secret, `.env`, dữ liệu cá nhân, file > 5 MB (pre-commit chặn).
- PR phải: `make lint test` xanh, mô tả thay đổi + cách kiểm chứng, cập nhật docs/CHANGELOG khi đổi hành vi.
- Mỗi thành viên tự commit/push phần việc của mình từ tài khoản cá nhân sau khi được review.

## 7. Vai trò thành viên

Rubric 3.3 chấm đóng góp cá nhân qua lịch sử commit, Q&A cá nhân và tài liệu vai trò. Mỗi mảng việc có **một owner**
chịu trách nhiệm chính (viết code, trả lời Q&A) và **một reviewer**.

| Mảng việc | Owner | Reviewer | Phạm vi | Tài liệu chịu trách nhiệm | Demo (live) |
|---|---|---|---|---|---|
| **M1 — Data & ML pipeline** | Hòa | Tùng | `data/`, `src/credit_risk/{config,data,features,training,evaluation,utils}`, `scripts/{split_data,build_data_manifest,validate_data,train,retrain,manage_registry}.py`, `tests/{data_quality,model_validation}` | [03](docs/03-ml-pipeline.md), [data card](docs/data-card.md) | `make train`, MLflow UI, kịch bản 3–5 |
| **M2 — Serving, container & CI/CD** | Tùng | Hoa | `src/credit_risk/serving`, `deploy/`, `Makefile`, `.github/workflows/final-project-*.yml`, `tests/integration` | [04](docs/04-api-reference.md), [07](docs/07-testing-cicd.md), [Ubuntu guide](docs/guides/ubuntu-deployment.md), [SECURITY](SECURITY.md) | Swagger, `make up`, kịch bản 6, 8 |
| **M3 — Monitoring, drift & orchestration** | Hoa | Thịnh | `monitoring/`, `services/drift_monitor/`, `orchestration/airflow/`, `src/credit_risk/monitoring`, `simulations/` | [05](docs/05-monitoring-alerting.md), [runbook alert](docs/runbooks/alerts.md), [scenario simulation](docs/guides/scenario-simulation.md), [operations runbook](docs/guides/operations-runbook.md) | Grafana, Airflow, kịch bản 1–2, 7, 9–10 |
| **M4 — Responsible AI, tài liệu & QA** | Thịnh | Hòa | `src/credit_risk/responsible_ai`, `notebooks/`, `docs/`, `tests/{e2e,load}` | [01](docs/01-problem-statement.md), [02](docs/02-architecture.md), [06](docs/06-responsible-ai.md), [model card](docs/model-card.md), README, [QA](docs/qa/README.md), [slide](docs/presentation/README.md) | `/api/v1/explain`, kịch bản 11, dẫn dắt thuyết trình |

Mọi thành viên tham gia live demo theo [demo script](docs/presentation/demo-script.md) và phải trả lời được câu hỏi về
phần mình owner.
