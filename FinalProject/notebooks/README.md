# Notebooks

Notebook dùng để khám phá và trình bày kết quả; logic tái sử dụng phải nằm trong `src/credit_risk`, notebook chỉ gọi lại
các hàm đó.

| Notebook | Nội dung | Chạy lại |
|---|---|---|
| `02_fairness_explainability.ipynb` | Fairness audit (Fairlearn), mitigation + trade-off, SHAP global/local, LIME, giải thích serving, privacy demo; tự kiểm tra khớp với `reports/fairness_report.json` | `make train && make responsible-ai && make notebook-rai` |
