from pathlib import Path
import json
import numpy as np
import pandas as pd

from src.features.feature_builder import build_action_dataset


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"


ACTIONS = [
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "RETRY_LATER",
    "HUMAN_ESCALATION",
]

ALL_ACTIONS = ACTIONS + ["STOP"]


# ============================================================
# DATA LOADING
# ============================================================

def load_data():
    """
    Reuse the project's existing feature-builder pipeline.

    This guarantees that V6 uses the exact same joins:
        recovery_actions
        -> events
        -> customers
        -> merchants
    """

    df, features = build_action_dataset()

    if "timestamp" not in df.columns:
        raise ValueError("timestamp column missing after feature construction.")

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    august = df[
        df["timestamp"].dt.month == 8
    ].copy()

    if august.empty:
        raise ValueError("No August records found.")

    return august, features


# ============================================================
# VALIDATION
# ============================================================

def validate_dataset(df):
    required = [
        "event_id",
        "action",
        "recovery_success",
        "revenue_recovered",
        "amount",
        "event_type",
    ]

    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(
            "Dataset is missing required columns: "
            + ", ".join(missing)
        )

    print("\nDataset validation:")
    print(f"Rows: {len(df):,}")
    print(f"Unique events: {df['event_id'].nunique():,}")

    print("\nActions:")
    print(df["action"].value_counts().to_string())

    print("\nSimulation columns:")
    cols = [
        "event_id",
        "action",
        "recovery_success",
        "revenue_recovered",
    ]
    print(df[cols].head(5).to_string(index=False))


# ============================================================
# PREPARE EVENT LEVEL DATA
# ============================================================

def prepare_event_data(action_df):
    """
    Convert the five-action simulation dataset into one row
    per event.

    The outcome table contains one row per:
        event × action

    We pivot the simulation outcomes so every event contains
    the counterfactual result of each action.
    """

    base_columns = [
        "event_id",
        "timestamp",
        "event_type",
        "amount",
        "payment_method",
        "device_type",
        "failure_type",
        "retry_count",
        "previous_attempt_hours",
        "checkout_duration_seconds",
        "payment_page_reached",
        "payment_attempted",
        "customer_id",
        "merchant_id",
    ]

    available = [
        c for c in base_columns
        if c in action_df.columns
    ]

    events = (
        action_df[available]
        .drop_duplicates("event_id")
        .copy()
    )

    # --------------------------------------------------------
    # Counterfactual outcomes
    # --------------------------------------------------------

    success_pivot = (
        action_df
        .pivot_table(
            index="event_id",
            columns="action",
            values="recovery_success",
            aggfunc="first",
        )
        .reset_index()
    )

    revenue_pivot = (
        action_df
        .pivot_table(
            index="event_id",
            columns="action",
            values="revenue_recovered",
            aggfunc="first",
        )
        .reset_index()
    )

    success_pivot.columns = [
        "event_id"
        if c == "event_id"
        else f"success_{c}"
        for c in success_pivot.columns
    ]

    revenue_pivot.columns = [
        "event_id"
        if c == "event_id"
        else f"revenue_{c}"
        for c in revenue_pivot.columns
    ]

    events = events.merge(
        success_pivot,
        on="event_id",
        how="left",
    )

    events = events.merge(
        revenue_pivot,
        on="event_id",
        how="left",
    )

    for action in ACTIONS:
        success_col = f"success_{action}"
        revenue_col = f"revenue_{action}"

        if success_col not in events.columns:
            events[success_col] = 0

        if revenue_col not in events.columns:
            events[revenue_col] = 0.0

        events[success_col] = (
            events[success_col]
            .fillna(0)
            .astype(float)
        )

        events[revenue_col] = (
            events[revenue_col]
            .fillna(0)
            .astype(float)
        )

    return events


# ============================================================
# CONTEXT FEATURES
# ============================================================

