# ADR-0004: Evidently (kèm PSI) cho phát hiện data drift

## Context

Kịch bản trọng tâm của dự án là **covariate drift**: chiến dịch marketing thu hút khách Gen-Z (AGE < 30) trong khi model được train trên nhóm AGE ≥ 30. Cần:

- Chỉ số drift theo từng feature, có ngưỡng giải thích được cho nghiệp vụ tín dụng.
- Báo cáo trực quan (HTML) làm evidence và hỗ trợ điều tra.
- Metrics dạng số để Prometheus scrape → alert `DataDriftDetected` → Airflow trigger retrain.
- Không cần label ngay (ground truth về trễ).

## Decision

- **PSI (Population Stability Index)** tự cài đặt (`calculate_psi`, quantile binning 10 bucket, additive smoothing) cho các feature chính (`AGE`, `LIMIT_BAL`, `PAY_0`, `BILL_AMT1` — cấu hình ở `configs/drift.yaml`). Ngưỡng chuẩn ngành tín dụng: `< 0.10` STABLE, `0.10–0.25` MODERATE, `≥ 0.25` CRITICAL → điều kiện trigger retrain.
- **Evidently** (`DataDriftPreset` + `DataQualityPreset`, API `evidently.legacy`) sinh `reports/drift_report.html` và `drift_summary.json` với test thống kê theo từng cột.
- Nguồn dữ liệu "current": bảng `inference_logs` (Postgres) khi đủ `min_current_samples`, fallback file `data/processed/stream_drifted.csv`.
- Logic này được bọc thành service `services/drift_monitor` expose `/metrics` cho Prometheus.

## Consequences

- **Tích cực:** PSI dễ giải thích với nghiệp vụ và không phụ thuộc phiên bản thư viện; Evidently cho báo cáo phong phú không cần tự vẽ; cả hai chạy offline trong test.
- **Tiêu cực:** Evidently thay đổi API giữa các phiên bản (đang dùng `evidently.legacy` trên 0.7.x) → phiên bản được pin trong `uv.lock`/`requirements.txt`, nâng cấp phải qua test `tests/unit/test_drift.py`; import Evidently chậm nên được import lười trong hàm.
- **Vận hành:** chạy định kỳ qua Airflow `drift_monitoring`; kết quả xuất metrics → alert rule; ngưỡng thay đổi qua `configs/drift.yaml` không cần sửa code.
- **Khả năng đảo ngược:** dễ đảo ngược — PSI được cài đặt độc lập, còn Evidently chỉ được gọi qua `credit_risk.monitoring.drift`, nên thay thư viện không ảnh hưởng phần còn lại.

## Alternatives considered

| Phương án | Ưu điểm | Nhược điểm | Lý do không chọn |
|---|---|---|---|
| Chỉ PSI tự viết | Nhẹ, không phụ thuộc | Không có báo cáo trực quan/test thống kê đa dạng | Thiếu evidence và chiều sâu phân tích |
| Alibi Detect | Nhiều detector (MMD, KS) cả cho DL | Nặng (TensorFlow/PyTorch), API phức tạp | Over-engineering cho dữ liệu bảng |
| NannyML | Ước lượng performance khi chưa có label (CBPE) | Thêm một thư viện lớn; CBPE giả định xác suất model đã calibrated và chỉ ước lượng performance, không thay được test drift theo từng feature | Có thể bổ sung sau, không cần cho MVP |
| WhyLabs / Arize | SaaS monitoring đầy đủ | Dữ liệu tín dụng ra ngoài, cần tài khoản | Vi phạm privacy + self-hosted |
