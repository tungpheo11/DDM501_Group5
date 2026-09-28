"""Generate the provisioned Grafana dashboards from code.

Dashboards are plain JSON (provisioned read-only by Grafana) but are built here
so panel layout, datasource wiring and thresholds stay consistent across the
four boards. Regenerate after editing:

    python scripts/build_grafana_dashboards.py          # write JSON files
    python scripts/build_grafana_dashboards.py --check  # fail if files are stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "monitoring" / "grafana" / "dashboards"
DATASOURCE = {"type": "prometheus", "uid": "prometheus"}
API = 'job="credit-risk-api"'
DRIFT = 'job="drift-monitor"'
BUSINESS_ENDPOINTS = f'{API},endpoint=~"/api/v1/.*"'
INFERENCE_BUCKETS = f"sum by (le) (rate(credit_prediction_duration_seconds_bucket{{{API}}}[2m]))"

Panel = dict[str, Any]


class Layout:
    """Left-to-right, top-to-bottom placement on Grafana's 24-column grid."""

    def __init__(self) -> None:
        self.x = 0
        self.y = 0
        self.row_height = 0
        self.next_id = 1

    def place(self, panel: Panel, w: int, h: int) -> Panel:
        if self.x + w > 24:
            self.x = 0
            self.y += self.row_height
            self.row_height = 0
        panel["gridPos"] = {"h": h, "w": w, "x": self.x, "y": self.y}
        panel["id"] = self.next_id
        self.next_id += 1
        self.x += w
        self.row_height = max(self.row_height, h)
        return panel

    def row(self, title: str) -> Panel:
        if self.x:
            self.y += self.row_height
        self.x, self.row_height = 0, 0
        panel = self.place({"type": "row", "title": title, "collapsed": False, "panels": []}, 24, 1)
        self.x, self.y, self.row_height = 0, self.y + 1, 0
        return panel


def target(expr: str, legend: str = "", *, instant: bool = False, fmt: str = "time_series", ref: str = "A") -> dict:
    return {
        "datasource": DATASOURCE,
        "expr": expr,
        "legendFormat": legend or "__auto",
        "instant": instant,
        "range": not instant,
        "format": fmt,
        "refId": ref,
    }


def thresholds(*steps: tuple[float | None, str]) -> dict:
    return {"mode": "absolute", "steps": [{"value": v, "color": c} for v, c in steps]}


GREEN_ONLY = thresholds((None, "green"))
NTD = "currency:NT$"
# Decision colours are an identity (same hue on every stat and series), not a health signal.
DECISION_COLORS = {"APPROVE": "green", "REVIEW": "yellow", "DECLINE": "red"}


def color_overrides(colors: dict[str, str]) -> list[dict]:
    return [
        {
            "matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}],
        }
        for name, color in colors.items()
    ]


def stat(
    title: str,
    expr: str,
    *,
    unit: str = "short",
    steps: dict | None = None,
    mappings: list | None = None,
    decimals: int | None = None,
    description: str = "",
    color_mode: str = "background",
    legend: str = "",
    text_mode: str = "auto",
    no_value: str | None = None,
) -> Panel:
    defaults: dict[str, Any] = {"unit": unit, "thresholds": steps or GREEN_ONLY, "mappings": mappings or []}
    if decimals is not None:
        defaults["decimals"] = decimals
    if no_value is not None:
        defaults["noValue"] = no_value
    return {
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": DATASOURCE,
        "targets": [target(expr, legend, instant=True)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": color_mode,
            "graphMode": "none",
            "textMode": text_mode,
            "justifyMode": "center",
        },
    }


