import numpy as np
import pandas as pd

PAYMENT_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
DEVICES = ["MOBILE", "DESKTOP", "TABLET"]
FAILURES = [
    "TIMEOUT", "BANK_TECHNICAL_ERROR", "NETWORK_ERROR",
    "INSUFFICIENT_BALANCE", "EXPIRED_PAYMENT_METHOD",
    "PAYMENT_LIMIT", "ISSUER_DECLINE"
]

def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))

def generate_events(customers, merchants, n=10000, seed=44):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-01-01")
    end = pd.Timestamp("2026-08-31")
    seconds = int((end - start).total_seconds())
    timestamps = start + pd.to_timedelta(rng.integers(0, seconds, n), unit="s")

    customer_idx = rng.integers(0, len(customers), n)
    merchant_idx = rng.integers(0, len(merchants), n)
    c = customers.iloc[customer_idx].reset_index(drop=True)
    m = merchants.iloc[merchant_idx].reset_index(drop=True)

    event_type = rng.choice(
        ["PAYMENT_FAILURE", "CHECKOUT_ABANDONMENT", "SUBSCRIPTION_FAILURE"],
        n, p=[0.62, 0.23, 0.15]
    )
    amount = np.maximum(
        100,
        np.round(np.exp(rng.normal(np.log(c["avg_transaction_amount"]), 0.55)), 2)
    )
    payment_method = rng.choice(PAYMENT_METHODS, n, p=[0.45, 0.35, 0.12, 0.08])
    device = rng.choice(DEVICES, n, p=[0.65, 0.30, 0.05])

    # ---- Injected incident: genuine, detectable UPI provider degradation ----
    # In the final INCIDENT_HOURS of the timeline, UPI events fail at an
    # elevated rate. This is baked into event_type/failure_type themselves
    # (not into any downstream "outcome" column), so the revenue-intelligence
    # anomaly detector — which only reads event_type/payment_status/timestamp —
    # picks up a real, non-fabricated spike instead of always reporting zero
    # anomalies on an otherwise time-stationary synthetic dataset.
    INCIDENT_HOURS = 30
    incident_window = timestamps >= (end - pd.Timedelta(hours=INCIDENT_HOURS))
    incident_mask = incident_window & (payment_method == "UPI") & (rng.random(n) < 0.72)
    event_type = np.where(incident_mask, "PAYMENT_FAILURE", event_type)

    failure = np.where(
        event_type == "PAYMENT_FAILURE",
        rng.choice(FAILURES, n, p=[0.18, 0.14, 0.10, 0.20, 0.10, 0.10, 0.18]),
        None
    )
    failure = np.where(incident_mask, rng.choice(["TIMEOUT", "BANK_TECHNICAL_ERROR"], n, p=[0.6, 0.4]), failure)
    retry_count = np.where(
        event_type == "PAYMENT_FAILURE",
        rng.integers(0, 4, n),
        0
    )

    checkout_duration = np.where(
        event_type == "CHECKOUT_ABANDONMENT",
        rng.integers(20, 900, n), 0
    )
    payment_page = np.where(
        event_type == "CHECKOUT_ABANDONMENT",
        rng.random(n) < 0.88, False
    )
    payment_attempted = np.where(
        event_type == "CHECKOUT_ABANDONMENT",
        rng.random(n) < 0.18, False
    )

    subscription_age = np.where(
        event_type == "SUBSCRIPTION_FAILURE",
        rng.integers(30, 900, n), 0
    )
    successful_cycles = np.where(
        event_type == "SUBSCRIPTION_FAILURE",
        rng.integers(1, 24, n), 0
    )
    failed_cycles = np.where(
        event_type == "SUBSCRIPTION_FAILURE",
        rng.integers(0, 4, n), 0
    )

    # Hidden simulator variables. These are NOT model features.
    base = (
        -0.4
        + 1.5 * (c["historical_success_rate"].to_numpy() - 0.75)
        + 0.8 * (m["historical_success_rate"].to_numpy() - 0.85)
        - 0.35 * retry_count
        + 0.00001 * np.minimum(amount, 50000)
    )

    failure_effect = np.zeros(n)
    failure_effect[failure == "TIMEOUT"] = 0.65
    failure_effect[failure == "BANK_TECHNICAL_ERROR"] = 0.75
    failure_effect[failure == "NETWORK_ERROR"] = 0.55
    failure_effect[failure == "INSUFFICIENT_BALANCE"] = -0.35
    failure_effect[failure == "EXPIRED_PAYMENT_METHOD"] = -0.10
    failure_effect[failure == "PAYMENT_LIMIT"] = -0.20
    failure_effect[failure == "ISSUER_DECLINE"] = -0.65

    checkout_effect = np.where(
        event_type == "CHECKOUT_ABANDONMENT",
        0.9 * payment_page.astype(float) + 0.25 * (checkout_duration > 120),
        0
    )
    subscription_effect = np.where(
        event_type == "SUBSCRIPTION_FAILURE",
        0.65 * (successful_cycles >= 6) - 0.45 * failed_cycles,
        0
    )

    true_probability = _sigmoid(base + failure_effect + checkout_effect + subscription_effect)
    true_probability = np.clip(true_probability, 0.02, 0.98)

    return pd.DataFrame({
        "event_id": [f"EVT_{i:08d}" for i in range(1, n + 1)],
        "event_type": event_type,
        "timestamp": timestamps,
        "customer_id": c["customer_id"],
        "merchant_id": m["merchant_id"],
        "amount": amount,
        "currency": "INR",
        "payment_method": payment_method,
        "device_type": device,
        "payment_status": np.where(event_type == "PAYMENT_FAILURE", "FAILED", "AT_RISK"),
        "failure_type": failure,
        "retry_count": retry_count,
        "previous_attempt_hours": np.round(rng.uniform(0, 72, n), 2),
        "checkout_duration_seconds": checkout_duration,
        "payment_page_reached": payment_page,
        "payment_attempted": payment_attempted,
        "subscription_age_days": subscription_age,
        "successful_cycles": successful_cycles,
        "failed_cycles": failed_cycles,
        # Ground-truth simulator state; exclude from model training.
        "true_recovery_probability": np.round(true_probability, 6),
    }).sort_values("timestamp").reset_index(drop=True)
