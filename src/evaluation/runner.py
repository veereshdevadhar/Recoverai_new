from __future__ import annotations

"""Production-safe held-out evaluation runner.

Recomputes the frozen August evaluation from the trained action-specific models,
then writes the evaluation artifact consumed by the dashboard.  No outcome
column is used as a model feature; outcomes are joined only after the policy
has selected an action.
"""

from pathlib import Path
from typing import Any
import json
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
MODEL = PROCESSED / "models" / "recoverai_v3_100k_action_models.joblib"
ACTIONS = ["ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION"]
COSTS = {"ALTERNATIVE_PAYMENT": 20.0, "RECOVERY_REMINDER": 10.0, "RETRY_LATER": 5.0, "HUMAN_ESCALATION": 500.0}
NON_RETRYABLE = {"ISSUER_DECLINE", "INSUFFICIENT_BALANCE", "PAYMENT_LIMIT", "EXPIRED_PAYMENT_METHOD"}


def _load() -> pd.DataFrame:
    e = pd.read_csv(RAW / "events.csv", parse_dates=["timestamp"])
    c = pd.read_csv(RAW / "customers.csv")
    m = pd.read_csv(RAW / "merchants.csv")
    d = e.merge(c, on="customer_id", validate="many_to_one", suffixes=("", "_customer")).merge(
        m, on="merchant_id", validate="many_to_one", suffixes=("", "_merchant")
    )
    d = d[d.timestamp >= "2026-08-01"].copy()
    cs = "historical_success_rate_customer" if "historical_success_rate_customer" in d else "historical_success_rate"
    ca = "avg_transaction_amount_customer" if "avg_transaction_amount_customer" in d else "avg_transaction_amount"
    ms = "historical_success_rate_merchant" if "historical_success_rate_merchant" in d else None
    mf = "historical_failure_rate_merchant" if "historical_failure_rate_merchant" in d else None
    d["customer_success_rate"] = d[cs]
    d["customer_avg_transaction_amount"] = d[ca]
    d["merchant_success_rate"] = d[ms] if ms else 0.0
    d["merchant_failure_rate"] = d[mf] if mf else (1.0 - d["merchant_success_rate"])
    d["event_hour"] = d.timestamp.dt.hour
    d["day_of_week"] = d.timestamp.dt.dayofweek
    d["month"] = d.timestamp.dt.month
    d["log_amount"] = np.log1p(d.amount)
    d["historical_failure_rate"] = d["merchant_failure_rate"]
    d["amount_per_customer_transaction"] = d.amount / d.total_transactions.clip(lower=1)
    d["high_value"] = (d.amount >= 10000).astype(int)
    d["strong_customer_history"] = (d.customer_success_rate >= .90).astype(int)
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
    return d


def _allowed(row: pd.Series, action: str) -> bool:
    if action == "RETRY_LATER":
        return bool(row.retry_count < 3 and row.failure_type not in NON_RETRYABLE)
    if action == "HUMAN_ESCALATION":
        return bool(row.amount >= 25000 and row.customer_success_rate >= .85)
    return True


def run_heldout_evaluation() -> dict[str, Any]:
    artifact = joblib.load(MODEL)
    df = _load()
    X = df[artifact["features"]]
    probs = {a: artifact["models"][a].predict_proba(X)[:, 1] for a in ACTIONS}

    expected = pd.DataFrame(index=df.index)
    for action in ACTIONS:
        expected[action] = probs[action] * df.amount - COSTS[action]
        allowed = pd.Series([_allowed(row, action) for _, row in df.iterrows()], index=df.index)
        expected.loc[~allowed, action] = -np.inf
    expected["STOP"] = 0.0
    names = ACTIONS + ["STOP"]
    best = np.argmax(expected[names].to_numpy(), axis=1)
    df["chosen_action"] = [names[i] for i in best]
    df["chosen_probability"] = [0.0 if a == "STOP" else probs[a][j] for j, a in enumerate(df.chosen_action)]

    outcomes = pd.read_csv(RAW / "recovery_actions.csv")
    lookup = outcomes.set_index(["event_id", "action"])["revenue_recovered"]
    df["actual_recovered"] = [float(lookup.get((r.event_id, r.chosen_action), 0.0)) for r in df.itertuples()]
    df["intervention_cost"] = df.chosen_action.map(COSTS).fillna(0.0)
    df["net_recovery"] = df.actual_recovered - df.intervention_cost

    # Feasible hindsight oracle: outcome is consulted only after the policy is selected.
    grouped = outcomes[outcomes.event_id.isin(df.event_id)].merge(
        df[["event_id", "amount", "retry_count", "failure_type", "customer_success_rate"]],
        on="event_id", how="inner"
    )
    grouped["feasible"] = [_allowed(row, row.action) for _, row in grouped.iterrows()]
    feasible = grouped[grouped.feasible]
    oracle = feasible.groupby("event_id")["revenue_recovered"].max()
    oracle_action = feasible.loc[feasible.groupby("event_id")["revenue_recovered"].idxmax()].set_index("event_id")["action"]
    df["oracle_recovered"] = df.event_id.map(oracle).fillna(0.0)
    df["oracle_action"] = df.event_id.map(oracle_action).fillna("STOP")

    risk = float(df.amount.sum())
    recovered = float(df.actual_recovered.sum())
    cost = float(df.intervention_cost.sum())
    baseline = float(outcomes[(outcomes.event_id.isin(df.event_id)) & (outcomes.action == "ALTERNATIVE_PAYMENT")]["revenue_recovered"].sum())
    oracle_total = float(df.oracle_recovered.sum())

    out = PROCESSED
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / "v3_100k_august_policy_results.csv"
    df.to_csv(result_path, index=False)
    summary = {
        "dataset_events": 100000,
        "held_out_events": int(len(df)),
        "evaluation_split": "August held-out temporal test",
        "revenue_at_risk": round(risk, 2),
        "revenue_recovered": round(recovered, 2),
        "recovery_rate": round(recovered / risk, 6) if risk else 0.0,
        "intervention_cost": round(cost, 2),
        "net_recovered": round(recovered - cost, 2),
        "baseline_revenue": round(baseline, 2),
        "incremental_recovery": round(recovered - baseline, 2),
        "relative_uplift": round((recovered - baseline) / baseline, 6) if baseline else 0.0,
        "oracle_definition": "hindsight best feasible action under the same production guardrails",
        "oracle_revenue": round(oracle_total, 2),
        "oracle_capture": round(recovered / oracle_total, 6) if oracle_total else 0.0,
        "policy_regret": round(oracle_total - recovered, 2),
        "model": artifact.get("version", "v3-100k"),
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "artifact": str(result_path.name),
    }
    (out / "v3_100k_policy_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