def add_context_features(df):
    """
    Create robust context signals directly from the available
    feature-builder columns.

    No hidden target variables are used.
    """

    df = df.copy()

    # --------------------------------------------------------
    # Amount
    # --------------------------------------------------------

    df["amount"] = pd.to_numeric(
        df["amount"],
        errors="coerce",
    ).fillna(0)

    df["log_amount"] = np.log1p(
        df["amount"].clip(lower=0)
    )

    # --------------------------------------------------------
    # Retry pressure
    # --------------------------------------------------------

    if "retry_count" in df.columns:
        df["retry_count"] = pd.to_numeric(
            df["retry_count"],
            errors="coerce",
        ).fillna(0)

    else:
        df["retry_count"] = 0

    df["retry_pressure"] = (
        df["retry_count"] / 3
    ).clip(0, 1)

    # --------------------------------------------------------
    # Customer history
    # --------------------------------------------------------

    if "historical_success_rate" in df.columns:
        customer_success = pd.to_numeric(
            df["historical_success_rate"],
            errors="coerce",
        )
    else:
        customer_success = pd.Series(
            0.5,
            index=df.index,
        )

    df["customer_success_rate"] = (
        customer_success
        .fillna(0.5)
        .clip(0, 1)
    )

    # --------------------------------------------------------
    # Previous recovery history
    # --------------------------------------------------------

    if "previous_recovery_success_rate" in df.columns:
        df["previous_recovery_success_rate"] = pd.to_numeric(
            df["previous_recovery_success_rate"],
            errors="coerce",
        ).fillna(0.5).clip(0, 1)

    else:
        df["previous_recovery_success_rate"] = 0.5

    # --------------------------------------------------------
    # Merchant history
    # --------------------------------------------------------

    if "historical_success_rate_merchant" in df.columns:
        merchant_success = pd.to_numeric(
            df["historical_success_rate_merchant"],
            errors="coerce",
        )
        df["merchant_success_rate"] = (
            merchant_success
            .fillna(0.5)
            .clip(0, 1)
        )
    else:
        df["merchant_success_rate"] = 0.5

    # --------------------------------------------------------
    # Event hour
    # --------------------------------------------------------

    if "event_hour" in df.columns:
        df["event_hour"] = pd.to_numeric(
            df["event_hour"],
            errors="coerce",
        ).fillna(12)

    else:
        df["event_hour"] = (
            pd.to_datetime(df["timestamp"])
            .dt.hour
        )

    # --------------------------------------------------------
    # Checkout friction
    # --------------------------------------------------------

    if "checkout_duration_seconds" in df.columns:
        duration = pd.to_numeric(
            df["checkout_duration_seconds"],
            errors="coerce",
        ).fillna(0)

        df["checkout_friction"] = (
            duration / 300
        ).clip(0, 1)

    else:
        df["checkout_friction"] = 0

    # --------------------------------------------------------
    # Payment page signal
    # --------------------------------------------------------

    if "payment_page_reached" in df.columns:
        df["payment_page_signal"] = pd.to_numeric(
            df["payment_page_reached"],
            errors="coerce",
        ).fillna(0)
    else:
        df["payment_page_signal"] = 0

    # --------------------------------------------------------
    # High value
    # --------------------------------------------------------

    value_threshold = df["amount"].quantile(0.90)

    df["high_value"] = (
        df["amount"] >= value_threshold
    ).astype(int)

    # --------------------------------------------------------
    # Strong customer
    # --------------------------------------------------------

    df["strong_customer"] = (
        df["customer_success_rate"] >= 0.70
    ).astype(int)

    # --------------------------------------------------------
    # Repeated failure
    # --------------------------------------------------------

    df["repeated_failure"] = (
        df["retry_count"] >= 2
    ).astype(int)

    return df


# ============================================================
# ACTION SCORING
# ============================================================

