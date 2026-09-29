# Grafana provisioning

- `datasources/prometheus.yml`: datasource `Prometheus` (uid `prometheus`, mặc định) và `Alertmanager` (uid `alertmanager`).
- `dashboards/dashboards.yml`: provider `credit-risk` nạp mọi JSON trong `/var/lib/grafana/dashboards` (mount từ `monitoring/grafana/dashboards/`) vào folder **Credit Risk**.

Dashboard được sinh bởi `scripts/build_grafana_dashboards.py` — sửa script rồi chạy `make dashboards`, không sửa JSON tay (`--check` phát hiện JSON lệch so với script).

| Dashboard | uid | Nội dung chính |
|---|---|---|
| Business | `credit-business` | Tỷ lệ APPROVE/REVIEW/DECLINE, expected loss, số quyết định/phút, chân dung chủ thẻ được chấm điểm |
| ML model | `credit-ml-model` | Phiên bản đang phục vụ, nguồn model, phân phối xác suất/score, prediction PSI, latency suy luận, trạng thái retrain |
| Drift | `credit-drift` | Drift detected, drift share, max PSI, PSI theo feature, thời điểm phân tích gần nhất |
| Infra & SLA | `credit-infra-sla` (home) | Up/uptime, success ratio, p95, RPS, alert đang firing, CPU/RAM, Airflow |

Quy ước hiển thị (chi tiết: [`docs/05-monitoring-alerting.md` §4.1](../../../docs/05-monitoring-alerting.md#41-quy-ước-hiển-thị)):

- Màu APPROVE = green, REVIEW = yellow, DECLINE = red là *danh tính quyết định* — giống nhau ở mọi stat/series, stat tô chữ (`colorMode: value`) chứ không tô nền.
- Nền xanh/cam/đỏ chỉ dành cho trạng thái và SLO; ngưỡng trên panel trùng ngưỡng alert, description ghi tên alert.
- Mọi panel có `noValue` nói rõ "không có lỗi" (vd. `No 5xx responses`) khác với "mất dữ liệu" (`API DOWN`, `MONITOR DOWN`).
- Tiền dùng `currency:NT$`, tốc độ request dùng `reqps`.

Mở: <http://localhost:13000> (user/pass lấy từ `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` trong `.env`).
