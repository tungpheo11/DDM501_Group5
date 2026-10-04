"""Champion/challenger quality gate.

Pure decision logic (no MLflow calls) so the same gate is used by ``make train``,
``make retrain`` and the Airflow retraining DAG, and is trivially unit-testable.
Both models must be scored on the **same** evaluation set before calling
:func:`compare_champion_challenger`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PromotionPolicy:
    """Thresholds of the promotion gate.

    Attributes:
        min_roc_auc: absolute quality floor for any model allowed to serve.
        max_roc_auc_drop: non-inferiority margin: the challenger may rank at most this
            much worse than the champion (ROC-AUC points).
        min_loss_improvement: relative reduction of expected financial loss per cardholder
            required when ROC-AUC does not improve (0.0 = any strict reduction).
    """

    min_roc_auc: float = 0.70
    max_roc_auc_drop: float = 0.005
    min_loss_improvement: float = 0.0


@dataclass(frozen=True)
class GateDecision:
    """Outcome of the gate with human-readable reasons (logged to MLflow and reports)."""

    promote: bool
    reasons: list[str] = field(default_factory=list)
    challenger: dict[str, float] = field(default_factory=dict)
    champion: dict[str, float] | None = None
    roc_auc_delta: float | None = None
    expected_loss_delta: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable representation."""
        return asdict(self)


def _pick(metrics: dict[str, float]) -> dict[str, float]:
    return {"roc_auc": float(metrics["roc_auc"]), "expected_loss": float(metrics["expected_loss"])}


def compare_champion_challenger(
    challenger_metrics: dict[str, float],
    champion_metrics: dict[str, float] | None,
    policy: PromotionPolicy | None = None,
) -> GateDecision:
    """Decide whether the challenger replaces the champion.

    Promote only when all hold:

    1. challenger ROC-AUC >= ``min_roc_auc``;
    2. no champion exists, **or**
    3. ROC-AUC is non-inferior (drop <= ``max_roc_auc_drop``), expected loss is not
       worse, and at least one of them strictly improves (ROC-AUC up, or expected
       loss down by more than ``min_loss_improvement`` relative).

    Args:
        challenger_metrics: needs ``roc_auc`` and ``expected_loss``.
        champion_metrics: same keys on the same evaluation set, or ``None`` if no champion.
        policy: gate thresholds; defaults to :class:`PromotionPolicy`.
    """
    rules = policy or PromotionPolicy()
    challenger = _pick(challenger_metrics)

    if challenger["roc_auc"] < rules.min_roc_auc:
        return GateDecision(
            promote=False,
            reasons=[f"challenger ROC-AUC {challenger['roc_auc']:.4f} below floor {rules.min_roc_auc:.2f}"],
            challenger=challenger,
            champion=_pick(champion_metrics) if champion_metrics else None,
        )
    if champion_metrics is None:
        return GateDecision(
            promote=True,
            reasons=["no current champion; challenger passes the quality floor"],
            challenger=challenger,
        )

    champion = _pick(champion_metrics)
    auc_delta = challenger["roc_auc"] - champion["roc_auc"]
    loss_delta = challenger["expected_loss"] - champion["expected_loss"]
    required_loss_drop = rules.min_loss_improvement * champion["expected_loss"]

    reasons: list[str] = [
        f"ROC-AUC {challenger['roc_auc']:.4f} vs {champion['roc_auc']:.4f} (delta {auc_delta:+.4f})",
        f"expected loss {challenger['expected_loss']:.4f} vs {champion['expected_loss']:.4f} "
        f"(delta {loss_delta:+.4f})",
    ]
    auc_non_inferior = auc_delta >= -rules.max_roc_auc_drop
    loss_not_worse = loss_delta <= 0.5
    auc_improves = auc_delta > 0
    loss_improves = loss_delta < 0 and -loss_delta > required_loss_drop

    if not auc_non_inferior:
        reasons.append(f"rejected: ROC-AUC drop exceeds margin {rules.max_roc_auc_drop:.3f}")
    elif not loss_not_worse:
        reasons.append("rejected: expected financial loss is higher than the champion's")
    elif not (auc_improves or loss_improves):
        reasons.append("rejected: no strict improvement over the champion")
    promote = auc_non_inferior and loss_not_worse and (auc_improves or loss_improves)
    if promote:
        reasons.append("promoted: non-inferior ranking and lower-or-equal business cost with a strict improvement")

    return GateDecision(
        promote=promote,
        reasons=reasons,
        challenger=challenger,
        champion=champion,
        roc_auc_delta=auc_delta,
        expected_loss_delta=loss_delta,
    )
