"""Wait until every Compose service is healthy, then print services and ports.

Long-running services must report ``healthy`` (all of them define a
healthcheck); one-shot jobs (``minio-init``, ``model-bootstrap``,
``airflow-init``) must have exited with code 0.

    python scripts/check_stack_health.py --compose "docker compose -f deploy/compose/docker-compose.yml"
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from typing import Any

ONE_SHOT = {"minio-init", "model-bootstrap", "airflow-init"}


def compose_ps(compose: list[str]) -> list[dict[str, Any]]:
    out = subprocess.run([*compose, "ps", "-a", "--format", "json"], check=True, capture_output=True, text=True).stdout
    out = out.strip()
    if not out:
        return []
    if out.startswith("["):
        return list(json.loads(out))
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def classify(container: dict[str, Any]) -> str:
    service, state, health = container["Service"], container.get("State", ""), container.get("Health", "")
    if service in ONE_SHOT:
        if state == "exited":
            return "ok" if container.get("ExitCode", 1) == 0 else "failed"
        return "pending"
    if state != "running":
        return "failed" if state in {"exited", "dead"} else "pending"
    if health == "healthy":
        return "ok"
    if health == "unhealthy":
        return "unhealthy"
    return "pending"


def ports(container: dict[str, Any]) -> str:
    published = sorted(
        {
            f"{p['URL']}:{p['PublishedPort']}->{p['TargetPort']}"
            for p in container.get("Publishers") or []
            if p.get("PublishedPort")
        }
    )
    return ", ".join(p.replace("0.0.0.0:", "localhost:") for p in published if "::" not in p) or "-"


def print_table(containers: list[dict[str, Any]]) -> None:
    print(f"{'SERVICE':<20} {'STATUS':<10} {'STATE':<28} PORTS")
    for c in sorted(containers, key=lambda item: item["Service"]):
        state = c.get("Status", c.get("State", ""))
        print(f"{c['Service']:<20} {classify(c):<10} {state[:27]:<28} {ports(c)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--compose", default="docker compose -f deploy/compose/docker-compose.yml")
    parser.add_argument("--timeout", type=float, default=600, help="seconds to wait (default 600)")
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    compose = shlex.split(args.compose)

    deadline = time.monotonic() + args.timeout
    containers: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        containers = compose_ps(compose)
        states = {c["Service"]: classify(c) for c in containers}
        failed = sorted(s for s, v in states.items() if v == "failed")
        if failed:
            print_table(containers)
            print(f"\nFAILED: {', '.join(failed)} (see: docker compose logs <service>)")
            return 1
        if containers and all(v == "ok" for v in states.values()):
            print_table(containers)
            print(f"\nAll {len(containers)} services healthy.")
            return 0
        waiting = sorted(s for s, v in states.items() if v != "ok")
        print(f"waiting for: {', '.join(waiting) or 'containers to be created'}", flush=True)
        time.sleep(args.interval)

    print_table(containers)
    print(f"\nTIMEOUT after {args.timeout:.0f}s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
