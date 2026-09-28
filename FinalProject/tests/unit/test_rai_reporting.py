import json
from pathlib import Path

import pytest

from credit_risk.responsible_ai import reporting
from credit_risk.responsible_ai.analysis import load_rai_config, select_profiles

ROOT = Path(__file__).resolve().parents[2]


def _group(name: str, count: int = 10) -> dict:
    return {
        "group": name,
        "count": count,
        "base_rate": 0.2,
        "selection_rate": 0.3,
        "approve_rate": 0.4,
        "review_rate": 0.4,
        "decline_rate": 0.2,
        "tpr": 0.6,
        "fpr": 0.2,
        "fnr": 0.4,
        "roc_auc": 0.75,
        "expected_loss": 1.1,
    }


@pytest.fixture
def fairness_report() -> dict:
    summary = {
        "demographic_parity_difference": 0.187,
        "demographic_parity_ratio": 0.5,
        "equalized_odds_difference": 0.161,
        "tpr_difference": 0.1,
        "fpr_difference": 0.16,
        "approval_rate_difference": 0.24,
        "disparate_impact_ratio": 0.41,
        "roc_auc_difference": 0.01,
    }
    audit = {"groups": [_group("<30"), _group("30-39")], "summary": summary, "status": "WARN", "violations": ["x"]}
    variant = {
        "variant": "champion",
        "roc_auc": 0.76,
        "expected_loss": 1.07,
        "recall": 0.63,
        "demographic_parity_difference": 0.18,
        "equalized_odds_difference": 0.15,
        "disparate_impact_ratio": 0.77,
    }
    return {
        "generated_at": "2026-09-28T00:00:00+00:00",
        "model": {
            "candidate": "logistic_regression",
            "params": {"C": 0.01},
            "decision_threshold": 0.5,
            "review_threshold": 0.3,
            "decline_threshold": 0.6,
            "artifact": "credit_model_v1.joblib",
            "artifact_sha256": "a" * 64,
            "registered_version": "1",
        },
        "costs": {"false_negative": 10.0, "false_positive": 1.0},
        "config": {
            "thresholds": {
                "demographic_parity_difference": 0.1,
                "equalized_odds_difference": 0.1,
                "disparate_impact_ratio": 0.8,
            },
            "threshold_optimizer": {"constraints": "equalized_odds", "objective": "balanced_accuracy_score"},
        },
        "overall": {"rows": 10, "default_rate": 0.24, "roc_auc": 0.75, "flagged_rate": 0.3, "approve_rate": 0.2},
        "composition": {"age_group": [{"group": "<30", "count": 5, "default_rate": 0.25}]},
        "sources": {"stream_normal": 5, "stream_drifted+feedback": 5},
        "dataset": {
            "dataset": {"name": "UCI", "url": "https://example.org", "license": "CC BY 4.0", "citation": "Yeh"},
            "fingerprint": "abc",
            "raw_rows": 30000,
            "raw_columns": 24,
            "raw_missing_values": 0,
            "raw_default_rate": 0.2329,
            "age_range": [21, 79],
            "codes": {"SEX": {"1": 10, "2": 20}},
            "partitions": [
                {
                    "path": "raw/x.csv",
                    "rows": 30,
                    "sha256": "deadbeef",
                    "age_min": 21,
                    "age_max": 79,
                    "default_rate": 0.2,
                }
            ],
        },
        "audit": {"age_group": audit},
        "mitigation": {"age_group": {"fit_rows": 5, "test_rows": 5, "variants": [variant]}},
    }


@pytest.fixture
def explainability_report() -> dict:
    local = {
        "decision": "DECLINE",
        "probability": 0.78,
        "shap_top": [{"feature": "PAY_0", "value": 2.0, "contribution": 0.29}],
        "lime_top": [{"feature": "PAY_0", "rule": "PAY_0 > 0", "weight": 0.21}],
        "agreement": {"k": 5, "overlap_at_k": 1.0, "sign_agreement": 1.0},
        "risk_factors": ["PAY_0 = 2 (repayment status last month) increases default risk by +29.0 pp"],
        "serving_additivity_error": 0.0,
    }
    return {
        "generated_at": "2026-09-28T00:00:00+00:00",
        "method": {"shap": "s", "lime": "l", "serving": "v"},
        "sample_size": 10,
        "global_importance": [{"feature": "PAY_0", "mean_abs_shap": 0.1, "share": 0.2}],
        "local": [local],
        "mean_overlap_at_k": 1.0,
    }


