import numpy as np
import pandas as pd

ACTIONS = [
    "RETRY_LATER",
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "HUMAN_ESCALATION",
    "STOP",
]

def action_base_probability(row, action):
    p = float(row["true_recovery_probability"])
    event = row["event_type"]
    failure = row["failure_type"]
    retry = int(row["retry_count"])

    if action == "STOP":
        return 0.0
    if action == "RETRY_LATER":
        bonus = 0.12 if failure in {"TIMEOUT", "BANK_TECHNICAL_ERROR", "NETWORK_ERROR"} else -0.05
        return np.clip(p + bonus - 0.10 * retry, 0.01, 0.99)
    if action == "ALTERNATIVE_PAYMENT":
        bonus = 0.18 if failure in {"EXPIRED_PAYMENT_METHOD", "PAYMENT_LIMIT", "ISSUER_DECLINE"} else 0.03
        return np.clip(p + bonus, 0.01, 0.99)
    if action == "RECOVERY_REMINDER":
        bonus = 0.15 if event == "CHECKOUT_ABANDONMENT" else 0.02
        return np.clip(p + bonus, 0.01, 0.99)
    if action == "HUMAN_ESCALATION":
        bonus = 0.10 if row["amount"] >= 20000 else -0.10
        return np.clip(p + bonus, 0.01, 0.99)
    raise ValueError(action)

def apply_policy(row, action):
    if action == "RETRY_LATER" and row["retry_count"] >= 3:
        return False, "RETRY_LIMIT_REACHED"
    if action == "RECOVERY_REMINDER" and row["event_type"] == "PAYMENT_FAILURE" and row["retry_count"] >= 3:
        return False, "EXCESSIVE_ATTEMPTS"
    if action == "HUMAN_ESCALATION" and row["amount"] < 1000:
        return False, "AMOUNT_BELOW_ESCALATION_THRESHOLD"
    return True, "ALLOWED"

def simulate_action(events, actions, seed=45):
    rng = np.random.default_rng(seed)
    rows = []
    for _, row in events.iterrows():
        for action in actions:
            allowed, reason = apply_policy(row, action)
            p = action_base_probability(row, action) if allowed else 0.0
            success = bool(rng.random() < p) if allowed and action != "STOP" else False
            recovered = float(row["amount"]) if success else 0.0
            rows.append({
                "event_id": row["event_id"],
                "action": action,
                "allowed": allowed,
                "policy_reason": reason,
                "simulated_success_probability": round(p, 6),
                "recovery_success": int(success),
                "revenue_recovered": round(recovered, 2),
            })
    return pd.DataFrame(rows)