def score_actions(row):
    """
    Context-aware heuristic policy.

    IMPORTANT:
    This does NOT use counterfactual outcomes when selecting
    the action.

    Counterfactual columns are used ONLY during evaluation.
    """

    scores = {
        action: 0.0
        for action in ACTIONS
    }

    event_type = str(
        row.get("event_type", "")
    )

    failure_type = str(
        row.get("failure_type", "")
    )

    amount = float(
        row.get("amount", 0)
    )

    retry = float(
        row.get("retry_count", 0)
    )

    customer_success = float(
        row.get("customer_success_rate", 0.5)
    )

    previous_recovery = float(
        row.get("previous_recovery_success_rate", 0.5)
    )

    checkout_friction = float(
        row.get("checkout_friction", 0)
    )

    payment_page = float(
        row.get("payment_page_signal", 0)
    )

    high_value = int(
        row.get("high_value", 0)
    )

    # ========================================================
    # PAYMENT FAILURE
    # ========================================================

    if event_type == "PAYMENT_FAILURE":

        scores["ALTERNATIVE_PAYMENT"] += 0.20

        if failure_type in {
            "TIMEOUT",
            "NETWORK_ERROR",
            "BANK_TECHNICAL_ERROR",
        }:
            scores["RETRY_LATER"] += 0.25

        if failure_type in {
            "INSUFFICIENT_BALANCE",
            "PAYMENT_LIMIT",
            "EXPIRED_PAYMENT_METHOD",
        }:
            scores["ALTERNATIVE_PAYMENT"] += 0.30

        if failure_type == "ISSUER_DECLINE":
            scores["HUMAN_ESCALATION"] += 0.10

    # ========================================================
    # CHECKOUT ABANDONMENT
    # ========================================================

    elif event_type == "CHECKOUT_ABANDONMENT":

        scores["RECOVERY_REMINDER"] += 0.45

        if payment_page:
            scores["RECOVERY_REMINDER"] += 0.20

        if checkout_friction > 0.7:
            scores["RECOVERY_REMINDER"] += 0.10

    # ========================================================
    # SUBSCRIPTION FAILURE
    # ========================================================

    elif event_type == "SUBSCRIPTION_FAILURE":

        scores["RECOVERY_REMINDER"] += 0.25
        scores["ALTERNATIVE_PAYMENT"] += 0.20

        if customer_success >= 0.70:
            scores["RECOVERY_REMINDER"] += 0.20

    # ========================================================
    # CUSTOMER HISTORY
    # ========================================================

    if customer_success >= 0.75:
        scores["RECOVERY_REMINDER"] += 0.10
        scores["RETRY_LATER"] += 0.05

    if customer_success < 0.30:
        scores["ALTERNATIVE_PAYMENT"] += 0.10

    # ========================================================
    # PREVIOUS RECOVERY
    # ========================================================

    if previous_recovery >= 0.65:
        scores["RECOVERY_REMINDER"] += 0.08

    # ========================================================
    # RETRY PRESSURE
    # ========================================================

    if retry >= 2:
        scores["RETRY_LATER"] -= 0.10
        scores["ALTERNATIVE_PAYMENT"] += 0.08

    # ========================================================
    # HIGH VALUE
    # ========================================================

    if high_value:
        scores["HUMAN_ESCALATION"] += 0.12
        scores["RECOVERY_REMINDER"] += 0.04

    # ========================================================
    # VERY LOW VALUE
    # ========================================================

    if amount < 1000:
        scores["HUMAN_ESCALATION"] -= 0.20

    return scores


# ============================================================
# GUARDRAILS
# ============================================================

