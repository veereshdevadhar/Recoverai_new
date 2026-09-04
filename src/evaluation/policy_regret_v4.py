from pathlib import Path
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

ACTIONS = [
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "RETRY_LATER",
    "HUMAN_ESCALATION",
]


def load_august():
    events = pd.read_csv(
        RAW / "events.csv",
        parse_dates=["timestamp"],
    )

    outcomes = pd.read_csv(
        RAW / "recovery_actions.csv"
    )

    df = outcomes.merge(
        events,
        on="event_id",
        how="left",
        validate="many_to_one",
    )

    return df[
        df["timestamp"] >= "2026-08-01"
    ].copy()


def main():

    print("\n" + "=" * 78)
    print("RECOVERAI V4 — POLICY REGRET & COUNTERFACTUAL ERROR ANALYSIS")
    print("=" * 78)

    df = load_august()

    # ------------------------------------------------------------
    # COUNTERFACTUAL ACTION OUTCOMES
    # ------------------------------------------------------------

    pivot = df.pivot_table(
        index="event_id",
        columns="action",
        values="revenue_recovered",
        aggfunc="first",
    )

    success = df.pivot_table(
        index="event_id",
        columns="action",
        values="recovery_success",
        aggfunc="first",
    )

    # One amount per event.
    amounts = (
        df.groupby(
            "event_id",
            as_index=False
        )["amount"]
        .first()
        .set_index("event_id")["amount"]
    )

    # ------------------------------------------------------------
    # EVENT METADATA
    # ------------------------------------------------------------

    meta_cols = [
        "event_type",
        "failure_type",
        "payment_method",
        "retry_count",
        "customer_id",
        "merchant_id",
    ]

    meta = (
        df.sort_values("action")
        .drop_duplicates("event_id")
        .set_index("event_id")[meta_cols]
    )

    # ------------------------------------------------------------
    # ORACLE
    # ------------------------------------------------------------

    # The oracle chooses the action that actually recovered
    # the greatest amount of revenue.
    oracle_action = pivot[ACTIONS].idxmax(axis=1)

    oracle_value = pivot[ACTIONS].max(axis=1)

    # ------------------------------------------------------------
    # LOAD V2 POLICY
    # ------------------------------------------------------------

    v2_path = OUT / "v2_august_policy_results.csv"

    if not v2_path.exists():

        print(
            "\nWARNING: V2 policy result file not found."
        )

        print(
            "\nRun:"
            "\npython -m src.evaluation.policy_v2"
        )

        return

    v2 = pd.read_csv(v2_path)

    if "event_id" not in v2.columns:

        raise ValueError(
            "V2 results must contain event_id."
        )

    v2 = v2.set_index("event_id")

    # Support either column naming convention.
    if "chosen_action" in v2.columns:

        chosen_col = "chosen_action"

    elif "action" in v2.columns:

        chosen_col = "action"

    else:

        raise ValueError(
            "V2 results must contain either "
            "'chosen_action' or 'action'."
        )

    v2_action = v2[
        chosen_col
    ].reindex(pivot.index)

    if "actual_recovered" in v2.columns:

        v2_recovered = v2[
            "actual_recovered"
        ].reindex(pivot.index)

    else:

        v2_recovered = pd.Series(
            np.nan,
            index=pivot.index,
        )

    # ------------------------------------------------------------
    # BUILD EVENT-LEVEL ANALYSIS
    # ------------------------------------------------------------

    analysis = meta.copy()

    analysis["amount"] = amounts

    analysis["v2_action"] = v2_action

    analysis["oracle_action"] = oracle_action

    analysis["oracle_recovered"] = oracle_value

    analysis["v2_recovered"] = v2_recovered

    # If V2 output doesn't contain recovered revenue,
    # recover it directly from the counterfactual table.
    missing = analysis[
        "v2_recovered"
    ].isna()

    for idx, action in analysis.loc[
        missing,
        "v2_action"
    ].items():

        if action in pivot.columns:

            analysis.loc[
                idx,
                "v2_recovered"
            ] = pivot.loc[
                idx,
                action
            ]

        else:

            analysis.loc[
                idx,
                "v2_recovered"
            ] = 0.0

    # ------------------------------------------------------------
    # REGRET
    # ------------------------------------------------------------

    analysis["regret"] = (
        analysis["oracle_recovered"]
        - analysis["v2_recovered"]
    )

    analysis["correct_action"] = (
        analysis["v2_action"]
        == analysis["oracle_action"]
    )

    # ============================================================
    # 1. OVERALL POLICY QUALITY
    # ============================================================

    print("\n1. OVERALL POLICY QUALITY")
    print("-" * 78)

    print(
        f"Events: {len(analysis):,}"
    )

    print(
        f"V2 recovered: "
        f"₹{analysis['v2_recovered'].sum():,.2f}"
    )

    print(
        f"Oracle recovered: "
        f"₹{analysis['oracle_recovered'].sum():,.2f}"
    )

    print(
        f"Total policy regret: "
        f"₹{analysis['regret'].sum():,.2f}"
    )

    print(
        f"Oracle action match rate: "
        f"{analysis['correct_action'].mean():.2%}"
    )

    # ============================================================
    # 2. ORACLE ACTION VS V2 ACTION
    # ============================================================

    print(
        "\n2. ORACLE ACTION vs V2 ACTION"
    )

    print("-" * 78)

    confusion = pd.crosstab(
        analysis["oracle_action"],
        analysis["v2_action"],
        margins=True,
    )

    print(
        confusion.to_string()
    )

    # ============================================================
    # 3. MISSED ORACLE ACTIONS
    # ============================================================

    misses = analysis[
        ~analysis["correct_action"]
    ].copy()

    print(
        "\n3. MISSED ORACLE ACTIONS"
    )

    print("-" * 78)

    print(
        f"Missed events: "
        f"{len(misses):,}"
    )

    print(
        f"Missed recovery opportunity: "
        f"₹{misses['regret'].sum():,.2f}"
    )

    missed_pairs = (
        misses.groupby(
            [
                "oracle_action",
                "v2_action",
            ],
            dropna=False,
        )
        .agg(
            events=("amount", "size"),
            regret=("regret", "sum"),
            avg_regret=("regret", "mean"),
        )
        .sort_values(
            "regret",
            ascending=False,
        )
    )

    print(
        missed_pairs.to_string()
    )

    # ============================================================
    # 4. REGRET BY EVENT TYPE
    # ============================================================

    print(
        "\n4. REGRET BY EVENT TYPE"
    )

    print("-" * 78)

    by_event = (
        analysis.groupby(
            "event_type"
        )
        .agg(
            events=("amount", "size"),
            v2_recovered=(
                "v2_recovered",
                "sum",
            ),
            oracle_recovered=(
                "oracle_recovered",
                "sum",
            ),
            regret=(
                "regret",
                "sum",
            ),
            action_match_rate=(
                "correct_action",
                "mean",
            ),
        )
        .sort_values(
            "regret",
            ascending=False,
        )
    )

    print(
        by_event.to_string()
    )

    # ============================================================
    # 5. REGRET BY FAILURE TYPE
    # ============================================================

    print(
        "\n5. REGRET BY FAILURE TYPE"
    )

    print("-" * 78)

    by_failure = (
        analysis[
            analysis["failure_type"].notna()
        ]
        .groupby(
            "failure_type"
        )
        .agg(
            events=("amount", "size"),
            v2_recovered=(
                "v2_recovered",
                "sum",
            ),
            oracle_recovered=(
                "oracle_recovered",
                "sum",
            ),
            regret=(
                "regret",
                "sum",
            ),
            action_match_rate=(
                "correct_action",
                "mean",
            ),
        )
        .sort_values(
            "regret",
            ascending=False,
        )
    )

    print(
        by_failure.to_string()
    )

    # ============================================================
    # 6. REGRET BY RETRY COUNT
    # ============================================================

    print(
        "\n6. REGRET BY RETRY COUNT"
    )

    print("-" * 78)

    by_retry = (
        analysis.groupby(
            "retry_count"
        )
        .agg(
            events=("amount", "size"),
            v2_recovered=(
                "v2_recovered",
                "sum",
            ),
            oracle_recovered=(
                "oracle_recovered",
                "sum",
            ),
            regret=(
                "regret",
                "sum",
            ),
            action_match_rate=(
                "correct_action",
                "mean",
            ),
        )
        .sort_index()
    )

    print(
        by_retry.to_string()
    )

    # ============================================================
    # 7. REGRET BY TRANSACTION VALUE
    # ============================================================

    print(
        "\n7. REGRET BY TRANSACTION VALUE"
    )

    print("-" * 78)

    analysis["value_band"] = pd.cut(
        analysis["amount"],
        bins=[
            -np.inf,
            2000,
            5000,
            10000,
            25000,
            np.inf,
        ],
        labels=[
            "<=₹2K",
            "₹2K–₹5K",
            "₹5K–₹10K",
            "₹10K–₹25K",
            ">₹25K",
        ],
    )

    by_value = (
        analysis.groupby(
            "value_band",
            observed=False,
        )
        .agg(
            events=("amount", "size"),
            v2_recovered=(
                "v2_recovered",
                "sum",
            ),
            oracle_recovered=(
                "oracle_recovered",
                "sum",
            ),
            regret=(
                "regret",
                "sum",
            ),
            action_match_rate=(
                "correct_action",
                "mean",
            ),
        )
    )

    print(
        by_value.to_string()
    )

    # ============================================================
    # 8. RETRY LATER OPPORTUNITIES
    # ============================================================

    print(
        "\n8. RETRY-LATER OPPORTUNITIES"
    )

    print("-" * 78)

    retry_oracle = analysis[
        analysis["oracle_action"]
        == "RETRY_LATER"
    ].copy()

    retry_missed = retry_oracle[
        retry_oracle["v2_action"]
        != "RETRY_LATER"
    ]

    print(
        f"Oracle RETRY_LATER events: "
        f"{len(retry_oracle):,}"
    )

    print(
        f"V2 missed RETRY_LATER: "
        f"{len(retry_missed):,}"
    )

    print(
        f"Recovery opportunity in missed "
        f"RETRY_LATER cases: "
        f"₹{retry_missed['regret'].sum():,.2f}"
    )

    if len(retry_missed):

        retry_breakdown = (
            retry_missed.groupby(
                "v2_action"
            )
            .agg(
                events=("amount", "size"),
                regret=("regret", "sum"),
                avg_regret=(
                    "regret",
                    "mean",
                ),
            )
            .sort_values(
                "regret",
                ascending=False,
            )
        )

        print(
            retry_breakdown.to_string()
        )

    # ============================================================
    # 9. TOP 20 MISSED OPPORTUNITIES
    # ============================================================

    print(
        "\n9. TOP 20 MISSED REVENUE OPPORTUNITIES"
    )

    print("-" * 78)

    top = (
        misses.sort_values(
            "regret",
            ascending=False,
        )
        .head(20)
        [
            [
                "amount",
                "event_type",
                "failure_type",
                "retry_count",
                "v2_action",
                "oracle_action",
                "v2_recovered",
                "oracle_recovered",
                "regret",
            ]
        ]
    )

    print(
        top.to_string()
    )

    # ============================================================
    # SAVE REPORTS
    # ============================================================

    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    analysis.reset_index().to_csv(
        OUT / "v4_policy_regret_event_analysis.csv",
        index=False,
    )

    missed_pairs.reset_index().to_csv(
        OUT / "v4_missed_action_pairs.csv",
        index=False,
    )

    by_event.reset_index().to_csv(
        OUT / "v4_regret_by_event_type.csv",
        index=False,
    )

    by_failure.reset_index().to_csv(
        OUT / "v4_regret_by_failure_type.csv",
        index=False,
    )

    by_retry.reset_index().to_csv(
        OUT / "v4_regret_by_retry_count.csv",
        index=False,
    )

    by_value.reset_index().to_csv(
        OUT / "v4_regret_by_value_band.csv",
        index=False,
    )

    summary = pd.DataFrame(
        {
            "metric": [
                "events",
                "v2_recovered",
                "oracle_recovered",
                "total_regret",
                "oracle_action_match_rate",
                "missed_events",
                "retry_later_oracle_events",
                "retry_later_missed_events",
                "retry_later_missed_regret",
            ],
            "value": [
                len(analysis),
                analysis[
                    "v2_recovered"
                ].sum(),
                analysis[
                    "oracle_recovered"
                ].sum(),
                analysis[
                    "regret"
                ].sum(),
                analysis[
                    "correct_action"
                ].mean(),
                len(misses),
                len(retry_oracle),
                len(retry_missed),
                retry_missed[
                    "regret"
                ].sum(),
            ],
        }
    )

    summary.to_csv(
        OUT / "v4_policy_regret_summary.csv",
        index=False,
    )

    # ============================================================
    # COMPLETE
    # ============================================================

    print("\nSaved:")

    print(
        OUT / "v4_policy_regret_event_analysis.csv"
    )

    print(
        OUT / "v4_missed_action_pairs.csv"
    )

    print(
        OUT / "v4_regret_by_event_type.csv"
    )

    print(
        OUT / "v4_regret_by_failure_type.csv"
    )

    print(
        OUT / "v4_regret_by_retry_count.csv"
    )

    print(
        OUT / "v4_regret_by_value_band.csv"
    )

    print(
        OUT / "v4_policy_regret_summary.csv"
    )

    print(
        "\n" + "=" * 78
    )

    print(
        "V4 COUNTERFACTUAL ANALYSIS COMPLETE"
    )

    print(
        "=" * 78
    )


if __name__ == "__main__":
    main()