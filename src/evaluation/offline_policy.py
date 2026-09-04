from pathlib import Path
import sys, joblib, numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.features.feature_builder import build_action_dataset

MODEL = ROOT / "data" / "processed" / "models" / "baseline_logistic_regression.joblib"
ACTIONS = ["RETRY_LATER", "ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "HUMAN_ESCALATION"]

def main():
    df, features = build_action_dataset()
    df = df[df["action"].isin(ACTIONS)].copy()
    test = df[df["timestamp"] >= "2026-08-01"].copy()

    model = joblib.load(MODEL)
    test["predicted_success_probability"] = model.predict_proba(test[features])[:, 1]

    test["allowed_by_policy"] = True
    test.loc[(test["action"] == "RETRY_LATER") & (test["retry_count"] >= 3), "allowed_by_policy"] = False
    test.loc[(test["action"] == "RECOVERY_REMINDER") & (test["retry_count"] >= 3), "allowed_by_policy"] = False
    test.loc[(test["action"] == "HUMAN_ESCALATION") & (test["amount"] < 1000), "allowed_by_policy"] = False

    test["expected_recovered_value"] = test["predicted_success_probability"] * test["amount"]
    test.loc[~test["allowed_by_policy"], "expected_recovered_value"] = -np.inf

    selected = (test.sort_values(["event_id", "expected_recovered_value"], ascending=[True, False])
                .groupby("event_id", as_index=False).first())

    recovered = selected["revenue_recovered"].sum()
    value = selected["amount"].sum()

    print("\nOFFLINE POLICY — HELD-OUT AUGUST")
    print("="*55)
    print(f"Events: {len(selected):,}")
    print(f"Revenue at risk: ₹{value:,.2f}")
    print(f"Simulated revenue recovered: ₹{recovered:,.2f}")
    print(f"Recovery by value: {recovered/value*100:.2f}%")
    print("\nChosen actions:")
    print(selected["action"].value_counts().to_string())

if __name__ == "__main__":
    main()
