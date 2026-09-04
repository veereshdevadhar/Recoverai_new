from __future__ import annotations

"""Budget-constrained intervention planning and deterministic Revenue Recovery Scenario Simulation.

The planner operates on the same held-out August population and the same
V3-100k action models/guardrails used by production. It never uses realized
outcomes to choose an action. Expected value is probability * amount minus
intervention cost. The oracle is only used for evaluation, never for planning.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
MODEL = PROCESSED / "models" / "recoverai_v3_100k_action_models.joblib"
ACTIONS = ["ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION"]
ALL_ACTIONS = ACTIONS + ["STOP"]
ACTION_COSTS = {
    "ALTERNATIVE_PAYMENT": 20.0,
    "RECOVERY_REMINDER": 10.0,
    "RETRY_LATER": 5.0,
    "HUMAN_ESCALATION": 500.0,
    "STOP": 0.0,
}
NON_RETRYABLE = {"ISSUER_DECLINE", "INSUFFICIENT_BALANCE", "PAYMENT_LIMIT", "EXPIRED_PAYMENT_METHOD"}


def _production_allowed(row: pd.Series, action: str) -> bool:
    if action == "RETRY_LATER":
        return bool(row.retry_count < 3 and row.failure_type not in NON_RETRYABLE)
    if action == "HUMAN_ESCALATION":
        return bool(row.amount >= 25000 and row.customer_success_rate >= 0.85)
    return True


@lru_cache(maxsize=1)
def load_august_population() -> pd.DataFrame:
    events = pd.read_csv(RAW / "events.csv", parse_dates=["timestamp"])
    customers = pd.read_csv(RAW / "customers.csv")
    merchants = pd.read_csv(RAW / "merchants.csv")
    df = events[events.timestamp >= "2026-08-01"].copy()
    df = df.merge(customers, on="customer_id", how="left", suffixes=("", "_customer"))
    df = df.merge(merchants, on="merchant_id", how="left", suffixes=("", "_merchant"))
    cs = "historical_success_rate_customer" if "historical_success_rate_customer" in df else "historical_success_rate"
    ca = "avg_transaction_amount_customer" if "avg_transaction_amount_customer" in df else "avg_transaction_amount"
    ms = "historical_success_rate_merchant" if "historical_success_rate_merchant" in df else None
    df["customer_success_rate"] = df[cs]
    df["customer_avg_transaction_amount"] = df[ca]
    df["merchant_success_rate"] = df[ms] if ms else np.nan
    mf = "historical_failure_rate_merchant" if "historical_failure_rate_merchant" in df else "historical_failure_rate_y" if "historical_failure_rate_y" in df else None
    df["merchant_failure_rate"] = df[mf] if mf else (1.0 - df["merchant_success_rate"])
    return df.reset_index(drop=True)


def _feature_frame(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    d = df.copy()
    d["event_hour"] = d.timestamp.dt.hour
    d["day_of_week"] = d.timestamp.dt.dayofweek
    d["month"] = d.timestamp.dt.month
    d["log_amount"] = np.log1p(d.amount)
    d["historical_failure_rate"] = d["merchant_failure_rate"]
    d["amount_per_customer_transaction"] = d.amount / d.total_transactions.clip(lower=1)
    d["high_value"] = (d.amount >= 10000).astype(int)
    d["strong_customer_history"] = (d.customer_success_rate >= 0.90).astype(int)
    d["repeated_failure"] = (d.retry_count >= 2).astype(int)
    d["failure_nonretryable"] = d.failure_type.isin(NON_RETRYABLE).astype(int)
    d["technical_failure"] = d.failure_type.isin({"TIMEOUT", "NETWORK_ERROR", "BANK_TECHNICAL_ERROR"}).astype(int)
    d["is_checkout"] = (d.event_type == "CHECKOUT_ABANDONMENT").astype(int)
    d["is_subscription"] = (d.event_type == "SUBSCRIPTION_FAILURE").astype(int)
    d["retry_pressure"] = d.retry_count / (1 + d.total_transactions)
    d["value_ratio"] = d.amount / (1 + d.customer_avg_transaction_amount)
    d["customer_merchant_gap"] = d.customer_success_rate - d.merchant_success_rate
    d["high_value_x_history"] = d.high_value * d.customer_success_rate
    d["failure_x_retry"] = d.failure_nonretryable * d.retry_count
    d["engagement_score"] = d.payment_page_reached.astype(int) + d.payment_attempted.astype(int)
    missing = [f for f in features if f not in d.columns]
    if missing:
        raise RuntimeError(f"Planner feature construction failed; missing: {missing}")
    return d[features]


@lru_cache(maxsize=1)
def _artifact() -> dict[str, Any]:
    return joblib.load(MODEL)


def score_population(df: pd.DataFrame | None = None, amount_multiplier: float = 1.0, recovery_multiplier: float = 1.0) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return expected recovery/net value for every eligible action."""
    pop = (load_august_population() if df is None else df).copy()
    pop["amount"] = pop["amount"].astype(float) * float(amount_multiplier)
    a = _artifact()
    X = _feature_frame(pop, a["features"])
    probs = pd.DataFrame(index=pop.index)
    for action in ACTIONS:
        probs[action] = np.clip(a["models"][action].predict_proba(X)[:, 1] * float(recovery_multiplier), 0.0, 1.0)
    expected = pd.DataFrame(index=pop.index)
    allowed = pd.DataFrame(True, index=pop.index, columns=ACTIONS)
    for action in ACTIONS:
        expected[action] = probs[action] * pop.amount - ACTION_COSTS[action]
        allowed[action] = [ _production_allowed(r, action) for _, r in pop.iterrows() ]
        expected.loc[~allowed[action], action] = -np.inf
    expected["STOP"] = 0.0
    choices = expected.idxmax(axis=1)
    rows = pd.DataFrame({"event_id": pop.event_id.astype(str), "amount": pop.amount, "chosen_action": choices}, index=pop.index)
    for action in ACTIONS:
        rows[f"prob_{action}"] = probs[action]
        rows[f"net_{action}"] = expected[action].replace(-np.inf, np.nan)
        rows[f"allowed_{action}"] = allowed[action]
    rows["expected_recovery"] = [0.0 if x == "STOP" else float(probs.loc[i, x] * pop.loc[i, "amount"]) for i, x in zip(rows.index, choices)]
    rows["expected_cost"] = choices.map(ACTION_COSTS).astype(float)
    rows["expected_net"] = rows["expected_recovery"] - rows["expected_cost"]
    return rows, {"population_events": int(len(rows)), "amount_multiplier": float(amount_multiplier), "recovery_multiplier": float(recovery_multiplier)}


