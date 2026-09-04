import pandas as pd

REQUIRED_EVENT_COLUMNS = [
    "event_id", "event_type", "timestamp", "customer_id", "merchant_id",
    "amount", "currency", "payment_method", "device_type",
    "payment_status", "failure_type", "retry_count",
    "true_recovery_probability"
]

LEAKAGE_COLUMNS = {
    "recovery_success",
    "revenue_recovered",
    "true_recovery_probability",
    "simulated_success_probability",
}

def validate_events(df):
    errors = []
    missing = [c for c in REQUIRED_EVENT_COLUMNS if c not in df.columns]
    if missing:
        errors.append(f"Missing columns: {missing}")

    if df["event_id"].duplicated().any():
        errors.append("Duplicate event_id values found.")
    if (df["amount"] <= 0).any():
        errors.append("Non-positive transaction amounts found.")
    if not df["timestamp"].is_monotonic_increasing:
        errors.append("Events are not chronologically sorted.")
    if df["retry_count"].min() < 0:
        errors.append("Negative retry_count found.")

    if errors:
        raise ValueError("\n".join(errors))
    return True

def check_no_target_leakage(feature_columns):
    leaked = sorted(set(feature_columns) & LEAKAGE_COLUMNS)
    if leaked:
        raise ValueError(f"Target/simulator leakage detected: {leaked}")
    return True