def timeseries(
    title: str,
    targets: list[dict],
    *,
    unit: str = "short",
    threshold: float | None = None,
    stack: bool = False,
    description: str = "",
    min_value: float | None = None,
    colors: dict[str, str] | None = None,
    decimals: int | None = None,
    no_value: str | None = None,
) -> Panel:
    custom: dict[str, Any] = {"lineWidth": 2, "fillOpacity": 15, "showPoints": "never", "spanNulls": True}
    steps = GREEN_ONLY
    if threshold is not None:
        custom["thresholdsStyle"] = {"mode": "line+area"}
        steps = thresholds((None, "transparent"), (threshold, "red"))
    if stack:
        custom["stacking"] = {"mode": "normal", "group": "A"}
    defaults: dict[str, Any] = {
        "unit": unit,
        "custom": custom,
        "thresholds": steps,
        "color": {"mode": "palette-classic"},
    }
    if min_value is not None:
        defaults["min"] = min_value
    if decimals is not None:
        defaults["decimals"] = decimals
    if no_value is not None:
        defaults["noValue"] = no_value
    for index, item in enumerate(targets):
        item["refId"] = chr(ord("A") + index)
    return {
        "type": "timeseries",
        "title": title,
        "description": description,
        "datasource": DATASOURCE,
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": color_overrides(colors or {})},
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def bar_gauge(
    title: str,
    expr: str,
    legend: str,
    *,
    unit: str = "short",
    steps: dict | None = None,
    fmt: str = "time_series",
    description: str = "",
) -> Panel:
    return {
        "type": "bargauge",
        "title": title,
        "description": description,
        "datasource": DATASOURCE,
        "targets": [target(expr, legend, instant=True, fmt=fmt)],
        "fieldConfig": {"defaults": {"unit": unit, "min": 0, "thresholds": steps or GREEN_ONLY}, "overrides": []},
        "options": {
            "orientation": "horizontal" if fmt != "heatmap" else "vertical",
            "displayMode": "gradient",
            "showUnfilled": True,
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
    }


def table(title: str, expr: str, columns: list[str], *, description: str = "", no_value: str | None = None) -> Panel:
    defaults: dict[str, Any] = {} if no_value is None else {"noValue": no_value}
    return {
        "type": "table",
        "title": title,
        "description": description,
        "datasource": DATASOURCE,
        "targets": [target(expr, instant=True, fmt="table")],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"showHeader": True, "cellHeight": "sm"},
        "transformations": [
            {
                "id": "filterFieldsByName",
                "options": {"include": {"names": columns}},
            }
        ],
    }


def heatmap(title: str, expr: str, *, unit: str = "short", description: str = "") -> Panel:
    return {
        "type": "heatmap",
        "title": title,
        "description": description,
        "datasource": DATASOURCE,
        "targets": [target(expr, "{{le}}", fmt="heatmap")],
        "options": {
            "calculate": False,
            "yAxis": {"unit": unit},
            "color": {"mode": "scheme", "scheme": "Oranges", "steps": 64},
            "cellGap": 1,
        },
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def state_map(*pairs: tuple[str, str, str]) -> list[dict]:
    return [{"type": "value", "options": {value: {"text": text, "color": color} for value, text, color in pairs}}]


def dashboard(uid: str, title: str, description: str, panels: list[Panel], refresh: str = "10s") -> dict:
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["credit-risk"],
        "timezone": "browser",
        "editable": False,
        "graphTooltip": 1,
        "refresh": refresh,
        "schemaVersion": 39,
        "version": 1,
        "time": {"from": "now-1h", "to": "now"},
        "links": [
            {
                "type": "dashboards",
                "tags": ["credit-risk"],
                "asDropdown": True,
                "title": "Credit Risk dashboards",
                "includeVars": False,
                "keepTime": True,
            }
        ],
        "templating": {"list": []},
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": True,
                    "hide": True,
                    "iconColor": "rgba(0, 211, 255, 1)",
                    "name": "Annotations & Alerts",
                    "type": "dashboard",
                },
                {
                    "datasource": DATASOURCE,
                    "enable": True,
                    "iconColor": "red",
                    "name": "Firing alerts",
                    "expr": 'ALERTS{alertstate="firing"}',
                    "step": "30s",
                    "titleFormat": "{{alertname}}",
                    "textFormat": "{{severity}} {{component}}",
                    "useValueForTime": False,
                },
            ]
        },
        "panels": panels,
    }


def decision_ratio(decision: str, window: str = "15m") -> str:
    return (
        f'sum(rate(credit_prediction_requests_total{{{API},decision="{decision}"}}[{window}]))'
        f" / sum(rate(credit_prediction_requests_total{{{API}}}[{window}]))"
    )


