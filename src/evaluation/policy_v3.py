
from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MODEL_PATH = (
    ROOT / "data" / "processed" / "models"
    / "recoverai_v2_action_models.joblib"
)
OUT = ROOT / "data" / "processed"

ACTIONS = [
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "RETRY_LATER",
    "HUMAN_ESCALATION",
]

# Synthetic operational assumptions for the prototype.
# These are NOT Razorpay internal costs.
ACTION_COST = {
    "ALTERNATIVE_PAYMENT": 5.0,
    "RECOVERY_REMINDER": 2.0,
    "RETRY_LATER": 1.0,
    "HUMAN_ESCALATION": 250.0,
}

# Prevent tiny expected-value differences from causing unstable
# action switching.
MIN_DECISION_MARGIN = 0.02

# Conservative minimum expected recovery probability.
# Below this, the system can stop rather than forcing an action.
STOP_THRESHOLD = 0.15


def load_data():
    events = pd.read_csv(
        RAW / "events.csv",
        parse_dates=["timestamp"]
    )
    customers = pd.read_csv(RAW / "customers.csv")
    merchants = pd.read_csv(RAW / "merchants.csv")
    outcomes = pd.read_csv(RAW / "recovery_actions.csv")

    df = outcomes.merge(
        events,
        on="event_id",
        how="left",
        validate="many_to_one",
    )
    df = df.merge(
        customers,
        on="customer_id",
        how="left",
        validate="many_to_one",
        suffixes=("", "_customer"),
    )
    df = df.merge(
        merchants,
        on="merchant_id",
        how="left",
        validate="many_to_one",
        suffixes=("", "_merchant"),
    )

    df["event_hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month
    df["log_amount"] = np.log1p(df["amount"])

    if "historical_success_rate_customer" in df:
        customer_success = "historical_success_rate_customer"
    elif "historical_success_rate_x" in df:
        customer_success = "historical_success_rate_x"
    else:
        customer_success = "historical_success_rate"

    if "avg_transaction_amount_customer" in df:
        customer_avg = "avg_transaction_amount_customer"
    elif "avg_transaction_amount_x" in df:
        customer_avg = "avg_transaction_amount_x"
    else:
        customer_avg = "avg_transaction_amount"

    if "historical_success_rate_merchant" in df:
        merchant_success = "historical_success_rate_merchant"
    elif "historical_success_rate_y" in df:
        merchant_success = "historical_success_rate_y"
    else:
        merchant_success = None

    df["customer_success_rate"] = df[customer_success]
    df["customer_avg_transaction_amount"] = df[customer_avg]

    if merchant_success:
        df["merchant_success_rate"] = df[merchant_success]
    else:
        df["merchant_success_rate"] = np.nan

    df["amount_per_customer_transaction"] = (
        df["amount"] /
        df["total_transactions"].clip(lower=1)
    )
    df["high_value"] = (df["amount"] >= 10000).astype(int)
    df["strong_customer_history"] = (
        df["customer_success_rate"] >= 0.90
    ).astype(int)
    df["repeated_failure"] = (df["retry_count"] >= 2).astype(int)

    return df


def explain(row, chosen_action, scores):
    reasons = []

    if chosen_action == "HUMAN_ESCALATION":
        reasons.append("high-value case eligible for human escalation")
    elif chosen_action == "RECOVERY_REMINDER":
        reasons.append("reminder has strong predicted recovery value")
    elif chosen_action == "RETRY_LATER":
        reasons.append("delayed retry has strong predicted recovery value")
    elif chosen_action == "ALTERNATIVE_PAYMENT":
        reasons.append("alternative payment has strongest net expected value")

    if row["retry_count"] >= 2:
        reasons.append("multiple previous attempts reduce retry priority")

    if row["customer_success_rate"] >= 0.90:
        reasons.append("strong customer payment history")

    if row["amount"] >= 10000:
        reasons.append("high-value transaction")

    ordered = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    if len(ordered) >= 2:
        gap = ordered[0][1] - ordered[1][1]
        if gap < max(1.0, row["amount"] * MIN_DECISION_MARGIN):
            reasons.append("decision margin is narrow")

    return "; ".join(dict.fromkeys(reasons))


def main():
    print("\n" + "=" * 78)
    print("RECOVERAI V3 — COST-AWARE POLICY + GUARDRAILS")
    print("=" * 78)

    artifact = joblib.load(MODEL_PATH)
    models = artifact["models"]
    features = artifact["features"]

    df = load_data()

    # August remains completely held out.
    test = df[df["timestamp"] >= "2026-08-01"].copy()

    # One row per event for counterfactual decision-making.
    events = (
        test.sort_values("action")
        .drop_duplicates("event_id")
        .copy()
    )

    X = events[features]

    probability_df = pd.DataFrame(
        {
            action: models[action].predict_proba(X)[:, 1]
            for action in ACTIONS
        },
        index=events.index,
    )

    # Economic objective:
    # expected recovered value = probability × amount
    # expected net value = expected recovered value - action cost
    gross_value = probability_df.multiply(
        events["amount"],
        axis=0,
    )

    net_value = gross_value.copy()

    for action in ACTIONS:
        net_value[action] -= ACTION_COST[action]

    # -----------------------------
    # HARD GUARDRAILS
    # -----------------------------

    # Human escalation is intentionally bounded.
    human_allowed = (
        (events["amount"] >= 10000)
        & (events["customer_success_rate"] >= 0.85)
    )
    net_value.loc[
        ~human_allowed,
        "HUMAN_ESCALATION"
    ] = -np.inf

    # Avoid repeated immediate retries after three failed attempts.
    net_value.loc[
        events["retry_count"] >= 3,
        "RETRY_LATER"
    ] = -np.inf

    chosen_actions = []
    chosen_probabilities = []
    chosen_net_values = []
    explanations = []

    for idx in events.index:
        row_scores = {
            action: float(net_value.loc[idx, action])
            for action in ACTIONS
        }

        finite_scores = {
            k: v for k, v in row_scores.items()
            if np.isfinite(v)
        }

        if not finite_scores:
            chosen = "STOP"
            chosen_probability = 0.0
            chosen_net = 0.0
            explanation = "all recovery actions blocked by guardrails"

        else:
            ranked = sorted(
                finite_scores.items(),
                key=lambda x: x[1],
                reverse=True,
            )

            best_action, best_score = ranked[0]

            # Stopping rule based on the best predicted probability.
            best_probability = float(
                probability_df.loc[idx, best_action]
            )

            if best_probability < STOP_THRESHOLD:
                chosen = "STOP"
                chosen_probability = best_probability
                chosen_net = 0.0
                explanation = (
                    f"best predicted recovery probability "
                    f"{best_probability:.3f} is below "
                    f"stop threshold {STOP_THRESHOLD:.2f}"
                )
            else:
                # If the best and second-best net values are nearly tied,
                # prefer the less operationally expensive action.
                if len(ranked) > 1:
                    second_action, second_score = ranked[1]
                    relative_gap = (
                        best_score - second_score
                    ) / max(abs(best_score), 1.0)

                    if relative_gap < MIN_DECISION_MARGIN:
                        cost_sorted = sorted(
                            ranked[:2],
                            key=lambda x: ACTION_COST[x[0]]
                        )
                        best_action = cost_sorted[0][0]
                        best_score = finite_scores[best_action]

                chosen = best_action
                chosen_probability = float(
                    probability_df.loc[idx, chosen]
                )
                chosen_net = float(best_score)
                explanation = explain(
                    events.loc[idx],
                    chosen,
                    finite_scores,
                )

        chosen_actions.append(chosen)
        chosen_probabilities.append(chosen_probability)
        chosen_net_values.append(chosen_net)
        explanations.append(explanation)

    events["chosen_action"] = chosen_actions
    events["chosen_probability"] = chosen_probabilities
    events["chosen_net_value"] = chosen_net_values
    events["decision_explanation"] = explanations

    # -----------------------------
    # ACTUAL AUGUST OUTCOME
    # -----------------------------

    actual_lookup = test.set_index(
        ["event_id", "action"]
    )

    actual_recovered = []

    for _, row in events.iterrows():
        action = row["chosen_action"]

        if action == "STOP":
            actual_recovered.append(0.0)
            continue

        key = (row["event_id"], action)

        if key in actual_lookup.index:
            outcome = actual_lookup.loc[key]
            actual_recovered.append(
                float(outcome["revenue_recovered"])
            )
        else:
            actual_recovered.append(0.0)

    events["actual_recovered"] = actual_recovered

    revenue_at_risk = events["amount"].sum()
    recovered = events["actual_recovered"].sum()

    print(f"\nEvents: {len(events):,}")
    print(f"Revenue at risk: ₹{revenue_at_risk:,.2f}")
    print(f"Revenue recovered: ₹{recovered:,.2f}")
    print(
        f"Recovery rate: "
        f"{recovered / revenue_at_risk:.2%}"
    )

    print("\nChosen actions:")
    print(events["chosen_action"].value_counts().to_string())

    print("\nActual results by chosen action:")
    selected = events[events["chosen_action"] != "STOP"]

    if len(selected):
        action_results = (
            selected.groupby("chosen_action")
            .agg(
                events=("event_id", "count"),
                success_rate=("recovery_success", "mean"),
                revenue_recovered=("actual_recovered", "sum"),
                avg_amount=("amount", "mean"),
            )
            .sort_values(
                "revenue_recovered",
                ascending=False
            )
        )
        print(action_results.to_string())

    # -----------------------------
    # BASELINE + V1 + V2 COMPARISON
    # -----------------------------

    baseline = test[
        test["action"] == "ALTERNATIVE_PAYMENT"
    ]["revenue_recovered"].sum()

    v1_path = OUT / "v1_august_policy_results.csv"
    v2_path = OUT / "v2_august_policy_results.csv"

    v1 = None
    v2 = None

    if v1_path.exists():
        v1_df = pd.read_csv(v1_path)
        if "actual_recovered" in v1_df:
            v1 = v1_df["actual_recovered"].sum()

    if v2_path.exists():
        v2_df = pd.read_csv(v2_path)
        if "actual_recovered" in v2_df:
            v2 = v2_df["actual_recovered"].sum()

    print("\nComparison:")
    print(f"Always Alternative: ₹{baseline:,.2f}")

    if v1 is not None:
        print(f"RecoverAI V1:       ₹{v1:,.2f}")

    if v2 is not None:
        print(f"RecoverAI V2:       ₹{v2:,.2f}")

    print(f"RecoverAI V3:       ₹{recovered:,.2f}")
    print(
        f"V3 uplift vs baseline: "
        f"{(recovered - baseline) / baseline:.2%}"
    )

    # Oracle.
    oracle = (
        test.groupby("event_id")["revenue_recovered"]
        .max()
        .sum()
    )

    print("\nOracle comparison:")
    print(f"Oracle: ₹{oracle:,.2f}")
    print(f"Oracle capture: {recovered / oracle:.2%}")
    print(f"Policy regret: ₹{oracle - recovered:,.2f}")

    # Audit-friendly summary.
    summary = {
        "version": "v3",
        "events": int(len(events)),
        "revenue_at_risk": float(revenue_at_risk),
        "revenue_recovered": float(recovered),
        "recovery_rate": float(recovered / revenue_at_risk),
        "baseline_recovered": float(baseline),
        "uplift_vs_baseline": float(
            (recovered - baseline) / baseline
        ),
        "oracle_recovered": float(oracle),
        "oracle_capture": float(recovered / oracle),
        "policy_regret": float(oracle - recovered),
        "action_cost_assumptions": ACTION_COST,
        "stop_threshold": STOP_THRESHOLD,
        "min_decision_margin": MIN_DECISION_MARGIN,
        "guardrails": [
            "human escalation requires amount >= 10000 and customer success rate >= 0.85",
            "retry later blocked after retry_count >= 3",
            "STOP when best predicted recovery probability is below threshold",
            "narrow decisions prefer lower operational cost",
        ],
    }

    OUT.mkdir(parents=True, exist_ok=True)

    events.to_csv(
        OUT / "v3_august_policy_results.csv",
        index=False,
    )

    with open(
        OUT / "v3_policy_summary.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(summary, f, indent=2)

    print("\nSaved:")
    print(OUT / "v3_august_policy_results.csv")
    print(OUT / "v3_policy_summary.json")

    print("\n" + "=" * 78)
    print("V3 POLICY EVALUATION COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
