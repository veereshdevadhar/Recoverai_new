from __future__ import annotations

"""Policy What-If Lab and A/B Comparison engine.

This module runs the *real* trained action-specific models (the same
artifact used by the live Decision Agent) in batch over the August held-out
evaluation set, then applies a configurable guardrail/policy layer on top —
never the other way around. It never retrains or fabricates probabilities.

Ground truth for "what would have happened" under each candidate action is
taken from ``data/raw/recovery_actions.csv``, which contains a real
per-action simulated outcome for every event in the dataset (this is a
counterfactual-logging synthetic dataset by design, which is what makes
honest offline policy evaluation possible here). This is the direct-method /
replay approach to offline policy evaluation: score every action with the
real model, apply the candidate policy's guardrails, then look up the
ground-truth simulated outcome for whichever action the candidate policy
would have picked.

Calling ``simulate_policy`` never mutates the production policy — it is a
pure function over an isolated ``PolicyParams`` object and returns a summary
dict. The live production dashboard (``dashboard_metrics`` in
``src/api/main.py``) is computed from a separately stored, already-executed
column (``actual_recovered``) and is completely unaffected by this module.
"""

from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
EVAL_PATH = PROCESSED / "v3_100k_august_policy_results.csv"
RAW_ACTIONS_PATH = RAW / "recovery_actions.csv"
MODEL_PATH = PROCESSED / "models" / "recoverai_v3_100k_action_models.joblib"

ACTIONS = ["ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION"]
ACTION_COSTS = {
    "ALTERNATIVE_PAYMENT": 20.0,
    "RECOVERY_REMINDER": 10.0,
    "RETRY_LATER": 5.0,
    "HUMAN_ESCALATION": 500.0,
    "STOP": 0.0,
}
NON_RETRYABLE_FAILURES = {"ISSUER_DECLINE", "INSUFFICIENT_BALANCE", "PAYMENT_LIMIT", "EXPIRED_PAYMENT_METHOD"}


@dataclass
class PolicyParams:
    """An isolated, non-production set of policy knobs.

    retry_cooldown_hours / reminder_cooldown_hours are accepted for API
    symmetry with the Adaptive Sequencer (where a timeline exists), but the
    static evaluation set below has exactly one decision point per event, so
    a cooldown has no observable effect there. This is stated explicitly in
    the response rather than silently ignored.
    """

    name: str = "Custom Policy"
    retry_limit: int = 3
    escalation_min_amount: float = 25000.0
    escalation_min_success_rate: float = 0.85
    high_value_threshold: float = 10000.0
    retry_cooldown_hours: float = 0.0
    reminder_cooldown_hours: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=1)
def _load_model():
    import joblib
    return joblib.load(MODEL_PATH)


@lru_cache(maxsize=1)
def _load_eval_frame() -> pd.DataFrame:
    return pd.read_csv(EVAL_PATH)


@lru_cache(maxsize=1)
def _load_raw_actions() -> pd.DataFrame:
    return pd.read_csv(RAW_ACTIONS_PATH)


@lru_cache(maxsize=1)
def _batch_probabilities() -> dict[str, np.ndarray]:
    """Real model, batch-scored once over the whole evaluation set and cached."""
    artifact = _load_model()
    df = _load_eval_frame()
    X = df[artifact["features"]]
    return {action: artifact["models"][action].predict_proba(X)[:, 1] for action in ACTIONS}


@lru_cache(maxsize=1)
def _oracle_per_event() -> pd.Series:
    raw = _load_raw_actions()
    eval_ids = set(_load_eval_frame()["event_id"])
    subset = raw[raw["event_id"].isin(eval_ids)]
    return subset.groupby("event_id")["revenue_recovered"].max()


@lru_cache(maxsize=1)
def _outcome_lookup() -> dict[tuple[str, str], float]:
    """(event_id, action) -> ground-truth simulated revenue_recovered."""
    raw = _load_raw_actions()
    eval_ids = set(_load_eval_frame()["event_id"])
    subset = raw[raw["event_id"].isin(eval_ids)]
    return {
        (row.event_id, row.action): float(row.revenue_recovered)
        for row in subset.itertuples()
    }


def _apply_policy_guardrails(df: pd.DataFrame, params: PolicyParams) -> pd.DataFrame:
    """Vectorized guardrail application matching the live apply_guardrails logic,
    parameterized by the candidate policy instead of the hardcoded defaults."""
    allowed = pd.DataFrame(True, index=df.index, columns=ACTIONS)

    retry_blocked = (df["retry_count"] >= params.retry_limit) | (
        df["failure_type"].isin(NON_RETRYABLE_FAILURES)
    )
    allowed.loc[retry_blocked, "RETRY_LATER"] = False

    escalation_threshold = max(params.escalation_min_amount, params.high_value_threshold)
    escalation_blocked = (df["amount"] < escalation_threshold) | (
        df["historical_success_rate"] < params.escalation_min_success_rate
    )
    allowed.loc[escalation_blocked, "HUMAN_ESCALATION"] = False

    return allowed


