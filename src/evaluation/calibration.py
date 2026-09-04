from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

from sklearn.metrics import (
    brier_score_loss,
    roc_auc_score,
    average_precision_score,
)
from sklearn.calibration import calibration_curve

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.features.v1_features import build_v1_dataset


MODEL_PATH = (
    ROOT
    / "data"
    / "processed"
    / "models"
    / "recoverai_v1.joblib"
)

ACTIONS = [
    "RETRY_LATER",
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "HUMAN_ESCALATION",
]


def calibration_table(y_true, probabilities, bins=10):

    y_true = np.asarray(y_true)
    probabilities = np.asarray(probabilities)

    rows = []

    edges = np.linspace(0, 1, bins + 1)

    for i in range(bins):

        if i == bins - 1:
            mask = (
                (probabilities >= edges[i]) &
                (probabilities <= edges[i + 1])
            )
        else:
            mask = (
                (probabilities >= edges[i]) &
                (probabilities < edges[i + 1])
            )

        if mask.sum() == 0:
            continue

        rows.append({
            "probability_range": (
                f"{edges[i]:.1f}-{edges[i + 1]:.1f}"
            ),
            "events": int(mask.sum()),
            "predicted_probability": float(
                probabilities[mask].mean()
            ),
            "actual_success_rate": float(
                y_true[mask].mean()
            ),
            "absolute_gap": float(
                abs(
                    probabilities[mask].mean()
                    - y_true[mask].mean()
                )
            ),
        })

    return pd.DataFrame(rows)


def main():

    print("\n")
    print("=" * 75)
    print("RECOVERAI V1 — PROBABILITY CALIBRATION")
    print("HELD-OUT AUGUST")
    print("=" * 75)

    df, features = build_v1_dataset()

    df = df[
        df["action"].isin(ACTIONS)
    ].copy()

    test = df[
        df["timestamp"] >= "2026-08-01"
    ].copy()

    model = joblib.load(MODEL_PATH)

    test["predicted_probability"] = model.predict_proba(
        test[features]
    )[:, 1]

    y = test["recovery_success"]
    p = test["predicted_probability"]

    # ---------------------------------------------------------
    # OVERALL CALIBRATION
    # ---------------------------------------------------------

    brier = brier_score_loss(y, p)
    auc = roc_auc_score(y, p)
    ap = average_precision_score(y, p)

    print("\nOVERALL")
    print("-" * 75)

    print(f"Events: {len(test):,}")
    print(f"Brier score: {brier:.6f}")
    print(f"ROC-AUC: {auc:.6f}")
    print(f"Average precision: {ap:.6f}")
    print(f"Mean predicted probability: {p.mean():.4f}")
    print(f"Actual success rate: {y.mean():.4f}")

    # ---------------------------------------------------------
    # CALIBRATION TABLE
    # ---------------------------------------------------------

    print("\nCALIBRATION TABLE")
    print("-" * 75)

    table = calibration_table(
        y,
        p,
        bins=10
    )

    print(
        table.to_string(
            index=False
        )
    )

    # ---------------------------------------------------------
    # ACTION-BY-ACTION CALIBRATION
    # ---------------------------------------------------------

    print("\nACTION-SPECIFIC CALIBRATION")
    print("-" * 75)

    action_results = []

    for action in ACTIONS:

        subset = test[
            test["action"] == action
        ]

        if len(subset) == 0:
            continue

        y_action = subset["recovery_success"]
        p_action = subset["predicted_probability"]

        action_results.append({
            "action": action,
            "events": len(subset),
            "predicted_mean": p_action.mean(),
            "actual_success_rate": y_action.mean(),
            "calibration_gap": abs(
                p_action.mean()
                - y_action.mean()
            ),
            "brier_score": brier_score_loss(
                y_action,
                p_action
            ),
            "roc_auc": (
                roc_auc_score(y_action, p_action)
                if y_action.nunique() > 1
                else np.nan
            ),
        })

    action_table = pd.DataFrame(
        action_results
    )

    print(
        action_table.to_string(
            index=False
        )
    )

    # ---------------------------------------------------------
    # DECISION-RELEVANT DIAGNOSTIC
    # ---------------------------------------------------------

    print("\nDECISION-RELEVANT DIAGNOSTIC")
    print("-" * 75)

    overall_gap = abs(
        p.mean() - y.mean()
    )

    print(
        f"Overall calibration gap: "
        f"{overall_gap:.4f}"
    )

    worst_action = (
        action_table
        .sort_values(
            "calibration_gap",
            ascending=False
        )
        .iloc[0]
    )

    print(
        f"Worst calibrated action: "
        f"{worst_action['action']}"
    )

    print(
        f"Worst action calibration gap: "
        f"{worst_action['calibration_gap']:.4f}"
    )

    print("\nInterpretation:")

    if overall_gap < 0.03:
        print(
            "GOOD — overall probabilities appear reasonably calibrated."
        )
    elif overall_gap < 0.07:
        print(
            "MODERATE — calibration could be improved before "
            "economic optimization."
        )
    else:
        print(
            "POOR — probability calibration is a significant "
            "risk for expected-value decisions."
        )

    # ---------------------------------------------------------
    # SAVE REPORT
    # ---------------------------------------------------------

    output_dir = (
        ROOT
        / "data"
        / "processed"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    table.to_csv(
        output_dir
        / "v1_calibration_bins.csv",
        index=False
    )

    action_table.to_csv(
        output_dir
        / "v1_action_calibration.csv",
        index=False
    )

    print("\nReports saved to:")
    print(output_dir)

    print("\n")
    print("=" * 75)
    print("CALIBRATION ANALYSIS COMPLETE")
    print("=" * 75)


if __name__ == "__main__":
    main()