def decision_rate_stat(decision: str) -> Panel:
    return stat(
        f"{decision.capitalize()} rate (15m)",
        decision_ratio(decision),
        unit="percentunit",
        steps=thresholds((None, DECISION_COLORS[decision])),
        decimals=1,
        color_mode="value",
        no_value="no traffic",
        description="Share of scored applications in the last 15 minutes. Colour identifies the decision "
        "(same hue as the series below); it is not an alert state.",
    )


def business_dashboard() -> dict:
    lay = Layout()
    panels = [
        lay.row("Portfolio decisions"),
        lay.place(
            stat(
                "Applications (1h)",
                f"sum(increase(credit_prediction_requests_total{{{API}}}[1h]))",
                decimals=0,
                color_mode="value",
                no_value="0",
                description="Applications scored by /api/v1/predict and /predict/batch in the last hour.",
            ),
            4,
            4,
        ),
        lay.place(decision_rate_stat("APPROVE"), 4, 4),
        lay.place(decision_rate_stat("REVIEW"), 4, 4),
        lay.place(decision_rate_stat("DECLINE"), 4, 4),
        lay.place(
            stat(
                "Loss at risk (24h)",
                f'sum(increase(credit_expected_loss_ntd_total{{{API},decision="APPROVE"}}[24h]))',
                unit=NTD,
                decimals=1,
                color_mode="value",
                steps=thresholds((None, "orange")),
                no_value="NT$0",
                description="Sum of PD x exposure x LGD (NTD) for approved applications.",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Loss avoided (24h)",
                f'sum(increase(credit_expected_loss_ntd_total{{{API},decision="DECLINE"}}[24h]))',
                unit=NTD,
                decimals=1,
                color_mode="value",
                no_value="NT$0",
                description="Expected loss (NTD) on the requested limit of declined applications.",
            ),
            4,
            4,
        ),
        lay.place(
            timeseries(
                "Decisions per minute",
                [
                    target(
                        f"sum by (decision) (rate(credit_prediction_requests_total{{{API}}}[2m])) * 60", "{{decision}}"
                    ),
                ],
                unit="short",
                stack=True,
                min_value=0,
                colors=DECISION_COLORS,
                description="Stacked applications per minute by decision (APPROVE PD < 0.30, REVIEW < 0.60).",
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "Decision share (15m window)",
                [
                    target("credit:decision_share:rate15m", "{{decision}}"),
                ],
                unit="percentunit",
                min_value=0,
                colors=DECISION_COLORS,
            ),
            12,
            8,
        ),
        lay.row("Financial impact (NTD)"),
        lay.place(
            timeseries(
                "Expected loss per hour by decision",
                [
                    target(
                        f"sum by (decision) (rate(credit_expected_loss_ntd_total{{{API}}}[5m])) * 3600", "{{decision}}"
                    ),
                ],
                unit=NTD,
                min_value=0,
                colors=DECISION_COLORS,
                description="PD x exposure x LGD (LGD from configs/serving.yaml). DECLINE = loss avoided.",
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "Credit volume per hour",
                [
                    target(f"rate(credit_approved_volume_ntd_total{{{API}}}[5m]) * 3600", "approved limit"),
                    target(f"rate(credit_declined_volume_ntd_total{{{API}}}[5m]) * 3600", "declined requested limit"),
                ],
                unit=NTD,
                min_value=0,
                colors={
                    "approved limit": DECISION_COLORS["APPROVE"],
                    "declined requested limit": DECISION_COLORS["DECLINE"],
                },
            ),
            12,
            8,
        ),
        lay.row("Applicant profile (rolling window)"),
        lay.place(
            timeseries(
                "Mean applicant age",
                [
                    target(f"credit_customer_age_rolling_mean{{{API}}}", "age"),
                ],
                unit="suffix: yrs",
            ),
            8,
            7,
        ),
        lay.place(
            timeseries(
                "Mean requested limit",
                [
                    target(f"credit_customer_limit_bal_rolling_mean{{{API}}}", "LIMIT_BAL"),
                ],
                unit=NTD,
            ),
            8,
            7,
        ),
        lay.place(
            timeseries(
                "Delinquency signals",
                [
                    target(f"credit_customer_pay_0_delayed_ratio{{{API}}}", "PAY_0 delayed ratio"),
                    target(f"credit_customer_utilization_ratio_mean{{{API}}}", "utilization mean"),
                    target(f"credit_default_prediction_ratio{{{API}}}", "predicted default ratio"),
                ],
                unit="percentunit",
            ),
            8,
            7,
        ),
    ]
    return dashboard(
        "credit-business",
        "Credit Risk - Business KPIs",
        "Approve/decline rates, expected loss and applicant profile.",
        panels,
    )


