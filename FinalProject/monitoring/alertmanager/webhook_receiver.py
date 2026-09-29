"""Internal Alertmanager webhook receiver (fallback when Telegram is not configured).

Stores the latest notifications in memory, logs one JSON line per alert, and
exposes them for demos and automated checks:

* ``POST /alerts``         Alertmanager webhook payload (version 4).
* ``GET  /alerts``         received notifications, newest first (``?limit=``, ``?alertname=``).
* ``GET  /alerts/state``   last known status per alert (fingerprint), to prove fire -> resolve.
  One-shot events (label ``kind=event``, e.g. Airflow DAG notifications) never
  resolve, so they are only listed under ``/alerts``.
* ``GET  /health``         liveness probe.

Standard library only so it runs on a bare ``python:3.11-slim`` image. The
service is internal to the compose network and has no authentication.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

MAX_BODY_BYTES = 1_000_000
MAX_NOTIFICATIONS = int(os.getenv("ALERT_WEBHOOK_MAX_NOTIFICATIONS", "500"))

logger = logging.getLogger("alert_webhook")


class AlertStore:
    """Thread-safe in-memory store of webhook notifications and per-alert state."""

    def __init__(self, max_notifications: int = MAX_NOTIFICATIONS) -> None:
        self._lock = threading.Lock()
        self._notifications: deque[dict[str, Any]] = deque(maxlen=max_notifications)
        self._state: dict[str, dict[str, Any]] = {}

    def add(self, payload: dict[str, Any]) -> int:
        """Store one webhook payload; return the number of alerts it carried."""
        alerts = payload.get("alerts")
        if not isinstance(alerts, list):
            raise ValueError("payload.alerts must be a list")
        received_at = datetime.now(UTC).isoformat()
        with self._lock:
            self._notifications.appendleft(
                {
                    "received_at": received_at,
                    "receiver": payload.get("receiver"),
                    "status": payload.get("status"),
                    "group_labels": payload.get("groupLabels", {}),
                    "alerts": alerts,
                }
            )
            for alert in alerts:
                labels = alert.get("labels", {})
                if labels.get("kind") == "event":
                    continue
                key = alert.get("fingerprint") or json.dumps(labels, sort_keys=True)
                previous = self._state.get(key, {})
                self._state[key] = {
                    "alertname": labels.get("alertname"),
                    "labels": labels,
                    "status": alert.get("status"),
                    "starts_at": alert.get("startsAt"),
                    "ends_at": alert.get("endsAt"),
                    "last_received_at": received_at,
                    "fired": previous.get("fired", False) or alert.get("status") == "firing",
                    "resolved": alert.get("status") == "resolved",
                }
        return len(alerts)

    def notifications(self, limit: int, alertname: str | None = None) -> list[dict[str, Any]]:
        """Latest notifications (newest first), optionally only those containing ``alertname``."""
        with self._lock:
            items = list(self._notifications)
        if alertname:
            items = [n for n in items if any(a.get("labels", {}).get("alertname") == alertname for a in n["alerts"])]
        return items[:limit]

    def state(self) -> list[dict[str, Any]]:
        """Last known status of every alert seen so far."""
        with self._lock:
            return sorted(self._state.values(), key=lambda s: s["last_received_at"], reverse=True)


def make_handler(store: AlertStore) -> type[BaseHTTPRequestHandler]:
    """Build the request handler class bound to ``store``."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "alert-webhook/1.0"

        def _send_json(self, status: HTTPStatus, body: Any) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "healthy"})
            elif url.path == "/alerts":
                try:
                    limit = max(1, min(int(query.get("limit", ["50"])[0]), MAX_NOTIFICATIONS))
                except ValueError:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "limit must be an integer"})
                    return
                alertname = query.get("alertname", [None])[0]
                self._send_json(HTTPStatus.OK, store.notifications(limit, alertname))
            elif url.path == "/alerts/state":
                self._send_json(HTTPStatus.OK, store.state())
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlparse(self.path).path != "/alerts":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")
                count = store.add(payload)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            for alert in payload["alerts"]:
                labels = alert.get("labels", {})
                logger.warning(
                    json.dumps(
                        {
                            "event": "alert",
                            "status": alert.get("status"),
                            "alertname": labels.get("alertname"),
                            "severity": labels.get("severity"),
                            "summary": alert.get("annotations", {}).get("summary"),
                        },
                        ensure_ascii=False,
                    )
                )
            self._send_json(HTTPStatus.OK, {"accepted": count})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            if self.path != "/health":
                logger.info("%s %s", self.address_string(), format % args)

    return Handler


def main() -> None:
    """Serve the receiver on ``ALERT_WEBHOOK_HOST:ALERT_WEBHOOK_PORT``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    host = os.getenv("ALERT_WEBHOOK_HOST", "0.0.0.0")  # noqa: S104 - container-internal
    port = int(os.getenv("ALERT_WEBHOOK_PORT", "9095"))
    server = ThreadingHTTPServer((host, port), make_handler(AlertStore()))
    logger.info("alert webhook receiver listening on %s:%d", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
