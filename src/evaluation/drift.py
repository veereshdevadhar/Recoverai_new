from __future__ import annotations

"""Model Health / Data Drift detection.

Compares the real distribution of a handful of pre-action numeric features
between the reference window the models were trained on (January-June, per
BUILD docs and ``recoverai_v3_100k_metrics.json``) and the current held-out
window (August) using two standard, real statistical tests:

  * Kolmogorov-Smirnov two-sample test (distribution shape difference)
  * Population Stability Index (PSI), the standard industry drift metric

No drift is invented: if the two distributions are close, the tests will
correctly report LOW/no drift.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
EVENTS_PATH = RAW / "events.csv"

DRIFT_FEATURES = ["amount", "retry_count", "checkout_duration_seconds", "subscription_age_days"]

PSI_DRIFT_THRESHOLD = 0.2
PSI_MODERATE_THRESHOLD = 0.1
KS_ALPHA = 0.01  # very small p-value required to flag drift, to avoid noise on 90K+ rows


def _psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index between two 1-D numeric samples."""
    reference = reference[np.isfinite(reference)]
    current = current[np.isfinite(current)]
    if len(reference) == 0 or len(current) == 0:
        return 0.0
    quantiles = np.linspace(0, 1, bins + 1)
    edges = np.unique(np.quantile(reference, quantiles))
    if len(edges) < 3:
        return 0.0
    edges[0] = -np.inf
    edges[-1] = np.inf

    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)

    ref_pct = np.clip(ref_counts / max(1, ref_counts.sum()), 1e-6, None)
    cur_pct = np.clip(cur_counts / max(1, cur_counts.sum()), 1e-6, None)

    return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))


@lru_cache(maxsize=1)
def _load_events() -> pd.DataFrame:
    df = pd.read_csv(EVENTS_PATH, parse_dates=["timestamp"])
    return df


def detect_drift() -> dict[str, Any]:
    df = _load_events()
    reference = df[df["timestamp"] < "2026-07-01"]
    current = df[df["timestamp"] >= "2026-08-01"]

    feature_results = []
    worst_status = "STABLE"
    status_rank = {"STABLE": 0, "MODERATE_DRIFT": 1, "DRIFT_DETECTED": 2}

    for feature in DRIFT_FEATURES:
        ref_vals = reference[feature].dropna().to_numpy(dtype=float)
        cur_vals = current[feature].dropna().to_numpy(dtype=float)

        psi = _psi(ref_vals, cur_vals)
        ks_stat, ks_pvalue = stats.ks_2samp(ref_vals, cur_vals)

        if psi >= PSI_DRIFT_THRESHOLD or (ks_pvalue < KS_ALPHA and ks_stat > 0.1):
            status = "DRIFT_DETECTED"
        elif psi >= PSI_MODERATE_THRESHOLD:
            status = "MODERATE_DRIFT"
        else:
            status = "STABLE"

        if status_rank[status] > status_rank[worst_status]:
            worst_status = status

        feature_results.append({
            "feature": feature,
            "reference_mean": round(float(np.mean(ref_vals)), 4) if len(ref_vals) else None,
            "current_mean": round(float(np.mean(cur_vals)), 4) if len(cur_vals) else None,
            "psi": round(psi, 4),
            "ks_statistic": round(float(ks_stat), 4),
            "ks_pvalue": float(ks_pvalue),
            "status": status,
        })

    return {
        "reference_window": "2026-01-01 to 2026-06-30 (training window)",
        "current_window": "2026-08-01 to 2026-08-31 (held-out evaluation window)",
        "reference_rows": int(len(reference)),
        "current_rows": int(len(current)),
        "features": feature_results,
        "overall_status": worst_status,
        "retraining_recommended": worst_status == "DRIFT_DETECTED",
        "methodology": "Population Stability Index (bins=10) and two-sample Kolmogorov-Smirnov test per feature.",
    }


def model_health(metrics: dict[str, Any], actions: list[str]) -> dict[str, Any]:
    """Per-action model metrics (AUC, average precision, sample counts) plus drift."""
    artifact_path = ROOT / "data" / "processed" / "models" / "recoverai_v3_100k_action_models.joblib"
    prediction_distribution = {}
    try:
        import joblib
        artifact = joblib.load(artifact_path)
        eval_df = pd.read_csv(ROOT / "data" / "processed" / "v3_100k_august_policy_results.csv")
        X = eval_df[artifact["features"]]
        for action in actions:
            probs = artifact["models"][action].predict_proba(X)[:, 1]
            prediction_distribution[action] = {
                "mean": round(float(np.mean(probs)), 4),
                "p10": round(float(np.percentile(probs, 10)), 4),
                "p50": round(float(np.percentile(probs, 50)), 4),
                "p90": round(float(np.percentile(probs, 90)), 4),
            }
    except Exception:
        prediction_distribution = {}

    per_action = []
    for action in actions:
        test_metrics = metrics.get(action, {}).get("test", {})
        per_action.append({
            "action": action,
            "roc_auc": round(test_metrics.get("roc_auc", 0.0), 4),
            "average_precision": round(test_metrics.get("average_precision", 0.0), 4) if test_metrics.get("average_precision") is not None else None,
            "sample_count": test_metrics.get("rows"),
            "prediction_distribution": prediction_distribution.get(action),
            "status": "HEALTHY" if test_metrics.get("roc_auc", 0.0) >= 0.65 else "NEEDS_REVIEW",
        })

    return {
        "per_action_metrics": per_action,
        "drift": detect_drift(),
    }