def ml_model_dashboard() -> dict:
    lay = Layout()
    panels = [
        lay.row("Served model"),
        lay.place(
            table("Model in production", f"credit_model_info{{{API}}} == 1", ["model_name", "model_version", "source"]),
            8,
            4,
        ),
        lay.place(
            stat(
                "Model loaded",
                f"credit_model_loaded{{{API}}}",
                mappings=state_map(("1", "LOADED", "green"), ("0", "NOT LOADED", "red")),
                no_value="API DOWN",
                description="ModelNotLoaded fires at 0 (API answers 503 MODEL_UNAVAILABLE).",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Serving source",
                f"credit_model_degraded{{{API}}}",
                mappings=state_map(("0", "REGISTRY", "green"), ("1", "FALLBACK", "orange")),
                no_value="UNKNOWN",
                description="FALLBACK = local joblib, MLflow @champion unreachable (ModelServedFromFallback).",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Reloads OK (24h)",
                f'sum(increase(credit_model_reloads_total{{{API},result="success"}}[24h]))',
                decimals=0,
                color_mode="value",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Failed reloads (24h)",
                f'sum(increase(credit_model_reloads_total{{{API},result!="success"}}[24h])) or vector(0)',
                decimals=0,
                steps=thresholds((None, "green"), (1, "red")),
            ),
            4,
            4,
        ),
        lay.row("Score distribution"),
        lay.place(
            bar_gauge(
                "Default probability distribution (15m)",
                f"sum by (le) (increase(credit_prediction_default_probability_bucket{{{API}}}[15m]))",
                "{{le}}",
                fmt="heatmap",
            ),
            12,
            8,
        ),
        lay.place(
            bar_gauge(
                "Applicant score distribution (15m)",
                f"sum by (le) (increase(credit_applicant_score_distribution_bucket{{{API}}}[15m]))",
                "{{le}}",
                fmt="heatmap",
            ),
            12,
            8,
        ),
        lay.place(
            heatmap(
                "Default probability over time",
                f"sum by (le) (rate(credit_prediction_default_probability_bucket{{{API}}}[2m]))",
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "Mean default probability vs predicted default ratio",
                [
                    target("credit:default_probability:mean15m", "mean PD (15m)"),
                    target(f"credit_default_prediction_ratio{{{API}}}", "predicted default ratio (rolling)"),
                ],
                unit="percentunit",
                min_value=0,
            ),
            12,
            8,
        ),
        lay.row("Model health"),
        lay.place(
            timeseries(
                "Prediction distribution PSI (vs reference)",
                [
                    target(f"credit_drift_prediction_psi{{{DRIFT}}}", "prediction PSI"),
                ],
                threshold=0.25,
                min_value=0,
                description="PredictionDistributionShift fires at PSI >= 0.25 for 2m.",
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "Model inference latency",
                [
                    target(f"histogram_quantile(0.5, {INFERENCE_BUCKETS}) >= 0", "p50"),
                    target(f"histogram_quantile(0.95, {INFERENCE_BUCKETS}) >= 0", "p95"),
                ],
                unit="s",
                threshold=0.1,
                min_value=0,
                no_value="no observations",
                description="model.predict_proba() time only (HTTP latency lives on Infra & SLA). "
                "Line = 100 ms latency budget.",
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "Model reloads",
                [
                    target(f"sum by (result) (increase(credit_model_reloads_total{{{API}}}[5m]))", "{{result}}"),
                ],
                min_value=0,
                colors={"success": "green", "failure": "red"},
                description="POST /api/v1/model/reload per 5 minutes (Airflow reload_api after promotion).",
            ),
            12,
            7,
        ),
        lay.place(
            stat(
                "Last retrain run",
                'credit_retrain_last_run_failed{job="airflow"}',
                mappings=state_map(("0", "OK", "green"), ("1", "FAILED", "red")),
                no_value="NO RUN YET",
                description="model_retrain DAG outcome; RetrainFailed fires while FAILED.",
            ),
            6,
            7,
        ),
        lay.place(
            stat(
                "Last promoted version",
                'credit_retrain_last_promoted_version{job="airflow"}',
                decimals=0,
                color_mode="value",
                steps=thresholds((None, "blue")),
                no_value="none since restart",
                description="Registry version moved to @champion by the last successful promotion.",
            ),
            6,
            7,
        ),
    ]
    return dashboard(
        "credit-ml-model",
        "Credit Risk - ML Model",
        "Served model version, score distribution and model lifecycle.",
        panels,
    )


