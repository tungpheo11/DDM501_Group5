"""Network helpers."""

from __future__ import annotations

import socket
from urllib.parse import urlparse


def is_service_reachable(url: str, timeout: float = 0.5) -> bool:
    """Return True when a TCP connection to the URL's host and port succeeds."""
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