def apply_guardrails(row, scores):
    scores = scores.copy()

    event_type = str(
        row.get("event_type", "")
    )

    retry = float(
        row.get("retry_count", 0)
    )

    amount = float(
        row.get("amount", 0)
    )

    # --------------------------------------------------------
    # Repeated retries
    # --------------------------------------------------------

    if retry >= 3:
        scores["RETRY_LATER"] = -np.inf

    # --------------------------------------------------------
    # Very low value
    # --------------------------------------------------------

    if amount < 500:
        scores["HUMAN_ESCALATION"] = -np.inf

    # --------------------------------------------------------
    # Checkout abandonment
    # --------------------------------------------------------

    if event_type == "CHECKOUT_ABANDONMENT":
        scores["RETRY_LATER"] -= 0.20

    # --------------------------------------------------------
    # Subscription failure
    # --------------------------------------------------------

    if event_type == "SUBSCRIPTION_FAILURE":
        scores["RETRY_LATER"] -= 0.10

    return scores


# ============================================================
# CHOOSE ACTION
# ============================================================

def choose_action(row):
    scores = score_actions(row)
    scores = apply_guardrails(row, scores)

    return max(
        scores,
        key=scores.get,
    )


# ============================================================
# ORACLE
# ============================================================

def calculate_oracle(row):
    values = {
        action: float(
            row.get(
                f"revenue_{action}",
                0
            )
        )
        for action in ACTIONS
    }

    best_action = max(
        values,
        key=values.get,
    )

    best_value = values[best_action]

    return best_action, best_value


# ============================================================
# POLICY EVALUATION
# ============================================================

def evaluate_policy(df):
    df = df.copy()

    chosen_actions = []
    chosen_revenue = []
    oracle_actions = []
    oracle_revenue = []

    for _, row in df.iterrows():

        action = choose_action(row)

        oracle_action, oracle_value = calculate_oracle(
            row
        )

        chosen_actions.append(action)

        chosen_revenue.append(
            float(
                row.get(
                    f"revenue_{action}",
                    0
                )
            )
        )

        oracle_actions.append(oracle_action)
        oracle_revenue.append(oracle_value)

    df["chosen_action"] = chosen_actions
    df["policy_revenue"] = chosen_revenue

    df["oracle_action"] = oracle_actions
    df["oracle_revenue"] = oracle_revenue

    df["regret"] = (
        df["oracle_revenue"]
        - df["policy_revenue"]
    ).clip(lower=0)

    df["action_match"] = (
        df["chosen_action"]
        == df["oracle_action"]
    )

    return df


# ============================================================
# BASELINE
# ============================================================

def calculate_baseline(df):
    column = "revenue_ALTERNATIVE_PAYMENT"

    if column not in df.columns:
        return 0.0

    return df[column].sum()


# ============================================================
# REPORTING
# ============================================================

def print_summary(df):
    revenue_at_risk = df["amount"].sum()

    recovered = df["policy_revenue"].sum()

    oracle = df["oracle_revenue"].sum()

    baseline = calculate_baseline(df)

    recovery_rate = (
        recovered / revenue_at_risk
        if revenue_at_risk
        else 0
    )

    uplift = (
        (recovered - baseline) / baseline
        if baseline
        else 0
    )

    oracle_capture = (
        recovered / oracle
        if oracle
        else 0
    )

    regret = df["regret"].sum()

    match_rate = df["action_match"].mean()

    print("\n==============================================================================")
    print("RECOVERAI V6 — CONTEXT-AWARE VALUE RECOVERY POLICY")
    print("==============================================================================")

    print(f"\nEvents: {len(df):,}")
    print(
        f"Revenue at risk: ₹{revenue_at_risk:,.2f}"
    )

    print(
        f"\nRevenue recovered: ₹{recovered:,.2f}"
    )

    print(
        f"Recovery rate: {recovery_rate:.2%}"
    )

    print("\nChosen actions:")

    print(
        df["chosen_action"]
        .value_counts()
        .to_string()
    )

    print("\nComparison:")
    print(
        f"Always Alternative: ₹{baseline:,.2f}"
    )

    print(
        f"RecoverAI V6:       ₹{recovered:,.2f}"
    )

    print(
        f"Incremental recovery: "
        f"₹{recovered - baseline:,.2f}"
    )

    print(
        f"Relative uplift: {uplift:.2%}"
    )

    print("\nOracle comparison:")

    print(
        f"Oracle: ₹{oracle:,.2f}"
    )

    print(
        f"Oracle capture: {oracle_capture:.2%}"
    )

    print(
        f"Policy regret: ₹{regret:,.2f}"
    )

    print(
        f"Oracle action match: {match_rate:.2%}"
    )


