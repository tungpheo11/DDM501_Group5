# Bài thuyết trình cuối kỳ — Credit Risk MLOps

| File | Dùng khi |
|---|---|
| [`index.html`](index.html) | **Bản trình chiếu chính** (20 slide, speaker notes, ảnh/diagram nhúng trực tiếp từ repo) |
| [`slides.pdf`](slides.pdf) | Nộp bài, gửi hội đồng, dự phòng khi trình duyệt có sự cố |
| [`slides.pptx`](slides.pptx) | Máy chiếu chỉ có PowerPoint/Keynote; mỗi slide là một ảnh 16:9 + speaker notes (không sửa chữ được — sửa trong `index.html` rồi export lại) |
| [`demo-script.md`](demo-script.md) | Kịch bản demo trực tiếp ~4 phút: phân vai, checklist chuẩn bị, lệnh, output kỳ vọng, dự phòng |

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

Trên điện thoại slide hiển thị letterbox 16:9 (ảnh chụp ở [`../assets/screenshots/presentation/`](../assets/screenshots/presentation/)); xoay ngang hoặc dùng `slides.pdf` để đọc dễ hơn.

`index.html?export` tắt thanh điều khiển (dùng cho chụp ảnh); in trực tiếp từ trình duyệt (`Cmd/Ctrl+P`, khổ ngang) cũng cho ra một slide mỗi trang.

## Thứ tự và thời lượng (~19 phút + Q&A)

Theo đúng thứ tự rubric:

| # | Phần | Slide | Thời lượng |
|---|---|---|---|
| — | Mở đầu, agenda | 1–2 | 0.5′ |
| 01 | Problem & yêu cầu | 3–4 | 2′ |
| 02 | Architecture (sơ đồ ngữ cảnh, container, ADR) | 5–7 | 2.5′ |
| 03 | ML Pipeline (train, HPO, quality gate, retrain DAG) | 8–9 | 2′ |
| 04 | Deployment (serving API, Docker, Ubuntu, CD) | 10–11 | 1.5′ |
| 05 | Monitoring (dashboard, alert, data flow) | 12–14 | 2′ |
| 06 | Testing / CI-CD | 15 | 1.5′ |
| 07 | Responsible AI (fairness, mitigation, XAI, privacy) | 16–17 | 2′ |
| 08 | Live demo | 18 | 4′ |
| 09 | Lessons learned | 19 | 1′ |
| — | Q&A | 20 | — |

Mỗi slide có speaker notes ghi thời lượng gợi ý. Nếu trễ giờ: bỏ cảnh 5 của demo (sự cố API) và rút slide 14 xuống 20 giây.

## Nguồn hình

Deck tham chiếu trực tiếp (đường dẫn tương đối, không copy):

- Diagram: [`../assets/diagrams/`](../assets/diagrams/) — sửa `.mmd` trong `src/` rồi `bash scripts/render_diagrams.sh`.
- Dashboard: [`../assets/screenshots/grafana/after/`](../assets/screenshots/grafana/after/) — quy ước hiển thị ở [05 §4.1](../05-monitoring-alerting.md#41-quy-ước-hiển-thị).
- Biểu đồ đánh giá/RAI: [`../../reports/figures/`](../../reports/figures/).

Số liệu trên slide lấy từ `reports/` và lần chạy `make test-ci` gần nhất; cập nhật slide khi các báo cáo đó thay đổi.

## Export lại PDF/PPTX

```bash
bash scripts/export_deck.sh
```

Cần Node.js và python3. Script cài puppeteer, Pillow, python-pptx vào thư mục tạm (không đụng `.venv`), chụp từng slide 1920×1080 và dừng với lỗi nếu có slide tràn khung hoặc ảnh hỏng. Dùng Chrome hệ thống nếu có (`CHROME_PATH` để chỉ định), ngược lại tải Chromium của puppeteer.
