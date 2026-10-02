# Triển khai production trên Ubuntu 22.04 / 24.04

Hướng dẫn đưa toàn bộ stack lên **một VPS Ubuntu** phía sau Nginx + TLS, chạy như dịch vụ systemd, có backup hằng ngày,
upgrade và rollback. Script tự động hoá nằm trong [`deploy/ubuntu/`](../../deploy/ubuntu/README.md); pipeline CD tự
động (GitHub Actions) mô tả trong [07 — Testing & CI/CD](../07-testing-cicd.md#6-release-và-rollback).

> Đã kiểm chứng: `install.sh` chạy trong container `ubuntu:24.04` (Docker 29.8.1, Compose v5.5.1, `nginx -t` OK,
> `systemd-analyze verify` OK cho 3 unit); `backup.sh backup/restore` chạy trên stack thật (dữ liệu giữ nguyên, API
> `ready` từ registry sau restore). Chưa có VPS/DNS thật nên bước certbot cần domain thật mới chạy được.

## 0. Kiến trúc triển khai

```text
Internet ──443/80──► Nginx (TLS, rate limit 20 r/s) ──► 127.0.0.1:18020  api
                                                   └──► 127.0.0.1:13000  grafana
SSH 22 (UFW) ──► tunnel ──► 127.0.0.1: MLflow 15040 · Airflow 18080 · Prometheus 19090 · Alertmanager 19093 · MinIO 19041
systemd: credit-risk.service (stack) · credit-risk-backup.timer (02:00 hằng ngày)
/opt/credit-risk/{releases/<tag>, current → releases/<tag>, previous_release, shared/.env}
```

Mọi cổng container chỉ bind `127.0.0.1` (`docker-compose.prod.yml`), nên Nginx là cửa vào duy nhất từ mạng.

## 1. Yêu cầu

| Hạng mục | Tối thiểu | Khuyến nghị |
|---|---|---|
| VPS | Ubuntu 22.04/24.04 LTS, 4 vCPU, 8 GB RAM, 40 GB SSD | 4–8 vCPU, 16 GB RAM, 80 GB SSD |
| DNS | 2 bản ghi A trỏ về IP VPS: `api.<domain>`, `grafana.<domain>` | + email cho Let's Encrypt |
| Truy cập | SSH bằng key vào user có `sudo` | Tắt đăng nhập password SSH |
| Máy quản trị | `ssh`, `git` | `jq` |

Các biến dùng trong guide (thay bằng giá trị thật):

```bash
export SERVER=203.0.113.10            # IP hoặc hostname VPS
export API_DOMAIN=api.example.com
export GRAFANA_DOMAIN=grafana.example.com
export TAG=v1.0.0                     # git tag cần deploy
```

## 2. Lấy mã nguồn release lên server

```bash
ssh ubuntu@$SERVER
sudo apt-get update && sudo apt-get install -y git
git clone --depth 1 --branch "$TAG" https://github.com/tungpheo11/DDM501_Group5.git /tmp/credit-src
```

(Chưa có tag: bỏ `--branch "$TAG"` để lấy nhánh mặc định, vẫn đặt tên release dạng `v0.0.0-dev`.)

## 3. Bootstrap host (một lần): Docker, user, UFW, Nginx, systemd

```bash
sudo API_DOMAIN=$API_DOMAIN GRAFANA_DOMAIN=$GRAFANA_DOMAIN \
  bash /tmp/credit-src/FinalProject/deploy/ubuntu/install.sh
```

Script idempotent (chạy lại an toàn), thực hiện:

| Bước | Chi tiết |
|---|---|
| Gói hệ thống | `ca-certificates curl gnupg python3 nginx certbot python3-certbot-nginx ufw` |
| Docker | Docker CE + compose plugin từ `download.docker.com` (không dùng `docker.io` của Ubuntu — compose quá cũ cho `!reset`) |
| User | `deploy` (không password), thuộc group `docker` |
| Thư mục | `/opt/credit-risk/releases` (755), `/opt/credit-risk/shared` (700), `/var/backups/credit-risk` (700), owner `deploy` |
| Firewall | UFW: deny incoming, allow `SSH_PORT` (22), 80, 443 |
| Nginx | vhost `credit-risk.conf` với 2 domain; xoá site `default`; `nginx -t` + reload |
| systemd | `credit-risk.service`, `credit-risk-backup.service`, `credit-risk-backup.timer` — enable |

SSH ở cổng khác 22: thêm `SSH_PORT=2222`. Chạy trong container không có firewall: `SKIP_UFW=1`.

Kiểm tra:

```bash
docker compose version            # >= 2.24.4
id deploy                         # groups=...,docker
sudo ufw status verbose           # 22, 80, 443 ALLOW
sudo nginx -t
systemctl list-unit-files 'credit-risk*'
```

## 4. Cấu hình `.env` và secret

```bash
sudo -u deploy cp /tmp/credit-src/FinalProject/.env.example /opt/credit-risk/shared/.env
sudo chmod 600 /opt/credit-risk/shared/.env
sudo -u deploy nano /opt/credit-risk/shared/.env
```

Sinh giá trị ngẫu nhiên: `openssl rand -hex 32`. Bắt buộc thay **mọi** giá trị `*-change-me` / mặc định:

| Biến | Ghi chú |
|---|---|
| `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD` | Bắt buộc (overlay prod dừng nếu thiếu). Chỉ có hiệu lực ở lần khởi tạo volume đầu tiên |
| `API_KEYS` | Key cho client, phân tách dấu phẩy (thêm key mới trước, bỏ key cũ sau ⇒ xoay không downtime) |
| `PSEUDONYMIZATION_KEY` | HMAC key để pseudonymize định danh trong inference log — bắt buộc |
| `GRAFANA_ADMIN_PASSWORD`, `AIRFLOW_ADMIN_PASSWORD`, `AIRFLOW_SECRET_KEY` | Đăng nhập UI |
| `AIRFLOW_FERNET_KEY` | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` (tuỳ chọn) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Tuỳ chọn — để trống thì alert chỉ tới webhook nội bộ `alert-webhook`. Tạo bot bằng [@BotFather](https://t.me/BotFather), lấy chat id qua `getUpdates` ([05 §5.4](../05-monitoring-alerting.md#54-kênh-telegram)). Nên dùng bot/group riêng cho production |
| `COMPOSE_PROFILES` | `core,monitoring,orchestration` (đầy đủ) hoặc `core,monitoring` cho VPS 8 GB |

`.env` **không bao giờ** vào git hay image; mỗi release chỉ symlink tới `shared/.env`. Chính sách secret:
[SECURITY.md](../../SECURITY.md).

## 5. Chuẩn bị release và image

```bash
sudo install -d -o deploy -g deploy /opt/credit-risk/releases/$TAG
sudo cp -a /tmp/credit-src/FinalProject/. /opt/credit-risk/releases/$TAG/
sudo chown -R deploy:deploy /opt/credit-risk/releases/$TAG
```

Chọn **một** nguồn image API (image này cũng chạy MLflow và `model-bootstrap`):

**A. Image GHCR do CD publish** (khuyến nghị — đúng image đã qua test + Trivy):

```bash
echo "$GHCR_TOKEN" | sudo -u deploy docker login ghcr.io -u <github-user> --password-stdin   # token scope read:packages
export IMAGE=ghcr.io/tungpheo11/credit-risk-api@sha256:<digest>                            # lấy digest từ log job CD
```

**B. Build ngay trên server** (không có registry):

```bash
cd /opt/credit-risk/releases/$TAG
sudo -u deploy docker build -f deploy/docker/Dockerfile.api -t credit-risk-api:$TAG .
export IMAGE=credit-risk-api:$TAG
```

## 6. Deploy

```bash
sudo -u deploy DEPLOY_ROOT=/opt/credit-risk \
  bash /opt/credit-risk/releases/$TAG/deploy/ubuntu/deploy.sh deploy $TAG $IMAGE
sudo -u deploy DEPLOY_ROOT=/opt/credit-risk bash /opt/credit-risk/current/deploy/ubuntu/deploy.sh smoke
sudo -u deploy DEPLOY_ROOT=/opt/credit-risk bash /opt/credit-risk/current/deploy/ubuntu/deploy.sh status
```

`deploy` kiểm tra tag/image, ghi `.image`, symlink `.env`, lưu release đang chạy vào `previous_release`, chạy
`docker compose config` → `pull --policy missing --ignore-buildable` → `up -d --build` (project `credit-risk-mlops`,
volume giữ nguyên), trỏ `current` sang release mới và giữ 5 release gần nhất. Image drift monitor + Airflow được build
lại từ bundle ở mỗi lần deploy/rollback (lần đầu ~10–15 phút, các lần sau dùng cache layer nên nhanh hơn). `model-bootstrap` tự đăng ký `models/credit_model_v1.joblib` làm `@champion` khi registry trống.

Kết quả mong đợi của `smoke`: `/health/live` 200, `/health/ready` `ready`/`degraded`, `POST /api/v1/predict` 200 có
`risk_decision`.

## 7. TLS với Let's Encrypt

DNS phải trỏ đúng trước bước này (`dig +short $API_DOMAIN`).

```bash
sudo certbot --nginx -d $API_DOMAIN -d $GRAFANA_DOMAIN --redirect -m ops@example.com --agree-tos --no-eff-email
sudo certbot renew --dry-run                 # certbot.timer tự gia hạn 2 lần/ngày
```

Kiểm tra từ máy quản trị:

```bash
curl -s https://$API_DOMAIN/health/ready | jq .status                      # "ready"
curl -s -o /dev/null -w '%{http_code}\n' https://$API_DOMAIN/metrics      # 404 (không public)
curl -s -o /dev/null -w '%{http_code}\n' http://$API_DOMAIN/health/live   # 301 → https
curl -s -H "X-API-Key: <key>" -H 'Content-Type: application/json' \
  -d @cardholder.json https://$API_DOMAIN/api/v1/predict | jq .risk_decision
```

Grafana: `https://$GRAFANA_DOMAIN` (đăng nhập bằng `GRAFANA_ADMIN_*`). UI nội bộ qua SSH tunnel:

```bash
ssh -N -L 15040:127.0.0.1:15040 -L 18080:127.0.0.1:18080 -L 19090:127.0.0.1:19090 \
       -L 19093:127.0.0.1:19093 -L 19041:127.0.0.1:19041 ubuntu@$SERVER
# rồi mở http://localhost:15040 (MLflow), :18080 (Airflow), :19090 (Prometheus), :19093, :19041
```

MLflow 3.x không có màn hình đăng nhập mặc định. Nếu mở UI bằng IP/domain thay vì `localhost`
(không qua tunnel), các request POST của UI bị chặn với `403 Cross-origin request blocked`. Khai báo
đúng origin trình duyệt đang dùng trong `.env` rồi tạo lại container `mlflow`:

```bash
MLFLOW_CORS_ALLOWED_ORIGINS=http://<server-ip>:15040,https://mlflow.example.com
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file ../../.env up -d mlflow
```

Mở MLflow ra mạng thì phải tự đặt lớp xác thực phía trước (Nginx basic auth hoặc `mlflow server --app-name basic-auth`).

## 8. systemd: tự khởi động cùng máy

`credit-risk.service` (oneshot, `RemainAfterExit`) gọi `deploy.sh start|stop` trên release `current`:

```bash
sudo systemctl start credit-risk        # = deploy.sh start (compose up -d)
sudo systemctl status credit-risk
sudo systemctl stop credit-risk         # compose stop, volume giữ nguyên
sudo reboot                             # sau khi boot: stack tự lên, kiểm tra bằng deploy.sh status
journalctl -u credit-risk -n 100
```

Container cũng có `restart: always` nên tự phục hồi khi process lỗi; systemd đảm bảo thứ tự sau `docker.service`.

## 9. Backup & restore

`credit-risk-backup.timer` chạy `backup.sh backup` lúc 02:00 (± 10 phút) mỗi ngày, giữ 7 bản trong
`/var/backups/credit-risk/<UTC timestamp>/`:

| Nội dung | Cách lấy |
|---|---|
| Mọi database Postgres (`credit_mlops_db` — MLflow metadata + `inference_logs`; `airflow`) | `pg_dump -Fc` từng DB |
| Mọi bucket MinIO (artifact model MLflow) | `mc mirror` |
| `MANIFEST` + `SHA256SUMS` | Kiểm tra toàn vẹn trước restore |

Không gồm: `shared/.env` (sao lưu riêng ở nơi an toàn, mã hoá), Prometheus TSDB và Grafana (provision lại từ git).

```bash
B="sudo -u deploy DEPLOY_ROOT=/opt/credit-risk bash /opt/credit-risk/current/deploy/ubuntu/backup.sh"
$B backup                                      # backup ngay (vd. trước khi upgrade)
$B list
$B restore /var/backups/credit-risk/20260928T020000Z
systemctl list-timers credit-risk-backup.timer
```

`restore` xác minh checksum → dừng mlflow/api/drift/airflow → drop + restore từng DB → mirror bucket → khởi động lại
**tuần tự** (mlflow healthy trước api, để API load champion từ registry thay vì fallback). Kỳ vọng sau restore:
`/health/ready` = `ready`, số dòng `inference_logs` như lúc backup.

Off-site: đồng bộ thư mục backup sang máy khác, ví dụ `rsync -a /var/backups/credit-risk/ backup@nas:/credit-risk/`.

## 10. Upgrade

1. `backup.sh backup` (mục 9).
2. Lấy bundle tag mới (mục 2 + 5) và image mới (GHCR digest hoặc build).
3. `deploy.sh deploy <tag-mới> <image-mới>` → `deploy.sh smoke`.
4. Theo dõi Grafana *Infrastructure & SLA* 15 phút (5xx ratio, p95, alert).

Với CD: đẩy tag `v*` → CI → build + Trivy → reviewer duyệt → tự chạy bước 3 và tự rollback khi smoke fail.

## 11. Rollback

| Loại | Lệnh | Khi nào |
|---|---|---|
| **Ứng dụng** (code + image) | `sudo -u deploy DEPLOY_ROOT=/opt/credit-risk bash /opt/credit-risk/current/deploy/ubuntu/deploy.sh rollback` | Release mới lỗi; về `previous_release` (image digest cũ) + smoke test |
| **Model** (alias MLflow) | xem lệnh bên dưới | Champion mới cho kết quả xấu; code không đổi |
| **Dữ liệu** | `backup.sh restore <dir>` | Hỏng dữ liệu Postgres/MinIO |

Rollback model trên server (image không chứa `scripts/`, gọi thẳng package):

```bash
docker exec credit-risk-mlops-api-1 python -c \
  "from credit_risk.training.registry import rollback_champion; print(rollback_champion())"
curl -s -X POST -H "X-API-Key: <key>" http://127.0.0.1:18020/api/v1/model/reload | jq '.status, .model.model_version'
```

Chỉ giữ một mức lịch sử ứng dụng: sau rollback, `previous_release` bị xoá cho tới lần deploy thành công tiếp theo.

## 12. Thử trên VM local (không có VPS)

```bash
multipass launch 24.04 --name credit --cpus 4 --memory 8G --disk 40G
multipass shell credit                  # rồi làm mục 2 → 6 như trên server
multipass info credit | grep IPv4       # vd. 192.168.64.5
curl -s -H 'Host: api.credit-risk.local' http://192.168.64.5/health/ready          # qua Nginx, không cần DNS
```

Hoặc thêm `192.168.64.5 api.credit-risk.local grafana.credit-risk.local` vào `/etc/hosts` của máy host. Bỏ qua
certbot (cần domain public); nếu muốn HTTPS local dùng chứng chỉ tự ký.

## 13. Checklist nghiệm thu

- [ ] `deploy.sh status`: `current` = tag mới, mọi container `healthy`
- [ ] `https://$API_DOMAIN/health/ready` = `ready`; `/metrics` = 404; HTTP → HTTPS 301
- [ ] `POST /api/v1/predict` có key = 200; không key = 401
- [ ] `sudo ufw status`: chỉ 22/80/443; `ss -tlnp` không có cổng 1xxxx nào bind `0.0.0.0`
- [ ] Grafana 4 dashboard có dữ liệu; Prometheus targets đều `up` (qua tunnel)
- [ ] `sudo reboot` → stack tự lên
- [ ] `backup.sh backup` tạo bản mới, `systemctl list-timers` có `credit-risk-backup.timer`
- [ ] `deploy.sh rollback` về release trước và smoke pass
- [ ] Có Telegram: log `alertmanager` có `Telegram receiver enabled`; `POST /api/v2/alerts` với alert test (như
      `make alerts-send-test`, qua tunnel tới `127.0.0.1:19093`) → group nhận FIRING rồi RESOLVED; `grep` token trong
      `docker logs` của `alertmanager` và `airflow-scheduler` ra 0 dòng

## 14. Xử lý sự cố

| Triệu chứng | Kiểm tra | Xử lý |
|---|---|---|
| `release bundle not found` | `ls /opt/credit-risk/releases/$TAG/deploy/compose` | Copy lại bundle (mục 5) |
| `missing .../shared/.env` | `ls -l /opt/credit-risk/shared` | Tạo `.env` (mục 4) |
| `POSTGRES_PASSWORD is required` | `.env` | Điền giá trị thật |
| Nginx 502 | `curl 127.0.0.1:18020/health/live`, `deploy.sh status` | `sudo systemctl start credit-risk`; xem `docker logs credit-risk-mlops-api-1` |
| Nginx 429 | `/var/log/nginx/credit-risk-api.access.log` | Client vượt 20 r/s; tăng `rate`/`burst` nếu hợp lệ |
| certbot lỗi challenge | `dig +short $API_DOMAIN`, `ufw status` | DNS chưa trỏ / cổng 80 bị chặn |
| Đổi mật khẩu Postgres không có hiệu lực | Volume đã khởi tạo | `ALTER USER` trong Postgres hoặc restore sang volume mới |
| `/health/ready` = `degraded` sau restart | `docker ps` (mlflow healthy?) | `POST /api/v1/model/reload` |
| Hết đĩa | `docker system df`, `du -sh /var/backups/credit-risk` | `docker image prune`, giảm `BACKUP_KEEP` |
| Không nhận alert Telegram | `docker logs credit-risk-mlops-alertmanager-1 2>&1 \| grep -E "render_config\|telegram"` | `webhook receiver only` = thiếu biến trong `shared/.env`; `401` = token sai/bị revoke; `400 chat not found` = chat id sai. Sửa `.env` rồi `docker compose ... up -d alertmanager airflow-scheduler airflow-webserver` |

Vận hành hằng ngày và xử lý sự cố theo alert: [operations-runbook.md](operations-runbook.md).
