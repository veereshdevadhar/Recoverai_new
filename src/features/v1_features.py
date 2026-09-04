from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"

LEAKAGE = {
    "true_recovery_probability",
    "simulated_success_probability",
    "recovery_success",
    "revenue_recovered",
}


def build_v1_dataset():

    events = pd.read_csv(
        RAW / "events.csv",
        parse_dates=["timestamp"]
    )

    customers = pd.read_csv(
        RAW / "customers.csv"
    )

    merchants = pd.read_csv(
        RAW / "merchants.csv"
    )

    outcomes = pd.read_csv(
        RAW / "recovery_actions.csv"
    )

    # ---------------------------------------------------------
    # MERGE DATA
    # ---------------------------------------------------------

    df = outcomes.merge(
        events,
        on="event_id",
        how="left",
        validate="many_to_one"
    )

    df = df.merge(
        customers,
        on="customer_id",
        how="left",
        validate="many_to_one",
        suffixes=("", "_customer")
    )

    df = df.merge(
        merchants,
        on="merchant_id",
        how="left",
        validate="many_to_one",
        suffixes=("", "_merchant")
    )

    # ---------------------------------------------------------
    # DEBUG / ROBUST COLUMN SELECTION
    # ---------------------------------------------------------

    def find_column(candidates, description):

        for column in candidates:
            if column in df.columns:
                return column

        raise KeyError(
            f"Could not find {description}. "
            f"Tried: {candidates}\n"
            f"Available columns:\n{list(df.columns)}"
        )

    customer_success_col = find_column(
        [
            "historical_success_rate_customer",
            "historical_success_rate_x",
            "historical_success_rate"
        ],
        "customer historical success rate"
    )

    customer_avg_amount_col = find_column(
        [
            "avg_transaction_amount_customer",
            "avg_transaction_amount_x",
            "avg_transaction_amount"
        ],
        "customer average transaction amount"
    )

    merchant_success_col = find_column(
        [
            "historical_success_rate_merchant",
            "historical_success_rate_y"
        ],
        "merchant historical success rate"
    )

    # ---------------------------------------------------------
    # TEMPORAL FEATURES
    # ---------------------------------------------------------

    df["event_hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month

    # ---------------------------------------------------------
    # NUMERICAL TRANSFORMATIONS
    # ---------------------------------------------------------

    df["log_amount"] = np.log1p(
        df["amount"]
    )

    df["amount_per_customer_transaction"] = (
        df["amount"]
        /
        df["total_transactions"].clip(lower=1)
    )

    df["customer_success_rate"] = (
        df[customer_success_col]
    )

    df["merchant_success_rate"] = (
        df[merchant_success_col]
    )

    df["customer_avg_transaction_amount"] = (
        df[customer_avg_amount_col]
    )

    # ---------------------------------------------------------
    # CONTEXT FLAGS
    # ---------------------------------------------------------

    df["high_value"] = (
        df["amount"] >= 10000
    ).astype(int)

    df["strong_customer_history"] = (
        df["customer_success_rate"] >= 0.90
    ).astype(int)

    df["repeated_failure"] = (
        df["retry_count"] >= 2
    ).astype(int)

    # ---------------------------------------------------------
    # ACTION × CONTEXT INTERACTIONS
    # ---------------------------------------------------------

    context_cols = [
        "event_type",
        "failure_type",
        "payment_method",
        "retry_count",
        "merchant_category",
        "merchant_size",
    ]

    for col in context_cols:

        df[f"action__{col}"] = (
            df["action"].astype(str)
            + "__"
            + df[col].fillna("UNKNOWN").astype(str)
        )

    flag_cols = [
        "high_value",
        "strong_customer_history",
        "repeated_failure",
    ]

    for col in flag_cols:

        df[f"action__{col}"] = (
            df["action"].astype(str)
            + "__"
            + df[col].astype(str)
        )

    # ---------------------------------------------------------
    # REMOVE LEAKAGE / IDENTIFIERS
    # ---------------------------------------------------------

    exclude = LEAKAGE | {
        "event_id",
        "customer_id",
        "merchant_id",
        "timestamp",
        "currency",
        "allowed",
        "policy_reason",
        "payment_status",
    }

    features = [
        column
        for column in df.columns
        if column not in exclude
    ]

    return df, features


if __name__ == "__main__":

    df, features = build_v1_dataset()

    print(f"Rows: {len(df):,}")
    print(f"V1 features: {len(features)}")

    print("\nFeatures:")

    for feature in features:
        print(f" - {feature}")