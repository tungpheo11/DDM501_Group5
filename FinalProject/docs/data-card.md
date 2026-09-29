# Data Card — UCI Default of Credit Card Clients

> Theo khung *Datasheets for Datasets* (Gebru et al.) / *Data Cards* (Pushkarna et al.). Khối số liệu
> `<!-- rai:… -->` được render từ `data/manifest.json` và `reports/fairness_report.json` bởi `make responsible-ai`
> — không sửa tay. Liên quan: [Model card](model-card.md) · [06 — Responsible AI](06-responsible-ai.md) · `data/README.md`.

## 1. Tổng quan

<!-- rai:data-overview:start -->
| Mục | Giá trị |
|---|---|
| Nguồn | [Default of Credit Card Clients (UCI ML Repository, id 350)](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients) |
| License | CC BY 4.0 |
| Trích dẫn | Yeh, I. C., & Lien, C. H. (2009). Expert Systems with Applications, 36(2), 2473-2480. |
| Kích thước raw | 30,000 dòng × 24 cột, 0 ô thiếu |
| Default rate (raw) | 23.3% |
| Tuổi | 21–79 |
| Data version (manifest fingerprint) | `3df05ace93a33597` |

**Phân bố mã trong raw**

| Cột | Phân bố mã (mã: số dòng) |
|---|---|
| `SEX` | 1: 11,808, 2: 18,192 |
| `EDUCATION` | 1: 10,674, 2: 14,046, 3: 4,826, 4: 454 |
| `MARRIAGE` | 1: 13,718, 2: 15,876, 3: 406 |
| `PAY_0` | -2: 2,740, -1: 5,665, 0: 16,107, 1: 3,873, 2: 1,371, 3: 199, 4: 13, 5: 7, 6: 6, 7: 6, 8: 13 |

**Partition có version**

| File (`data/…`) | Dòng | Tuổi | Default rate | sha256 |
|---|---|---|---|---|
| `raw/credit_default.csv` | 30,000 | 21–79 | 23.3% | `756d0c82d6e9` |
| `reference/train_baseline.csv` | 15,000 | 30–79 | 22.3% | `636c6ebaffdb` |
| `processed/ground_truth_feedback.csv` | 5,000 | — | 25.8% | `51a664945d28` |
| `processed/stream_drifted.csv` | 5,000 | 21–29 | — | `92cfdefd1e92` |
| `processed/stream_normal.csv` | 5,000 | 30–79 | 22.9% | `a66b20ad1415` |

_Sinh tự động bởi `make responsible-ai` (2026-09-29T11:54:02+00:00) — không sửa tay._
<!-- rai:data-overview:end -->

## 2. Động cơ và bối cảnh thu thập

- Thu thập bởi Yeh & Lien (2009) từ một ngân hàng tại **Đài Loan**, kỳ **04–09/2005** — giai đoạn sau khủng hoảng thẻ tín
  dụng Đài Loan (2005–2006), khi tỷ lệ vỡ nợ thẻ tăng cao. Mục đích gốc: so sánh các kỹ thuật data mining dự báo xác suất
  vỡ nợ.
- Mỗi dòng là một chủ thẻ; nhãn `default_payment_next_month` = 1 nếu vỡ nợ ở kỳ thanh toán kế tiếp.
- **Đây là dữ liệu hành vi của chủ thẻ hiện hữu** — người đã có thẻ, đang có hạn mức (`LIMIT_BAL`), 6 tháng sao kê,
  số tiền đã trả và lịch sử trả nợ. Vì vậy dataset phù hợp cho *behavioral scoring* (quản lý hạn mức: duyệt yêu cầu tăng
  hạn mức, rà soát hạn mức sau kỳ sao kê, cảnh báo sớm) và **không dùng được để chấm điểm khách xin thẻ mới
  (application scoring)**: khách chưa có thẻ
  không có 18/23 feature này tại thời điểm xin thẻ, còn nhãn "vỡ nợ kỳ tới" chỉ có nghĩa với người đang có dư nợ. Ngoài
  ra dữ liệu chỉ gồm người đã được chấp thuận trong quá khứ (survivorship, xem mục 6).
- Khách hàng không được hỏi ý kiến về việc dùng dữ liệu cho nghiên cứu (không có thông tin consent trong nguồn); dữ liệu
  được công bố công khai dưới license CC BY 4.0 và **không có định danh trực tiếp**.

## 3. Thành phần

| Nhóm | Cột | Ý nghĩa |
|---|---|---|
| Hạn mức | `LIMIT_BAL` | tổng hạn mức (NTD), gồm thẻ phụ |
| Nhân khẩu học (nhạy cảm) | `SEX` (1 nam, 2 nữ), `EDUCATION` (1 sau ĐH, 2 ĐH, 3 THPT, 4 khác), `MARRIAGE` (1 kết hôn, 2 độc thân, 3 khác), `AGE` (năm) | thuộc tính được bảo vệ — chỉ dùng cho audit fairness khi chia sẻ |
| Lịch sử trả nợ | `PAY_0`, `PAY_2`…`PAY_6` (09→04/2005) | -2 không sử dụng, -1 trả đủ, 0 trả tối thiểu/quay vòng, 1..9 trễ n tháng |
| Dư nợ sao kê | `BILL_AMT1`…`BILL_AMT6` (09→04/2005) | NTD, có thể âm (trả thừa) |
| Số tiền đã trả | `PAY_AMT1`…`PAY_AMT6` (09→04/2005) | NTD |
| Nhãn | `default_payment_next_month` | 1 = vỡ nợ tháng 10/2005 |

