"""Markdown rendering of the Responsible AI reports and generated blocks in ``docs/``.

Docs keep their narrative by hand; every number lives between
``<!-- rai:<block>:start -->`` and ``<!-- rai:<block>:end -->`` markers and is
re-rendered from ``reports/*.json`` by ``make responsible-ai``, so docs and reports
cannot disagree.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

DOC_BLOCKS: dict[str, tuple[str, ...]] = {
    "docs/06-responsible-ai.md": (
        "fairness-summary",
        "fairness-age",
        "mitigation",
        "explainability",
    ),
    "docs/model-card.md": ("model-details", "model-performance", "fairness-summary", "explainability-global"),
    "docs/data-card.md": ("data-overview", "data-composition"),
}

ATTRIBUTE_LABELS = {
    "SEX": "Giới tính (SEX)",
    "age_group": "Nhóm tuổi (AGE)",
    "EDUCATION": "Học vấn",
    "MARRIAGE": "Hôn nhân",
}
VARIANT_LABELS = {
    "champion": "Champion (không mitigation)",
    "retrained": "Retrained (đối chứng)",
    "reweighing": "Reweighing",
    "unawareness": "Unawareness",
    "threshold_optimizer": "ThresholdOptimizer",
}


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def write_json(report: Mapping[str, Any], path: Path) -> Path:
    """Write ``report`` as indented UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return path


