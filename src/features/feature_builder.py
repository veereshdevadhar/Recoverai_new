from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"

LEAKAGE_COLUMNS = {
    "true_recovery_probability",
    "simulated_success_probability",
    "recovery_success",
    "revenue_recovered",
}

def build_action_dataset():
    events = pd.read_csv(RAW / "events.csv", parse_dates=["timestamp"])
    customers = pd.read_csv(RAW / "customers.csv")
    merchants = pd.read_csv(RAW / "merchants.csv")
    outcomes = pd.read_csv(RAW / "recovery_actions.csv")

    df = outcomes.merge(events, on="event_id", how="left", validate="many_to_one")
    df = df.merge(customers, on="customer_id", how="left", validate="many_to_one")
    df = df.merge(merchants, on="merchant_id", how="left", validate="many_to_one")

    df["event_hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month

    exclude = LEAKAGE_COLUMNS | {
        "event_id", "customer_id", "merchant_id", "timestamp",
        "currency", "allowed", "policy_reason", "payment_status"
    }
    features = [c for c in df.columns if c not in exclude]
    return df, features

if __name__ == "__main__":
    df, features = build_action_dataset()
    print(f"Rows: {len(df):,}")
    print(f"Features ({len(features)}):")
    print(features)
