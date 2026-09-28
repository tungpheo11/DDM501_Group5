"""End-to-end Responsible AI analysis behind ``make responsible-ai``.

Steps:

1. Load the served champion (local champion artifact + ``models/model_spec.json``).
2. Build the fairness evaluation set: ``stream_normal`` (AGE >= 30) + ``stream_drifted``
   joined with its delayed labels (AGE < 30). No row was used for training.
3. Audit group fairness for ``SEX``, ``age_group``, ``EDUCATION`` and ``MARRIAGE``.
4. For each mitigation attribute: split the evaluation set into fit/test halves
   (stratified by group x label) and compare champion, retrained, reweighing,
   unawareness and ThresholdOptimizer on the test half.
5. Explain the champion with SHAP (global beeswarm/bar + local waterfalls) and LIME on
   three representative applicants (APPROVE / REVIEW / DECLINE).
6. Write ``reports/fairness_report.{json,md}``, ``reports/explainability_report.{json,md}``,
   figures ``reports/figures/rai_*.png`` and refresh the generated blocks in the docs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from credit_risk.config import Settings, get_logger, get_settings  # noqa: E402
from credit_risk.data.manifest import sha256_of  # noqa: E402
from credit_risk.data.schema import ALL_FEATURES, REQUEST_ID_COLUMN, TARGET_COLUMN  # noqa: E402
from credit_risk.responsible_ai import explainability as xai  # noqa: E402
from credit_risk.responsible_ai import fairness  # noqa: E402
from credit_risk.responsible_ai.privacy import DEFAULT_RETENTION_DAYS, PII_INVENTORY  # noqa: E402
from credit_risk.training.pipeline import build_model_pipeline  # noqa: E402
from credit_risk.training.retrain import load_champion_spec  # noqa: E402

logger = get_logger(__name__)

CONFIG_FILE = "responsible_ai.yaml"
FAIRNESS_JSON = "fairness_report.json"
FAIRNESS_MD = "fairness_report.md"
EXPLAINABILITY_JSON = "explainability_report.json"
EXPLAINABILITY_MD = "explainability_report.md"
PROFILE_DECISIONS = ("APPROVE", "REVIEW", "DECLINE")


@dataclass(frozen=True)
class ResponsibleAIConfig:
    """Settings from ``configs/responsible_ai.yaml``."""

    random_state: int = 42
    attributes: tuple[str, ...] = fairness.SENSITIVE_ATTRIBUTES
    thresholds: fairness.FairnessThresholds = field(default_factory=fairness.FairnessThresholds)
    mitigation_attributes: tuple[str, ...] = ("age_group", "SEX")
    fit_fraction: float = 0.5
    constraints: str = "equalized_odds"
    objective: str = "balanced_accuracy_score"
    background_size: int = 100
    sample_size: int = 500
    max_evals: int = 500
    top_k: int = 5
    lime_num_features: int = 10
    lime_num_samples: int = 5000


def load_rai_config(path: Path) -> ResponsibleAIConfig:
    """Parse the YAML config; missing keys keep their defaults."""
    import yaml

    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw = raw or {}
    fair = raw.get("fairness", {}) or {}
    mit = raw.get("mitigation", {}) or {}
    optimizer = mit.get("threshold_optimizer", {}) or {}
    expl = raw.get("explainability", {}) or {}
    defaults = ResponsibleAIConfig()
    return ResponsibleAIConfig(
        random_state=int(raw.get("random_state", defaults.random_state)),
        attributes=tuple(fair.get("attributes", defaults.attributes)),
        thresholds=fairness.FairnessThresholds(**(fair.get("thresholds") or {})),
        mitigation_attributes=tuple(mit.get("attributes", defaults.mitigation_attributes)),
        fit_fraction=float(mit.get("fit_fraction", defaults.fit_fraction)),
        constraints=str(optimizer.get("constraints", defaults.constraints)),
        objective=str(optimizer.get("objective", defaults.objective)),
        background_size=int(expl.get("background_size", defaults.background_size)),
        sample_size=int(expl.get("sample_size", defaults.sample_size)),
        max_evals=int(expl.get("max_evals", defaults.max_evals)),
        top_k=int(expl.get("top_k", defaults.top_k)),
        lime_num_features=int(expl.get("lime_num_features", defaults.lime_num_features)),
        lime_num_samples=int(expl.get("lime_num_samples", defaults.lime_num_samples)),
    )


@dataclass(frozen=True)
class Champion:
    """The model under audit and where it came from."""

    model: Any
    candidate: str
    params: dict[str, Any]
    threshold: float
    artifact: str
    artifact_sha256: str
    version: str | None


def load_champion(settings: Settings) -> Champion:
    """Local champion artifact (written by ``make train`` together with ``model_spec.json``)."""
    models_dir = settings.paths.models_dir
    artifact = models_dir / settings.training.champion_artifact_name
    candidate, params, _ = load_champion_spec(settings)
    spec_path = models_dir / "model_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists() else {}
    return Champion(
        model=joblib.load(artifact),
        candidate=candidate,
        params=params,
        threshold=float(spec.get("decision_threshold", settings.training.decision_threshold)),
        artifact=artifact.name,
        artifact_sha256=sha256_of(artifact),
        version=str(spec["registered_version"]) if spec.get("registered_version") else None,
    )


def load_evaluation_data(settings: Settings) -> pd.DataFrame:
    """Labeled, never-trained-on applicants covering all ages, with a ``source`` column."""
    paths = settings.paths
    normal = pd.read_csv(paths.normal_stream).assign(source="stream_normal")
    drifted = pd.read_csv(paths.drifted_stream).merge(pd.read_csv(paths.ground_truth), on=REQUEST_ID_COLUMN)
    drifted = drifted.drop(columns=[REQUEST_ID_COLUMN]).assign(source="stream_drifted+feedback")
    columns = [*ALL_FEATURES, TARGET_COLUMN, "source"]
    return pd.concat([normal[columns], drifted[columns]], ignore_index=True)


def load_training_split(settings: Settings) -> tuple[pd.DataFrame, pd.Series]:
    """Training split of the baseline, identical to the one used by ``make train``."""
    training = settings.training
    baseline = pd.read_csv(settings.paths.baseline_data)
    x_train, _, y_train, _ = train_test_split(
        baseline[ALL_FEATURES],
        baseline[TARGET_COLUMN],
        test_size=training.test_size,
        random_state=training.random_state,
        stratify=baseline[TARGET_COLUMN],
    )
    return x_train, y_train


def dataset_overview(settings: Settings) -> dict[str, Any]:
    """Raw dataset statistics and the versioned partitions (for the data card)."""
    paths = settings.paths
    raw = pd.read_csv(paths.raw_data)
    manifest = json.loads(paths.data_manifest.read_text(encoding="utf-8")) if paths.data_manifest.exists() else {}
    partitions = []
    for entry in manifest.get("files", []):
        frame = pd.read_csv(paths.data_dir / entry["path"])
        partitions.append(
            {
                "path": entry["path"],
                "rows": int(len(frame)),
                "sha256": str(entry.get("sha256", ""))[:12],
                "age_min": int(frame["AGE"].min()) if "AGE" in frame else None,
                "age_max": int(frame["AGE"].max()) if "AGE" in frame else None,
                "default_rate": round(float(frame[TARGET_COLUMN].mean()), 6) if TARGET_COLUMN in frame else None,
            }
        )
    return {
        "dataset": manifest.get("dataset", {}),
        "fingerprint": manifest.get("fingerprint"),
        "raw_rows": int(len(raw)),
        "raw_columns": int(raw.shape[1]),
        "raw_default_rate": round(float(raw[TARGET_COLUMN].mean()), 6),
        "raw_missing_values": int(raw.isna().sum().sum()),
        "age_range": [int(raw["AGE"].min()), int(raw["AGE"].max())],
        "codes": {
            column: {str(code): int(count) for code, count in raw[column].value_counts().sort_index().items()}
            for column in ("SEX", "EDUCATION", "MARRIAGE", "PAY_0")
        },
        "partitions": partitions,
    }


# --- Fairness -----------------------------------------------------------------


def _composition(frame: pd.DataFrame, attributes: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    sensitive = fairness.sensitive_frame(frame)
    result = {}
    for attribute in attributes:
        grouped = pd.DataFrame({"group": sensitive[attribute], "y": frame[TARGET_COLUMN].to_numpy()}).groupby("group")
        result[attribute] = [
            {"group": str(group), "count": int(len(rows)), "default_rate": round(float(rows["y"].mean()), 6)}
            for group, rows in sorted(grouped, key=lambda item: fairness.group_sort_key(item[0]))
        ]
    return result


def run_fairness(
    champion: Champion,
    evaluation: pd.DataFrame,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    settings: Settings,
    cfg: ResponsibleAIConfig,
) -> dict[str, Any]:
    """Fairness audit on the full evaluation set plus the mitigation comparison per attribute."""
    serving, training = settings.serving, settings.training
    costs = {"cost_fn": training.cost_false_negative, "cost_fp": training.cost_false_positive}
    features, target = evaluation[ALL_FEATURES], evaluation[TARGET_COLUMN]
    sensitive = fairness.sensitive_frame(features)
    probabilities = np.asarray(champion.model.predict_proba(features))[:, 1]

    audit = fairness.audit_fairness(
        target,
        probabilities,
        sensitive,
        attributes=cfg.attributes,
        threshold=champion.threshold,
        review_threshold=serving.review_threshold,
        decline_threshold=serving.decline_threshold,
        tolerances=cfg.thresholds,
        **costs,
    )

    neutral = {column: serving.explain_reference[column] for column in fairness.PROTECTED_COLUMNS}
    train_sensitive = fairness.sensitive_frame(x_train)
    mitigation = {}
    for attribute in cfg.mitigation_attributes:
        strata = sensitive[attribute].astype(str) + "|" + target.astype(str)
        fit_idx, test_idx = train_test_split(
            np.arange(len(evaluation)), train_size=cfg.fit_fraction, random_state=cfg.random_state, stratify=strata
        )
        data = fairness.MitigationData(
            x_train=x_train,
            y_train=y_train,
            x_fit=features.iloc[fit_idx],
            y_fit=target.iloc[fit_idx],
            sensitive_fit=sensitive[attribute].iloc[fit_idx],
            x_test=features.iloc[test_idx],
            y_test=target.iloc[test_idx],
            sensitive_test=sensitive[attribute].iloc[test_idx],
            sensitive_train=train_sensitive[attribute],
        )
        rows = fairness.run_mitigation(
            champion.model,
            lambda: build_model_pipeline(champion.params, training.random_state, champion.candidate),
            data,
            threshold=champion.threshold,
            neutral_values=neutral,
            constraints=cfg.constraints,
            objective=cfg.objective,
            random_state=cfg.random_state,
            **costs,
        )
        mitigation[attribute] = {"fit_rows": int(len(fit_idx)), "test_rows": int(len(test_idx)), "variants": rows}
        logger.info("Mitigation %s: %d variants compared on %d test rows", attribute, len(rows), len(test_idx))

    return {
        "overall": {
            "rows": int(len(evaluation)),
            "default_rate": round(float(target.mean()), 6),
            "roc_auc": round(float(_roc_auc(target, probabilities)), 6),
            "flagged_rate": round(float(np.mean(probabilities >= champion.threshold)), 6),
            "approve_rate": round(float(np.mean(probabilities < serving.review_threshold)), 6),
        },
        "composition": _composition(evaluation, cfg.attributes),
        "sources": evaluation["source"].value_counts().to_dict(),
        "audit": audit,
        "mitigation": mitigation,
    }


def _roc_auc(target: pd.Series, scores: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(target, scores))


def plot_group_metrics(audit: dict[str, dict[str, Any]], path: Path) -> Path:
    """Approval rate, TPR and FPR per group for every audited attribute."""
    attributes = list(audit)
    fig, axes = plt.subplots(1, len(attributes), figsize=(4.6 * len(attributes), 4.2), squeeze=False)
    metrics = (("approve_rate", "approval rate"), ("tpr", "TPR"), ("fpr", "FPR"))
    for ax, attribute in zip(axes[0], attributes, strict=True):
        groups = audit[attribute]["groups"]
        labels = [row["group"] for row in groups]
        positions = np.arange(len(labels))
        width = 0.27
        for offset, (key, name) in enumerate(metrics):
            ax.bar(positions + (offset - 1) * width, [row[key] or 0.0 for row in groups], width, label=name)
        ax.set_xticks(positions, labels, rotation=30, ha="right")
        summary = audit[attribute]["summary"]
        ax.set_title(
            f"{attribute}\nDPD={summary['demographic_parity_difference']:.3f} "
            f"EOD={summary['equalized_odds_difference']:.3f}"
        )
        ax.set_ylim(0, 1)
    axes[0][0].legend(loc="upper left")
    fig.suptitle("Group metrics of the champion (evaluation set)")
    return _save(path)


def plot_decisions_by_group(audit: dict[str, Any], attribute: str, path: Path) -> Path:
    """Stacked APPROVE / REVIEW / DECLINE shares per group of ``attribute``."""
    groups = audit[attribute]["groups"]
    labels = [row["group"] for row in groups]
    bottom = np.zeros(len(labels))
    fig, ax = plt.subplots(figsize=(7, 4))
    for key, color in (("approve_rate", "#2ca02c"), ("review_rate", "#ff7f0e"), ("decline_rate", "#d62728")):
        values = np.array([row[key] for row in groups], dtype=float)
        ax.bar(labels, values, bottom=bottom, color=color, label=key.replace("_rate", "").upper())
        bottom += values
    ax.set_ylabel("share of applicants")
    ax.set_title(f"Serving decisions by {attribute}")
    ax.legend(loc="upper right")
    del fig
    return _save(path)


def plot_mitigation_tradeoff(mitigation: dict[str, Any], path: Path) -> Path:
    """Equalized odds difference vs expected loss (annotated with ROC-AUC) for each variant."""
    attributes = list(mitigation)
    fig, axes = plt.subplots(1, len(attributes), figsize=(6.2 * len(attributes), 4.6), squeeze=False)
    for ax, attribute in zip(axes[0], attributes, strict=True):
        for row in mitigation[attribute]["variants"]:
            x, y = row["equalized_odds_difference"], row["expected_loss"]
            ax.scatter(x, y, s=70)
            ax.annotate(
                f"{row['variant']}\nAUC {row['roc_auc']:.3f}",
                (x, y),
                fontsize=8,
                xytext=(5, 4),
                textcoords="offset points",
            )
        ax.set_xlabel("equalized odds difference (lower = fairer)")
        ax.set_ylabel("expected loss per applicant (lower = better)")
        ax.set_title(f"Mitigation trade-off — {attribute}")
        ax.grid(alpha=0.3)
    del fig
    return _save(path)


def _save(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close("all")
    return path


# --- Explainability -------------------------------------------------------------


def select_profiles(probabilities: np.ndarray, review_threshold: float, decline_threshold: float) -> dict[str, int]:
    """One representative row per decision: the applicant closest to that decision's median probability."""
    decisions = fairness.approval_decisions(probabilities, review_threshold, decline_threshold)
    selected = {}
    for decision in PROFILE_DECISIONS:
        rows = np.flatnonzero(decisions == decision)
        if len(rows):
            median = float(np.median(probabilities[rows]))
            selected[decision] = int(rows[np.argmin(np.abs(probabilities[rows] - median))])
    return selected


