"""DAG notifications: Telegram when configured, otherwise the internal alert webhook.

Notifications never raise: a delivery problem must not fail the task or the
callback that reports the original failure.
"""

from __future__ import annotations

import html
import logging
import os
import socket
from datetime import UTC, datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "http://alert-webhook:9095/alerts").rstrip("/")
STATSD_HOST = os.getenv("AIRFLOW__METRICS__STATSD_HOST", "statsd-exporter")
STATSD_PORT = int(os.getenv("AIRFLOW__METRICS__STATSD_PORT", "9125"))
TIMEOUT_SECONDS = 10


def escape(value: Any) -> str:
    """HTML-escape ``value`` for Telegram's HTML parse mode."""
    return html.escape(str(value), quote=False)


def _telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send_telegram(text: str) -> bool:
    """Send ``text`` to the configured chat; True on success. The token is never logged."""
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    try:
        response = requests.post(
            f"{TELEGRAM_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("Telegram delivery failed: %s", type(exc).__name__)
        return False
    if response.status_code != 200:
        logger.warning("Telegram delivery failed: HTTP %s", response.status_code)
        return False
    return True


def send_webhook(
    event: str,
    summary: str,
    text: str,
    *,
    status: str = "firing",
    severity: str = "info",
    labels: dict[str, str] | None = None,
) -> bool:
    """Post an Alertmanager-shaped payload to the internal alert webhook."""
    now = datetime.now(UTC).isoformat()
    payload = {
        "version": "4",
        "receiver": "airflow",
        "status": status,
        "groupLabels": {"alertname": event},
        "alerts": [
            {
                "status": status,
                "labels": {"alertname": event, "severity": severity, "source": "airflow", **(labels or {})},
                "annotations": {"summary": summary, "description": text},
                "startsAt": now,
                "endsAt": now if status == "resolved" else "0001-01-01T00:00:00Z",
            }
        ],
    }
    try:
        response = requests.post(ALERT_WEBHOOK_URL, json=payload, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Webhook delivery failed: %s", exc)
        return False
    return True


def notify(
    event: str,
    summary: str,
    lines: list[str],
    *,
    status: str = "firing",
    severity: str = "info",
    labels: dict[str, str] | None = None,
) -> str:
    """Deliver a DAG event; returns the channel used (``telegram`` | ``webhook`` | ``none``)."""
    text = "\n".join([f"<b>{escape(summary)}</b>", *lines])
    if _telegram_configured() and send_telegram(text):
        return "telegram"
    plain = html.unescape("\n".join(lines))
    if send_webhook(event, summary, plain, status=status, severity=severity, labels=labels):
        return "webhook"
    logger.error("Notification %s could not be delivered: %s", event, summary)
    return "none"


def statsd_gauge(name: str, value: float) -> None:
    """Send a StatsD gauge to statsd-exporter (UDP, fire-and-forget)."""
    message = f"{name}:{value}|g".encode()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(message, (STATSD_HOST, STATSD_PORT))
    except OSError as exc:
        logger.warning("Could not send StatsD gauge %s: %s", name, exc)


def task_failure_callback(context: dict[str, Any]) -> None:
    """Task-level ``on_failure_callback``: report which task failed and why."""
    ti = context.get("task_instance")
    dag_id = getattr(ti, "dag_id", "?")
    task_id = getattr(ti, "task_id", "?")
    exception = context.get("exception")
    notify(
        "AirflowTaskFailed",
        f"[AIRFLOW] {dag_id}.{task_id} failed",
        [
            f"Run: <code>{escape(context.get('run_id', '-'))}</code>",
            f"Try: {getattr(ti, 'try_number', '?')}",
            f"Error: <code>{escape(str(exception)[:500])}</code>",
            f"Log: {escape(getattr(ti, 'log_url', '-'))}",
        ],
        severity="warning",
        labels={"dag_id": str(dag_id), "task_id": str(task_id)},
    )
