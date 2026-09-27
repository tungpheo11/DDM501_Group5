"""
SHAP explanations for individual scoring decisions.

"""

import logging
from typing import Any, Dict, List

import numpy as np

from pipeline.preprocessing import add_derived_features

logger = logging.getLogger(__name__)


class Explainer:
    """Wraps a SHAP TreeExplainer around the fitted pipeline.

    The pipeline is (features -> classifier). SHAP needs the raw estimator and
    the TRANSFORMED matrix, so this class holds both halves and does the
    transformation itself. Handing the whole pipeline to shap and hoping is
    the usual mistake.
    """

    def __init__(self, pipeline: Any):
        self.pipeline = pipeline
        self.feature_step = pipeline.named_steps["features"]
        self.classifier = pipeline.named_steps["classifier"]
        self.feature_names = list(
            self.feature_step.named_steps["preprocess"].get_feature_names_out()
        )
        self._explainer = None

    def _ensure_explainer(self):
        """Build the explainer on first use.

        Lazily, because importing shap costs about a second and a container
        that is not asked for explanations should not pay it at startup.
        """
        if self._explainer is None:
            import shap

            self._explainer = shap.TreeExplainer(self.classifier)
        return self._explainer

    def explain(self, frame, top_n: int = 8) -> Dict[str, Any]:
        """Return the features that moved this one score, largest first.

        TASK 10:
          - Transform the frame with self.feature_step, then call
            shap_values on self.classifier's explainer.
          - Depending on the model, shap returns (n, features) or
            (n, features, classes). Normalise to the positive class.
          - expected_value may be a scalar or an array; normalise it too.
          - Sort by ABSOLUTE contribution and keep the top n.
          - Report the applicant's OWN value for each feature, not the
            standardised one. add_derived_features(frame) gives you the
            derived ones; one-hot columns have no counterpart in the
            application and fall back to the transformed value. An adverse
            action notice quoting "your PAY_0 was 2.16" cannot be reconciled
            with the application form by anyone outside the ML team.
        """
        explainer = self._ensure_explainer()

        # Add derived features so derived columns are present
        enriched = add_derived_features(frame)

        # Transform with the feature pipeline step
        X_transformed = self.feature_step.transform(enriched)

        # Compute SHAP values
        shap_values = explainer.shap_values(X_transformed)

        # Normalise to positive class (default probability):
        # shap returns (n, features) for binary or list/3D for multi-class
        ev = explainer.expected_value
        if isinstance(shap_values, list):
            # Older shap: list of [neg_class_array, pos_class_array]
            sv = shap_values[-1][0]  # last = positive class
            base_val = float(ev[-1]) if hasattr(ev, "__len__") else float(ev)
        elif hasattr(shap_values, "ndim") and shap_values.ndim == 3:
            # (n, features, classes) — take last class
            sv = shap_values[0, :, -1]
            base_val = float(ev[-1]) if hasattr(ev, "__len__") else float(ev)
        else:
            # (n, features) — single output, row 0
            sv = shap_values[0] if (hasattr(shap_values, "ndim") and shap_values.ndim == 2) else shap_values
            # expected_value may be scalar or 1-element array — always take [0] or itself
            base_val = float(ev[0]) if hasattr(ev, "__len__") else float(ev)

        # Raw feature values from enriched frame (includes derived features)
        raw_row = enriched.iloc[0].to_dict()

        # Sort by absolute contribution, keep top_n
        indices = sorted(range(len(sv)), key=lambda i: abs(sv[i]), reverse=True)[:top_n]

        contributions: List[Dict[str, Any]] = []
        for idx in indices:
            fname = self.feature_names[idx]
            contrib = float(sv[idx])

            # Use raw applicant value if available; fall back to transformed
            if fname in raw_row and raw_row[fname] is not None:
                raw_val = float(raw_row[fname])
            else:
                raw_val = float(X_transformed[0, idx])

            contributions.append({
                "feature": fname,
                "value": raw_val,
                "contribution": contrib,
                "direction": "increases risk" if contrib > 0 else "reduces risk",
            })

        return {
            "base_value": base_val,
            "contributions": contributions,
            "note": f"Top {top_n} features by absolute SHAP value (log-odds scale)",
        }
