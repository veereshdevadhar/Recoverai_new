
from pathlib import Path
import sys
import json
import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    roc_auc_score,
    average_precision_score,
)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "models"
OUT.mkdir(parents=True, exist_ok=True)

ACTIONS = [
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "RETRY_LATER",
    "HUMAN_ESCALATION",
]

TARGET = "recovery_success"

LEAKAGE = {
    "true_recovery_probability",
    "recovery_success",
    "revenue_recovered",
    "simulated_success_probability",
    "event_id",
    "customer_id",
    "merchant_id",
    "timestamp",
    "allowed",
    "policy_reason",
    "payment_status",
    "currency",
    "action",
}

def load_data():
    events = pd.read_csv(RAW / "events.csv", parse_dates=["timestamp"])
    customers = pd.read_csv(RAW / "customers.csv")
    merchants = pd.read_csv(RAW / "merchants.csv")
    outcomes = pd.read_csv(RAW / "recovery_actions.csv")

    df = outcomes.merge(
        events, on="event_id", how="left", validate="many_to_one"
    )
    df = df.merge(
        customers, on="customer_id", how="left",
        validate="many_to_one", suffixes=("", "_customer")
    )
    df = df.merge(
        merchants, on="merchant_id", how="left",
        validate="many_to_one", suffixes=("", "_merchant")
    )

    df["event_hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month
    df["log_amount"] = np.log1p(df["amount"])

    # Resolve customer/merchant duplicate column names robustly.
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
        df["amount"] / df["total_transactions"].clip(lower=1)
    )
    df["high_value"] = (df["amount"] >= 10000).astype(int)
    df["strong_customer_history"] = (
        df["customer_success_rate"] >= 0.90
    ).astype(int)
    df["repeated_failure"] = (df["retry_count"] >= 2).astype(int)

    # V2 deliberately excludes action and action×context features.
    # Each model represents one action, so the event context is identical
    # when we score all four counterfactual actions.
    features = [
        c for c in df.columns
        if c not in LEAKAGE
        and not c.startswith("action__")
    ]

    return df, features


def make_pipeline(X):
    categorical = X.select_dtypes(
        include=["object", "category", "bool"]
    ).columns.tolist()

    numeric = [
        c for c in X.columns
        if c not in categorical
    ]

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="median"))
                ]),
                numeric,
            ),
            (
                "categorical",
                Pipeline([
                    (
                        "imputer",
                        SimpleImputer(strategy="most_frequent")
                    ),
                    (
                        "onehot",
                        OneHotEncoder(
                            handle_unknown="ignore",
                            min_frequency=2
                        )
                    ),
                ]),
                categorical,
            ),
        ]
    )

    model = RandomForestClassifier(
        n_estimators=350,
        max_depth=None,
        min_samples_leaf=8,
        max_features="sqrt",
        random_state=42,
        n_jobs=-1,
    )

    return Pipeline([
        ("preprocessor", preprocessor),
        ("model", model),
    ])


def evaluate(model, X, y, name):
    p = model.predict_proba(X)[:, 1]
    pred = (p >= 0.5).astype(int)

    result = {
        "split": name,
        "rows": int(len(y)),
        "positive_rate": float(y.mean()),
        "accuracy": float(accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, p)),
        "average_precision": float(average_precision_score(y, p)),
    }

    return result


def main():
    print("\n" + "=" * 75)
    print("RECOVERAI V2 — ACTION-SPECIFIC MODELS")
    print("=" * 75)

    df, features = load_data()

    train = df[df["timestamp"] < "2026-07-01"].copy()
    validation = df[
        (df["timestamp"] >= "2026-07-01") &
        (df["timestamp"] < "2026-08-01")
    ].copy()
    test = df[df["timestamp"] >= "2026-08-01"].copy()

    print(f"\nFeatures: {len(features)}")
    print(f"Train rows: {len(train):,}")
    print(f"Validation rows: {len(validation):,}")
    print(f"Held-out August rows: {len(test):,}")

    models = {}
    metrics = {}

    for action in ACTIONS:
        print("\n" + "-" * 75)
        print(f"TRAINING ACTION MODEL: {action}")
        print("-" * 75)

        action_train = train[train["action"] == action]
        action_validation = validation[
            validation["action"] == action
        ]
        action_test = test[test["action"] == action]

        print(f"Train:      {len(action_train):,}")
        print(f"Validation: {len(action_validation):,}")
        print(f"Test:       {len(action_test):,}")

        X_train = action_train[features]
        y_train = action_train[TARGET].astype(int)

        X_val = action_validation[features]
        y_val = action_validation[TARGET].astype(int)

        X_test = action_test[features]
        y_test = action_test[TARGET].astype(int)

        model = make_pipeline(X_train)
        model.fit(X_train, y_train)

        train_metrics = evaluate(
            model, X_train, y_train, "TRAIN"
        )
        val_metrics = evaluate(
            model, X_val, y_val, "VALIDATION"
        )
        test_metrics = evaluate(
            model, X_test, y_test, "HELD-OUT TEST"
        )

        metrics[action] = {
            "train": train_metrics,
            "validation": val_metrics,
            "test": test_metrics,
        }

        for result in [
            train_metrics,
            val_metrics,
            test_metrics,
        ]:
            print(
                f"{result['split']}: "
                f"AUC={result['roc_auc']:.4f} | "
                f"AP={result['average_precision']:.4f} | "
                f"Precision={result['precision']:.4f} | "
                f"Recall={result['recall']:.4f}"
            )

        models[action] = model

    artifact = {
        "models": models,
        "features": features,
        "actions": ACTIONS,
        "metrics": metrics,
        "version": "v2",
    }

    model_path = OUT / "recoverai_v2_action_models.joblib"
    metrics_path = OUT / "recoverai_v2_metrics.json"

    joblib.dump(artifact, model_path)

    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print("\n" + "=" * 75)
    print("V2 TRAINING COMPLETE")
    print("=" * 75)
    print(f"Saved model:   {model_path}")
    print(f"Saved metrics: {metrics_path}")


if __name__ == "__main__":
    main()