def test_summary_table_contains_metrics_and_status(fairness_report):
    table = reporting.fairness_summary_table(fairness_report)
    assert "| Nhóm tuổi (AGE) | 0.1870 | 0.1610 |" in table
    assert "**WARN**" in table
    assert "four-fifths rule" in table


def test_full_reports_render(fairness_report, explainability_report):
    fairness_md = reporting.render_fairness_markdown(fairness_report)
    assert fairness_md.startswith("# Báo cáo Fairness")
    assert "| Champion (không mitigation) | 0.7600 | 1.0700 |" in fairness_md
    explain_md = reporting.render_explainability_markdown(explainability_report)
    assert "`PAY_0` +0.290" in explain_md
    assert "rai_shap_waterfall_decline.png" in explain_md


def test_replace_block_only_touches_marked_region():
    content = "intro\n<!-- rai:x:start -->\nold\n<!-- rai:x:end -->\noutro\n"
    updated = reporting.replace_block(content, "x", "new")
    assert updated == "intro\n<!-- rai:x:start -->\nnew\n<!-- rai:x:end -->\noutro\n"
    assert reporting.replace_block(content, "missing", "new") == content


def test_sync_docs_is_idempotent(tmp_path, fairness_report, explainability_report):
    doc = tmp_path / "docs" / "data-card.md"
    doc.parent.mkdir()
    doc.write_text(
        "# Data\n<!-- rai:data-composition:start -->\n<!-- rai:data-composition:end -->\n"
        "<!-- rai:data-overview:start -->\n<!-- rai:data-overview:end -->\n",
        encoding="utf-8",
    )
    assert reporting.sync_docs(tmp_path, fairness_report, explainability_report) == [doc]
    content = doc.read_text(encoding="utf-8")
    assert "10 dòng" in content
    assert "30,000 dòng × 24 cột" in content
    assert reporting.sync_docs(tmp_path, fairness_report, explainability_report) == []


def test_select_profiles_picks_one_row_per_decision():
    import numpy as np

    probs = np.array([0.05, 0.1, 0.2, 0.35, 0.4, 0.5, 0.65, 0.7, 0.9])
    assert select_profiles(probs, 0.3, 0.6) == {"APPROVE": 1, "REVIEW": 4, "DECLINE": 7}


def test_repository_config_loads():
    cfg = load_rai_config(ROOT / "configs" / "responsible_ai.yaml")
    assert cfg.attributes == ("SEX", "age_group", "EDUCATION", "MARRIAGE")
    assert cfg.mitigation_attributes == ("age_group", "SEX")
    assert cfg.thresholds.disparate_impact_ratio == pytest.approx(0.8)


@pytest.mark.parametrize("doc", sorted(reporting.DOC_BLOCKS))
def test_docs_match_generated_reports(doc):
    """Committed docs must equal a fresh render from the committed reports (no hand-edited numbers)."""
    fairness_path = ROOT / "reports" / "fairness_report.json"
    explain_path = ROOT / "reports" / "explainability_report.json"
    if not (fairness_path.exists() and explain_path.exists() and (ROOT / doc).exists()):
        pytest.skip("run `make responsible-ai` first")
    fairness_report = json.loads(fairness_path.read_text(encoding="utf-8"))
    explain_report = json.loads(explain_path.read_text(encoding="utf-8"))
    comparison_path = ROOT / "reports" / "model_comparison.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8")) if comparison_path.exists() else None
    content = (ROOT / doc).read_text(encoding="utf-8")
    for block in reporting.DOC_BLOCKS[doc]:
        body = reporting.render_block(block, fairness_report, explain_report, comparison)
        assert f"<!-- rai:{block}:start -->\n{body}\n<!-- rai:{block}:end -->" in content, f"{doc}: block {block} stale"
