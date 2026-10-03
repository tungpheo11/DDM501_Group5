# Bài thuyết trình cuối kỳ — Credit Risk MLOps

| File | Dùng khi |
|---|---|
| [`index.html`](index.html) | **Bản trình chiếu duy nhất** (21 slide, speaker notes, ảnh chụp thật nhúng trực tiếp từ repo). Mọi chỉnh sửa làm trực tiếp trên file này |
| [`script_present.md`](script_present.md) | Lời thoại từng slide và phân chia người nói (Thịnh · Tùng · Hoa · Hòa) |
| [`demo-script.md`](demo-script.md) | Kịch bản demo trực tiếp ~4 phút 30 giây trên Staff Portal và công cụ vận hành: phân vai, checklist chuẩn bị, thao tác, output kỳ vọng, dự phòng |

Câu chuyện nghiệp vụ xuyên suốt: quản lý hạn mức cho chủ thẻ đang lưu hành. Realtime là xử lý yêu cầu tăng hạn mức (chủ thẻ gửi trên mobile app, hoặc CSKH tạo trên Staff Portal); batch là rà soát hạn mức toàn danh mục sau mỗi kỳ sao kê. Staff Portal (`http://localhost:18030`) có ba vai trò: CSKH, chuyên viên rủi ro tín dụng, quản trị hệ thống.

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

Ảnh `deck-{desktop-1440x900,mobile-390x844}-slideNN.png` chụp chế độ trình chiếu thường tại `index.html#NN` (desktop tỉ lệ điểm ảnh 1, mobile tỉ lệ 2). Khi sửa slide 01, 07, 08, 13, 17, 18, 19 hoặc 21, chụp lại ảnh tương ứng.

## Thứ tự và thời lượng (~16 phút trình bày + ~4 phút 30 giây demo + Q&A)

| Phần | Slide | Người nói | Thời lượng |
|---|---|---|---|
| Mở đầu, problem, ML solution, từ ML sang MLOps | 1–4 | Thịnh | 2′ |
| Requirement → SLO, lifecycle, architecture, Staff Portal, CI/CD | 5–9 | Tùng | 4′15″ |
| Serving, monitoring, incident, drift, champion/challenger | 10–14 | Hoa | 4′ |
| Failure modes, Responsible AI, Staff Portal (3 vai trò, drift), live demo, lessons learned | 15–20 | Hòa | 4′30″ |
| Q&A | 21 | Cả nhóm | — |

Live demo chạy theo [`demo-script.md`](demo-script.md) khi tới slide 19. Mỗi slide có speaker notes ghi thời lượng gợi ý. Nếu trễ giờ: bỏ cảnh 6 của demo (sự cố API) và cắt theo mục *Nếu bị quá giờ* trong [`script_present.md`](script_present.md).

## Nguồn hình

Deck tham chiếu trực tiếp (đường dẫn tương đối, không copy):

- Staff Portal (slide 8, 17, 18): [`../assets/screenshots/staff-portal/`](../assets/screenshots/staff-portal/) — ảnh chụp từ portal và công cụ vận hành đang chạy trên stack local, dữ liệu chủ thẻ giả lập.
- Diagram: [`../assets/diagrams/`](../assets/diagrams/) — sửa `.mmd` trong `src/` rồi `bash scripts/render_diagrams.sh`.
- Dashboard: [`../assets/screenshots/grafana/after/`](../assets/screenshots/grafana/after/) — quy ước hiển thị ở [05 §4.1](../05-monitoring-alerting.md#41-quy-ước-hiển-thị).
- Biểu đồ đánh giá/RAI: [`../../reports/figures/`](../../reports/figures/).

Số liệu trên slide lấy từ `reports/` và [`../qa/test-report.md`](../qa/test-report.md) (lần chạy `make test-ci` gần nhất); cập nhật slide khi các báo cáo đó thay đổi.
