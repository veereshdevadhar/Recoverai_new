from __future__ import annotations

"""Counterfactual Recovery Simulator.

For a live (hypothetical) event, the counterfactual view is simply a
clearly-labeled re-presentation of what the Decision Agent already computed
in ``/predict`` for every action (probabilities, expected value, allowed/
blocked, decision advantage) — no invented numbers.

For a *historical* evaluation event (looked up by ``event_id``), this module
additionally attaches the real ground-truth simulated outcome for every
action from ``data/raw/recovery_actions.csv`` (a genuine counterfactual
logging dataset — every action was simulated for every event), so we can
show the real oracle action and the real opportunity gap versus what the
live model/policy would have chosen.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
EVAL_PATH = PROCESSED / "v3_100k_august_policy_results.csv"
RAW_ACTIONS_PATH = RAW / "recovery_actions.csv"

NON_RETRYABLE = {"ISSUER_DECLINE", "INSUFFICIENT_BALANCE", "PAYMENT_LIMIT", "EXPIRED_PAYMENT_METHOD"}

def _production_allowed(payload: dict[str, Any], action: str) -> bool:
    if action == "RETRY_LATER":
        return payload.get("retry_count", 0) < 3 and payload.get("failure_type") not in NON_RETRYABLE
    if action == "HUMAN_ESCALATION":
        return payload.get("amount", 0) >= 25000 and payload.get("historical_success_rate", 0) >= 0.85
    return True


PAYLOAD_FIELD_MAP = {
    "event_type": "event_type",
    "amount": "amount",
    "payment_method": "payment_method",
    "device_type": "device_type",
    "failure_type": "failure_type",
    "retry_count": "retry_count",
    "previous_attempt_hours": "previous_attempt_hours",
    "checkout_duration_seconds": "checkout_duration_seconds",
    "payment_page_reached": "payment_page_reached",
    "payment_attempted": "payment_attempted",
    "subscription_age_days": "subscription_age_days",
    "successful_cycles": "successful_cycles",
    "failed_cycles": "failed_cycles",
    "customer_tenure_days": "customer_tenure_days",
    "total_transactions": "total_transactions",
    "successful_transactions": "successful_transactions",
    "failed_transactions": "failed_transactions",
    "historical_success_rate": "historical_success_rate",
    "avg_transaction_amount": "avg_transaction_amount",
    "previous_recovery_success_rate": "previous_recovery_success_rate",
    "days_since_last_success": "days_since_last_success",
    "preferred_payment_method": "preferred_payment_method",
    "merchant_category": "merchant_category",
    "merchant_size": "merchant_size",
    "merchant_avg_transaction_amount": "avg_transaction_amount_merchant",
    "merchant_success_rate": "historical_success_rate_merchant",
    "merchant_failure_rate": "historical_failure_rate",
    "event_hour": "event_hour",
    "day_of_week": "day_of_week",
    "month": "month",
}


@lru_cache(maxsize=1)
def _load_eval_frame() -> pd.DataFrame:
    return pd.read_csv(EVAL_PATH)


@lru_cache(maxsize=1)
def _load_raw_actions() -> pd.DataFrame:
    return pd.read_csv(RAW_ACTIONS_PATH)


def sample_event_ids(n: int = 12) -> list[dict[str, Any]]:
    df = _load_eval_frame()
    sample = df.sample(n=min(n, len(df)), random_state=42)
    return sample[["event_id", "event_type", "amount", "failure_type", "chosen_action", "actual_recovered"]].fillna("NONE").to_dict(orient="records")


def payload_dict_for_event(event_id: str) -> dict[str, Any] | None:
    df = _load_eval_frame()
    row = df[df["event_id"] == event_id]
    if row.empty:
        return None
    row = row.iloc[0]
    payload = {}
    for field, column in PAYLOAD_FIELD_MAP.items():
        value = row[column]
        if field in {"payment_page_reached", "payment_attempted", "retry_count", "successful_cycles",
                     "failed_cycles", "total_transactions", "successful_transactions", "failed_transactions",
                     "event_hour", "day_of_week", "month"}:
            value = int(value)
        elif field == "failure_type" and pd.isna(value):
            value = None
        payload[field] = value
    return payload


def oracle_for_event(event_id: str) -> dict[str, Any]:
    raw = _load_raw_actions()
    subset = raw[raw["event_id"] == event_id]
    outcomes = {
        row.action: {
            "allowed": bool(row.allowed),
            "policy_reason": row.policy_reason,
            "simulated_success_probability": round(float(row.simulated_success_probability), 4),
            "revenue_recovered": round(float(row.revenue_recovered), 2),
        }
        for row in subset.itertuples()
    }
    if not outcomes:
        return {"available": False}
    payload = payload_dict_for_event(event_id) or {}
    for action in outcomes:
        outcomes[action]["production_guardrail_allowed"] = _production_allowed(payload, action)
    feasible = [a for a in outcomes if outcomes[a]["production_guardrail_allowed"]]
    best_action = max(feasible, key=lambda a: outcomes[a]["revenue_recovered"]) if feasible else "STOP"
    return {
        "available": True,
        "action_outcomes": outcomes,
        "oracle_definition": "hindsight best feasible action under the same production guardrails",
        "oracle_action": best_action,
        "oracle_revenue": outcomes[best_action]["revenue_recovered"] if best_action != "STOP" else 0.0,
    }


def build_counterfactual(decision: dict[str, Any], oracle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn a live decision result into the counterfactual view. Uses only
    numbers the Decision Agent already computed (probabilities, expected
    revenue, expected net value, guardrails, score margin)."""
    ranked = decision["ranked_actions"]
    chosen = decision["recommended_action"]

    alternatives = []
    for entry in ranked:
        action = entry["action"]
        if action == chosen:
            continue
        alternatives.append({
            "action": action,
            "allowed": entry["allowed"],
            "expected_net_value": entry["score"],
            "expected_recovery": decision["expected_revenue"].get(action),
            "status": "BLOCKED" if not entry["allowed"] else "ALLOWED",
        })

    result = {
        "selected": {
            "action": chosen,
            "expected_recovery": decision["expected_revenue"].get(chosen),
            "expected_net_value": decision["expected_net_value"].get(chosen),
        },
        "alternatives": alternatives,
        "decision_advantage": decision["score_margin"],
        "decision_advantage_note": "Expected net value gap between the selected action and the next-best allowed alternative.",
    }

    if oracle and oracle.get("available"):
        chosen_ground_truth = oracle["action_outcomes"].get(chosen, {}).get("revenue_recovered", 0.0)
        result["oracle"] = {
            "oracle_action": oracle["oracle_action"],
            "oracle_revenue": oracle["oracle_revenue"],
            "actual_ground_truth_for_selected_action": chosen_ground_truth,
            "opportunity_gap": round(oracle["oracle_revenue"] - chosen_ground_truth, 2),
            "note": "Ground-truth simulated outcome for every action on this historical event, from the counterfactual-logging dataset.",
        }
    else:
        result["oracle"] = {
            "note": "No oracle comparison available for a live/hypothetical event; oracle comparison only applies to historical evaluation events looked up by event_id.",
        }

    return result