def print_action_summary(df):
    summary = (
        df.groupby("chosen_action")
        .agg(
            events=("event_id", "size"),
            recovered=("policy_revenue", "sum"),
            regret=("regret", "sum"),
            action_match=("action_match", "mean"),
        )
        .reset_index()
    )

    summary["recovered"] = summary["recovered"].round(2)
    summary["regret"] = summary["regret"].round(2)
    summary["action_match"] = (
        summary["action_match"] * 100
    ).round(2)

    print("\nAction performance:")
    print(
        summary.to_string(index=False)
    )

    return summary


def print_event_type_summary(df):
    summary = (
        df.groupby("event_type")
        .agg(
            events=("event_id", "size"),
            recovered=("policy_revenue", "sum"),
            oracle=("oracle_revenue", "sum"),
            regret=("regret", "sum"),
            action_match=("action_match", "mean"),
        )
        .reset_index()
    )

    summary["recovery_capture"] = np.where(
        summary["oracle"] > 0,
        summary["recovered"]
        / summary["oracle"],
        0,
    )

    summary["action_match"] = (
        summary["action_match"] * 100
    ).round(2)

    summary["recovery_capture"] = (
        summary["recovery_capture"] * 100
    ).round(2)

    print("\nPerformance by event type:")
    print(
        summary.to_string(index=False)
    )

    return summary


# ============================================================
# ACTION SCORES
# ============================================================

def create_action_score_report(df):
    rows = []

    for _, row in df.iterrows():

        scores = score_actions(row)

        scores = apply_guardrails(
            row,
            scores,
        )

        for action, score in scores.items():

            if np.isinf(score):
                score_value = -999999.0
            else:
                score_value = float(score)

            rows.append(
                {
                    "event_id": row["event_id"],
                    "action": action,
                    "score": score_value,
                    "chosen_action":
                        row["chosen_action"],
                }
            )

    return pd.DataFrame(rows)


# ============================================================
# HIGH VALUE ANALYSIS
# ============================================================

def high_value_analysis(df):
    threshold = df["amount"].quantile(0.90)

    high = df[
        df["amount"] >= threshold
    ].copy()

    if high.empty:
        return pd.DataFrame()

    recovered = high["policy_revenue"].sum()
    oracle = high["oracle_revenue"].sum()

    summary = pd.DataFrame(
        [
            {
                "events": len(high),
                "recovered": recovered,
                "oracle": oracle,
                "regret": high["regret"].sum(),
                "action_match":
                    high["action_match"].mean(),
            }
        ]
    )

    print("\nHigh-value transaction analysis:")
    print(
        f"Events: {len(high):,}"
    )

    print(
        f"Recovered: ₹{recovered:,.2f}"
    )

    print(
        f"Oracle: ₹{oracle:,.2f}"
    )

    print(
        f"Regret: ₹{high['regret'].sum():,.2f}"
    )

    print(
        f"Action match: "
        f"{high['action_match'].mean():.2%}"
    )

    return summary


# ============================================================
# SAVE REPORTS
# ============================================================

