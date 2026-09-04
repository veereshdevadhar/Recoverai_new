from pathlib import Path
import sys, json, joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score, average_precision_score, confusion_matrix

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.features.feature_builder import build_action_dataset

MODEL_DIR = ROOT / "data" / "processed" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

def evaluate(model, X, y, name):
    p = model.predict_proba(X)[:, 1]
    pred = (p >= 0.5).astype(int)
    result = {
        "split": name, "rows": int(len(y)), "positive_rate": float(y.mean()),
        "accuracy": float(accuracy_score(y, pred)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, p)),
        "average_precision": float(average_precision_score(y, p)),
        "confusion_matrix": confusion_matrix(y, pred).tolist(),
    }
    print(f"\n{name}\n" + "-"*55)
    for k, v in result.items(): print(f"{k}: {v}")
    return result

def main():
    df, features = build_action_dataset()
    df = df[df["action"] != "STOP"].copy()

    train = df[df["timestamp"] < "2026-07-01"]
    val = df[(df["timestamp"] >= "2026-07-01") & (df["timestamp"] < "2026-08-01")]
    test = df[df["timestamp"] >= "2026-08-01"]

    X_train, y_train = train[features], train["recovery_success"]
    X_val, y_val = val[features], val["recovery_success"]
    X_test, y_test = test[features], test["recovery_success"]

    categorical = X_train.select_dtypes(include=["object", "bool"]).columns.tolist()
    numeric = [c for c in features if c not in categorical]

    prep = ColumnTransformer([
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler())
        ]), numeric),
        ("cat", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore"))
        ]), categorical)
    ])

    model = Pipeline([
        ("prep", prep),
        ("model", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42))
    ])

    print(f"Training rows: {len(train):,}")
    print(f"Validation rows: {len(val):,}")
    print(f"Test rows: {len(test):,}")

    model.fit(X_train, y_train)
    results = [
        evaluate(model, X_train, y_train, "TRAIN"),
        evaluate(model, X_val, y_val, "VALIDATION"),
        evaluate(model, X_test, y_test, "HELD-OUT TEST"),
    ]

    joblib.dump(model, MODEL_DIR / "baseline_logistic_regression.joblib")
    (MODEL_DIR / "baseline_metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nSaved baseline model and metrics.")

if __name__ == "__main__":
    main()
