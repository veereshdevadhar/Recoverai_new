from pathlib import Path
import sys
import json
import joblib
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    roc_auc_score,
    average_precision_score,
    confusion_matrix,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.features.v1_features import build_v1_dataset

MODEL_DIR = ROOT / "data" / "processed" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


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
        "confusion_matrix": confusion_matrix(y, pred).tolist(),
    }

    print(f"\n{name}")
    print("-" * 60)
    for k, v in result.items():
        print(f"{k}: {v}")

    return result


def main():
    df, features = build_v1_dataset()

    # STOP is a deterministic fallback, not a learned recovery action.
    df = df[df["action"] != "STOP"].copy()

    # Chronological split — no random split.
    train = df[df["timestamp"] < "2026-07-01"].copy()
    val = df[
        (df["timestamp"] >= "2026-07-01") &
        (df["timestamp"] < "2026-08-01")
    ].copy()
    test = df[df["timestamp"] >= "2026-08-01"].copy()

    X_train, y_train = train[features], train["recovery_success"]
    X_val, y_val = val[features], val["recovery_success"]
    X_test, y_test = test[features], test["recovery_success"]

    categorical = X_train.select_dtypes(
        include=["object", "bool"]
    ).columns.tolist()

    numeric = [
        c for c in features
        if c not in categorical
    ]

    # HistGradientBoosting requires numerical inputs, so one-hot encode
    # categorical variables first.
    preprocessor = ColumnTransformer([
        (
            "numeric",
            Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
            ]),
            numeric,
        ),
        (
            "categorical",
            Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                )),
            ]),
            categorical,
        ),
    ])

    model = Pipeline([
        ("preprocessor", preprocessor),
        (
            "classifier",
            HistGradientBoostingClassifier(
                max_iter=250,
                learning_rate=0.06,
                max_leaf_nodes=31,
                l2_regularization=1.0,
                random_state=42,
            ),
        ),
    ])

    print("Training RecoverAI V1...")
    print(f"Features: {len(features)}")
    print(f"Train rows: {len(train):,}")
    print(f"Validation rows: {len(val):,}")
    print(f"Test rows: {len(test):,}")

    model.fit(X_train, y_train)

    results = [
        evaluate(model, X_train, y_train, "TRAIN"),
        evaluate(model, X_val, y_val, "VALIDATION"),
        evaluate(model, X_test, y_test, "HELD-OUT TEST"),
    ]

    model_path = MODEL_DIR / "recoverai_v1.joblib"
    metrics_path = MODEL_DIR / "recoverai_v1_metrics.json"

    joblib.dump(model, model_path)

    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\nSaved:")
    print(model_path)
    print(metrics_path)


if __name__ == "__main__":
    main()