def save_outputs(df):
    PROCESSED.mkdir(
        parents=True,
        exist_ok=True,
    )

    result_columns = [
        "event_id",
        "timestamp",
        "event_type",
        "amount",
        "chosen_action",
        "policy_revenue",
        "oracle_action",
        "oracle_revenue",
        "regret",
        "action_match",
    ]

    result_columns = [
        c
        for c in result_columns
        if c in df.columns
    ]

    result_path = (
        PROCESSED
        / "v6_august_policy_results.csv"
    )

    df[result_columns].to_csv(
        result_path,
        index=False,
    )

    action_summary = print_action_summary(df)

    action_summary.to_csv(
        PROCESSED
        / "v6_action_summary.csv",
        index=False,
    )

    event_summary = print_event_type_summary(df)

    event_summary.to_csv(
        PROCESSED
        / "v6_event_type_summary.csv",
        index=False,
    )

    score_df = create_action_score_report(
        df
    )

    score_df.to_csv(
        PROCESSED
        / "v6_action_scores.csv",
        index=False,
    )

    high_value = high_value_analysis(
        df
    )

    if not high_value.empty:
        high_value.to_csv(
            PROCESSED
            / "v6_high_value_summary.csv",
            index=False,
        )

    summary = {
        "events": int(len(df)),
        "revenue_at_risk": float(
            df["amount"].sum()
        ),
        "revenue_recovered": float(
            df["policy_revenue"].sum()
        ),
        "oracle_revenue": float(
            df["oracle_revenue"].sum()
        ),
        "policy_regret": float(
            df["regret"].sum()
        ),
        "oracle_action_match_rate": float(
            df["action_match"].mean()
        ),
        "baseline_alternative_payment": float(
            calculate_baseline(df)
        ),
    }

    summary["recovery_rate"] = (
        summary["revenue_recovered"]
        / summary["revenue_at_risk"]
        if summary["revenue_at_risk"]
        else 0
    )

    summary["oracle_capture"] = (
        summary["revenue_recovered"]
        / summary["oracle_revenue"]
        if summary["oracle_revenue"]
        else 0
    )

    summary["relative_uplift_vs_baseline"] = (
        (
            summary["revenue_recovered"]
            - summary["baseline_alternative_payment"]
        )
        / summary["baseline_alternative_payment"]
        if summary["baseline_alternative_payment"]
        else 0
    )

    with open(
        PROCESSED / "v6_policy_summary.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            summary,
            f,
            indent=2,
        )

    print("\nSaved:")

    print(
        PROCESSED
        / "v6_august_policy_results.csv"
    )

    print(
        PROCESSED
        / "v6_action_summary.csv"
    )

    print(
        PROCESSED
        / "v6_event_type_summary.csv"
    )

    print(
        PROCESSED
        / "v6_action_scores.csv"
    )

    print(
        PROCESSED
        / "v6_policy_summary.json"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "\n=============================================================================="
    )
    print(
        "RECOVERAI V6 — CONTEXT-AWARE VALUE RECOVERY POLICY"
    )
    print(
        "=============================================================================="
    )

    # --------------------------------------------------------
    # Load using the EXISTING project feature pipeline
    # --------------------------------------------------------

    august_action_df, features = load_data()

    validate_dataset(
        august_action_df
    )

    # --------------------------------------------------------
    # Convert action simulations to event level
    # --------------------------------------------------------

    august = prepare_event_data(
        august_action_df
    )

    # --------------------------------------------------------
    # Add context features
    # --------------------------------------------------------

    august = add_context_features(
        august
    )

    print(
        f"\nEvents: {len(august):,}"
    )

    print(
        f"Revenue at risk: "
        f"₹{august['amount'].sum():,.2f}"
    )

    # --------------------------------------------------------
    # Evaluate
    # --------------------------------------------------------

    results = evaluate_policy(
        august
    )

    # --------------------------------------------------------
    # Print
    # --------------------------------------------------------

    print_summary(
        results
    )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    save_outputs(
        results
    )

    print(
        "\n=============================================================================="
    )
    print(
        "V6 POLICY EVALUATION COMPLETE"
    )
    print(
        "=============================================================================="
    )


if __name__ == "__main__":
    main()