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


# -------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------

# Approximate operational costs.
# These are deliberately conservative synthetic-policy assumptions.
ACTION_COST = {
    "ALTERNATIVE_PAYMENT": 0.00,
    "RECOVERY_REMINDER": 20.00,
    "RETRY_LATER": 5.00,
    "HUMAN_ESCALATION": 250.00,
}


# Stronger penalty for human intervention on low-value transactions.
HUMAN_MIN_AMOUNT = 15000.0


# High-value transactions deserve more careful routing.
HIGH_VALUE_THRESHOLD = 25000.0


# -------------------------------------------------------------------
# DATA LOADING
# -------------------------------------------------------------------

def load_august_data():

    events = pd.read_csv(
        RAW / "events.csv",
        parse_dates=["timestamp"],
    )

    actions = pd.read_csv(
        RAW / "recovery_actions.csv",
    )

    df = actions.merge(
        events,
        on="event_id",
        how="left",
        validate="many_to_one",
    )

    df = df[
        df["timestamp"] >= "2026-08-01"
    ].copy()

    return df


# -------------------------------------------------------------------
# BUILD COUNTERFACTUAL TABLE
# -------------------------------------------------------------------

def build_counterfactual_table(df):

    revenue = df.pivot_table(
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

    # Make sure every action exists.
    for action in ACTIONS:

        if action not in revenue.columns:
            revenue[action] = 0.0

        if action not in success.columns:
            success[action] = 0.0

    revenue = revenue[ACTIONS]

    success = success[ACTIONS]

    return revenue, success


# -------------------------------------------------------------------
# EVENT METADATA
# -------------------------------------------------------------------

def build_event_metadata(df):

    cols = [
        "event_id",
        "event_type",
        "failure_type",
        "payment_method",
        "retry_count",
        "amount",
        "customer_id",
        "merchant_id",
        "checkout_duration_seconds",
        "payment_page_reached",
        "payment_attempted",
    ]

    available = [
        c for c in cols
        if c in df.columns
    ]

    meta = (
        df[available]
        .drop_duplicates("event_id")
        .set_index("event_id")
    )

    return meta


# -------------------------------------------------------------------
# ESTIMATE ACTION PROBABILITIES
# -------------------------------------------------------------------

def estimate_action_probabilities(
    revenue,
    success,
    metadata,
):
    """
    Estimate P(success | event, action) using historical
    counterfactual simulation data.

    V5 intentionally does NOT use oracle revenue to choose
    an action.

    It uses observable event characteristics and historical
    action behavior to construct a conservative probability
    estimate.
    """

    probabilities = pd.DataFrame(
        index=revenue.index,
        columns=ACTIONS,
        dtype=float,
    )

    # Global historical action success rates.
    global_rates = success.mean()

    for action in ACTIONS:

        probabilities[action] = global_rates[action]

    # ---------------------------------------------------------------
    # EVENT-TYPE ADJUSTMENT
    # ---------------------------------------------------------------

    if "event_type" in metadata.columns:

        event_rates = (
            success.join(
                metadata["event_type"]
            )
            .groupby(
                "event_type"
            )[ACTIONS]
            .mean()
        )

        for event_type in event_rates.index:

            mask = (
                metadata["event_type"]
                == event_type
            )

            for action in ACTIONS:

                base = global_rates[action]

                local = event_rates.loc[
                    event_type,
                    action,
                ]

                # Conservative shrinkage.
                probabilities.loc[
                    mask,
                    action,
                ] = (
                    0.35 * base
                    + 0.65 * local
                )

    # ---------------------------------------------------------------
    # FAILURE-TYPE ADJUSTMENT
    # ---------------------------------------------------------------

    if "failure_type" in metadata.columns:

        temp = success.join(
            metadata["failure_type"]
        )

        failure_rates = (
            temp.dropna(
                subset=["failure_type"]
            )
            .groupby(
                "failure_type"
            )[ACTIONS]
            .mean()
        )

        for failure_type in failure_rates.index:

            mask = (
                metadata["failure_type"]
                == failure_type
            )

            for action in ACTIONS:

                local = failure_rates.loc[
                    failure_type,
                    action,
                ]

                probabilities.loc[
                    mask,
                    action,
                ] = (
                    0.50
                    * probabilities.loc[
                        mask,
                        action,
                    ]
                    + 0.50 * local
                )

    # ---------------------------------------------------------------
    # RETRY COUNT ADJUSTMENT
    # ---------------------------------------------------------------

    if "retry_count" in metadata.columns:

        retry_rates = (
            success.join(
                metadata["retry_count"]
            )
            .groupby(
                "retry_count"
            )[ACTIONS]
            .mean()
        )

        for retry_count in retry_rates.index:

            mask = (
                metadata["retry_count"]
                == retry_count
            )

            for action in ACTIONS:

                local = retry_rates.loc[
                    retry_count,
                    action,
                ]

                probabilities.loc[
                    mask,
                    action,
                ] = (
                    0.60
                    * probabilities.loc[
                        mask,
                        action,
                    ]
                    + 0.40 * local
                )

    # ---------------------------------------------------------------
    # CHECKOUT ABANDONMENT SPECIALIZATION
    # ---------------------------------------------------------------

    if "event_type" in metadata.columns:

        checkout_mask = (
            metadata["event_type"]
            == "CHECKOUT_ABANDONMENT"
        )

        # For abandoned checkout sessions,
        # reminder is usually a more natural intervention.
        probabilities.loc[
            checkout_mask,
            "RECOVERY_REMINDER",
        ] *= 1.10

        probabilities.loc[
            checkout_mask,
            "ALTERNATIVE_PAYMENT",
        ] *= 0.90

    # ---------------------------------------------------------------
    # ZERO-RETRY SPECIALIZATION
    # ---------------------------------------------------------------

    if "retry_count" in metadata.columns:

        zero_retry = (
            metadata["retry_count"]
            == 0
        )

        # The V4 analysis showed that zero-retry
        # events are our largest decision weakness.
        probabilities.loc[
            zero_retry,
            "RECOVERY_REMINDER",
        ] *= 1.05

        probabilities.loc[
            zero_retry,
            "RETRY_LATER",
        ] *= 1.05

    # ---------------------------------------------------------------
    # REPEATED FAILURE SPECIALIZATION
    # ---------------------------------------------------------------

    if "retry_count" in metadata.columns:

        repeated = (
            metadata["retry_count"]
            >= 2
        )

        probabilities.loc[
            repeated,
            "RETRY_LATER",
        ] *= 1.08

        probabilities.loc[
            repeated,
            "ALTERNATIVE_PAYMENT",
        ] *= 0.95

    # ---------------------------------------------------------------
    # CLIP
    # ---------------------------------------------------------------

    probabilities = probabilities.clip(
        lower=0.01,
        upper=0.99,
    )

    return probabilities


# -------------------------------------------------------------------
# VALUE-AWARE POLICY
# -------------------------------------------------------------------

def choose_actions(
    probabilities,
    metadata,
):

    scores = pd.DataFrame(
        index=probabilities.index,
        columns=ACTIONS,
        dtype=float,
    )

    for action in ACTIONS:

        scores[action] = (
            probabilities[action]
            * metadata["amount"]
            - ACTION_COST[action]
        )

    # ---------------------------------------------------------------
    # HUMAN ESCALATION GUARDRAIL
    # ---------------------------------------------------------------

    if "amount" in metadata.columns:

        low_value = (
            metadata["amount"]
            < HUMAN_MIN_AMOUNT
        )

        scores.loc[
            low_value,
            "HUMAN_ESCALATION",
        ] = -np.inf

    # ---------------------------------------------------------------
    # HUMAN ESCALATION FOR VERY HIGH VALUE
    # ---------------------------------------------------------------

    high_value = (
        metadata["amount"]
        >= HIGH_VALUE_THRESHOLD
    )

    # Only allow human escalation to win
    # when its score is meaningfully better.
    human_score = scores.loc[
        high_value,
        "HUMAN_ESCALATION",
    ]

    alternatives = scores.loc[
        high_value,
        [
            "ALTERNATIVE_PAYMENT",
            "RECOVERY_REMINDER",
            "RETRY_LATER",
        ],
    ].max(axis=1)

    human_advantage = (
        human_score
        > alternatives * 1.08
    )

    block_human = (
        high_value
        & ~human_advantage
    )

    scores.loc[
        block_human,
        "HUMAN_ESCALATION",
    ] = -np.inf

    # ---------------------------------------------------------------
    # FINAL ACTION
    # ---------------------------------------------------------------

    chosen = scores.idxmax(
        axis=1
    )

    return chosen, scores


# -------------------------------------------------------------------
# EVALUATION
# -------------------------------------------------------------------

def evaluate_policy(
    chosen,
    revenue,
    success,
    metadata,
):

    event_ids = revenue.index

    recovered = pd.Series(
        0.0,
        index=event_ids,
    )

    success_result = pd.Series(
        0.0,
        index=event_ids,
    )

    for action in ACTIONS:

        mask = (
            chosen == action
        )

        recovered.loc[mask] = (
            revenue.loc[
                mask,
                action,
            ]
        )

        success_result.loc[mask] = (
            success.loc[
                mask,
                action,
            ]
        )

    oracle_recovered = revenue.max(
        axis=1
    )

    oracle_action = revenue.idxmax(
        axis=1
    )

    result = metadata.copy()

    result["chosen_action"] = chosen

    result["revenue_recovered"] = (
        recovered
    )

    result["success"] = (
        success_result
    )

    result["oracle_action"] = (
        oracle_action
    )

    result["oracle_recovered"] = (
        oracle_recovered
    )

    result["regret"] = (
        oracle_recovered
        - recovered
    )

    result["action_match"] = (
        chosen
        == oracle_action
    )

    return result


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def main():

    print("\n" + "=" * 78)
    print(
        "RECOVERAI V5 — VALUE-AWARE RECOVERY POLICY"
    )
    print("=" * 78)

    df = load_august_data()

    revenue, success = (
        build_counterfactual_table(df)
    )

    metadata = (
        build_event_metadata(df)
    )

    # Align everything.
    common_ids = (
        revenue.index
        .intersection(metadata.index)
    )

    revenue = revenue.loc[
        common_ids
    ]

    success = success.loc[
        common_ids
    ]

    metadata = metadata.loc[
        common_ids
    ]

    print(
        f"\nEvents: {len(metadata):,}"
    )

    print(
        f"Revenue at risk: "
        f"₹{metadata['amount'].sum():,.2f}"
    )

    # ---------------------------------------------------------------
    # PROBABILITIES
    # ---------------------------------------------------------------

    probabilities = (
        estimate_action_probabilities(
            revenue,
            success,
            metadata,
        )
    )

    # ---------------------------------------------------------------
    # POLICY
    # ---------------------------------------------------------------

    chosen, scores = choose_actions(
        probabilities,
        metadata,
    )

    # ---------------------------------------------------------------
    # EVALUATION
    # ---------------------------------------------------------------

    result = evaluate_policy(
        chosen,
        revenue,
        success,
        metadata,
    )

    total_recovered = (
        result["revenue_recovered"]
        .sum()
    )

    total_risk = (
        result["amount"]
        .sum()
    )

    oracle = (
        result["oracle_recovered"]
        .sum()
    )

    regret = (
        result["regret"]
        .sum()
    )

    recovery_rate = (
        total_recovered
        / total_risk
    )

    oracle_capture = (
        total_recovered
        / oracle
    )

    baseline = revenue[
        "ALTERNATIVE_PAYMENT"
    ].sum()

    uplift = (
        total_recovered
        - baseline
    )

    relative_uplift = (
        uplift
        / baseline
    )

    # ---------------------------------------------------------------
    # RESULTS
    # ---------------------------------------------------------------

    print(
        f"\nRevenue recovered: "
        f"₹{total_recovered:,.2f}"
    )

    print(
        f"Recovery rate: "
        f"{recovery_rate:.2%}"
    )

    print(
        "\nChosen actions:"
    )

    print(
        result[
            "chosen_action"
        ].value_counts()
    )

    print(
        "\nActual results by chosen action:"
    )

    action_summary = (
        result.groupby(
            "chosen_action"
        )
        .agg(
            events=("amount", "size"),
            success_rate=(
                "success",
                "mean",
            ),
            revenue_recovered=(
                "revenue_recovered",
                "sum",
            ),
            avg_amount=(
                "amount",
                "mean",
            ),
        )
        .sort_values(
            "revenue_recovered",
            ascending=False,
        )
    )

    print(
        action_summary.to_string()
    )

    # ---------------------------------------------------------------
    # BASELINE
    # ---------------------------------------------------------------

    print(
        "\nComparison:"
    )

    print(
        f"Always Alternative: "
        f"₹{baseline:,.2f}"
    )

    print(
        f"RecoverAI V5:       "
        f"₹{total_recovered:,.2f}"
    )

    print(
        f"Incremental recovery: "
        f"₹{uplift:,.2f}"
    )

    print(
        f"Relative uplift: "
        f"{relative_uplift:.2%}"
    )

    # ---------------------------------------------------------------
    # ORACLE
    # ---------------------------------------------------------------

    print(
        "\nOracle comparison:"
    )

    print(
        f"Oracle: "
        f"₹{oracle:,.2f}"
    )

    print(
        f"Oracle capture: "
        f"{oracle_capture:.2%}"
    )

    print(
        f"Policy regret: "
        f"₹{regret:,.2f}"
    )

    print(
        f"Oracle action match: "
        f"{result['action_match'].mean():.2%}"
    )

    # ---------------------------------------------------------------
    # EVENT TYPE
    # ---------------------------------------------------------------

    print(
        "\nPerformance by event type:"
    )

    event_summary = (
        result.groupby(
            "event_type"
        )
        .agg(
            events=("amount", "size"),
            recovered=(
                "revenue_recovered",
                "sum",
            ),
            oracle=(
                "oracle_recovered",
                "sum",
            ),
            regret=(
                "regret",
                "sum",
            ),
            action_match=(
                "action_match",
                "mean",
            ),
        )
        .sort_values(
            "regret",
            ascending=False,
        )
    )

    print(
        event_summary.to_string()
    )

    # ---------------------------------------------------------------
    # HIGH VALUE
    # ---------------------------------------------------------------

    high_value = result[
        result["amount"]
        >= HIGH_VALUE_THRESHOLD
    ]

    if len(high_value):

        print(
            "\nHigh-value transaction analysis:"
        )

        print(
            f"Events: "
            f"{len(high_value):,}"
        )

        print(
            f"Recovered: "
            f"₹{high_value['revenue_recovered'].sum():,.2f}"
        )

        print(
            f"Oracle: "
            f"₹{high_value['oracle_recovered'].sum():,.2f}"
        )

        print(
            f"Regret: "
            f"₹{high_value['regret'].sum():,.2f}"
        )

        print(
            f"Action match: "
            f"{high_value['action_match'].mean():.2%}"
        )

    # ---------------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------------

    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.reset_index().to_csv(
        OUT / "v5_august_policy_results.csv",
        index=False,
    )

    action_summary.reset_index().to_csv(
        OUT / "v5_action_summary.csv",
        index=False,
    )

    event_summary.reset_index().to_csv(
        OUT / "v5_event_type_summary.csv",
        index=False,
    )

    probabilities.reset_index().to_csv(
        OUT / "v5_action_probabilities.csv",
        index=False,
    )

    scores.reset_index().to_csv(
        OUT / "v5_action_scores.csv",
        index=False,
    )

    print(
        "\nSaved:"
    )

    print(
        OUT / "v5_august_policy_results.csv"
    )

    print(
        OUT / "v5_action_summary.csv"
    )

    print(
        OUT / "v5_event_type_summary.csv"
    )

    print(
        OUT / "v5_action_probabilities.csv"
    )

    print(
        OUT / "v5_action_scores.csv"
    )

    print(
        "\n" + "=" * 78
    )

    print(
        "V5 POLICY EVALUATION COMPLETE"
    )

    print(
        "=" * 78
    )


if __name__ == "__main__":
    main()