def write_text(content: str, path: Path) -> Path:
    """Write ``content`` (newline-terminated)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


# --- Blocks -------------------------------------------------------------------


def fairness_summary_table(report: Mapping[str, Any]) -> str:
    """One row per audited attribute: DPD, EOD, approval gap, disparate impact, status."""
    thresholds = report["config"]["thresholds"]
    rows = []
    for attribute, result in report["audit"].items():
        summary = result["summary"]
        rows.append(
            [
                ATTRIBUTE_LABELS.get(attribute, attribute),
                _fmt(summary["demographic_parity_difference"]),
                _fmt(summary["equalized_odds_difference"]),
                _fmt(summary["tpr_difference"]),
                _fmt(summary["fpr_difference"]),
                _fmt(summary["approval_rate_difference"]),
                _fmt(summary["disparate_impact_ratio"]),
                f"**{result['status']}**" + (f" ({', '.join(result['violations'])})" if result["violations"] else ""),
            ]
        )
    note = (
        f"\n\nNgưỡng cảnh báo: DPD > {thresholds['demographic_parity_difference']}, "
        f"EOD > {thresholds['equalized_odds_difference']}, disparate impact ratio (approval) < "
        f"{thresholds['disparate_impact_ratio']} (four-fifths rule). DPD/EOD tính trên quyết định nhị phân tại "
        f"threshold {report['model']['decision_threshold']}; approval theo policy serving (APPROVE khi "
        f"P(default) < {report['model']['review_threshold']})."
    )
    headers = ["Thuộc tính", "DPD", "EOD", "ΔTPR", "ΔFPR", "ΔApproval", "DI ratio", "Trạng thái"]
    return _table(headers, rows) + note


def group_table(result: Mapping[str, Any]) -> str:
    """Per-group metrics of one attribute."""
    rows = [
        [
            row["group"],
            _fmt(row["count"]),
            _pct(row["base_rate"]),
            _pct(row["approve_rate"]),
            _pct(row["review_rate"]),
            _pct(row["decline_rate"]),
            _fmt(row["tpr"], 3),
            _fmt(row["fpr"], 3),
            _fmt(row["roc_auc"], 3),
            _fmt(row["expected_loss"], 3),
        ]
        for row in result["groups"]
    ]
    headers = ["Nhóm", "n", "Default rate", "APPROVE", "REVIEW", "DECLINE", "TPR", "FPR", "ROC-AUC", "Expected loss"]
    return _table(headers, rows)


def mitigation_table(report: Mapping[str, Any]) -> str:
    """Before/after comparison per mitigation attribute."""
    parts = []
    for attribute, result in report["mitigation"].items():
        rows = [
            [
                VARIANT_LABELS.get(row["variant"], row["variant"]),
                _fmt(row["roc_auc"]),
                _fmt(row["expected_loss"]),
                _fmt(row["recall"], 3),
                _fmt(row["demographic_parity_difference"]),
                _fmt(row["equalized_odds_difference"]),
                _fmt(row["disparate_impact_ratio"], 3),
            ]
            for row in result["variants"]
        ]
        headers = ["Biến thể", "ROC-AUC", "Expected loss", "Recall", "DPD", "EOD", "DI ratio (nhị phân)"]
        parts.append(
            f"**{ATTRIBUTE_LABELS.get(attribute, attribute)}** — test split {result['test_rows']:,} dòng "
            f"(fit split {result['fit_rows']:,} dòng)\n\n" + _table(headers, rows)
        )
    parts.append(
        "DI ratio ở bảng này tính trên quyết định nhị phân (không bị gắn cờ default tại threshold) để so sánh "
        "được với ThresholdOptimizer (chỉ cho ra nhãn nhị phân); bảng audit dùng tỷ lệ APPROVE của policy 3 mức."
    )
    return "\n\n".join(parts)


def explainability_global_table(report: Mapping[str, Any], top: int = 10) -> str:
    """Top SHAP features by mean |contribution|."""
    rows = [
        [str(rank), f"`{item['feature']}`", _fmt(item["mean_abs_shap"]), _pct(item["share"])]
        for rank, item in enumerate(report["global_importance"][:top], start=1)
    ]
    return _table(["#", "Feature", "mean \\|SHAP\\| (xác suất)", "Tỷ trọng"], rows)


def explainability_local_table(report: Mapping[str, Any]) -> str:
    """Representative applicants: SHAP vs LIME top features and their agreement."""
    rows = []
    for item in report["local"]:
        shap_top = ", ".join(f"`{x['feature']}` {x['contribution']:+.3f}" for x in item["shap_top"][:3])
        lime_top = ", ".join(f"`{x['feature']}` {x['weight']:+.3f}" for x in item["lime_top"][:3])
        agreement = item["agreement"]
        rows.append(
            [
                item["decision"],
                _fmt(item["probability"], 3),
                shap_top,
                lime_top,
                f"{agreement['overlap_at_k']:.0%} / {agreement['sign_agreement']:.0%}",
            ]
        )
    k = report["local"][0]["agreement"]["k"] if report["local"] else 5
    headers = ["Hồ sơ", "P(default)", "SHAP top-3", "LIME top-3", f"Overlap@{k} / cùng dấu"]
    return _table(headers, rows)


def model_details_block(fairness_report: Mapping[str, Any]) -> str:
    """Champion identity and decision thresholds."""
    model = fairness_report["model"]
    params = ", ".join(f"`{key}={value}`" for key, value in model["params"].items())
    rows = [
        ["Thuật toán", f"`{model['candidate']}` ({params})"],
        ["Registry version", _fmt(model["registered_version"])],
        ["Artifact", f"`models/{model['artifact']}` (sha256 `{model['artifact_sha256'][:16]}…`)"],
        ["Decision threshold (nhị phân)", _fmt(model["decision_threshold"], 2)],
        [
            "Policy serving",
            f"APPROVE < {model['review_threshold']:.2f} ≤ REVIEW < {model['decline_threshold']:.2f} ≤ DECLINE",
        ],
    ]
    return _table(["Mục", "Giá trị"], rows)


def model_performance_block(comparison: Mapping[str, Any] | None) -> str:
    """Selected model metrics from ``reports/model_comparison.json``."""
    if not comparison:
        return "_Chưa có `reports/model_comparison.json` — chạy `make train`._"
    selected = next(m for m in comparison["models"] if m["name"] == comparison["selected_model"])
    rows = []
    for label, key in (("Holdout (15k baseline, 20%)", "holdout"), ("Gate set `stream_normal`", "normal_stream")):
        metrics = selected[key]
        rows.append(
            [
                label,
                _fmt(metrics["roc_auc"]),
                _fmt(metrics["pr_auc"]),
                _fmt(metrics["f1_score"]),
                _fmt(metrics["recall"]),
                _fmt(metrics["precision"]),
                _fmt(metrics["brier"]),
                _fmt(metrics["expected_loss"]),
            ]
        )
    cv = selected["cv"]
    headers = ["Tập", "ROC-AUC", "PR-AUC", "F1", "Recall", "Precision", "Brier", "Expected loss"]
    return (
        _table(headers, rows)
        + f"\n\nCV {comparison['config']['cv_folds']}-fold ROC-AUC: {cv['roc_auc_mean']:.4f} ± {cv['roc_auc_std']:.4f}"
        f" · session `{comparison['session_id']}` · nguồn: `reports/model_comparison.json`."
    )


def data_composition_block(fairness_report: Mapping[str, Any]) -> str:
    """Group sizes and default rates of the evaluation set."""
    parts = [
        f"Tập đánh giá fairness: {fairness_report['overall']['rows']:,} dòng "
        + "("
        + ", ".join(f"`{source}` {count:,}" for source, count in fairness_report["sources"].items())
        + f"), default rate {_pct(fairness_report['overall']['default_rate'])}."
    ]
    for attribute, groups in fairness_report["composition"].items():
        rows = [[g["group"], _fmt(g["count"]), _pct(g["default_rate"])] for g in groups]
        parts.append(
            f"**{ATTRIBUTE_LABELS.get(attribute, attribute)}**\n\n" + _table(["Nhóm", "n", "Default rate"], rows)
        )
    return "\n\n".join(parts)


def data_overview_block(fairness_report: Mapping[str, Any]) -> str:
    """Raw dataset statistics, code distributions and versioned partitions."""
    data = fairness_report["dataset"]
    source = data.get("dataset", {})
    header = _table(
        ["Mục", "Giá trị"],
        [
            ["Nguồn", f"[{source.get('name', '—')}]({source.get('url', '')})"],
            ["License", str(source.get("license", "—"))],
            ["Trích dẫn", str(source.get("citation", "—"))],
            [
                "Kích thước raw",
                f"{data['raw_rows']:,} dòng × {data['raw_columns']} cột, {data['raw_missing_values']} ô thiếu",
            ],
            ["Default rate (raw)", _pct(data["raw_default_rate"])],
            ["Tuổi", f"{data['age_range'][0]}–{data['age_range'][1]}"],
            ["Data version (manifest fingerprint)", f"`{data.get('fingerprint') or '—'}`"],
        ],
    )
    codes = _table(
        ["Cột", "Phân bố mã (mã: số dòng)"],
        [
            [f"`{column}`", ", ".join(f"{code}: {count:,}" for code, count in counts.items())]
            for column, counts in data["codes"].items()
        ],
    )
    partitions = _table(
        ["File (`data/…`)", "Dòng", "Tuổi", "Default rate", "sha256"],
        [
            [
                f"`{p['path']}`",
                _fmt(p["rows"]),
                "—" if p["age_min"] is None else f"{p['age_min']}–{p['age_max']}",
                _pct(p["default_rate"]),
                f"`{p['sha256']}`",
            ]
            for p in data["partitions"]
        ],
    )
    return f"{header}\n\n**Phân bố mã trong raw**\n\n{codes}\n\n**Partition có version**\n\n{partitions}"


def _source_line(fairness_report: Mapping[str, Any]) -> str:
    return f"_Sinh tự động bởi `make responsible-ai` ({fairness_report['generated_at']}) — không sửa tay._"


# --- Full reports -------------------------------------------------------------


def render_fairness_markdown(report: Mapping[str, Any]) -> str:
    """``reports/fairness_report.md``."""
    overall = report["overall"]
    sections = [
        "# Báo cáo Fairness",
        "",
        f"> Sinh tự động bởi `make responsible-ai` ({report['generated_at']}). Không sửa tay — "
        "số liệu trong docs được render từ `reports/fairness_report.json`.",
        "",
        "## Thiết lập",
        "",
        model_details_block(report),
        "",
        f"- Tập đánh giá: {overall['rows']:,} hồ sơ chưa từng dùng để train "
        f"({', '.join(f'`{k}` {v:,}' for k, v in report['sources'].items())}); default rate "
        f"{_pct(overall['default_rate'])}, ROC-AUC {overall['roc_auc']:.4f}, APPROVE {_pct(overall['approve_rate'])}.",
        f"- Cost matrix: FN = {report['costs']['false_negative']}, FP = {report['costs']['false_positive']} "
        "(expected loss = tổng loss / số hồ sơ).",
        "",
        "## Tổng quan theo thuộc tính nhạy cảm",
        "",
        fairness_summary_table(report),
        "",
        "![Group metrics](figures/rai_fairness_group_metrics.png)",
        "",
        "## Chi tiết theo nhóm",
    ]
    for attribute, result in report["audit"].items():
        sections += ["", f"### {ATTRIBUTE_LABELS.get(attribute, attribute)}", "", group_table(result)]
    sections += [
        "",
        "![Decisions by age group](figures/rai_decisions_by_age_group.png)",
        "",
        "## Mitigation — trước / sau",
        "",
        "Tất cả biến thể được đánh giá trên cùng test split (50% tập đánh giá, stratified theo nhóm × nhãn). "
        "`retrained`/`reweighing`/`unawareness` fit lại cùng thuật toán + hyper-parameter của champion trên "
        "train split baseline + fit split; `threshold_optimizer` hậu xử lý champion với ngưỡng theo nhóm "
        f"({report['config']['threshold_optimizer']['constraints']}, "
        f"{report['config']['threshold_optimizer']['objective']}) fit trên fit split. "
        "ROC-AUC của ThresholdOptimizer tính trên xác suất trộn ngẫu nhiên nên thấp hơn tự nhiên.",
        "",
        mitigation_table(report),
        "",
        "![Mitigation trade-off](figures/rai_mitigation_tradeoff.png)",
        "",
        "Phân tích trade-off và khuyến nghị: xem `docs/06-responsible-ai.md`.",
    ]
    return "\n".join(sections)


def render_explainability_markdown(report: Mapping[str, Any]) -> str:
    """``reports/explainability_report.md``."""
    sections = [
        "# Báo cáo Explainability (SHAP + LIME)",
        "",
        f"> Sinh tự động bởi `make responsible-ai` ({report['generated_at']}). Không sửa tay.",
        "",
        "## Phương pháp",
        "",
        f"- SHAP: {report['method']['shap']} — {report['sample_size']} hồ sơ đánh giá.",
        f"- LIME: {report['method']['lime']}.",
        f"- Serving (`POST /api/v1/explain`): {report['method']['serving']}.",
        "",
        "## Global — SHAP",
        "",
        explainability_global_table(report),
        "",
        "![SHAP summary](figures/rai_shap_summary.png)",
        "",
        "![SHAP bar](figures/rai_shap_bar.png)",
        "",
        "## Local — 3 hồ sơ đại diện (SHAP vs LIME)",
        "",
        explainability_local_table(report),
        "",
        f"Overlap@k trung bình SHAP↔LIME: {report['mean_overlap_at_k']:.0%}.",
    ]
    for item in report["local"]:
        slug = item["decision"].lower()
        sections += [
            "",
            f"### {item['decision']} — P(default) = {item['probability']:.3f}",
            "",
            "Risk factors (SHAP, như API trả về):",
            "",
            *[f"- {message}" for message in item["risk_factors"]],
            "",
            f"Sai số additivity của SHAP serving: {item['serving_additivity_error']:.2e}.",
            "",
            f"![SHAP waterfall {slug}](figures/rai_shap_waterfall_{slug}.png)",
            "",
            f"![LIME {slug}](figures/rai_lime_{slug}.png)",
        ]
    return "\n".join(sections)


# --- Doc sync -----------------------------------------------------------------


def render_block(
    name: str,
    fairness_report: Mapping[str, Any],
    explainability_report: Mapping[str, Any],
    comparison: Mapping[str, Any] | None,
) -> str:
    """Markdown body of the generated doc block ``name``."""
    renderers: dict[str, Callable[[], str]] = {
        "fairness-summary": lambda: fairness_summary_table(fairness_report),
        "fairness-age": lambda: group_table(fairness_report["audit"]["age_group"]),
        "mitigation": lambda: mitigation_table(fairness_report),
        "explainability": lambda: explainability_global_table(explainability_report, top=8)
        + "\n\n"
        + explainability_local_table(explainability_report),
        "explainability-global": lambda: explainability_global_table(explainability_report, top=8),
        "model-details": lambda: model_details_block(fairness_report),
        "model-performance": lambda: model_performance_block(comparison),
        "data-composition": lambda: data_composition_block(fairness_report),
        "data-overview": lambda: data_overview_block(fairness_report),
    }
    return renderers[name]() + "\n\n" + _source_line(fairness_report)


def replace_block(content: str, name: str, body: str) -> str:
    """Replace the text between the ``rai:<name>`` markers; unchanged if markers are absent."""
    start, end = f"<!-- rai:{name}:start -->", f"<!-- rai:{name}:end -->"
    if start not in content or end not in content:
        return content
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", content, count=1)


def sync_docs(
    project_root: Path, fairness_report: Mapping[str, Any], explainability_report: Mapping[str, Any]
) -> list[Path]:
    """Refresh generated blocks in every doc of :data:`DOC_BLOCKS`; return the files changed."""
    comparison_path = project_root / "reports" / "model_comparison.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8")) if comparison_path.exists() else None
    changed = []
    for relative, blocks in DOC_BLOCKS.items():
        path = project_root / relative
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        content = original
        for name in blocks:
            content = replace_block(
                content, name, render_block(name, fairness_report, explainability_report, comparison)
            )
        if content != original:
            path.write_text(content, encoding="utf-8")
            changed.append(path)
    return changed
