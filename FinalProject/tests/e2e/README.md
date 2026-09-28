# E2E tests

Thư mục dành cho test end-to-end chạy trên stack Compose thật (`make up`), đánh dấu `@pytest.mark.e2e` và tự skip khi
stack không chạy.

Luồng drift → retrain → promote → rollback hiện được kiểm chứng bằng các kịch bản trong
[`docs/guides/scenario-simulation.md`](../../docs/guides/scenario-simulation.md); kết quả mỗi lần chạy lưu ở
`reports/simulations/`.
