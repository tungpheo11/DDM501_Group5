# 🛠️ DDM501: AI in DevOps, DataOps & MLOps

> *"Machine learning code is only 5–10% of the system. The rest is plumbing, infrastructure, and operational discipline."*  
> — Inspired by Sculley et al. (NeurIPS 2015) & Google's Rules of ML

Repository trung tâm lưu trữ toàn bộ hành trình nghiên cứu, thiết kế kiến trúc và triển khai hệ thống thuộc học phần **DDM501 (AI in DevOps, DataOps, MLOps)** tại **FPT School of Business & Technology (FSB)**.

Dự án tuân thủ các nguyên lý Kỹ nghệ Phần mềm cho Hệ thống Trí tuệ Nhân tạo (SE4ML), dịch chuyển tư duy từ **"thực nghiệm mô hình trong notebook"** sang **"xây dựng hệ thống ML-enabled sẵn sàng chạy production 24/7"**

---

## 🎯 Định hướng & Mục tiêu môn học (Course Learning Outcomes)

* **Phân tích vòng đời toàn diện:** Phân rã vòng đời hệ thống ML (ML Lifecycle) và cân nhắc đánh đổi (trade-offs) trong các quyết định kiến trúc ở môi trường production thực tế.
* **Kỹ nghệ phần mềm & Khả năng tái lập:** Ứng dụng các nguyên tắc Software Engineering để xây dựng pipeline ML có khả năng kiểm thử, tái lập (reproducible) với bộ công cụ MLOps hiện đại.
* **Kiểm thử & CI/CD:** Thiết lập kiểm thử tự động, tích hợp/triển khai liên tục (CI/CD) cho cả code, dữ liệu và mô hình để ngăn chặn lỗi tiềm ẩn (silent failures).
* **Giám sát & Quản trị rủi ro:** Phát hiện suy giảm hiệu năng do Data Drift, Concept Drift, đồng thời thiết lập cơ chế phục hồi (fallback), guardrails và giám sát liên tục.
* **Responsible AI & Tuân thủ pháp lý:** Đảm bảo tính công bằng (Fairness), minh bạch, giải thích được (Explainability) và tuân thủ các quy định bảo vệ dữ liệu, pháp lý AI (Decree 13/2023, Vietnam AI Law).

---

## ⚙️ Trọng tâm nguyên lý kỹ thuật (Engineering Principles)

* **System Thinking > Model Accuracy:** Cải thiện 0.1% độ chính xác mô hình trở nên vô nghĩa nếu hệ thống không đáp ứng được SLA về độ trễ, khả năng chịu tải hoặc chi phí hạ tầng.
* **Quy chuẩn REQ = ASM ∧ SPEC:** Định nghĩa bài toán thông qua phân rã yêu cầu hệ thống (Requirements), kiểm soát giả định môi trường (Environment Assumptions) và thông số kỹ thuật (System Specifications).
* **Thừa nhận sai số (Planning for Mistakes):** Hệ thống học máy mang tính xác suất; việc thiết kế kiến trúc phải đi kèm phương án ứng phó khi mô hình phán đoán sai (Guardrails, Fallback, Human-in-the-loop).
* **Hạn chế nợ kỹ thuật (Technical Debt):** Chủ động kiểm soát các rủi ro đặc thù như Training-Serving Skew, Entanglement (CACE), Pipeline Jungles và Data Dependencies.

---