def run_explainability(
    champion: Champion,
    evaluation: pd.DataFrame,
    x_train: pd.DataFrame,
    settings: Settings,
    cfg: ResponsibleAIConfig,
    figures_dir: Path,
) -> dict[str, Any]:
    """SHAP global + local explanations and LIME for the same representative applicants."""
    serving = settings.serving
    features = evaluation[ALL_FEATURES].reset_index(drop=True)
    background = x_train.sample(n=min(cfg.background_size, len(x_train)), random_state=cfg.random_state)
    sample = features.sample(n=min(cfg.sample_size, len(features)), random_state=cfg.random_state)
    explainer = xai.ShapExplainer(champion.model, background, max_evals=cfg.max_evals, seed=cfg.random_state)

    logger.info("SHAP: explaining %d applicants against %d background rows", len(sample), len(background))
    global_explanation = explainer.explain(sample)
    importance = xai.global_importance(global_explanation)
    figures = {
        "shap_summary": xai.plot_shap_summary(global_explanation, figures_dir / "rai_shap_summary.png"),
        "shap_bar": xai.plot_shap_bar(global_explanation, figures_dir / "rai_shap_bar.png"),
    }

    probabilities = np.asarray(champion.model.predict_proba(features))[:, 1]
    profiles = select_profiles(probabilities, serving.review_threshold, serving.decline_threshold)
    profile_frame = features.iloc[list(profiles.values())]
    local_explanation = explainer.explain(profile_frame)

    local: list[dict[str, Any]] = []
    for position, (decision, row_index) in enumerate(profiles.items()):
        slug = decision.lower()
        shap_items = xai.local_contributions(local_explanation, position)
        lime_items = xai.lime_explain(
            champion.model,
            x_train,
            features.iloc[row_index],
            num_features=cfg.lime_num_features,
            num_samples=cfg.lime_num_samples,
            seed=cfg.random_state,
        )
        probability = float(probabilities[row_index])
        figures[f"shap_waterfall_{slug}"] = xai.plot_shap_waterfall(
            local_explanation[position],
            figures_dir / f"rai_shap_waterfall_{slug}.png",
            f"SHAP — {decision} applicant (P(default) = {probability:.3f})",
        )
        figures[f"lime_{slug}"] = xai.plot_lime(
            lime_items,
            figures_dir / f"rai_lime_{slug}.png",
            f"LIME — {decision} applicant (P(default) = {probability:.3f})",
        )
        serving_view = xai.explain_against_reference(
            champion.model,
            features.iloc[row_index].to_dict(),
            serving.explain_reference,
            ALL_FEATURES,
            max_evals=serving.explain_shap_max_evals,
            seed=serving.explain_seed,
        )
        additivity_error = abs(
            serving_view.reference_probability + sum(serving_view.contributions.values()) - probability
        )
        local.append(
            {
                "decision": decision,
                "evaluation_row": row_index,
                "probability": round(probability, 6),
                "base_value": round(float(np.ravel(local_explanation.base_values)[position]), 6),
                "shap_top": [_round_item(item) for item in shap_items[: cfg.top_k]],
                "lime_top": [_round_item(item) for item in lime_items[: cfg.top_k]],
                "agreement": xai.rank_agreement(shap_items, lime_items, k=cfg.top_k),
                "risk_factors": xai.risk_factor_messages(shap_items),
                "serving_additivity_error": round(float(additivity_error), 8),
            }
        )

    return {
        "method": {
            "shap": f"PermutationExplainer on P(default) of the full pipeline, {len(background)} background "
            f"training applicants, max_evals={cfg.max_evals}",
            "lime": f"LimeTabularExplainer, {cfg.lime_num_samples} samples, discretized continuous features",
            "serving": "PermutationExplainer against the reference applicant, "
            f"max_evals={serving.explain_shap_max_evals}",
        },
        "sample_size": int(len(sample)),
        "background_size": int(len(background)),
        "global_importance": [
            {
                "feature": row.feature,
                "mean_abs_shap": round(float(row.mean_abs_shap), 6),
                "share": round(float(row.share), 6),
            }
            for row in importance.itertuples()
        ],
        "local": local,
        "mean_overlap_at_k": round(float(np.mean([item["agreement"]["overlap_at_k"] for item in local])), 4),
        "figures": {name: _relative(path, settings.paths.project_root) for name, path in figures.items()},
    }