**Bất thường đã biết:** tên cột lệch (`PAY_0` thay vì `PAY_1`); mã `PAY_*` = -2/0 không được mô tả rõ trong tài liệu
gốc; `BILL_AMT` âm; lớp dương chiếm ~22–24% (mất cân bằng). Schema và miền giá trị được kiểm tra bằng pandera
(`make validate` → `reports/data_validation.json`).

## 4. Partition và mục đích

Dữ liệu được chia **có chủ đích theo tuổi** để mô phỏng drift production (`scripts/split_data.py`, `random_state=42`):

| Partition | Nội dung | Dùng cho |
|---|---|---|
| `reference/train_baseline.csv` | 15,000 chủ thẻ **≥ 30 tuổi** | train + holdout, reference cho drift |
| `processed/stream_normal.csv` | 5,000 chủ thẻ ≥ 30 tuổi | champion/challenger gate, traffic "bình thường" |
| `processed/stream_drifted.csv` | 5,000 chủ thẻ **< 30 tuổi**, không nhãn | traffic drift cho simulator/monitoring |
| `processed/ground_truth_feedback.csv` | nhãn trễ của `stream_drifted` | retrain + đánh giá fairness nhóm < 30 |

Hệ quả Responsible AI: model **chưa từng thấy** người < 30 tuổi khi train → nhóm này vừa là drift vừa là rủi ro fairness
(xem [06 — mục 3](06-responsible-ai.md#3-fairness)). Tập đánh giá fairness = `stream_normal` + `stream_drifted` có nhãn:

<!-- rai:data-composition:start -->
Tập đánh giá fairness: 10,000 dòng (`stream_normal` 5,000, `stream_drifted+feedback` 5,000), default rate 24.3%.

**Giới tính (SEX)**

| Nhóm | n | Default rate |
|---|---|---|
| female | 6,107 | 23.4% |
| male | 3,893 | 25.8% |

**Nhóm tuổi (AGE)**

| Nhóm | n | Default rate |
|---|---|---|
| <30 | 5,000 | 25.8% |
| 30-39 | 3,263 | 24.8% |
| 40-49 | 1,310 | 20.4% |
| 50+ | 427 | 15.7% |

**Học vấn**

| Nhóm | n | Default rate |
|---|---|---|
| graduate_school | 3,504 | 23.1% |
| high_school | 1,598 | 26.2% |
| others | 162 | 26.5% |
| university | 4,736 | 24.6% |

**Hôn nhân**

| Nhóm | n | Default rate |
|---|---|---|
| married | 4,595 | 24.7% |
| others | 137 | 27.7% |
| single | 5,268 | 23.9% |

_Sinh tự động bởi `make responsible-ai` (2026-09-29T11:54:02+00:00) — không sửa tay._
<!-- rai:data-composition:end -->

## 5. Tiền xử lý

- Không impute (dataset không có giá trị thiếu); không loại bỏ outlier.
- Feature engineering row-wise, stateless trong pipeline model (`credit_risk.features.feature_engineering`): utilization
  (latest/mean/max/trend), payment ratio, pay-to-limit, số tháng không trả, delinquency max/mean/count/trend.
- Chuẩn hoá (StandardScaler) và one-hot fit trên train split — nằm trong pipeline, được version cùng model.

## 6. Bias đã biết và rủi ro

| Bias | Mô tả | Ảnh hưởng |
|---|---|---|
| Thời gian & địa lý | Đài Loan 2005, giai đoạn khủng hoảng thẻ | không đại diện cho thị trường/giai đoạn khác |
| Partition theo tuổi | train chỉ có ≥ 30 tuổi | disparity theo tuổi, cần feedback để retrain |
| Nhãn lịch sử | chỉ gồm chủ thẻ đã được ngân hàng chấp thuận trước đây (survivorship) | không biết hành vi của người bị từ chối; không dùng để suy ra rủi ro của người chưa có thẻ |
| Proxy | `EDUCATION`, `LIMIT_BAL` tương quan thu nhập/tầng lớp | disparate impact gián tiếp |
| Mất cân bằng lớp | ~1/4 là default | cần class weighting + metric PR-AUC/cost |

## 7. Privacy và sử dụng

- Không có định danh trực tiếp; mọi cột vẫn là dữ liệu cá nhân (tài chính + nhân khẩu học) → áp dụng PII inventory,
  log redaction, pseudonymization, retention trong [06 — mục 6](06-responsible-ai.md#6-privacy).
- **Được dùng:** nghiên cứu/giáo dục, xây dựng và audit model rủi ro tín dụng.
- **Không được dùng:** tái định danh cá nhân, ra quyết định thực tế về người trong dataset, hay các mục đích ngoài phạm vi
  ghi trong [model card](model-card.md#2-mục-đích-sử-dụng).

## 8. Phân phối và bảo trì

- License CC BY 4.0 — phải trích dẫn Yeh & Lien (2009).
- Mọi file dưới `data/` được version bằng `data/manifest.json` (sha256 + số dòng + fingerprint); `make manifest` sinh lại,
  `make validate` kiểm tra khớp manifest. Training ghi fingerprint vào MLflow để truy vết lineage.
- Thay đổi partition (`make data`) phải chạy lại `make train` và `make responsible-ai` để cập nhật model card và data card.
