# Airflow DAGs

| DAG | Lịch | Luồng |
|---|---|---|
| `service_health_check` | `HEALTH_CHECK_SCHEDULE` (mặc định 5 phút) | `probe` (dynamic mapping: API ready, API model info, MLflow, drift monitor, Prometheus, Alertmanager) → `active_alerts` → `summarize` (thông báo khi service lỗi/degraded, fail nếu service critical down) |
| `drift_monitoring` | `DRIFT_MONITORING_SCHEDULE` (mặc định 30 phút) | `run_drift_analysis` → `decide` → `no_drift` \| `alert_drift` + `check_retrain_cooldown` → `trigger_model_retrain` |
| `model_retrain` | chỉ trigger | `train_challenger` → `quality_gate` → `decide_promotion` → `promote_champion` → `reload_api` → `refresh_drift_reference` → `notify_promoted`; hoặc `keep_champion`. `rollback_champion` chạy khi bước promote/reload lỗi (`ONE_FAILED`) |

## Ngữ nghĩa retrain

- Quality gate từ chối challenger (không tốt hơn champion) → **thành công**, giữ champion, gauge `credit_retrain_last_run_failed=0`.
- Gate luôn so với đúng model đang giữ `@champion` trong registry. Nếu alias tồn tại mà không tải được model
  (MinIO/MLflow lỗi), `train_challenger` **failed** thay vì so với `models/credit_model_v1.joblib` local, vì như vậy
  thông báo sẽ ghi sai version champion.
- Retrain là tất định: cùng file dữ liệu (baseline, drifted stream, ground truth), cùng spec, seed, policy thì ra cùng
  challenger và cùng lý do. Mỗi run được gắn tag `training_fingerprint` (SHA-256 của các đầu vào đó) và
  `champion_version`. Nếu lần retrain trước với cùng fingerprint và cùng champion đã bị từ chối, run mới **không đăng ký
  thêm version trùng**; nhánh `keep_champion` gửi `[RETRAIN] inputs unchanged - champion vX kept (same result as
  rejected vY)`. Chỉ khi có feedback có nhãn mới (hoặc đổi spec/champion), challenger mới thay đổi.
- Lỗi thật (train lỗi, ROC-AUC dưới `min_roc_auc`, promote lỗi, reload lỗi) → DAG **failed**, `on_failure_callback` đặt gauge = 1 → alert `RetrainFailed`; `@champion` được giữ hoặc rollback về `@previous_champion`. Lần chạy thành công kế tiếp đặt lại gauge = 0 → alert resolve.
- Task ML chạy bằng `@task.external_python` trong `/opt/venv` (cùng dependency với API), tái sử dụng `run_retraining_pipeline`, `promote_model_version`, `rollback_champion` của `credit_risk.training`.

```bash
make dags-check                      # không có import error
make retrain-dag REASON=manual       # chạy retrain
make retrain-fail                    # min_roc_auc=0.99 → RetrainFailed
make drift-dag                       # chạy drift_monitoring ngay
```
