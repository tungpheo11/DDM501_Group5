# Alertmanager

| File | Vai trò |
|---|---|
| `alertmanager.yml.tmpl` | Cấu hình route/receiver/inhibit. Khối Telegram nằm giữa `# BEGIN_TELEGRAM` / `# END_TELEGRAM`. |
| `render_config.sh` | Entrypoint container: nếu `.env` có `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` thì giữ khối Telegram (token ghi vào tmpfs `/tmp/alertmanager/telegram_bot_token`, không nằm trong file cấu hình); nếu không thì xoá khối đó → chỉ còn webhook. |
| `templates/telegram.tmpl` | Template `telegram.credit.message` (HTML): tên alert, FIRING/RESOLVED, severity, service (`component`), summary, description, thời điểm, link runbook + dashboard. Text tự do được escape `<`, `>`, `&` qua `telegram.credit.escape`. |
| `webhook_receiver.py` | Receiver fallback (stdlib) tại `alert-webhook:9095`. Lưu notification trong RAM để kiểm chứng fire → resolve. |

## Routing

- Mọi alert → `webhook` (luôn có, `send_resolved: true`); `critical` lặp lại mỗi 1h, còn lại 4h.
- Khi bật Telegram: route `telegram` đứng đầu với `continue: true` → Telegram **và** webhook cùng nhận.
- Inhibit: `APIDown` chặn `HighErrorRate`, `HighLatencyP95`, `ModelNotLoaded`, `ModelServedFromFallback`; alert `critical` chặn `warning` cùng `alertname` + `component`.

## Bật Telegram

```bash
# .env
TELEGRAM_BOT_TOKEN=<token từ @BotFather>
TELEGRAM_CHAT_ID=<chat id dạng số, group thì có dấu ->
docker compose -f deploy/compose/docker-compose.yml --env-file .env up -d --force-recreate alertmanager
make alerts-send-test   # FIRING sau ~15 s, RESOLVED sau 2–3 phút
```

Tạo bot, lấy chat id và checklist kiểm tra: [`docs/05-monitoring-alerting.md` §5.4](../../docs/05-monitoring-alerting.md#54-kênh-telegram).

## Xem notification ở webhook

```bash
curl -s localhost:19095/alerts/state | jq            # trạng thái cuối mỗi alert (firing/resolved); không gồm event Airflow
curl -s 'localhost:19095/alerts?limit=10' | jq '.[] | select(.receiver=="airflow")'   # event one-shot từ DAG (label kind=event)
curl -s 'localhost:19095/alerts?limit=5&alertname=APIDown' | jq
make alerts                                          # alert đang firing + state webhook
```

`make alerts-test` kiểm tra cú pháp bằng `amtool` cho cả hai chế độ (webhook-only và Telegram). Danh sách alert, ngưỡng và cách kích hoạt: [`docs/runbooks/alerts.md`](../../docs/runbooks/alerts.md).
