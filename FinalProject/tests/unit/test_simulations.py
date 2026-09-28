"""Tests for the traffic scenario helpers (no running stack needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
import run_scenario as rs


def test_replay_payloads_match_the_api_schema() -> None:
    payloads = rs.replay_payloads("stream_drifted.csv")
    assert len(payloads) == 5000
    assert set(payloads[0]) == set(rs.FEATURES)
    assert all(isinstance(value, int | float) for value in payloads[0].values())


def test_drift_stream_is_younger_than_normal_stream() -> None:
    normal = [p["AGE"] for p in rs.replay_payloads("stream_normal.csv")]
    drifted = [p["AGE"] for p in rs.replay_payloads("stream_drifted.csv")]
    assert sum(drifted) / len(drifted) < sum(normal) / len(normal) - 5


def test_attack_personas_are_delinquent() -> None:
    payloads = rs.persona_payloads("fraud_attack", 200)
    delinquent = sum(p["PAY_0"] >= 2 for p in payloads)
    assert delinquent / len(payloads) > 0.5


def test_run_stats_summary_percentiles() -> None:
    stats = rs.RunStats()
    for index in range(100):
        stats.record("200", float(index + 1), {"risk_decision": "APPROVE", "default_probability": 0.1})
    stats.record("503", 5.0, None)
    summary = stats.summary()
    assert summary["requests"] == 101
    assert summary["errors"] == 1
    assert summary["decision_share"] == {"APPROVE": 1.0}
    assert summary["latency_ms"]["p95"] >= 90


def test_resolve_api_key_prefers_explicit_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEYS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("API_KEYS=first,second\n# comment\n", encoding="utf-8")
    assert rs.resolve_api_key(rs.read_env_file(env_file)) == "first"
    monkeypatch.setenv("API_KEY", "explicit")
    assert rs.resolve_api_key(rs.read_env_file(env_file)) == "explicit"


def test_parse_args_defaults_per_scenario() -> None:
    assert rs.parse_args(["load"]).concurrency == 32
    assert rs.parse_args(["drift"]).concurrency == 2
    assert "docker compose" in rs.parse_args(["outage"]).compose
