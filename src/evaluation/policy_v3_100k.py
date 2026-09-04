from __future__ import annotations

from pathlib import Path
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


def load() -> pd.DataFrame:
    e = pd.read_csv(RAW / "events.csv", parse_dates=["timestamp"])
    c = pd.read_csv(RAW / "customers.csv")
    m = pd.read_csv(RAW / "merchants.csv")
    o = pd.read_csv(RAW / "recovery_actions.csv")
    d = e.merge(c, on="customer_id", validate="many_to_one", suffixes=("", "_customer")).merge(
        m, on="merchant_id", validate="many_to_one", suffixes=("", "_merchant")
    )
    d = d[d.timestamp >= "2026-08-01"].copy()
    cs = "historical_success_rate_customer" if "historical_success_rate_customer" in d else "historical_success_rate_x" if "historical_success_rate_x" in d else "historical_success_rate"
    ca = "avg_transaction_amount_customer" if "avg_transaction_amount_customer" in d else "avg_transaction_amount_x" if "avg_transaction_amount_x" in d else "avg_transaction_amount"
    ms = "historical_success_rate_merchant" if "historical_success_rate_merchant" in d else "historical_success_rate_y" if "historical_success_rate_y" in d else None
    d["customer_success_rate"] = d[cs]
    d["customer_avg_transaction_amount"] = d[ca]
    d["merchant_success_rate"] = d[ms] if ms else 0.0
    mf = "historical_failure_rate_merchant" if "historical_failure_rate_merchant" in d else "historical_failure_rate_y" if "historical_failure_rate_y" in d else None
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


def production_allowed(row: pd.Series, action: str) -> bool:
    if action == "RETRY_LATER":
        return bool(row.retry_count < 3 and row.failure_type not in NON_RETRYABLE)
    if action == "HUMAN_ESCALATION":
        return bool(row.amount >= 25000 and row.customer_success_rate >= .85)
    return True


def main() -> None:
    a = joblib.load(MODEL)
    df = load()
    X = df[a["features"]]
    probs = pd.DataFrame({action: a["models"][action].predict_proba(X)[:, 1] for action in ACTIONS}, index=df.index)
    expected_net = pd.DataFrame(index=df.index)
    for action in ACTIONS:
        expected_net[action] = probs[action] * df.amount - COSTS[action]
        mask = [production_allowed(row, action) for _, row in df.iterrows()]
        expected_net.loc[~pd.Series(mask, index=df.index), action] = -np.inf
    expected_net["STOP"] = 0.0
    df["chosen_action"] = expected_net.idxmax(axis=1)
    df["chosen_probability"] = [0.0 if action == "STOP" else probs.loc[i, action] for i, action in df.chosen_action.items()]

    actions = pd.read_csv(RAW / "recovery_actions.csv")
    lookup = actions.set_index(["event_id", "action"])
    df["actual_recovered"] = [float(lookup.loc[(r.event_id, r.chosen_action), "revenue_recovered"]) for _, r in df.iterrows()]
    df["intervention_cost"] = df.chosen_action.map(COSTS).fillna(0.0)
    df["net_recovery"] = df.actual_recovered - df.intervention_cost

    # Hindsight oracle = best ACTUAL recovery among actions that satisfy the
    # same production guardrails. It is not allowed to choose blocked actions.
    grouped = actions[actions.event_id.isin(df.event_id)].merge(
        df[["event_id", "amount", "retry_count", "failure_type", "customer_success_rate"]], on="event_id", how="inner"
    )
    grouped["feasible"] = [production_allowed(row, row.action) for _, row in grouped.iterrows()]
    feasible = grouped[grouped.feasible]
    oracle = feasible.groupby("event_id")["revenue_recovered"].max()
    oracle_action = feasible.loc[feasible.groupby("event_id")["revenue_recovered"].idxmax()].set_index("event_id")["action"]
    df["oracle_recovered"] = df.event_id.map(oracle).fillna(0.0)
    df["oracle_action"] = df.event_id.map(oracle_action).fillna("STOP")
    df["oracle_net"] = df.oracle_recovered - df.oracle_action.map(COSTS).fillna(0.0)

    risk = float(df.amount.sum())
    recovered = float(df.actual_recovered.sum())
    baseline = float(actions[(actions.event_id.isin(df.event_id)) & (actions.action == "ALTERNATIVE_PAYMENT")]["revenue_recovered"].sum())
    oracle_recovered = float(df.oracle_recovered.sum())
    cost = float(df.intervention_cost.sum())
    net = float(df.net_recovery.sum())
    print("\n" + "=" * 78)
    print("RECOVERAI V3 — 100K EVENT HELD-OUT POLICY")
    print("=" * 78)
    print(f"Events: {len(df):,}")
    print(f"Revenue at risk: ₹{risk:,.2f}")
    print(f"Revenue recovered: ₹{recovered:,.2f}")
    print(f"Recovery rate: {recovered / risk:.2%}")
    print(f"Intervention cost: ₹{cost:,.2f}")
    print(f"Net realized recovery: ₹{net:,.2f}")
    print(f"Baseline always alternative: ₹{baseline:,.2f}")
    print(f"Incremental recovery: ₹{recovered - baseline:,.2f}")
    print(f"Relative uplift: {(recovered - baseline) / baseline:.2%}")
    print(f"Feasible hindsight oracle: ₹{oracle_recovered:,.2f}")
    print(f"Oracle capture: {recovered / oracle_recovered:.2%}")
    print(f"Policy regret: ₹{oracle_recovered - recovered:,.2f}")

    out = PROCESSED
    df.to_csv(out / "v3_100k_august_policy_results.csv", index=False)
    summary = {
        "dataset_events": 100000,
        "held_out_events": int(len(df)),
        "revenue_at_risk": round(risk, 2),
        "revenue_recovered": round(recovered, 2),
        "intervention_cost": round(cost, 2),
        "net_recovered": round(net, 2),
        "baseline_revenue": round(baseline, 2),
        "incremental_recovery": round(recovered - baseline, 2),
        "relative_uplift": round((recovered - baseline) / baseline, 6),
        "oracle_definition": "hindsight best feasible action under the same production guardrails",
        "oracle_revenue": round(oracle_recovered, 2),
        "oracle_capture": round(recovered / oracle_recovered, 6),
        "policy_regret": round(oracle_recovered - recovered, 2),
        "model": "v3-100k",
    }
    (out / "v3_100k_policy_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Saved corrected V3 100K policy artifacts.")


if __name__ == "__main__":
    main()
