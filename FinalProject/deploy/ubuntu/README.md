# Ubuntu deployment

Hướng dẫn từng bước (Docker, user, UFW, `.env`/secrets, compose prod, Nginx + TLS, systemd, backup/restore, upgrade & rollback): [`docs/guides/ubuntu-deployment.md`](../../docs/guides/ubuntu-deployment.md).

| File | Vai trò |
|---|---|
| [`install.sh`](install.sh) | Bootstrap host một lần (root): Docker CE + compose plugin, nginx, certbot, UFW 22/80/443, user `deploy`, thư mục `/opt/credit-risk`, cài vhost + systemd unit. Idempotent |
| [`deploy.sh`](deploy.sh) | Release theo thư mục `releases/<tag>` + symlink `current`: `deploy`, `smoke`, `rollback`, `status`, `start`, `stop`. Được CD gọi qua SSH, cũng dùng tay được |
| [`backup.sh`](backup.sh) | `backup` (pg_dump từng database + mc mirror bucket MLflow, SHA256SUMS, giữ `BACKUP_KEEP` bản), `list`, `restore <dir>` |
| [`nginx/credit-risk.conf`](nginx/credit-risk.conf) | Reverse proxy: API (`/api/`, `/health/`, `/docs`) có rate limit, Grafana; `certbot --nginx` thêm TLS |
| [`systemd/credit-risk.service`](systemd/credit-risk.service) | Bật release `current` khi boot (`deploy.sh start` / `stop`) |
| [`systemd/credit-risk-backup.{service,timer}`](systemd/) | Backup 02:00 hằng ngày |
