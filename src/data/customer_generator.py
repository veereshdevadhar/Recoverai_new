import numpy as np
import pandas as pd

PAYMENT_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]

def generate_customers(n=2000, seed=42):
    rng = np.random.default_rng(seed)
    tenure = rng.integers(30, 1500, n)
    total = rng.integers(1, 80, n)
    success_rate = np.clip(rng.beta(14, 2, n), 0.55, 0.995)
    successful = np.maximum(0, np.round(total * success_rate).astype(int))
    failed = total - successful

    return pd.DataFrame({
        "customer_id": [f"CUS_{i:06d}" for i in range(1, n + 1)],
        "customer_tenure_days": tenure,
        "total_transactions": total,
        "successful_transactions": successful,
        "failed_transactions": failed,
        "historical_success_rate": np.round(successful / total, 4),
        "avg_transaction_amount": np.round(np.exp(rng.normal(np.log(4500), 0.8, n)), 2),
        "previous_recovery_success_rate": np.round(rng.beta(5, 2, n), 4),
        "days_since_last_success": rng.integers(0, 90, n),
        "preferred_payment_method": rng.choice(PAYMENT_METHODS, n, p=[0.45, 0.35, 0.12, 0.08]),
    })
