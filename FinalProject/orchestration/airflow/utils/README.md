# Airflow utils

Import trong DAG bằng `from utils... import ...` (`PYTHONPATH=/opt/airflow/orchestration`).

| Module | Nội dung |
|---|---|
| `common.py` | URL nội bộ/public của các service, `API_KEY`, lịch chạy, ngưỡng (`RETRAIN_MIN_ROC_AUC`, `RETRAIN_COOLDOWN_MINUTES`, `DRIFT_WINDOW_SIZE`), `DEFAULT_ARGS`, `http_json()` |
| `notify.py` | `notify()` gửi Telegram nếu có token, nếu không thì POST payload kiểu Alertmanager tới `ALERT_WEBHOOK_URL` dưới dạng event one-shot (label `kind=event`, `endsAt = startsAt`) nên không kẹt `firing` trong `/alerts/state`; không bao giờ raise, không log token. `statsd_gauge()` đẩy gauge (ví dụ `credit.retrain.last_run_failed`) tới statsd-exporter; `task_failure_callback()` |
| `check_dags.py` | Parse `DagBag`, exit 1 nếu có import error hoặc thiếu DAG mong đợi — dùng bởi `make dags-check` |