def _round_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: round(value, 6) if isinstance(value, float) else value for key, value in item.items()}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --- Orchestration --------------------------------------------------------------


@dataclass
class ResponsibleAIOutcome:
    """Reports written by :func:`run_responsible_ai`."""

    fairness: dict[str, Any]
    explainability: dict[str, Any]
    paths: dict[str, Path]
    synced_docs: list[Path]


def run_responsible_ai(
    settings: Settings | None = None, config_path: Path | None = None, sync_docs: bool = True
) -> ResponsibleAIOutcome:
    """Run the full analysis and write reports, figures and doc blocks."""
    from credit_risk.responsible_ai import reporting

    cfg_settings = settings or get_settings()
    paths = cfg_settings.paths
    cfg = load_rai_config(config_path or paths.configs_dir / CONFIG_FILE)
    reports_dir = paths.reports_dir
    figures_dir = reports_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    champion = load_champion(cfg_settings)
    evaluation = load_evaluation_data(cfg_settings)
    x_train, y_train = load_training_split(cfg_settings)
    logger.info("Champion %s (%s) | evaluation rows %d", champion.candidate, champion.artifact, len(evaluation))

    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    model_info = {
        "candidate": champion.candidate,
        "params": champion.params,
        "decision_threshold": champion.threshold,
        "review_threshold": cfg_settings.serving.review_threshold,
        "decline_threshold": cfg_settings.serving.decline_threshold,
        "artifact": champion.artifact,
        "artifact_sha256": champion.artifact_sha256,
        "registered_version": champion.version,
    }

    fairness_result = run_fairness(champion, evaluation, x_train, y_train, cfg_settings, cfg)
    figure_paths = {
        "group_metrics": plot_group_metrics(fairness_result["audit"], figures_dir / "rai_fairness_group_metrics.png"),
        "decisions_by_age": plot_decisions_by_group(
            fairness_result["audit"], "age_group", figures_dir / "rai_decisions_by_age_group.png"
        ),
        "mitigation_tradeoff": plot_mitigation_tradeoff(
            fairness_result["mitigation"], figures_dir / "rai_mitigation_tradeoff.png"
        ),
    }
    fairness_report = {
        "generated_at": generated_at,
        "model": model_info,
        "costs": {
            "false_negative": cfg_settings.training.cost_false_negative,
            "false_positive": cfg_settings.training.cost_false_positive,
        },
        "config": {
            "attributes": list(cfg.attributes),
            "thresholds": vars(cfg.thresholds),
            "mitigation_attributes": list(cfg.mitigation_attributes),
            "fit_fraction": cfg.fit_fraction,
            "threshold_optimizer": {"constraints": cfg.constraints, "objective": cfg.objective},
            "random_state": cfg.random_state,
        },
        **fairness_result,
        "dataset": dataset_overview(cfg_settings),
        "privacy": {
            "pii_inventory": PII_INVENTORY,
            "inference_log_retention_days": DEFAULT_RETENTION_DAYS,
        },
        "figures": {name: _relative(path, paths.project_root) for name, path in figure_paths.items()},
    }

    explainability_report = {
        "generated_at": generated_at,
        "model": model_info,
        **run_explainability(champion, evaluation, x_train, cfg_settings, cfg, figures_dir),
    }

    written = {
        "fairness_json": reporting.write_json(fairness_report, reports_dir / FAIRNESS_JSON),
        "fairness_md": reporting.write_text(
            reporting.render_fairness_markdown(fairness_report), reports_dir / FAIRNESS_MD
        ),
        "explainability_json": reporting.write_json(explainability_report, reports_dir / EXPLAINABILITY_JSON),
        "explainability_md": reporting.write_text(
            reporting.render_explainability_markdown(explainability_report), reports_dir / EXPLAINABILITY_MD
        ),
    }
    synced = []
    if sync_docs:
        synced = reporting.sync_docs(paths.project_root, fairness_report, explainability_report)
    return ResponsibleAIOutcome(fairness_report, explainability_report, written, synced)
