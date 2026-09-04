from pathlib import Path
import sys
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.features.v1_features import build_v1_dataset

MODEL = ROOT / "data" / "processed" / "models" / "recoverai_v1.joblib"

ACTIONS = [
    "RETRY_LATER",
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "HUMAN_ESCALATION",
]

def main():
    df, features = build_v1_dataset()

    df = df[df["action"].isin(ACTIONS)].copy()

    # August is untouched until final policy evaluation.
    test = df[df["timestamp"] >= "2026-08-01"].copy()

    model = joblib.load(MODEL)

    test["predicted_success_probability"] = model.predict_proba(
        test[features]
    )[:, 1]

    # ---------------------------------------------------------
    # Guardrails
    # ---------------------------------------------------------

    test["allowed_by_policy"] = True

    # Never blindly retry after three attempts.
    test.loc[
        (test["action"] == "RETRY_LATER") &
        (test["retry_count"] >= 3),
        "allowed_by_policy"
    ] = False

    # Avoid repeated customer reminders.
    test.loc[
        (test["action"] == "RECOVERY_REMINDER") &
        (test["retry_count"] >= 3),
        "allowed_by_policy"
    ] = False

    # Human escalation only makes sense for meaningful-value cases.
    test.loc[
        (test["action"] == "HUMAN_ESCALATION") &
        (test["amount"] < 1000),
        "allowed_by_policy"
    ] = False

    # ---------------------------------------------------------
    # Expected value
    # ---------------------------------------------------------

    test["expected_recovered_value"] = (
        test["predicted_success_probability"] *
        test["amount"]
    )

    test.loc[
        ~test["allowed_by_policy"],
        "expected_recovered_value"
    ] = -np.inf

    # One action per event.
    selected = (
        test.sort_values(
            ["event_id", "expected_recovered_value"],
            ascending=[True, False]
        )
        .groupby("event_id", as_index=False)
        .first()
    )

    revenue_at_risk = selected["amount"].sum()
    revenue_recovered = selected["revenue_recovered"].sum()

    print("\n")
    print("=" * 75)
    print("RECOVERAI V1 — HELD-OUT AUGUST POLICY")
    print("=" * 75)

    print(f"\nEvents: {len(selected):,}")
    print(f"Revenue at risk: ₹{revenue_at_risk:,.2f}")
    print(f"Revenue recovered: ₹{revenue_recovered:,.2f}")
    print(
        f"Recovery rate: "
        f"{revenue_recovered / revenue_at_risk * 100:.2f}%"
    )

    print("\nChosen actions:")
    print(
        selected["action"]
        .value_counts()
        .to_string()
    )

    print("\nActual results by chosen action:")
    print(
        selected.groupby("action")
        .agg(
            events=("event_id", "count"),
            success_rate=("recovery_success", "mean"),
            revenue_recovered=("revenue_recovered", "sum"),
        )
        .sort_values(
            "revenue_recovered",
            ascending=False
        )
        .round(4)
        .to_string()
    )

    # ---------------------------------------------------------
    # Compare against static baseline
    # ---------------------------------------------------------

    baseline_recovered = (
        test[test["action"] == "ALTERNATIVE_PAYMENT"]
        ["revenue_recovered"]
        .sum()
    )

    incremental = revenue_recovered - baseline_recovered

    print("\nComparison against ALWAYS ALTERNATIVE:")
    print(f"Baseline: ₹{baseline_recovered:,.2f}")
    print(f"RecoverAI V1: ₹{revenue_recovered:,.2f}")
    print(f"Incremental recovery: ₹{incremental:,.2f}")

    if baseline_recovered > 0:
        print(
            f"Relative uplift: "
            f"{incremental / baseline_recovered * 100:.2f}%"
        )

    oracle = (
        test.sort_values(
            ["event_id", "revenue_recovered"],
            ascending=[True, False]
        )
        .groupby("event_id")
        .first()
    )

    oracle_recovered = oracle["revenue_recovered"].sum()

    print("\nOracle comparison:")
    print(f"Oracle: ₹{oracle_recovered:,.2f}")
    print(
        f"Oracle capture: "
        f"{revenue_recovered / oracle_recovered * 100:.2f}%"
    )
    print(
        f"Policy regret: "
        f"₹{oracle_recovered - revenue_recovered:,.2f}"
    )


if __name__ == "__main__":
    main()