def optimize_budget(budget: float, population_limit: int | None = None, amount_multiplier: float = 1.0, recovery_multiplier: float = 1.0) -> dict[str, Any]:
    if budget < 0:
        raise ValueError("Budget must be non-negative")
    rows, meta = score_population(amount_multiplier=amount_multiplier, recovery_multiplier=recovery_multiplier)
    if population_limit:
        rows = rows.head(max(1, min(int(population_limit), len(rows)))).copy()

    # Lagrangian relaxation: maximize expected net value - lambda * spend,
    # then repair any residual budget with the best affordable upgrade. This
    # handles thousands of events without a huge knapsack matrix.
    def choose(lam: float) -> pd.Series:
        vals = pd.DataFrame({a: rows[f"net_{a}"].fillna(-np.inf) - lam * ACTION_COSTS[a] for a in ACTIONS}, index=rows.index)
        vals["STOP"] = 0.0
        return vals.idxmax(axis=1)

    def spend_for(actions: pd.Series) -> float:
        return float(actions.map(ACTION_COSTS).sum())

    if budget == 0:
        chosen = pd.Series("STOP", index=rows.index)
        shadow = 0.0
    else:
        lo, hi = 0.0, 1.0
        while spend_for(choose(hi)) > budget and hi < 1e9:
            hi *= 2
        for _ in range(45):
            mid = (lo + hi) / 2
            if spend_for(choose(mid)) > budget:
                lo = mid
            else:
                hi = mid
        shadow = hi
        chosen = choose(hi)

        # Deterministic budget repair: promote STOP/less-expensive choices
        # using the highest positive net gain per incremental rupee.
        current_spend = spend_for(chosen)
        if current_spend < budget:
            upgrades = []
            for i, current in chosen.items():
                current_val = 0.0 if current == "STOP" else float(rows.loc[i, f"net_{current}"] if pd.notna(rows.loc[i, f"net_{current}"]) else -np.inf)
                for action in ACTIONS:
                    val = rows.loc[i, f"net_{action}"]
                    if pd.isna(val) or action == current:
                        continue
                    cost_delta = ACTION_COSTS[action] - ACTION_COSTS[current]
                    gain = float(val) - current_val
                    if cost_delta > 0 and gain > 0:
                        upgrades.append((gain / cost_delta, gain, cost_delta, i, action))
            for _, gain, cost_delta, i, action in sorted(upgrades, reverse=True):
                if current_spend + cost_delta <= budget and gain > 0:
                    chosen.loc[i] = action
                    current_spend += cost_delta

    rows["optimized_action"] = chosen
    rows["allocated_cost"] = chosen.map(ACTION_COSTS).astype(float)
    rows["allocated_expected_recovery"] = [0.0 if a == "STOP" else float(rows.loc[i, f"prob_{a}"] * rows.loc[i, "amount"]) for i, a in chosen.items()]
    rows["allocated_expected_net"] = rows["allocated_expected_recovery"] - rows["allocated_cost"]
    spend = float(rows.allocated_cost.sum())
    expected_recovery = float(rows.allocated_expected_recovery.sum())
    expected_net = float(rows.allocated_expected_net.sum())
    mix = rows.optimized_action.value_counts().to_dict()
    return {
        "budget": round(float(budget), 2),
        "budget_used": round(spend, 2),
        "budget_remaining": round(max(0.0, float(budget) - spend), 2),
        "budget_utilization": round(spend / budget, 6) if budget else 0.0,
        "expected_recovery": round(expected_recovery, 2),
        "expected_intervention_cost": round(spend, 2),
        "expected_net_value": round(expected_net, 2),
        "shadow_price": round(float(shadow), 6),
        "events_planned": int(len(rows)),
        "action_mix": [{"action": a, "events": int(mix.get(a, 0)), "cost": ACTION_COSTS[a]} for a in ALL_ACTIONS],
        "objective": "sum(expected recovery - action cost) subject to hard production guardrails and total intervention budget",
        "model_version": _artifact().get("version", "V3-100k"),
        "guardrails_source": "same production apply_guardrails policy implemented as eligibility rules",
        "population": meta,
    }


