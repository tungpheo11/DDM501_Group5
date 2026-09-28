"""
Module: explainability.py
Provides Model Explainability and Interpretability for Credit Risk Decisions:
- Global Feature Importance ranking (Tree & Linear models)
- Local Sample Decision Explanations (Adverse Action Reasons for FCRA/ECOA compliance)
- Feature Attribution Analysis
"""

from typing import Dict, Any, List
import numpy as np
import pandas as pd


def get_global_feature_importance(model: Any, feature_names: List[str]) -> List[Dict[str, Any]]:
    """
    Extracts global feature importances from a trained model pipeline or estimator.
    Returns sorted list of features with importance weights and percentages.
    """
    estimator = model.named_steps.get("classifier", model) if hasattr(model, "named_steps") else model

    if hasattr(estimator, "feature_importances_"):
        importances = estimator.feature_importances_
    elif hasattr(estimator, "coef_"):
        importances = np.abs(estimator.coef_[0])
    else:
        # Uniform fallback
        importances = np.ones(len(feature_names)) / len(feature_names)

    total_weight = float(np.sum(importances)) or 1.0
    ranked = []
    for name, weight in zip(feature_names, importances):
        ranked.append({
            "feature": name,
            "importance_weight": float(weight),
            "importance_pct": round(float(weight / total_weight) * 100, 2),
        })

    ranked.sort(key=lambda x: x["importance_weight"], reverse=True)
    return ranked


def explain_single_prediction(
    model: Any,
    feature_row: Dict[str, Any],
    all_features: List[str],
    top_n: int = 4,
) -> Dict[str, Any]:
    """
    Generates local decision explanation and Adverse Action Reason Codes.
    Complies with Fair Credit Reporting Act (FCRA) and ECOA requirement
    to explain credit decline or review decisions.
    """
    df_row = pd.DataFrame([feature_row])[all_features]

    # Predict probability
    if hasattr(model, "predict_proba"):
        prob = float(model.predict_proba(df_row)[0, 1])
    else:
        prob = float(model.predict(df_row)[0])

    global_importances = get_global_feature_importance(model, all_features)

    # Derive local contribution proxy: Feature Weight * Deviation from Healthy Benchmark
    local_factors = []
    for item in global_importances:
        feat = item["feature"]
        val = float(feature_row.get(feat, 0.0))
        weight = item["importance_weight"]

        # Calculate directional risk contribution
        if feat.startswith("PAY_") and not feat.startswith("PAY_AMT"):
            # Repayment delay is strongest risk driver
            risk_impact = max(0.0, val) * weight * 3.0
            description = (
                f"Delinquent payment status in recent billing cycle ({int(val)} month(s) past due)"
                if val > 0
                else "Satisfactory on-time payment track record"
            )
        elif feat == "LIMIT_BAL":
            # Low credit limit relative to risk
            risk_impact = max(0.0, (150000.0 - val) / 150000.0) * weight
            description = f"Total credit line limit (${val:,.0f} NTD)"
        elif feat.startswith("BILL_AMT"):
            risk_impact = max(0.0, val / 100000.0) * weight
            description = f"Outstanding statement billing balance (${val:,.0f} NTD)"
        elif feat.startswith("PAY_AMT"):
            risk_impact = max(0.0, (10000.0 - val) / 10000.0) * weight
            description = f"Amount of previous payment settled (${val:,.0f} NTD)"
        else:
            risk_impact = weight * 0.1
            description = f"Demographic / Account parameter: {feat} = {val}"

        local_factors.append({
            "feature": feat,
            "current_value": val,
            "risk_impact_score": round(float(risk_impact), 4),
            "regulatory_reason": description,
        })

    local_factors.sort(key=lambda x: x["risk_impact_score"], reverse=True)
    top_drivers = local_factors[:top_n]

    risk_tier = "DECLINE" if prob >= 0.60 else ("REVIEW" if prob >= 0.30 else "APPROVE")

    return {
        "default_probability": round(prob, 4),
        "risk_tier": risk_tier,
        "primary_risk_drivers": top_drivers,
        "adverse_action_codes": [d["regulatory_reason"] for d in top_drivers if d["risk_impact_score"] > 0],
    }
