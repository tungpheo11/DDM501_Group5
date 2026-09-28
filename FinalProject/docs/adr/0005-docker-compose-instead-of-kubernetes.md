# ADR-0005: Docker Compose thay cho Kubernetes cho môi trường chạy

## Context

Stack gồm ~10 service: PostgreSQL, MinIO (+init), MLflow, API, drift monitor, Prometheus, Alertmanager, Grafana, Airflow (webserver/scheduler), statsd-exporter. Ràng buộc:

- Chạy được trên **laptop sinh viên** (macOS/Linux, 8–16 GB RAM) và **một Ubuntu 24.04 VM/VPS** duy nhất.
- Một lệnh khởi động cho demo/chấm điểm (`make up`) và cho QA tái lập.
- Không có cluster/managed K8s; thời gian dự án ngắn; team nhỏ.
- Lưu lượng dự kiến thấp (demo, simulator, Locust) — một node đủ đáp ứng SLO p95 < 100 ms.

## Decision

Dùng **Docker Compose v2** làm runtime cho cả local lẫn triển khai Ubuntu:

- File chính `deploy/compose/docker-compose.yml`, chia **profiles** (`core`, `monitoring`, `orchestration`), kèm overlay `docker-compose.prod.yml` (resource limits, restart policy, không publish port nội bộ).
- Mọi service có **healthcheck** và `depends_on: condition: service_healthy`.
- Trên Ubuntu: systemd unit gọi Compose + Nginx reverse proxy/TLS (`deploy/ubuntu/`).
- Image pin tag cụ thể (không dùng `latest`), secret qua `.env` không commit.

## Consequences

- **Tích cực:** một lệnh dựng toàn bộ hệ thống; cấu hình đọc được trong một file; chi phí vận hành thấp; giống hệt giữa laptop và VM → giảm "works on my machine".
- **Tiêu cực:** không có auto-scaling, self-healing đa node, rolling update native; single node là single point of failure (chấp nhận được cho phạm vi dự án, ghi rõ trong trade-off ở `ARCHITECTURE.md`).
- **Vận hành:** rollback = `docker compose up -d` với tag image trước; backup volume Postgres/MinIO bằng script; monitoring qua Prometheus/Grafana ngay trong stack. Blast radius được giới hạn bằng healthcheck + restart policy từng service.
- **Khả năng đảo ngược:** dễ đảo ngược — mọi service đã container hoá và API stateless, có thể viết thêm manifest Kubernetes/Helm khi cần chạy nhiều node.

## Alternatives considered

| Phương án | Ưu điểm | Nhược điểm | Lý do không chọn |
|---|---|---|---|
| Kubernetes (k3s/minikube/kind) | Auto-scaling, self-healing, chuẩn production lớn | Phức tạp (manifest, ingress, PV), tốn RAM, đường cong học tập | Over-engineering cho 1 node + thời gian ngắn |
| Managed K8s (EKS/GKE) | Production thật | Chi phí cloud, credential | Ngoài ngân sách/phạm vi |
| Docker Swarm | Gần Compose, có multi-node | Hệ sinh thái đang thu hẹp | Không cần multi-node |
| Chạy trực tiếp bằng systemd/venv | Nhẹ nhất | Không tái lập, xung đột dependency (Airflow vs MLflow) | Mất tính di động |
