# Bài thuyết trình cuối kỳ — Credit Risk MLOps

| File | Dùng khi |
|---|---|
| [`index.html`](index.html) | **Bản trình chiếu duy nhất** (21 slide, speaker notes, ảnh/diagram nhúng trực tiếp từ repo). Mọi chỉnh sửa làm trực tiếp trên file này |
| [`demo-script.md`](demo-script.md) | Kịch bản demo trực tiếp ~4 phút: phân vai, checklist chuẩn bị, lệnh, output kỳ vọng, dự phòng |

Câu chuyện nghiệp vụ xuyên suốt: quản lý hạn mức cho chủ thẻ đang lưu hành. Realtime là duyệt yêu cầu tăng hạn mức chủ thẻ gửi trên mobile app; batch là rà soát hạn mức toàn danh mục sau mỗi kỳ sao kê.

## Trình chiếu

Mở `index.html` bằng Chrome/Edge/Safari (mở trực tiếp file, không cần server). Canvas cố định 1920×1080, tự co giãn theo cửa sổ.

| Phím | Tác dụng |
|---|---|
| `→` `Space` `PageDown` / `←` `PageUp` | Slide sau / trước (vuốt trái/phải trên màn hình cảm ứng) |
| `Home` / `End` | Slide đầu / cuối |
| `N` | Bật/tắt speaker notes |
| `O` | Xem tổng quan tất cả slide |
| `F` | Toàn màn hình |
| `#5` trên URL | Nhảy tới slide 5 |

Trên điện thoại slide hiển thị letterbox 16:9 (ảnh chụp ở [`../assets/screenshots/presentation/`](../assets/screenshots/presentation/)); xoay ngang để đọc dễ hơn.

Ảnh `deck-{desktop-1440x900,mobile-390x844}-slideNN.png` chụp chế độ trình chiếu thường tại `index.html#NN` (desktop tỉ lệ điểm ảnh 1, mobile tỉ lệ 2). Khi sửa slide 01, 12 hoặc 18, chụp lại ảnh tương ứng.

## Thứ tự và thời lượng (~19 phút + Q&A)

Theo đúng thứ tự rubric:

| # | Phần | Slide | Thời lượng |
|---|---|---|---|
| — | Mở đầu, agenda | 1–2 | 0.5′ |
| 01 | Problem, use case realtime/batch, yêu cầu | 3–5 | 2.5′ |
| 02 | Architecture (sơ đồ ngữ cảnh, container, ADR) | 6–8 | 2.5′ |
| 03 | ML Pipeline (train, HPO, quality gate, retrain DAG) | 9–10 | 2′ |
| 04 | Deployment (serving API, Docker, Ubuntu, CD) | 11–12 | 1.5′ |
| 05 | Monitoring (dashboard, alert, data flow) | 13–15 | 2′ |
| 06 | Testing / CI-CD | 16 | 1.5′ |
| 07 | Responsible AI (fairness, mitigation, XAI, privacy) | 17–18 | 2′ |
| 08 | Live demo | 19 | 4′ |
| 09 | Lessons learned | 20 | 1′ |
| — | Q&A | 21 | — |

Mỗi slide có speaker notes ghi thời lượng gợi ý. Nếu trễ giờ: bỏ cảnh 6 của demo (sự cố API) và rút slide 15 xuống 20 giây.

## Nguồn hình

Deck tham chiếu trực tiếp (đường dẫn tương đối, không copy):

- Diagram: [`../assets/diagrams/`](../assets/diagrams/) — sửa `.mmd` trong `src/` rồi `bash scripts/render_diagrams.sh`.
- Dashboard: [`../assets/screenshots/grafana/after/`](../assets/screenshots/grafana/after/) — quy ước hiển thị ở [05 §4.1](../05-monitoring-alerting.md#41-quy-ước-hiển-thị).
- Biểu đồ đánh giá/RAI: [`../../reports/figures/`](../../reports/figures/).

Số liệu trên slide lấy từ `reports/` và [`../qa/test-report.md`](../qa/test-report.md) (lần chạy `make test-ci` gần nhất); cập nhật slide khi các báo cáo đó thay đổi.
