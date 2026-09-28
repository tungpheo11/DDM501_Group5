# Local quickstart (macOS / Linux)

Mục tiêu: từ máy sạch tới toàn bộ stack (API + MLflow + monitoring + Airflow) chạy healthy và gửi được request đầu tiên
trong khoảng **15–25 phút** (phần lớn là build image lần đầu). Deploy lên server: [ubuntu-deployment.md](ubuntu-deployment.md).

## 1. Yêu cầu

| Thành phần | Phiên bản | Kiểm tra |
|---|---|---|
| OS | macOS 13+ (Intel/Apple Silicon) hoặc Linux x86_64/arm64 | — |
| Docker | Docker Desktop 4.30+ hoặc Docker Engine 25+; **Compose ≥ 2.24.4** | `docker compose version` |
| RAM cho Docker | tối thiểu 6 GB (máy 8 GB), khuyến nghị 8 GB (máy 12–16 GB) | Docker Desktop → Settings → Resources |
| Đĩa trống | ≥ 15 GB | `df -h` |
| Python | 3.11 (chỉ cần cho test/train/simulate chạy trên host) | `python3 --version` |
| Công cụ | `git`, `make`, `curl`; tuỳ chọn `jq`, [`uv`](https://docs.astral.sh/uv/) (cài deps nhanh hơn) | `make --version` |

Các cổng host phải trống: 13000, 15040, 15434, 18020, 18080, 18085, 19040, 19041, 19090, 19093, 19095, 19102
(`lsof -iTCP -sTCP:LISTEN -P | grep -E '1[35-9][0-9]{3}'`). Đổi cổng trong `.env` nếu trùng.

## 2. Cài đặt

```bash
git clone https://github.com/tungpheo11/DDM501_Group5.git
cd DDM501_Group5/FinalProject
make setup          # tạo .venv (uv nếu có, không thì venv + pip) và copy .env.example → .env
source .venv/bin/activate
```

`.env` mặc định dùng giá trị dev (`*-change-me`) — đủ để chạy local. **Không commit `.env`.** Muốn nhận alert qua
Telegram thì điền `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; để trống thì alert vẫn tới receiver webhook nội bộ.

Bật Telegram nhanh (tạo bot, lấy chat id chi tiết ở [05 §5.4](../05-monitoring-alerting.md#54-kênh-telegram)):

1. [@BotFather](https://t.me/BotFather) → `/newbot` → lấy token; thêm bot vào group và gửi một tin trong group.
2. Điền `TELEGRAM_BOT_TOKEN` vào `.env`, rồi lấy chat id:
   `set -a; . ./.env; set +a; curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates" | jq '.result[].message.chat'`.
3. Điền `TELEGRAM_CHAT_ID` vào `.env` → `make up` (stack đang chạy thì compose tự tạo lại `alertmanager` và Airflow).
4. `make alerts-send-test` → group nhận `[FIRING:1] AlertmanagerTest`, 2–3 phút sau nhận `[RESOLVED]`.

## 3. Chạy stack

```bash
make up             # build + up -d, chờ tới khi 15 service healthy (timeout 900 s), in bảng SERVICE/STATUS/PORTS
```

Kết quả mong đợi: mọi service long-running `healthy`, các job one-shot (`minio-init`, `model-bootstrap`,
`airflow-init`) `exited (0)`. `model-bootstrap` tự đăng ký model trong `models/` làm `@champion` nếu registry còn trống,
nên API sẵn sàng ngay mà không cần train.

Chỉ cần API + MLflow (máy yếu): `make up-core` (postgres, minio, mlflow, api — ~1.5 GB RAM).

| Giao diện | URL | Đăng nhập |
|---|---|---|
| Swagger UI | <http://localhost:18020/docs> | nút *Authorize* → `X-API-Key` = giá trị `API_KEYS` trong `.env` |
| MLflow | <http://localhost:15040> | — |
| Grafana | <http://localhost:13000> | `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` |
| Prometheus | <http://localhost:19090> | — |
| Alertmanager | <http://localhost:19093> | — |
| Airflow | <http://localhost:18080> | `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` |
| MinIO console | <http://localhost:19041> | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| Drift monitor | <http://localhost:18085/health> | — |

## 4. Request đầu tiên

```bash
export API_URL=http://localhost:18020
export API_KEY=$(grep -E '^API_KEYS=' .env | cut -d= -f2 | cut -d, -f1)

curl -s $API_URL/health/ready | jq .
# {"status":"ready", ..., "checks":{"model":{"status":"ok","detail":"mlflow_registry version 1"}, ...}}

python scripts/sample_predict.py        # 1 hồ sơ rủi ro thấp + 1 hồ sơ rủi ro cao
```

Hoặc dùng curl với body đầy đủ trong [API reference §2.1](../04-api-reference.md#21-post-apiv1predict). Kết quả mong đợi:
HTTP 200, có `risk_decision`, `credit_score`, `request_id`.

## 5. Vòng làm việc thường gặp

```bash
make test                               # toàn bộ test, không cần Docker (~1–2 phút)
make lint                               # ruff + black --check + mypy
make train                              # 4 thuật toán × 20 trial Optuna → MLflow → reports/ (N_TRIALS=5 để nhanh)
make registry                           # xem version + alias
make simulate SCENARIO=normal           # 600 request bình thường → reports/simulations/
make alerts                             # alert đang firing + notification webhook
make logs SERVICE=api                   # log một service
make down                               # dừng, giữ dữ liệu · make down-v: xoá sạch volume
```

11 kịch bản vận hành (drift → retrain, rollback, sự cố...): [scenario-simulation.md](scenario-simulation.md).

## 6. Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `make up` báo `port is already allocated` | Cổng bị process khác chiếm | Đổi `*_PORT` tương ứng trong `.env`, chạy lại |
| Service bị `OOMKilled` / `make health` timeout | Docker thiếu RAM | Tăng RAM Docker ≥ 6 GB, hoặc `make up-core` |
| `!reset` / `unknown tag` khi chạy compose | Compose < 2.24.4 | Cập nhật Docker Desktop / compose plugin |
| `/health/ready` = `degraded`, `served_by: local_artifact` | MLflow chưa sẵn sàng lúc API khởi động | `curl -X POST -H "X-API-Key: $API_KEY" $API_URL/api/v1/model/reload` |
| 401/403 khi gọi `/api/v1/*` | Thiếu/sai `X-API-Key` | Lấy lại từ `API_KEYS` trong `.env` |
| Airflow webserver `unhealthy` lâu | Lần đầu migrate DB + tạo user | Chờ thêm 2–3 phút; `make logs SERVICE=airflow-init` |
| Grafana dashboard trống | Chưa có traffic | `make simulate SCENARIO=normal` rồi refresh |
| `make test` lỗi import | Chưa kích hoạt venv | `source .venv/bin/activate` hoặc `make setup` lại |
| Muốn làm lại từ đầu | Volume cũ | `make down-v && make up` |
| Không nhận tin Telegram | Sai token/chat id, bot chưa ở trong group | `make logs SERVICE=alertmanager` tìm `telegram:` (`401` = token, `400 chat not found` = chat id); webhook vẫn nhận (`make alerts`) |

Chi tiết theo từng alert: [operations-runbook.md](operations-runbook.md) và [runbooks/alerts.md](../runbooks/alerts.md).
