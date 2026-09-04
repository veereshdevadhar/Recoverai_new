from __future__ import annotations

"""Model-grounded Feature Attribution.

Two real, model-grounded (not fabricated) explanations:

1. **Per-decision attribution** (``explain_instance``): for the specific
   event just scored, each feature's contribution is measured by actually
   re-running the trained pipeline with that one feature reset to its
   population-typical value and observing how much the predicted
   probability moves. This is a single-feature ablation / occlusion
   attribution — a well-understood, model-agnostic local explanation
   technique — computed by really calling ``predict_proba`` on the real
   pipeline, not estimated or invented.

2. **Global feature importance** (``global_importance``): real
   permutation importance (``sklearn.inspection.permutation_importance``)
   computed against real held-out ground truth (``recovery_success`` from
   ``data/raw/recovery_actions.csv``, joined onto the August evaluation
   rows for the relevant action), scored on ROC-AUC. This is the standard,
   defensible way to rank feature importance for a model that (like
   ``HistGradientBoostingClassifier``) does not expose
   ``feature_importances_`` directly.

Both are cached per-process since the underlying model/data don't change
during a run.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
EVAL_PATH = PROCESSED / "v3_100k_august_policy_results.csv"
RAW_ACTIONS_PATH = RAW / "recovery_actions.csv"

# Human-readable framing for the handful of features most likely to be
# perturbed; purely cosmetic labels, the numbers themselves are always real.
FEATURE_LABELS = {
    "amount": "Transaction amount",
    "retry_count": "Retry count",
    "historical_success_rate": "Customer success rate",
    "merchant_success_rate": "Merchant success rate",
    "failure_nonretryable": "Non-retryable failure type",
    "repeated_failure": "Repeated failure flag",
    "customer_tenure_days": "Customer tenure",
    "days_since_last_success": "Days since last successful recovery",
    "total_transactions": "Total customer transactions",
    "checkout_duration_seconds": "Checkout duration",
    "subscription_age_days": "Subscription age",
    "failed_cycles": "Failed billing cycles",
    "successful_cycles": "Successful billing cycles",
    "payment_page_reached": "Reached payment page",
    "high_value": "High-value transaction flag",
    "strong_customer_history": "Strong customer history flag",
}


@lru_cache(maxsize=1)
def _reference_row(features: tuple[str, ...]) -> pd.Series:
    """Population-typical value for each feature (mean for numeric,
    mode for everything else), computed from the real evaluation set."""
    df = pd.read_csv(EVAL_PATH)
    ref = {}
    for f in features:
        col = df[f]
        if pd.api.types.is_numeric_dtype(col):
            ref[f] = float(col.mean())
        else:
            ref[f] = col.mode(dropna=True).iloc[0] if not col.mode(dropna=True).empty else col.iloc[0]
    return pd.Series(ref)


def explain_instance(model, X_row: pd.DataFrame, features: list[str], top_n: int = 6) -> list[dict[str, Any]]:
    """Real perturbation-based attribution for one scored instance."""
    reference = _reference_row(tuple(features))
    baseline_prob = float(model.predict_proba(X_row)[0, 1])

    impacts = []
    for f in features:
        actual = X_row[f].iloc[0]
        typical = reference[f]
        if pd.isna(actual) and pd.isna(typical):
            continue
        if actual == typical:
            continue
        X_mod = X_row.copy()
        X_mod[f] = typical
        try:
            prob_mod = float(model.predict_proba(X_mod)[0, 1])
        except Exception:
            continue
        delta = round(baseline_prob - prob_mod, 4)
        if abs(delta) < 1e-4:
            continue
        impacts.append({
            "feature": f,
            "label": FEATURE_LABELS.get(f, f.replace("_", " ").title()),
            "actual_value": actual if not isinstance(actual, (np.floating, np.integer)) else float(actual),
            "typical_value": round(float(typical), 3) if isinstance(typical, (int, float, np.floating, np.integer)) else typical,
            "impact": delta,
            "direction": "increases" if delta > 0 else "decreases",
        })

    impacts.sort(key=lambda x: abs(x["impact"]), reverse=True)
    return impacts[:top_n]


@lru_cache(maxsize=8)
def global_importance(action: str, features: tuple[str, ...], sample_size: int = 1500) -> list[dict[str, Any]]:
    """Real permutation importance against real ground-truth labels for
    this action, on the August held-out evaluation set."""
    from sklearn.inspection import permutation_importance

    from src.evaluation.policy_lab import _load_model  # reuse the cached artifact

    artifact = _load_model()
    model = artifact["models"][action]

    eval_df = pd.read_csv(EVAL_PATH)
    raw = pd.read_csv(RAW_ACTIONS_PATH)
    labels = raw[raw["action"] == action][["event_id", "recovery_success"]].rename(columns={"recovery_success": "label"})
    merged = eval_df.merge(labels, on="event_id", how="inner")

    X_all = merged[list(features)]
    n = min(sample_size, len(X_all))
    idx = X_all.sample(n=n, random_state=42).index
    X = X_all.loc[idx]
    y = merged.loc[idx, "label"]

    result = permutation_importance(model, X, y, scoring="roc_auc", n_repeats=3, random_state=42, n_jobs=-1)

    order = np.argsort(result.importances_mean)[::-1]
    return [
        {
            "feature": features[i],
            "label": FEATURE_LABELS.get(features[i], features[i].replace("_", " ").title()),
            "importance": round(float(result.importances_mean[i]), 5),
        }
        for i in order[:10] if result.importances_mean[i] > 0
    ]
