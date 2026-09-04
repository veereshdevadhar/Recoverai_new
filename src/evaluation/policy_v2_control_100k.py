
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MODEL_PATH = (
    ROOT / "data" / "processed" / "models"
    / "recoverai_v2_action_models.joblib"
)

ACTIONS = [
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "RETRY_LATER",
    "HUMAN_ESCALATION",
]

def load_policy_data():
    events = pd.read_csv(
        RAW / "events.csv",
        parse_dates=["timestamp"]
    )
    customers = pd.read_csv(RAW / "customers.csv")
    merchants = pd.read_csv(RAW / "merchants.csv")
    outcomes = pd.read_csv(RAW / "recovery_actions.csv")

    df = outcomes.merge(
        events, on="event_id", how="left",
        validate="many_to_one"
    )
    df = df.merge(
        customers, on="customer_id", how="left",
        validate="many_to_one", suffixes=("", "_customer")
    )
    df = df.merge(
        merchants, on="merchant_id", how="left",
        validate="many_to_one", suffixes=("", "_merchant")
    )

    df["event_hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month
    df["log_amount"] = np.log1p(df["amount"])

    if "historical_success_rate_customer" in df:
        customer_success = "historical_success_rate_customer"
    elif "historical_success_rate_x" in df:
        customer_success = "historical_success_rate_x"
    else:
        customer_success = "historical_success_rate"

    if "avg_transaction_amount_customer" in df:
        customer_avg = "avg_transaction_amount_customer"
    elif "avg_transaction_amount_x" in df:
        customer_avg = "avg_transaction_amount_x"
    else:
        customer_avg = "avg_transaction_amount"

    if "historical_success_rate_merchant" in df:
        merchant_success = "historical_success_rate_merchant"
    elif "historical_success_rate_y" in df:
        merchant_success = "historical_success_rate_y"
    else:
        merchant_success = None

    df["customer_success_rate"] = df[customer_success]
    df["customer_avg_transaction_amount"] = df[customer_avg]

    if merchant_success:
        df["merchant_success_rate"] = df[merchant_success]
    else:
        df["merchant_success_rate"] = np.nan

    df["amount_per_customer_transaction"] = (
        df["amount"] / df["total_transactions"].clip(lower=1)
    )
    df["high_value"] = (df["amount"] >= 10000).astype(int)
    df["strong_customer_history"] = (
        df["customer_success_rate"] >= 0.90
    ).astype(int)
    df["repeated_failure"] = (df["retry_count"] >= 2).astype(int)

    return df


def main():
    print("\n" + "=" * 75)
    print("RECOVERAI V2 CONTROL — CURRENT 100K HELD-OUT AUGUST POLICY")
    print("=" * 75)

    artifact = joblib.load(MODEL_PATH)
    models = artifact["models"]
    features = artifact["features"]

    df = load_policy_data()

    # August is NEVER used for training.
    test = df[
        df["timestamp"] >= "2026-08-01"
    ].copy()

    # One physical event appears once per possible action in the
    # synthetic outcome table. Keep one event row for policy scoring.
    events = (
        test.sort_values("action")
        .drop_duplicates("event_id")
        .copy()
    )

    X = events[features]

    probabilities = {}

    for action in ACTIONS:
        probabilities[action] = (
            models[action]
            .predict_proba(X)[:, 1]
        )

    probability_df = pd.DataFrame(
        probabilities,
        index=events.index
    )

    # Expected recovered value.
    # V2 initially uses the same simple economic objective as V1:
    # predicted probability × transaction amount.
    expected_value = probability_df.multiply(
        events["amount"],
        axis=0
    )

    # ---------------------------------------------------------
    # GUARDRAILS
    # ---------------------------------------------------------

    # Human escalation is reserved for higher-value cases with
    # strong customer history. This keeps the automated policy
    # bounded and prevents indiscriminate human escalation.
    human_allowed = (
        (events["amount"] >= 10000)
        &
        (events["customer_success_rate"] >= 0.85)
    )

    expected_value.loc[~human_allowed, "HUMAN_ESCALATION"] = -np.inf

    # After repeated failed attempts, do not recommend another
    # immediate retry.
    expected_value.loc[
        events["retry_count"] >= 3,
        "RETRY_LATER"
    ] = -np.inf

    chosen = expected_value.idxmax(axis=1)

    events["chosen_action"] = chosen
    events["chosen_probability"] = [
        probability_df.loc[idx, action]
        for idx, action in zip(
            events.index,
            chosen
        )
    ]

    events["expected_value"] = [
        expected_value.loc[idx, action]
        for idx, action in zip(
            events.index,
            chosen
        )
    ]

    # ---------------------------------------------------------
    # ACTUAL AUGUST OUTCOME
    # ---------------------------------------------------------

    actual_lookup = test.set_index(
        ["event_id", "action"]
    )

    actual_recovered = []

    for _, row in events.iterrows():
        key = (row["event_id"], row["chosen_action"])

        if key in actual_lookup.index:
            outcome = actual_lookup.loc[key]
            actual_recovered.append(
                float(outcome["revenue_recovered"])
            )
        else:
            actual_recovered.append(0.0)

    events["actual_recovered"] = actual_recovered

    revenue_at_risk = events["amount"].sum()
    recovered = events["actual_recovered"].sum()

    print(f"\nEvents: {len(events):,}")
    print(f"Revenue at risk: ₹{revenue_at_risk:,.2f}")
    print(f"Revenue recovered: ₹{recovered:,.2f}")
    print(
        f"Recovery rate: "
        f"{recovered / revenue_at_risk:.2%}"
    )

    print("\nChosen actions:")
    print(
        events["chosen_action"]
        .value_counts()
        .to_string()
    )

    print("\nActual results by chosen action:")

    action_results = (
        events.groupby("chosen_action")
        .agg(
            events=("event_id", "count"),
            success_rate=(
                "recovery_success",
                "mean"
            ),
            revenue_recovered=(
                "actual_recovered",
                "sum"
            ),
        )
        .sort_values(
            "revenue_recovered",
            ascending=False
        )
    )

    print(action_results.to_string())

    # ---------------------------------------------------------
    # BASELINE COMPARISON
    # ---------------------------------------------------------

    baseline = test[
        test["action"] == "ALTERNATIVE_PAYMENT"
    ]["revenue_recovered"].sum()

    incremental = recovered - baseline
    uplift = incremental / baseline

    print("\nComparison against ALWAYS ALTERNATIVE:")
    print(f"Baseline: ₹{baseline:,.2f}")
    print(f"RecoverAI V2: ₹{recovered:,.2f}")
    print(f"Incremental recovery: ₹{incremental:,.2f}")
    print(f"Relative uplift: {uplift:.2%}")

    # ---------------------------------------------------------
    # ORACLE
    # ---------------------------------------------------------

    oracle = (
        test.groupby("event_id")["revenue_recovered"]
        .max()
        .sum()
    )

    oracle_capture = recovered / oracle
    regret = oracle - recovered

    print("\nOracle comparison:")
    print(f"Oracle: ₹{oracle:,.2f}")
    print(f"Oracle capture: {oracle_capture:.2%}")
    print(f"Policy regret: ₹{regret:,.2f}")

    # ---------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------

    output = ROOT / "data" / "processed"
    output.mkdir(parents=True, exist_ok=True)

    events.to_csv(
        output / "v2_control_100k_august_policy_results.csv",
        index=False
    )

    print("\nSaved:")
    print(output / "v2_control_100k_august_policy_results.csv")

    print("\n" + "=" * 75)
    print("V2 POLICY EVALUATION COMPLETE")
    print("=" * 75)


if __name__ == "__main__":
    main()