def simulate_policy(params: PolicyParams) -> dict[str, Any]:
    df = _load_eval_frame()
    probs = _batch_probabilities()
    allowed = _apply_policy_guardrails(df, params)
    outcome_lookup = _outcome_lookup()
    oracle = _oracle_per_event()

    amount = df["amount"].to_numpy()
    expected_net = {}
    for action in ACTIONS:
        rev = probs[action] * amount - ACTION_COSTS[action]
        rev = np.where(allowed[action].to_numpy(), rev, -np.inf)
        expected_net[action] = rev
    stop_net = np.zeros(len(df))

    all_nets = np.column_stack([expected_net[a] for a in ACTIONS] + [stop_net])
    all_names = ACTIONS + ["STOP"]
    best_idx = np.argmax(all_nets, axis=1)
    chosen_action = [all_names[i] for i in best_idx]

    event_ids = df["event_id"].tolist()
    actual_recovered = np.array([
        outcome_lookup.get((eid, act), 0.0) if act != "STOP" else 0.0
        for eid, act in zip(event_ids, chosen_action)
    ])
    intervention_cost = np.array([ACTION_COSTS[act] for act in chosen_action])

    revenue_at_risk = float(amount.sum())
    revenue_recovered = float(actual_recovered.sum())
    total_cost = float(intervention_cost.sum())
    oracle_total = float(oracle.reindex(event_ids).fillna(0.0).sum())

    action_counts = pd.Series(chosen_action).value_counts().to_dict()
    eligibility_counts = {action: int(allowed[action].sum()) for action in ACTIONS}

    return {
        "policy": params.to_dict(),
        "events": int(len(df)),
        "revenue_at_risk": round(revenue_at_risk, 2),
        "revenue_recovered": round(revenue_recovered, 2),
        "recovery_rate": round(revenue_recovered / revenue_at_risk, 6) if revenue_at_risk else 0.0,
        "intervention_cost": round(total_cost, 2),
        "net_recovery": round(revenue_recovered - total_cost, 2),
        "oracle_revenue": round(oracle_total, 2),
        "oracle_capture": round(revenue_recovered / oracle_total, 6) if oracle_total else 0.0,
        "regret": round(oracle_total - revenue_recovered, 2),
        "human_escalations": int(action_counts.get("HUMAN_ESCALATION", 0)),
        "retry_count_total": int(action_counts.get("RETRY_LATER", 0)),
        "stop_count": int(action_counts.get("STOP", 0)),
        "stop_rate": round(action_counts.get("STOP", 0) / len(df), 6) if len(df) else 0.0,
        "action_mix": action_counts,
        "eligibility_counts": eligibility_counts,
        "cooldown_note": (
            "retry_cooldown_hours / reminder_cooldown_hours are sequencer-only settings; the static "
            "evaluation has one decision point per event, so these fields are not applied. "
            ""
        ) if (params.retry_cooldown_hours or params.reminder_cooldown_hours) else None,
    }


def _chosen_actions_for_policy(params: PolicyParams) -> list[str]:
    df = _load_eval_frame()
    probs = _batch_probabilities()
    allowed = _apply_policy_guardrails(df, params)
    nets = []
    for action in ACTIONS:
        value = probs[action] * df["amount"].to_numpy() - ACTION_COSTS[action]
        nets.append(np.where(allowed[action].to_numpy(), value, -np.inf))
    nets.append(np.zeros(len(df)))
    names = ACTIONS + ["STOP"]
    return [names[i] for i in np.argmax(np.column_stack(nets), axis=1)]


def what_if(new_params: PolicyParams) -> dict[str, Any]:
    current = simulate_policy(PolicyParams(name="Current Policy"))
    new = simulate_policy(new_params)
    incremental_recovery = round(new["revenue_recovered"] - current["revenue_recovered"], 2)
    incremental_cost = round(new["intervention_cost"] - current["intervention_cost"], 2)
    changed = int(sum(a != b for a, b in zip(
        _chosen_actions_for_policy(PolicyParams(name="Current Policy")),
        _chosen_actions_for_policy(new_params),
    )))
    eligibility_delta = {
        action: new["eligibility_counts"][action] - current["eligibility_counts"][action]
        for action in ACTIONS
    }
    return {
        "current_policy": current,
        "new_policy": new,
        "incremental_recovery": incremental_recovery,
        "incremental_intervention_cost": incremental_cost,
        "net_incremental_value": round(incremental_recovery - incremental_cost, 2),
        "selected_action_changes": changed,
        "eligibility_delta": eligibility_delta,
        "interpretation": (
            "The policy changes eligibility, but selected actions can remain unchanged when the newly eligible action still has lower expected net value."
            if changed == 0 else "The policy changed the selected action for some held-out events."
        ).strip(),
    }


def compare(policy_a: PolicyParams, policy_b: PolicyParams) -> dict[str, Any]:
    result_a = simulate_policy(policy_a)
    result_b = simulate_policy(policy_b)
    action_changes = int(sum(a != b for a, b in zip(_chosen_actions_for_policy(policy_a), _chosen_actions_for_policy(policy_b))))
    return {
        "policy_a": result_a,
        "policy_b": result_b,
        "selected_action_changes": action_changes,
        "revenue_delta_b_minus_a": round(result_b["revenue_recovered"] - result_a["revenue_recovered"], 2),
        "cost_delta_b_minus_a": round(result_b["intervention_cost"] - result_a["intervention_cost"], 2),
        "oracle_capture_delta_b_minus_a": round(result_b["oracle_capture"] - result_a["oracle_capture"], 6),
        "regret_delta_b_minus_a": round(result_b["regret"] - result_a["regret"], 2),
    }
