from pathlib import Path
import sys
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.features.feature_builder import build_action_dataset


ACTIONS = [
    "RETRY_LATER",
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "HUMAN_ESCALATION",
]


def evaluate_policy(df, policy_name, selected_actions):
    """
    selected_actions:
        Series indexed by event_id containing the chosen action.
    """

    chosen = df.merge(
        selected_actions.rename("selected_action"),
        left_on="event_id",
        right_index=True,
        how="inner"
    )

    chosen = chosen[
        chosen["action"] == chosen["selected_action"]
    ].copy()

    revenue_at_risk = chosen["amount"].sum()
    revenue_recovered = chosen["revenue_recovered"].sum()

    recovery_rate = (
        revenue_recovered / revenue_at_risk
        if revenue_at_risk > 0
        else 0
    )

    success_rate = chosen["recovery_success"].mean()

    return {
        "policy": policy_name,
        "events": len(chosen),
        "revenue_at_risk": revenue_at_risk,
        "revenue_recovered": revenue_recovered,
        "recovery_rate": recovery_rate,
        "success_rate": success_rate,
    }


def main():

    df, _ = build_action_dataset()

    # Only actions that can actually attempt recovery.
    action_df = df[
        df["action"].isin(ACTIONS)
    ].copy()

    # ---------------------------------------------------------
    # HELD-OUT AUGUST
    # ---------------------------------------------------------

    test = action_df[
        action_df["timestamp"] >= "2026-08-01"
    ].copy()

    print("\n")
    print("=" * 75)
    print("RECOVERAI — POLICY BASELINES")
    print("HELD-OUT AUGUST")
    print("=" * 75)

    print(f"\nEvents: {test['event_id'].nunique():,}")

    # ---------------------------------------------------------
    # BASELINE 1 — ALWAYS STOP
    # ---------------------------------------------------------

    event_amounts = (
        test.groupby("event_id")["amount"]
        .first()
    )

    stop_value = event_amounts.sum()

    print("\n1. STOP")
    print("-" * 75)
    print(f"Revenue at risk: ₹{stop_value:,.2f}")
    print("Revenue recovered: ₹0.00")
    print("Recovery rate: 0.00%")

    # ---------------------------------------------------------
    # BASELINE 2 — ALWAYS ALTERNATIVE PAYMENT
    # ---------------------------------------------------------

    alternative = test[
        test["action"] == "ALTERNATIVE_PAYMENT"
    ]

    alt_recovered = alternative["revenue_recovered"].sum()
    alt_value = alternative["amount"].sum()

    print("\n2. ALWAYS ALTERNATIVE PAYMENT")
    print("-" * 75)
    print(f"Revenue at risk: ₹{alt_value:,.2f}")
    print(f"Revenue recovered: ₹{alt_recovered:,.2f}")
    print(
        f"Recovery rate: "
        f"{alt_recovered / alt_value * 100:.2f}%"
    )
    print(
        f"Success rate: "
        f"{alternative['recovery_success'].mean() * 100:.2f}%"
    )

    # ---------------------------------------------------------
    # BASELINE 3 — EACH STATIC ACTION
    # ---------------------------------------------------------

    print("\n3. STATIC ACTION COMPARISON")
    print("-" * 75)

    static_results = []

    for action in ACTIONS:

        subset = test[
            test["action"] == action
        ]

        recovered = subset["revenue_recovered"].sum()
        value = subset["amount"].sum()

        static_results.append({
            "action": action,
            "revenue_at_risk": value,
            "revenue_recovered": recovered,
            "recovery_rate": recovered / value,
            "success_rate": subset["recovery_success"].mean(),
        })

    static = pd.DataFrame(static_results)

    print(
        static.sort_values(
            "revenue_recovered",
            ascending=False
        ).to_string(index=False)
    )

    # ---------------------------------------------------------
    # BASELINE 4 — ORACLE
    # ---------------------------------------------------------
    #
    # The oracle knows the actual counterfactual outcome.
    #
    # THIS IS NOT A DEPLOYABLE POLICY.
    #
    # It represents the theoretical upper bound available
    # in our simulator.
    # ---------------------------------------------------------

    oracle = (
        test.sort_values(
            ["event_id", "revenue_recovered"],
            ascending=[True, False]
        )
        .groupby("event_id")
        .first()
        .reset_index()
    )

    oracle_value = oracle["amount"].sum()
    oracle_recovered = oracle["revenue_recovered"].sum()

    print("\n4. ORACLE UPPER BOUND")
    print("-" * 75)
    print(
        f"Revenue at risk: "
        f"₹{oracle_value:,.2f}"
    )
    print(
        f"Revenue recovered: "
        f"₹{oracle_recovered:,.2f}"
    )
    print(
        f"Recovery rate: "
        f"{oracle_recovered / oracle_value * 100:.2f}%"
    )

    print("\nOracle action distribution:")
    print(
        oracle["action"]
        .value_counts()
        .to_string()
    )

    # ---------------------------------------------------------
    # SAVE RESULTS
    # ---------------------------------------------------------

    output_dir = ROOT / "data" / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    static.to_csv(
        output_dir / "static_action_baselines.csv",
        index=False
    )

    oracle.to_csv(
        output_dir / "oracle_results.csv",
        index=False
    )

    print("\n")
    print("=" * 75)
    print("BASELINE ANALYSIS COMPLETE")
    print("=" * 75)

    print(
        "\nFiles saved to:\n"
        f"{output_dir}"
    )


if __name__ == "__main__":
    main()