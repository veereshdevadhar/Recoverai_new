import numpy as np
import pandas as pd

CATEGORIES = ["E_COMMERCE", "SAAS", "EDUCATION", "FOOD_DELIVERY", "TRAVEL", "RETAIL", "DIGITAL_SERVICES"]
SIZES = ["SMALL", "MEDIUM", "LARGE"]

def generate_merchants(n=200, seed=43):
    rng = np.random.default_rng(seed)
    avg_amount = np.exp(rng.normal(np.log(5000), 0.9, n))
    success = np.clip(rng.beta(18, 2, n), 0.70, 0.995)

    return pd.DataFrame({
        "merchant_id": [f"MER_{i:05d}" for i in range(1, n + 1)],
        "merchant_category": rng.choice(CATEGORIES, n),
        "merchant_size": rng.choice(SIZES, n, p=[0.55, 0.30, 0.15]),
        "avg_transaction_amount": np.round(avg_amount, 2),
        "historical_success_rate": np.round(success, 4),
        "historical_failure_rate": np.round(1 - success, 4),
    })
