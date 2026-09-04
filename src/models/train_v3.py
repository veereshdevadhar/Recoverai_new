from pathlib import Path
import json
import sys
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder
from sklearn.impute import SimpleImputer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score, average_precision_score

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "models"
OUT.mkdir(parents=True, exist_ok=True)
ACTIONS = ["ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION"]
LEAKAGE = {"true_recovery_probability","recovery_success","revenue_recovered","simulated_success_probability","event_id","customer_id","merchant_id","timestamp","allowed","policy_reason","payment_status","currency","action"}

def load_data():
    events=pd.read_csv(RAW/"events.csv",parse_dates=["timestamp"])
    customers=pd.read_csv(RAW/"customers.csv")
    merchants=pd.read_csv(RAW/"merchants.csv")
    outcomes=pd.read_csv(RAW/"recovery_actions.csv")
    df=outcomes.merge(events,on="event_id",how="left",validate="many_to_one")
    df=df.merge(customers,on="customer_id",how="left",validate="many_to_one",suffixes=("","_customer"))
    df=df.merge(merchants,on="merchant_id",how="left",validate="many_to_one",suffixes=("","_merchant"))
    df["event_hour"]=df.timestamp.dt.hour; df["day_of_week"]=df.timestamp.dt.dayofweek; df["month"]=df.timestamp.dt.month
    df["log_amount"]=np.log1p(df.amount)
    cs="historical_success_rate_customer" if "historical_success_rate_customer" in df else ("historical_success_rate_x" if "historical_success_rate_x" in df else "historical_success_rate")
    ca="avg_transaction_amount_customer" if "avg_transaction_amount_customer" in df else ("avg_transaction_amount_x" if "avg_transaction_amount_x" in df else "avg_transaction_amount")
    ms="historical_success_rate_merchant" if "historical_success_rate_merchant" in df else ("historical_success_rate_y" if "historical_success_rate_y" in df else None)
    df["customer_success_rate"]=df[cs]; df["customer_avg_transaction_amount"]=df[ca]
    df["merchant_success_rate"]=df[ms] if ms else np.nan
    df["amount_per_customer_transaction"]=df.amount/df.total_transactions.clip(lower=1)
    df["high_value"]=(df.amount>=10000).astype(int)
    df["strong_customer_history"]=(df.customer_success_rate>=.90).astype(int)
    df["repeated_failure"]=(df.retry_count>=2).astype(int)
    # Pre-action interaction features. They are deterministic transformations of context.
    nonretry={"ISSUER_DECLINE","INSUFFICIENT_BALANCE","PAYMENT_LIMIT","EXPIRED_PAYMENT_METHOD"}
    tech={"TIMEOUT","NETWORK_ERROR","BANK_TECHNICAL_ERROR"}
    df["failure_nonretryable"]=df.failure_type.isin(nonretry).astype(int)
    df["technical_failure"]=df.failure_type.isin(tech).astype(int)
    df["is_checkout"]=(df.event_type=="CHECKOUT_ABANDONMENT").astype(int)
    df["is_subscription"]=(df.event_type=="SUBSCRIPTION_FAILURE").astype(int)
    df["retry_pressure"]=df.retry_count/(1+df.total_transactions)
    df["value_ratio"]=df.amount/(1+df.customer_avg_transaction_amount)
    df["customer_merchant_gap"]=df.customer_success_rate-df.merchant_success_rate
    df["high_value_x_history"]=df.high_value*df.customer_success_rate
    df["failure_x_retry"]=df.failure_nonretryable*df.retry_count
    df["engagement_score"]=df.payment_page_reached.astype(int)+df.payment_attempted.astype(int)
    features=[c for c in df.columns if c not in LEAKAGE]
    return df,features

def make_pipeline(X):
    cat=X.select_dtypes(include=["object","category","bool"]).columns.tolist(); num=[c for c in X.columns if c not in cat]
    pre=ColumnTransformer([("numeric",SimpleImputer(strategy="median"),num),("categorical",Pipeline([("imputer",SimpleImputer(strategy="most_frequent")),("ordinal",OrdinalEncoder(handle_unknown="use_encoded_value",unknown_value=-1))]),cat)])
    model=HistGradientBoostingClassifier(max_iter=220,learning_rate=.06,max_leaf_nodes=31,l2_regularization=2.0,random_state=42,categorical_features=[False]*len(num)+[True]*len(cat))
    return Pipeline([("preprocessor",pre),("model",model)])

def evaluate(model,X,y,name):
    p=model.predict_proba(X)[:,1]; pred=(p>=.5).astype(int)
    return {"split":name,"rows":int(len(y)),"positive_rate":float(y.mean()),"accuracy":float(accuracy_score(y,pred)),"precision":float(precision_score(y,pred,zero_division=0)),"recall":float(recall_score(y,pred,zero_division=0)),"roc_auc":float(roc_auc_score(y,p)),"average_precision":float(average_precision_score(y,p))}

def main():
    print("\n"+"="*78); print("RECOVERAI V3 — 100K EVENT ACTION MODELS"); print("="*78)
    df,features=load_data(); train=df[df.timestamp<"2026-07-01"]; val=df[(df.timestamp>="2026-07-01")&(df.timestamp<"2026-08-01")]; test=df[df.timestamp>="2026-08-01"]
    print(f"Events: {df.event_id.nunique():,} | action rows: {len(df):,} | features: {len(features)}")
    models={}; metrics={}
    for action in ACTIONS:
        a_train=train[train.action==action]; a_val=val[val.action==action]; a_test=test[test.action==action]
        print(f"\nTRAINING {action}: {len(a_train):,} train / {len(a_val):,} val / {len(a_test):,} test")
        model=make_pipeline(a_train[features]); model.fit(a_train[features],a_train.recovery_success.astype(int))
        tm=evaluate(model,a_train[features],a_train.recovery_success.astype(int),"TRAIN"); vm=evaluate(model,a_val[features],a_val.recovery_success.astype(int),"VALIDATION"); em=evaluate(model,a_test[features],a_test.recovery_success.astype(int),"HELD-OUT TEST")
        metrics[action]={"train":tm,"validation":vm,"test":em}; models[action]=model
        print(f"AUC train/val/test: {tm['roc_auc']:.4f} / {vm['roc_auc']:.4f} / {em['roc_auc']:.4f} | AP test: {em['average_precision']:.4f}")
    artifact={"models":models,"features":features,"actions":ACTIONS,"metrics":metrics,"version":"v3-100k","dataset_events":int(df.event_id.nunique()),"training_rows":int(len(train))}
    joblib.dump(artifact,OUT/"recoverai_v3_100k_action_models.joblib")
    (OUT/"recoverai_v3_100k_metrics.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
    print("\nSaved V3 100K model and metrics.")
if __name__=="__main__": main()
