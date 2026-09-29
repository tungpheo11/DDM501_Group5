# Chính sách bảo mật

Tài liệu mô tả cách báo cáo lỗ hổng và các biện pháp bảo mật đã áp dụng trong hệ thống chấm điểm rủi ro tín dụng.
Privacy và PII chi tiết: [06 — Responsible AI](docs/06-responsible-ai.md); triển khai production:
[Ubuntu deployment](docs/guides/ubuntu-deployment.md).

## 1. Báo cáo lỗ hổng

- **Không** mở issue công khai. Gửi GitHub private vulnerability report (tab *Security → Report a vulnerability*) hoặc
  liên hệ trực tiếp maintainer (xem [CONTRIBUTING §7](CONTRIBUTING.md#7-vai-trò-thành-viên)).
- Nội dung: mô tả, bước tái hiện, phiên bản/commit, mức ảnh hưởng ước lượng.
- Phản hồi ban đầu trong 3 ngày làm việc; bản vá cho lỗ hổng mức High/Critical trong 7 ngày.

## 2. Phiên bản được hỗ trợ

| Phiên bản | Hỗ trợ |
|---|---|
| Unreleased (nhánh `main`) và 1.1.x | ✔ |
| < 1.1 | ✖ |

## 3. Quản lý secret

- Mọi secret (mật khẩu Postgres/MinIO/Grafana/Airflow, `API_KEYS`, `PSEUDONYMIZATION_KEY`, Telegram token, SSH key)
  chỉ cấp qua biến môi trường / file `.env`. `.env` bị git-ignore; [`.env.example`](.env.example) chỉ chứa giá trị dev
  mặc định, **không phải secret thật**.
- Overlay production [`docker-compose.prod.yml`](deploy/compose/docker-compose.prod.yml) **từ chối khởi động** nếu thiếu
  `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `PSEUDONYMIZATION_KEY` (cú pháp `${VAR:?…}`).
- Trên server, `.env` nằm ở `/opt/credit-risk/shared/.env`, quyền `600`, owner là user deploy.
- Sinh secret: `openssl rand -hex 32` (API key, pseudonymization key), `openssl rand -base64 24` (mật khẩu).
- Xoay vòng API key: thêm key mới vào `API_KEYS=new,old` (phân tách bằng dấu phẩy) → `docker compose … up -d api` →
  client chuyển sang key mới → bỏ `old` → `up -d api` lần nữa. Quy trình chi tiết:
  [operations runbook](docs/guides/operations-runbook.md).
- Pre-commit chạy `detect-private-key`; secret của CI/CD chỉ nằm trong GitHub Environment secrets.

## 4. Xác thực và kiểm soát đầu vào

- Mọi endpoint `/api/v1/*` yêu cầu header `X-API-Key`; so khớp bằng `hmac.compare_digest` trên **mọi** key cấu hình
  (constant-time, không lộ key nào khớp qua timing) — [`serving/security.py`](src/credit_risk/serving/security.py).
  Thiếu key → 401, sai key → 403.
- Pydantic validation giới hạn miền giá trị UCI và **từ chối field lạ**; batch tối đa 500 chủ thẻ (413 khi vượt).
- Error contract `{code, message, details, request_id}` không echo lại payload bị từ chối, không trả stack trace.
- `/health/*` và `/metrics` không cần key nhưng không chứa dữ liệu khách hàng; ở production, Nginx chặn `/metrics`
  từ Internet (Prometheus scrape qua mạng Compose nội bộ).

## 5. Mạng

| Lớp | Biện pháp |
|---|---|
| Host | UFW `deny incoming`, chỉ mở SSH, 80 (ACME + redirect), 443 — [`install.sh`](deploy/ubuntu/install.sh) |
| Container | Production bind mọi cổng vào `127.0.0.1`; UI nội bộ (Grafana, MLflow, Airflow…) truy cập qua `ssh -L` |
| Reverse proxy | [Nginx](deploy/ubuntu/nginx/credit-risk.conf): TLS Let's Encrypt, `X-Content-Type-Options`, `X-Frame-Options DENY`, rate limit 20 r/s/IP (burst 40, trả 429), `/metrics` và path lạ → 404 |

## 6. Container và supply chain

- Image API multi-stage, base `python:3.11.16-slim-trixie` pin theo digest, chạy user non-root `app`, không có
  compiler/`curl`/dữ liệu trong image ([`Dockerfile.api`](deploy/docker/Dockerfile.api)).
- Trivy (image pin digest) quét mỗi lần CI (`make scan`); **fail khi có lỗ hổng CRITICAL**, bảng HIGH chỉ để báo cáo
  (`reports/security/trivy-report.json`, artifact CI). Lần quét gần nhất: 0 CRITICAL, 45 HIGH — xử lý bằng cách nâng
  base image/dependency khi upstream có bản vá.
- GitHub Actions pin theo commit SHA; dependency Python khoá bằng `uv.lock`.
- Image phát hành lên GHCR với tag theo commit/tag; CD chỉ deploy image đã qua CI.

## 7. Dữ liệu và privacy

- Dataset UCI là dữ liệu công khai, không có định danh trực tiếp, nhưng mỗi dòng vẫn là dữ liệu cá nhân (thuộc tính
  được bảo vệ + lịch sử tài chính) — [`privacy.py`](src/credit_risk/responsible_ai/privacy.py):
  - định danh rời khỏi ranh giới serving được pseudonymize bằng HMAC với `PSEUDONYMIZATION_KEY`;
  - bản xuất phân tích generalize quasi-identifier (nhóm tuổi, nhóm hạn mức) và bỏ thuộc tính được bảo vệ không cần thiết;
  - inference log giữ feature gốc (cần cho drift + retrain) và bị xoá sau 90 ngày: `make purge-logs`
    (`RETENTION_DAYS` để đổi).
- Log ứng dụng không bao giờ chứa field dữ liệu chủ thẻ gốc: logging JSON redact thành `[REDACTED]` —
  [`config/logging.py`](src/credit_risk/config/logging.py), có test kiểm tra.

## 8. Backup

- `deploy/ubuntu/backup.sh` dump Postgres (MLflow + Airflow + inference log) và mirror bucket MinIO, giữ 7 bản mới nhất
  (`BACKUP_KEEP`), chạy 02:00 hằng ngày qua systemd timer; restore đã diễn tập trên stack thật —
  [Ubuntu deployment §9](docs/guides/ubuntu-deployment.md#9-backup--restore).
- File backup chứa inference log → cùng quyền `600`, không đưa lên storage công khai.