def digital_twin(volume_multiplier: float = 1.0, amount_multiplier: float = 1.0, recovery_multiplier: float = 1.0, budget: float | None = None) -> dict[str, Any]:
    if volume_multiplier <= 0 or amount_multiplier <= 0 or recovery_multiplier <= 0:
        raise ValueError("Scenario multipliers must be positive")
    rows, meta = score_population(amount_multiplier=amount_multiplier, recovery_multiplier=recovery_multiplier)
    # Scale the representative August population to the requested volume.
    base_n = len(rows)
    scenario_events = max(1, int(round(base_n * volume_multiplier)))
    scale = scenario_events / base_n
    if budget is not None:
        # Optimize one representative population with a proportionally scaled
        # budget, then scale the allocation to the requested scenario volume.
        # This keeps the user's budget a true total cap rather than accidentally
        # multiplying the budget when volume_multiplier > 1.
        base_budget = float(budget) / scale
        result = optimize_budget(base_budget, amount_multiplier=amount_multiplier, recovery_multiplier=recovery_multiplier)
        result["events_planned"] = scenario_events
        for item in result["action_mix"]:
            item["events"] = int(round(item["events"] * scale))
            item["cost"] = ACTION_COSTS[item["action"]]
        result["budget_used"] = round(result["budget_used"] * scale, 2)
        result["budget_remaining"] = round(max(0.0, float(budget) - result["budget_used"]), 2)
        result["budget_utilization"] = round(result["budget_used"] / float(budget), 6) if budget else 0.0
        result["expected_recovery"] = round(result["expected_recovery"] * scale, 2)
        result["expected_intervention_cost"] = round(result["expected_intervention_cost"] * scale, 2)
        result["expected_net_value"] = round(result["expected_net_value"] * scale, 2)
        result["budget"] = round(float(budget), 2)
        result["scenario_mode"] = "budget-constrained"
    else:
        expected_recovery = float(rows.expected_recovery.sum()) * scale
        cost = float(rows.expected_cost.sum()) * scale
        result = {
            "events_planned": scenario_events,
            "expected_recovery": round(expected_recovery, 2),
            "expected_intervention_cost": round(cost, 2),
            "expected_net_value": round(expected_recovery - cost, 2),
            "budget": None,
            "budget_used": round(cost, 2),
            "budget_remaining": None,
            "budget_utilization": None,
            "shadow_price": None,
            "action_mix": [{"action": a, "events": int(round((rows.chosen_action == a).sum() * scale)), "cost": ACTION_COSTS[a]} for a in ALL_ACTIONS],
            "objective": "expected net value under production policy",
            "model_version": _artifact().get("version", "V3-100k"),
            "scenario_mode": "unconstrained",
        }
    result["scenario"] = {
        "volume_multiplier": float(volume_multiplier),
        "amount_multiplier": float(amount_multiplier),
        "recovery_multiplier": float(recovery_multiplier),
        "baseline_population_events": base_n,
    }
    result["methodology"] = "Deterministic scenario simulation over the August held-out population using V3-100k action probabilities, production eligibility rules and intervention costs. This is a modelled planning scenario, not realized revenue."
    return result
