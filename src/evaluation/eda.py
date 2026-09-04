from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
REPORT = ROOT / "data" / "processed"

REPORT.mkdir(parents=True, exist_ok=True)

events = pd.read_csv(RAW / "events.csv")
customers = pd.read_csv(RAW / "customers.csv")
merchants = pd.read_csv(RAW / "merchants.csv")
actions = pd.read_csv(RAW / "recovery_actions.csv")

events["timestamp"] = pd.to_datetime(events["timestamp"])


def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------
# 1. BASIC DATASET INFORMATION
# ---------------------------------------------------------

section("1. DATASET OVERVIEW")

print("Events:", events.shape)
print("Customers:", customers.shape)
print("Merchants:", merchants.shape)
print("Action simulations:", actions.shape)

print("\nMissing values:")
print(events.isna().sum().sort_values(ascending=False).head(15))


# ---------------------------------------------------------
# 2. EVENT DISTRIBUTION
# ---------------------------------------------------------

section("2. EVENT DISTRIBUTION")

event_distribution = (
    events["event_type"]
    .value_counts()
    .rename_axis("event_type")
    .reset_index(name="count")
)

event_distribution["percentage"] = (
    event_distribution["count"] / len(events) * 100
).round(2)

print(event_distribution.to_string(index=False))

event_distribution.to_csv(
    REPORT / "event_distribution.csv",
    index=False
)


# ---------------------------------------------------------
# 3. FAILURE TYPES
# ---------------------------------------------------------

section("3. FAILURE TYPES")

failure_distribution = (
    events["failure_type"]
    .value_counts(dropna=False)
    .rename_axis("failure_type")
    .reset_index(name="count")
)

failure_distribution["percentage"] = (
    failure_distribution["count"] / len(events) * 100
).round(2)

print(failure_distribution.to_string(index=False))

failure_distribution.to_csv(
    REPORT / "failure_distribution.csv",
    index=False
)


# ---------------------------------------------------------
# 4. TRANSACTION VALUE
# ---------------------------------------------------------

section("4. TRANSACTION VALUE")

print(events["amount"].describe())

print("\nRevenue by event type:")

revenue_by_event = (
    events.groupby("event_type")["amount"]
    .agg(["count", "sum", "mean", "median"])
    .sort_values("sum", ascending=False)
)

print(revenue_by_event.round(2).to_string())

revenue_by_event.to_csv(
    REPORT / "revenue_by_event.csv"
)


# ---------------------------------------------------------
# 5. RECOVERY PROBABILITY
# ---------------------------------------------------------

section("5. HIDDEN RECOVERY PROBABILITY")

print(
    events["true_recovery_probability"]
    .describe()
)

print("\nRecovery probability by event type:")

recovery_by_event = (
    events.groupby("event_type")["true_recovery_probability"]
    .agg(["mean", "median", "min", "max"])
)

print(recovery_by_event.round(4).to_string())

recovery_by_event.to_csv(
    REPORT / "recovery_probability_by_event.csv"
)


# ---------------------------------------------------------
# 6. FAILURE TYPE VS RECOVERY
# ---------------------------------------------------------

section("6. FAILURE TYPE VS RECOVERY")

failure_recovery = (
    events[events["failure_type"].notna()]
    .groupby("failure_type")
    .agg(
        events=("event_id", "count"),
        avg_recovery_probability=(
            "true_recovery_probability",
            "mean"
        ),
        avg_amount=("amount", "mean")
    )
    .sort_values(
        "avg_recovery_probability",
        ascending=False
    )
)

print(failure_recovery.round(4).to_string())

failure_recovery.to_csv(
    REPORT / "failure_recovery_analysis.csv"
)


# ---------------------------------------------------------
# 7. CUSTOMER HISTORY VS RECOVERY
# ---------------------------------------------------------

section("7. CUSTOMER HISTORY VS RECOVERY")

customer_recovery = (
    events.groupby(
        pd.qcut(
            events["customer_id"].map(
                customers.set_index("customer_id")
                ["historical_success_rate"]
            ),
            q=5,
            duplicates="drop"
        )
    )["true_recovery_probability"]
    .agg(["count", "mean"])
)

print(customer_recovery.round(4).to_string())


# ---------------------------------------------------------
# 8. RETRY COUNT VS RECOVERY
# ---------------------------------------------------------