def drift_dashboard() -> dict:
    lay = Layout()
    psi_steps = thresholds((None, "green"), (0.1, "orange"), (0.25, "red"))
    panels = [
        lay.row("Latest Evidently analysis"),
        lay.place(
            stat(
                "Dataset drift",
                f"credit_drift_detected{{{DRIFT}}}",
                mappings=state_map(("0", "NO DRIFT", "green"), ("1", "DRIFT", "red")),
                no_value="MONITOR DOWN",
                description="DRIFT = key-feature PSI >= 0.25 or drift share >= 50% (DataDriftDetected after 2m).",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Drift share",
                f"credit_drift_share{{{DRIFT}}}",
                unit="percentunit",
                decimals=0,
                steps=thresholds((None, "green"), (0.3, "orange"), (0.5, "red")),
            ),
            4,
            4,
        ),
        lay.place(stat("Max key-feature PSI", f"credit_drift_max_psi{{{DRIFT}}}", decimals=2, steps=psi_steps), 4, 4),
        lay.place(
            stat(
                "Drifted features",
                f"credit_drift_drifted_features{{{DRIFT}}}",
                decimals=0,
                steps=thresholds((None, "green"), (1, "orange"), (5, "red")),
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Window size",
                f"credit_drift_current_samples{{{DRIFT}}}",
                decimals=0,
                color_mode="value",
                description="Inference-log rows in the latest analysed window.",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Last analysis age",
                f"(time() - credit_drift_last_analysis_timestamp_seconds{{{DRIFT}}})"
                f" and credit_drift_last_analysis_timestamp_seconds{{{DRIFT}}} > 0",
                unit="s",
                decimals=0,
                steps=thresholds((None, "green"), (300, "orange"), (900, "red")),
                no_value="NEVER",
                description="Red at 15 min = DriftAnalysisStale threshold. NEVER = no successful run since restart.",
            ),
            4,
            4,
        ),
        lay.place(
            timeseries(
                "Drift share over time",
                [
                    target(f"credit_drift_share{{{DRIFT}}}", "drift share"),
                ],
                unit="percentunit",
                threshold=0.5,
                min_value=0,
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "PSI over time",
                [
                    target(f"credit_drift_max_psi{{{DRIFT}}}", "max key-feature PSI"),
                    target(f"credit_drift_prediction_psi{{{DRIFT}}}", "prediction PSI"),
                ],
                threshold=0.25,
                min_value=0,
            ),
            12,
            8,
        ),
        lay.row("Per-feature drift"),
        lay.place(
            bar_gauge(
                "Key-feature PSI (latest)",
                f"sort_desc(credit_drift_feature_psi{{{DRIFT}}})",
                "{{feature}}",
                steps=psi_steps,
            ),
            12,
            10,
        ),
        lay.place(
            table(
                "Drifted features (Evidently)",
                f"credit_drift_feature_drifted{{{DRIFT}}} == 1",
                ["feature", "Value"],
                description="Columns flagged by Evidently's per-column statistical test.",
                no_value="No drifted features",
            ),
            12,
            10,
        ),
        lay.place(
            timeseries(
                "Key-feature PSI over time",
                [
                    target(f"topk(6, credit_drift_feature_psi{{{DRIFT}}})", "{{feature}}"),
                ],
                threshold=0.25,
                min_value=0,
            ),
            24,
            8,
        ),
        lay.row("Monitor health"),
        lay.place(
            timeseries(
                "Analyses by result",
                [
                    target(f"sum by (result) (increase(credit_drift_analyses_total{{{DRIFT}}}[5m]))", "{{result}}"),
                ],
                min_value=0,
                colors={"success": "green", "skipped": "yellow", "error": "red"},
                description="skipped = fewer than 50 new inference rows in the window.",
            ),
            12,
            7,
        ),
        lay.place(
            timeseries(
                "Analysis duration",
                [
                    target(
                        f"rate(credit_drift_analysis_duration_seconds_sum{{{DRIFT}}}[5m])"
                        f" / rate(credit_drift_analysis_duration_seconds_count{{{DRIFT}}}[5m])",
                        "mean",
                    ),
                ],
                unit="s",
                min_value=0,
            ),
            12,
            7,
        ),
    ]
    return dashboard(
        "credit-drift",
        "Credit Risk - Data Drift (Evidently)",
        "PSI and Evidently drift share of recent inference logs vs data/reference.",
        panels,
        refresh="30s",
    )


