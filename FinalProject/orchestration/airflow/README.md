# Airflow orchestration

- `Dockerfile`: image riêng, Airflow 2.10.5 (constraints chính thức Python 3.11) trong `/opt/airflow-venv`; stage `builder` giống hệt `Dockerfile.api` nên layer `/opt/venv` (dependency ML) được chia sẻ với image API/drift-monitor. Task ML chạy trong `/opt/venv` qua `@task.external_python`, nên Airflow không cần cài vào `requirements.txt`.
- `init_airflow.sh`: tạo database `airflow` trên Postgres dùng chung, `airflow db migrate`, tạo user admin (`AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD`).
- `dags/`, `utils/`: xem README trong từng thư mục.

Compose (profile `orchestration`): `airflow-init` (one-shot) → `airflow-webserver` (<http://localhost:18080>) + `airflow-scheduler` (health `:8974`). Metric Airflow đi qua StatsD → `statsd-exporter:9102` → Prometheus (job `airflow`).