section("8. RETRY COUNT VS RECOVERY")

retry_analysis = (
    events.groupby("retry_count")
    .agg(
        events=("event_id", "count"),
        avg_recovery_probability=(
            "true_recovery_probability",
            "mean"
        ),
        avg_amount=("amount", "mean")
    )
)

print(retry_analysis.round(4).to_string())

retry_analysis.to_csv(
    REPORT / "retry_analysis.csv"
)


# ---------------------------------------------------------
# 9. PAYMENT METHOD VS RECOVERY
# ---------------------------------------------------------

section("9. PAYMENT METHOD VS RECOVERY")

payment_analysis = (
    events.groupby("payment_method")
    .agg(
        events=("event_id", "count"),
        avg_recovery_probability=(
            "true_recovery_probability",
            "mean"
        ),
        avg_amount=("amount", "mean")
    )
    .sort_values(
        "avg_recovery_probability",
        ascending=False
    )
)

print(payment_analysis.round(4).to_string())

payment_analysis.to_csv(
    REPORT / "payment_method_analysis.csv"
)


# ---------------------------------------------------------
# 10. ACTION PERFORMANCE
# ---------------------------------------------------------

section("10. RECOVERY ACTION PERFORMANCE")

action_analysis = (
    actions.groupby("action")
    .agg(
        attempts=("event_id", "count"),
        success_rate=("recovery_success", "mean"),
        total_revenue_recovered=("revenue_recovered", "sum"),
        avg_revenue_recovered=("revenue_recovered", "mean")
    )
    .sort_values(
        "total_revenue_recovered",
        ascending=False
    )
)

action_analysis["success_rate"] *= 100

print(action_analysis.round(2).to_string())

action_analysis.to_csv(
    REPORT / "action_performance.csv"
)


# ---------------------------------------------------------
# 11. POLICY BLOCKS
# ---------------------------------------------------------

section("11. POLICY / GUARDRAIL ANALYSIS")

policy_analysis = (
    actions.groupby(["action", "allowed"])
    .size()
    .reset_index(name="count")
)

print(policy_analysis.to_string(index=False))

policy_analysis.to_csv(
    REPORT / "policy_analysis.csv",
    index=False
)


# ---------------------------------------------------------
# 12. REVENUE AT RISK
# ---------------------------------------------------------

section("12. REVENUE AT RISK")

total_revenue = events["amount"].sum()

expected_recoverable_revenue = (
    events["amount"] *
    events["true_recovery_probability"]
).sum()

print(f"Total event value: ₹{total_revenue:,.2f}")

print(
    f"Expected recoverable value: "
    f"₹{expected_recoverable_revenue:,.2f}"
)

print(
    f"Expected recoverable percentage: "
    f"{expected_recoverable_revenue / total_revenue * 100:.2f}%"
)


# ---------------------------------------------------------
# 13. TEMPORAL DISTRIBUTION
# ---------------------------------------------------------

section("13. TEMPORAL DISTRIBUTION")

events["month"] = events["timestamp"].dt.to_period("M").astype(str)

monthly = (
    events.groupby("month")
    .agg(
        events=("event_id", "count"),
        revenue_at_risk=("amount", "sum"),
        avg_recovery_probability=(
            "true_recovery_probability",
            "mean"
        )
    )
)

print(monthly.round(2).to_string())

monthly.to_csv(
    REPORT / "monthly_analysis.csv"
)


# ---------------------------------------------------------
# 14. LEAKAGE CHECK
# ---------------------------------------------------------

section("14. DATA LEAKAGE CHECK")

forbidden = {
    "recovery_success",
    "revenue_recovered",
    "simulated_success_probability",
    "true_recovery_probability"
}

feature_candidates = set(events.columns)

leaked = feature_candidates.intersection(forbidden)

if leaked:
    print("⚠️ Simulator/target columns detected:")
    print(sorted(leaked))
    print(
        "\nThese columns exist in the raw dataset but MUST NOT "
        "be used as model features."
    )
else:
    print("✅ No forbidden columns found.")


# ---------------------------------------------------------
# COMPLETE
# ---------------------------------------------------------

section("EDA COMPLETE")

print(
    f"""
Reports saved to:

{REPORT}

Next step:
Feature engineering + baseline ML model
"""
)