def infra_sla_dashboard() -> dict:
    lay = Layout()
    total_1h = f"sum(increase(credit_api_requests_total{{{BUSINESS_ENDPOINTS}}}[1h]))"
    errors_1h = f'sum(increase(credit_api_requests_total{{{BUSINESS_ENDPOINTS},status=~"5.."}}[1h]))'
    panels = [
        lay.row("Service level"),
        lay.place(
            stat(
                "Scoring API",
                f"up{{{API}}}",
                mappings=state_map(("1", "UP", "green"), ("0", "DOWN", "red")),
                no_value="NO TARGET",
                description="Prometheus scrape of api:8000/metrics; APIDown fires after 1m at 0.",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Uptime (24h)",
                f"avg_over_time(up{{{API}}}[24h])",
                unit="percentunit",
                decimals=2,
                steps=thresholds((None, "red"), (0.99, "orange"), (0.999, "green")),
                description="Share of successful scrapes over 24h. SLO 99.9% (green), 99% (orange).",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Success ratio (1h)",
                f"1 - (({errors_1h}) or vector(0)) / {total_1h}",
                unit="percentunit",
                decimals=2,
                steps=thresholds((None, "red"), (0.95, "orange"), (0.99, "green")),
                no_value="no traffic",
                description="Non-5xx share of /api/v1/* requests. Red below 95% mirrors HighErrorRate (> 5%).",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "p95 latency",
                "credit:predict_latency_seconds:p95_2m",
                unit="s",
                decimals=1,
                steps=thresholds((None, "green"), (0.075, "orange"), (0.1, "red")),
                no_value="no traffic",
                description="Server-side HTTP p95 of POST /api/v1/predict over 2m. Budget 100 ms (HighLatencyP95).",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Requests / s",
                "credit:api_requests:rate2m",
                unit="reqps",
                decimals=1,
                color_mode="value",
                steps=thresholds((None, "blue")),
                no_value="0 req/s",
            ),
            4,
            4,
        ),
        lay.place(
            stat(
                "Firing alerts",
                'count(ALERTS{alertstate="firing"}) or vector(0)',
                decimals=0,
                steps=thresholds((None, "green"), (1, "red")),
                description="Alerts in firing state (pending excluded); details in Active alerts below.",
            ),
            4,
            4,
        ),
        lay.place(
            timeseries(
                "Latency /api/v1/predict",
                [
                    target("credit:predict_latency_seconds:p50_2m", "p50"),
                    target("credit:predict_latency_seconds:p95_2m", "p95"),
                    target("credit:predict_latency_seconds:p99_2m", "p99"),
                ],
                unit="s",
                threshold=0.1,
                min_value=0,
                description="HighLatencyP95 fires at p95 > 100 ms for 2m.",
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "5xx error ratio (business endpoints)",
                [
                    target("credit:api_error_ratio:rate2m", "error ratio"),
                ],
                unit="percentunit",
                threshold=0.05,
                min_value=0,
                no_value="No 5xx responses",
                description="HighErrorRate fires at > 5% for 2m.",
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "Requests by endpoint and status",
                [
                    target(
                        f"sum by (endpoint, status) (rate(credit_api_requests_total{{{API}}}[2m]))",
                        "{{endpoint}} {{status}}",
                    ),
                ],
                unit="reqps",
                min_value=0,
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "Auth failures",
                [
                    target(f"sum by (reason) (rate(credit_api_auth_failures_total{{{API}}}[2m]))", "{{reason}}"),
                ],
                unit="reqps",
                min_value=0,
                no_value="No auth failures",
                description="401 MISSING_API_KEY / 403 INVALID_API_KEY; a spike means a key rotation or a scan.",
            ),
            12,
            8,
        ),
        lay.row("Platform"),
        lay.place(
            stat(
                "Scrape targets",
                "min by (job) (up)",
                legend="{{job}}",
                mappings=state_map(("1", "UP", "green"), ("0", "DOWN", "red")),
                text_mode="value_and_name",
                description="One tile per Prometheus job; DOWN = last scrape failed.",
            ),
            12,
            8,
        ),
        lay.place(
            table(
                "Active alerts",
                "ALERTS",
                ["alertname", "alertstate", "severity", "component"],
                no_value="No pending or firing alerts",
            ),
            12,
            8,
        ),
        lay.place(
            timeseries(
                "Resident memory",
                [
                    target(
                        'process_resident_memory_bytes{job=~"credit-risk-api|drift-monitor|prometheus|alertmanager"}',
                        "{{job}}",
                    ),
                ],
                unit="bytes",
                min_value=0,
            ),
            12,
            7,
        ),
        lay.place(
            timeseries(
                "CPU usage (cores)",
                [
                    target(
                        'rate(process_cpu_seconds_total{job=~"credit-risk-api|drift-monitor|prometheus|alertmanager"}[2m])',
                        "{{job}}",
                    ),
                ],
                min_value=0,
                decimals=2,
            ),
            12,
            7,
        ),
        lay.row("Orchestration (Airflow via statsd-exporter)"),
        lay.place(
            timeseries(
                "DAG run duration",
                [
                    target(
                        'airflow_dagrun_duration_success_seconds{job="airflow",quantile="0.5"}',
                        "{{dag_id}} success p50",
                    ),
                    target(
                        'airflow_dagrun_duration_failed_seconds{job="airflow",quantile="0.5"}', "{{dag_id}} failed p50"
                    ),
                ],
                unit="s",
                min_value=0,
            ),
            12,
            7,
        ),
        lay.place(
            timeseries(
                "Task outcomes and scheduler",
                [
                    target('rate(airflow_task_failures_total{job="airflow"}[5m]) * 60', "task failures / min"),
                    target('rate(airflow_task_successes_total{job="airflow"}[5m]) * 60', "task successes / min"),
                    target(
                        'rate(airflow_scheduler_heartbeat_total{job="airflow"}[2m]) * 60', "scheduler heartbeats / min"
                    ),
                    target('airflow_dag_import_errors{job="airflow"}', "DAG import errors"),
                ],
                min_value=0,
                colors={
                    "task failures / min": "red",
                    "task successes / min": "green",
                    "scheduler heartbeats / min": "blue",
                    "DAG import errors": "orange",
                },
                description="AirflowDagImportErrors fires while DAG import errors > 0.",
            ),
            12,
            7,
        ),
    ]
    return dashboard(
        "credit-infra-sla",
        "Credit Risk - Infrastructure & SLA",
        "Availability, latency and error-rate SLOs, active alerts and platform health.",
        panels,
    )


DASHBOARDS = {
    "business.json": business_dashboard,
    "ml_model.json": ml_model_dashboard,
    "drift.json": drift_dashboard,
    "infra_sla.json": infra_sla_dashboard,
}


def render_all() -> dict[str, str]:
    return {name: json.dumps(build(), indent=2, ensure_ascii=False) + "\n" for name, build in DASHBOARDS.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if generated files differ from disk")
    args = parser.parse_args()

    rendered = render_all()
    if args.check:
        stale = [
            n
            for n, body in rendered.items()
            if not (OUTPUT_DIR / n).is_file() or (OUTPUT_DIR / n).read_text(encoding="utf-8") != body
        ]
        if stale:
            print(f"stale dashboards: {', '.join(stale)} (run scripts/build_grafana_dashboards.py)")
            return 1
        print("dashboards up to date")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, body in rendered.items():
        (OUTPUT_DIR / name).write_text(body, encoding="utf-8")
        print(f"wrote {OUTPUT_DIR / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
