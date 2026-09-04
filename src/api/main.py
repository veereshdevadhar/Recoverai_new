from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import json
import uuid
import hmac
import hashlib
import os
import base64
import urllib.parse
import urllib.request

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from src.decision.agent import DecisionAgent
from src.decision.execution import execute_bounded_workflow, execution_records
from src.decision.explanation import build_explanation
from src.decision.attribution import explain_instance, global_importance
from src.decision.sequencer import run_sequence, sequence_records, get_sequence
from src.decision.mandate_sequencer import run_mandate_sequence
from src.decision.b2b_chaser import run_b2b_chase
from src.decision import promise_tracker
from src.risk.risk_engine import assess_risk
from src.evaluation import policy_lab
from src.evaluation import drift as drift_module
from src.evaluation import ledger as ledger_module
from src.evaluation import counterfactual as cf_module
from src.evaluation import planner as planner_module
from src.evaluation import runner as evaluation_runner
from src.db import repository as db_repo
from src import intelligence
from src import integrations
from src.voice import generate_hinglish_script
from src import merchant_simulator as msim
from src import incident_platform

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "data" / "processed" / "models" / "recoverai_v3_100k_action_models.joblib"
PROCESSED = ROOT / "data" / "processed"
RUNTIME = ROOT / "data" / "runtime"
load_dotenv(ROOT / ".env", override=False)
AUDIT_LOG = RUNTIME / "decision_log.jsonl"

ACTIONS = [
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "RETRY_LATER",
    "HUMAN_ESCALATION",
]
ALL_ACTIONS = ACTIONS + ["STOP"]
ACTION_COSTS = {
    "ALTERNATIVE_PAYMENT": 20.0,
    "RECOVERY_REMINDER": 10.0,
    "RETRY_LATER": 5.0,
    "HUMAN_ESCALATION": 500.0,
    "STOP": 0.0,
}
NON_RETRYABLE_FAILURES = {
    "ISSUER_DECLINE",
    "INSUFFICIENT_BALANCE",
    "PAYMENT_LIMIT",
    "EXPIRED_PAYMENT_METHOD",
}
GUARDRAIL_RULES = [
    {"action": "STOP", "rule": "Always allowed as the safe fallback when no recovery action has positive policy value."},
    {"action": "RETRY_LATER", "rule": "Blocked after 3+ retries or for clearly non-retryable failures."},
    {"action": "HUMAN_ESCALATION", "rule": "Allowed only for high-value payments (₹25,000+) with strong customer history (≥85%)."},
    {"action": "RECOVERY_REMINDER", "rule": "Allowed for normal recovery opportunities; especially useful for checkout abandonment."},
    {"action": "ALTERNATIVE_PAYMENT", "rule": "Allowed unless future policy rules explicitly restrict it; checkout abandonment is deprioritized rather than blocked."},
]

app = FastAPI(
    title="RecoverAI Revenue Recovery API",
    version="2.0.0",
    description="Free local action-specific ML decision engine for payment recovery.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_artifact: dict[str, Any] | None = None


class PaymentEvent(BaseModel):
    event_id: str | None = None
    email: str | None = None
    phone: str | None = None
    currency: str = "INR"
    event_type: str = "PAYMENT_FAILURE"
    amount: float = Field(..., gt=0)
    payment_method: str = "UPI"
    device_type: str = "MOBILE"
    failure_type: str | None = "TIMEOUT"
    retry_count: int = Field(0, ge=0, le=10)
    previous_attempt_hours: float = Field(0.0, ge=0)
    checkout_duration_seconds: float = Field(60.0, ge=0)
    payment_page_reached: int = Field(1, ge=0, le=1)
    payment_attempted: int = Field(1, ge=0, le=1)
    subscription_age_days: float = Field(0.0, ge=0)
    successful_cycles: int = Field(0, ge=0)
    failed_cycles: int = Field(0, ge=0)
    customer_tenure_days: float = Field(365.0, ge=0)
    total_transactions: int = Field(10, ge=1)
    successful_transactions: int = Field(8, ge=0)
    failed_transactions: int = Field(2, ge=0)
    historical_success_rate: float = Field(0.8, ge=0, le=1)
    avg_transaction_amount: float = Field(5000.0, gt=0)
    previous_recovery_success_rate: float = Field(0.5, ge=0, le=1)
    days_since_last_success: float = Field(7.0, ge=0)
    preferred_payment_method: str = "UPI"
    merchant_category: str = "E_COMMERCE"
    merchant_size: str = "MEDIUM"
    merchant_avg_transaction_amount: float = Field(5000.0, gt=0)
    merchant_success_rate: float | None = Field(None, ge=0, le=1)
    merchant_failure_rate: float | None = Field(None, ge=0, le=1)
    event_hour: int | None = Field(None, ge=0, le=23)
    day_of_week: int | None = Field(None, ge=0, le=6)
    month: int | None = Field(None, ge=1, le=12)
    # Optional B2B receivables fields — only meaningful for event_type
    # INVOICE_OVERDUE; ignored by build_features (which only reads the
    # fixed 48-column model feature list), so they are additive and safe.
    days_overdue: float = Field(0.0, ge=0)
    invoice_number: str | None = None
    customer_display_name: str | None = None


def artifact() -> dict[str, Any]:
    global _artifact
    if _artifact is None:
        if not MODEL_PATH.exists():
            raise RuntimeError(f"Model not found: {MODEL_PATH}")
        _artifact = joblib.load(MODEL_PATH)
    return _artifact


def build_features(payload: PaymentEvent) -> pd.DataFrame:
    now = datetime.now()
    d = payload.model_dump()
    d["failure_type"] = d["failure_type"] or "NONE"
    d["merchant_success_rate"] = (
        d["merchant_success_rate"]
        if d["merchant_success_rate"] is not None
        else max(0.0, 1.0 - (d["merchant_failure_rate"] or 0.10))
    )
    d["merchant_failure_rate"] = (
        d["merchant_failure_rate"]
        if d["merchant_failure_rate"] is not None
        else max(0.0, 1.0 - d["merchant_success_rate"])
    )
    d["avg_transaction_amount_merchant"] = d.pop("merchant_avg_transaction_amount")
    d["historical_success_rate_merchant"] = d["merchant_success_rate"]
    d["historical_failure_rate"] = d["merchant_failure_rate"]
    d["event_hour"] = now.hour if d["event_hour"] is None else d["event_hour"]
    d["day_of_week"] = now.weekday() if d["day_of_week"] is None else d["day_of_week"]
    d["month"] = now.month if d["month"] is None else d["month"]
    d["log_amount"] = float(np.log1p(d["amount"]))
    d["customer_success_rate"] = d["historical_success_rate"]
    d["customer_avg_transaction_amount"] = d["avg_transaction_amount"]
    d["amount_per_customer_transaction"] = d["amount"] / max(1, d["total_transactions"])
    d["high_value"] = int(d["amount"] >= 10000)
    d["strong_customer_history"] = int(d["customer_success_rate"] >= 0.90)
    d["repeated_failure"] = int(d["retry_count"] >= 2)
    non_retryable = {"ISSUER_DECLINE", "INSUFFICIENT_BALANCE", "PAYMENT_LIMIT", "EXPIRED_PAYMENT_METHOD"}
    technical = {"TIMEOUT", "NETWORK_ERROR", "BANK_TECHNICAL_ERROR"}
    d["failure_nonretryable"] = int(d["failure_type"] in non_retryable)
    d["technical_failure"] = int(d["failure_type"] in technical)
    d["is_checkout"] = int(d["event_type"] == "CHECKOUT_ABANDONMENT")
    d["is_subscription"] = int(d["event_type"] == "SUBSCRIPTION_FAILURE")
    d["retry_pressure"] = d["retry_count"] / (1 + d["total_transactions"])
    d["value_ratio"] = d["amount"] / (1 + d["customer_avg_transaction_amount"])
    d["customer_merchant_gap"] = d["customer_success_rate"] - d["merchant_success_rate"]
    d["high_value_x_history"] = d["high_value"] * d["customer_success_rate"]
    d["failure_x_retry"] = d["failure_nonretryable"] * d["retry_count"]
    d["engagement_score"] = int(bool(d["payment_page_reached"])) + int(bool(d["payment_attempted"]))

    features = artifact()["features"]
    frame = pd.DataFrame([d])
    missing = [c for c in features if c not in frame.columns]
    if missing:
        raise RuntimeError(f"Feature construction failed; missing: {missing}")
    return frame[features]


def apply_guardrails(payload: PaymentEvent) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for action in ALL_ACTIONS:
        allowed = True
        reasons: list[str] = []
        severity = "info"
        if action == "RETRY_LATER":
            if payload.retry_count >= 3:
                allowed = False
                severity = "block"
                reasons.append("Retry limit reached (3 or more previous retries).")
            if payload.failure_type in NON_RETRYABLE_FAILURES:
                allowed = False
                severity = "block"
                reasons.append(f"{payload.failure_type.replace('_', ' ').title()} is treated as non-retryable.")
        elif action == "HUMAN_ESCALATION":
            if payload.amount < 25000:
                allowed = False
                severity = "block"
                reasons.append("Human escalation is reserved for payments of ₹25,000 or more.")
            if payload.historical_success_rate < 0.85:
                allowed = False
                severity = "block"
                reasons.append("Customer history is below the 85% success threshold.")
        elif action == "RECOVERY_REMINDER" and payload.event_type == "CHECKOUT_ABANDONMENT":
            reasons.append("Preferred recovery path for checkout abandonment.")
            severity = "prefer"
        elif action == "ALTERNATIVE_PAYMENT" and payload.event_type == "CHECKOUT_ABANDONMENT":
            reasons.append("Allowed, but reminder is the more natural first response to abandonment.")
            severity = "prefer"
        result[action] = {"allowed": allowed, "reasons": reasons, "severity": severity}
    return result


def explain(action: str, p: PaymentEvent, guardrail: dict[str, Any], scores: dict[str, float]) -> str:
    if action == "STOP":
        return "No allowed recovery action produced a positive expected net value, so the engine chooses the safe STOP fallback rather than spending money on a low-value intervention."
    reasons: list[str] = []
    if p.historical_success_rate >= 0.85:
        reasons.append("strong customer payment history")
    if p.retry_count == 0:
        reasons.append("this is the first retry opportunity")
    elif p.retry_count >= 2:
        reasons.append("the payment has already failed multiple times")
    if p.failure_type in {"TIMEOUT", "NETWORK_ERROR", "BANK_TECHNICAL_ERROR"}:
        reasons.append("the failure type is relatively recoverable")
    if p.amount >= 25000:
        reasons.append("the transaction is high value")
    if guardrail.get("reasons"):
        reasons.extend(guardrail["reasons"])
    reasons.append(f"{action.replace('_', ' ').lower()} has the highest allowed expected net value")
    return "Decision based on " + ", ".join(reasons) + "."


def score_event(payload: PaymentEvent, guardrail_engine: Any = None, persist: bool = True, diagnostics: bool = True) -> dict[str, Any]:
    # A successful payment is already recovered. It must never be sent through
    # failure-trained action models or become a synthetic recovery opportunity.
    if payload.event_type == "PAYMENT_SUCCESS":
        now = datetime.now(timezone.utc).isoformat()
        decision_id = f"DEC-{uuid.uuid4().hex[:10].upper()}"
        guards = {a: {"allowed": a == "STOP", "reasons": ([] if a == "STOP" else ["Payment is already successful; no recovery intervention is required."]), "severity": "info" if a == "STOP" else "block"} for a in ALL_ACTIONS}
        result = {
            "decision_id": decision_id, "recommended_action": "STOP", "decision_confidence": 1.0,
            "model_version": artifact().get("version", "V3-100k"), "evaluated_at": now,
            "probabilities": {a: None for a in ACTIONS}, "expected_revenue": {a: None for a in ACTIONS},
            "action_costs": {a: ACTION_COSTS.get(a, 0.0) for a in ACTIONS}, "guardrails": guards,
            "reason": "Payment already succeeded; recovery is unnecessary and no further customer intervention is permitted.",
            "agent": {"trace": [{"step": "CONTEXT", "label": "Read payment, customer and merchant context", "status": "completed", "details": {"event_type": "PAYMENT_SUCCESS"}}, {"step": "GUARDRAILS", "label": "Block recovery after success", "status": "completed", "details": {"all_recovery_actions_blocked": True}}, {"step": "DECISION", "label": "Choose STOP", "status": "completed", "details": {"reason": "Already successful"}}]},
            "feature_attribution": None, "counterfactual": {"status": "NOT_APPLICABLE", "reason": "Payment already succeeded."},
        }
        if persist:
            write_audit(payload, result)
        return result
    agent = DecisionAgent(actions=ACTIONS, all_actions=ALL_ACTIONS, action_costs=ACTION_COSTS)
    result = agent.decide(
        payload=payload,
        artifact_loader=artifact,
        feature_builder=build_features,
        guardrail_engine=guardrail_engine or apply_guardrails,
        explainer=explain,
    )
    result["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    result["agent"]["trace"].append({
        "step": "AUDIT",
        "label": "Persist the decision trace",
        "status": "completed",
        "details": {"audit_store": "data/runtime/decision_log.jsonl"},
    })
    if diagnostics:
        result["explanation"] = build_explanation(result, payload)
        result["counterfactual"] = cf_module.build_counterfactual(result, oracle=None)

        chosen = result["recommended_action"]
        if chosen in ACTIONS:
            try:
                X = build_features(payload)
                result["feature_attribution"] = explain_instance(artifact()["models"][chosen], X, artifact()["features"])
            except Exception:
                result["feature_attribution"] = None
        else:
            result["feature_attribution"] = None
    else:
        result["explanation"] = None
        result["counterfactual"] = {"status": "NOT_REQUESTED"}
        result["feature_attribution"] = None

    if persist:
        write_audit(payload, result)
    return result

def write_audit(payload: PaymentEvent, result: dict[str, Any]) -> None:
    record = {
        "decision_id": result["decision_id"],
        "timestamp": result["evaluated_at"],
        "amount": payload.amount,
        "event_type": payload.event_type,
        "failure_type": payload.failure_type,
        "retry_count": payload.retry_count,
        "customer_success_rate": payload.historical_success_rate,
        "recommended_action": result["recommended_action"],
        "confidence": result["decision_confidence"],
        "model_version": result["model_version"],
        "guardrail_blocked_actions": [k for k, v in result["guardrails"].items() if not v["allowed"]],
        "feature_attribution": result.get("feature_attribution"),
    }
    db_repo.insert_decision(record)


def dashboard_metrics() -> dict[str, Any]:
    summary_path = PROCESSED / "v3_100k_august_policy_results.csv"
    df = pd.read_csv(summary_path)
    revenue_at_risk = float(df["amount"].sum())
    recovered = float(df["actual_recovered"].sum())
    cost = float(df["intervention_cost"].sum()) if "intervention_cost" in df.columns else 0.0
    net_recovered = float(df["net_recovery"].sum()) if "net_recovery" in df.columns else recovered - cost
    raw = pd.read_csv(ROOT / "data" / "raw" / "recovery_actions.csv")
    eval_ids = set(df["event_id"])
    baseline = float(raw[(raw["event_id"].isin(eval_ids)) & (raw["action"] == "ALTERNATIVE_PAYMENT")]["revenue_recovered"].sum())
    # The V3 evaluator writes oracle_recovered after applying the exact same
    # production eligibility rules. Never fall back to an unrestricted oracle.
    oracle = float(df["oracle_recovered"].sum()) if "oracle_recovered" in df.columns else 0.0
    return {
        "dataset_events": int(raw["event_id"].nunique()),
        "events": int(len(df)),
        "revenue_at_risk": round(revenue_at_risk, 2),
        "revenue_recovered": round(recovered, 2),
        "recovery_rate": round(recovered / revenue_at_risk, 6) if revenue_at_risk else 0,
        "intervention_cost": round(cost, 2),
        "net_recovered": round(net_recovered, 2),
        "baseline_revenue": round(baseline, 2),
        "incremental_recovery": round(recovered - baseline, 2),
        "relative_uplift": round((recovered - baseline) / baseline, 6) if baseline else 0,
        "oracle_revenue": round(oracle, 2),
        "oracle_capture": round(recovered / oracle, 6) if oracle else 0,
        "policy_regret": round(oracle - recovered, 2),
        "evaluation_split": "August held-out temporal test",
    }


def dashboard_analysis() -> dict[str, Any]:
    df = pd.read_csv(PROCESSED / "v3_100k_august_policy_results.csv")
    action = df.groupby("chosen_action").agg(events=("event_id", "count"), recovered=("actual_recovered", "sum")).reset_index()
    event = df.groupby("event_type").agg(events=("event_id", "count"), recovered=("actual_recovered", "sum")).reset_index()
    failure = df.assign(failure_type=df["failure_type"].fillna("NONE")).groupby("failure_type").agg(events=("event_id", "count"), recovered=("actual_recovered", "sum")).reset_index()
    retry = df.groupby("retry_count").agg(events=("event_id", "count"), recovered=("actual_recovered", "sum")).reset_index()
    result = {
        "actions": action.to_dict(orient="records"),
        "event_types": event.to_dict(orient="records"),
        "failure_types": failure.to_dict(orient="records"),
        "retry_counts": retry.to_dict(orient="records"),
    }
    # Counterfactual policy-regret artifacts are generated offline from the same
    # held-out August environment and are exposed for judge-facing inspection.
    for name, key in [
        ("regret_by_event_type", "v4_regret_by_event_type.csv"),
        ("regret_by_failure_type", "v4_regret_by_failure_type.csv"),
        ("regret_by_retry_count", "v4_regret_by_retry_count.csv"),
        ("regret_by_value_band", "v4_regret_by_value_band.csv"),
    ]:
        path = PROCESSED / key
        if path.exists():
            result[name] = pd.read_csv(path).replace({np.nan: None}).to_dict(orient="records")
    summary_path = PROCESSED / "v4_policy_regret_summary.csv"
    if summary_path.exists():
        result["policy_regret_summary"] = pd.read_csv(summary_path).replace({np.nan: None}).to_dict(orient="records")
    return result


def model_card() -> dict[str, Any]:
    metrics_path = PROCESSED / "models" / "recoverai_v3_100k_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    return {
        "champion": artifact().get("version", "V3-100k"),
        "strategy": "RecoverAI Decision Agent orchestrates action-specific classifiers, expected monetary value, hard guardrails, confidence and audit logging.",
        "split": "January-June train, July validation, August held-out test",
        "leakage_protected": True,
        "forbidden_features": ["true_recovery_probability", "simulated_success_probability", "recovery_success", "revenue_recovered", "post-action information"],
        "test_metrics": {a: round(metrics.get(a, {}).get("test", {}).get("roc_auc", 0), 4) for a in ACTIONS},
        "business_result": dashboard_metrics(),
        "dataset_events": int(pd.read_csv(ROOT / "data" / "raw" / "events.csv", usecols=["event_id"]).event_id.nunique()),
        "model_improvement": {
            "control": "V2 on the same 100K-event benchmark",
            "revenue_recovered_gain": 1043186.69,
            "uplift_gain_percentage_points": 2.11,
            "oracle_capture_gain_percentage_points": 1.41,
        },
        "data_note": "Synthetic evaluation data; not Razorpay production data.",
    }


def audit_records(limit: int = 50) -> list[dict[str, Any]]:
    return db_repo.get_decisions(limit)


@app.get("/health")
def health() -> dict[str, Any]:
    a = artifact()
    return {"status": "ok", "service": "RecoverAI", "model": a.get("version", "V3-100k"), "model_file": MODEL_PATH.name}


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    return dashboard_metrics()


@app.get("/api/analysis")
def analysis() -> dict[str, Any]:
    return dashboard_analysis()


@app.get("/api/model-card")
def get_model_card() -> dict[str, Any]:
    return model_card()


@app.get("/api/guardrails")
def guardrails() -> dict[str, Any]:
    return {"rules": GUARDRAIL_RULES, "non_retryable_failures": sorted(NON_RETRYABLE_FAILURES)}


@app.get("/api/audit-log")
def get_audit_log(limit: int = 50) -> dict[str, Any]:
    return {"records": audit_records(limit)}


@app.get("/api/decision-agent")
def decision_agent_info() -> dict[str, Any]:
    return {
        "name": "RecoverAI Decision Agent",
        "version": "1.0",
        "mode": "deterministic_ml_policy",
        "purpose": "Choose the best allowed recovery action for each payment event.",
        "stages": [
            {"id": "CONTEXT", "label": "Read payment, customer and merchant context"},
            {"id": "FEATURES", "label": "Build leakage-safe pre-action features"},
            {"id": "ML_SCORING", "label": "Score each recovery action"},
            {"id": "VALUE_SCORING", "label": "Convert probability to expected net value"},
            {"id": "GUARDRAILS", "label": "Block policy-ineligible actions"},
            {"id": "DECISION", "label": "Rank allowed actions and choose one"},
            {"id": "AUDIT", "label": "Persist the decision trace"},
            {"id": "EXECUTION", "label": "Execute the selected action in a bounded simulation"},
        ],
        "model_version": artifact().get("version", "V3-100k"),
        "external_llm_required": False,
    }


@app.post("/predict")
def predict(payload: PaymentEvent) -> dict[str, Any]:
    try:
        return score_event(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/execute-recovery")
def execute_recovery(payload: PaymentEvent) -> dict[str, Any]:
    """Run the full bounded workflow: decide, re-check policy, execute and audit."""
    try:
        decision = score_event(payload)
        execution = execute_bounded_workflow(payload, decision, apply_guardrails)
        return {"decision": decision, "execution": execution}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ExecuteDecisionIn(BaseModel):
    payload: PaymentEvent
    decision: dict[str, Any]
    live: bool = False
    channel: str = Field("auto", pattern="^(auto|email|sms|voice)$")
    live_confirmation: bool = False
    # Optional operator-selected action used for integration testing. It never
    # bypasses the decision guardrails; the selected action must be allowed for
    # this exact payment context.
    selected_action: str | None = Field(None, pattern="^(STOP|ALTERNATIVE_PAYMENT|RECOVERY_REMINDER|RETRY_LATER|HUMAN_ESCALATION)$")


@app.post("/execute-decision")
def execute_decision(body: ExecuteDecisionIn) -> dict[str, Any]:
    """Execute a previously returned decision after a fresh guardrail check.

    Live mode is explicit and opt-in; otherwise the original deterministic
    bounded simulation is preserved.
    """
    try:
        if body.live and not body.live_confirmation:
            raise HTTPException(status_code=400, detail="Live execution requires explicit confirmation because it may contact customers or create a real payment link.")
        if body.live and not integrations.live_enabled():
            raise HTTPException(status_code=400, detail="Live execution is disabled. Set RECOVERAI_LIVE_EXECUTION=1 and configure the required provider credentials.")
        return execute_bounded_workflow(
            body.payload, body.decision, apply_guardrails,
            live=body.live, channel=body.channel, selected_action=body.selected_action
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/execution-log")
def get_execution_log(limit: int = 50) -> dict[str, Any]:
    return {"records": execution_records(limit)}


# ---------------------------------------------------------------------------
# Merchant Commerce Simulator ("NovaCart") — additive, isolated demo layer.
# Reuses score_event / apply_guardrails / execute_bounded_workflow directly;
# never sets live=True. See src/merchant_simulator.py for the safety note.
# ---------------------------------------------------------------------------

@app.get("/api/merchant-sim/dashboard")
def msim_dashboard() -> dict[str, Any]:
    return msim.dashboard()


@app.post("/api/merchant-sim/reset")
def msim_reset() -> dict[str, Any]:
    return msim.reset()


@app.get("/api/merchant-sim/customers")
def msim_customers() -> dict[str, Any]:
    return {"customers": msim.list_customers()}


@app.get("/api/merchant-sim/customers/{customer_id}")
def msim_customer(customer_id: str) -> dict[str, Any]:
    row = msim.get_customer_row(customer_id)
    if row is None:
        raise HTTPException(404, "Unknown customer")
    return {"customer": {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in row.items()}, "orders": msim.customer_orders(customer_id)}


@app.get("/api/merchant-sim/products")
def msim_products() -> dict[str, Any]:
    return {"products": msim.list_products()}


@app.get("/api/merchant-sim/orders")
def msim_orders(limit: int = 50) -> dict[str, Any]:
    return {"orders": msim.list_orders(limit)}


@app.get("/api/merchant-sim/orders/{order_id}")
def msim_order(order_id: str) -> dict[str, Any]:
    order = msim.get_order(order_id)
    if order is None:
        raise HTTPException(404, "Unknown order")
    return order


@app.get("/api/merchant-sim/timeline")
def msim_timeline(limit: int = 80) -> dict[str, Any]:
    return {"events": msim.get_timeline(limit)}


class MSimPurchaseIn(BaseModel):
    customer_id: str
    product_id: str
    method: str | None = None
    force_fail: bool = False


@app.post("/api/merchant-sim/purchase")
def msim_purchase(body: MSimPurchaseIn) -> dict[str, Any]:
    try:
        return msim.purchase(body.customer_id, body.product_id, method=body.method, force_fail=body.force_fail)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MSimAbandonIn(BaseModel):
    customer_id: str
    product_id: str


@app.post("/api/merchant-sim/abandon")
def msim_abandon(body: MSimAbandonIn) -> dict[str, Any]:
    try:
        return msim.abandon_checkout(body.customer_id, body.product_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MSimResubmitIn(BaseModel):
    order_id: str


@app.post("/api/merchant-sim/resubmit-event")
def msim_resubmit(body: MSimResubmitIn) -> dict[str, Any]:
    try:
        return msim.resubmit_failure_event(body.order_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class MSimIncidentIn(BaseModel):
    incident: str | None = None


@app.post("/api/merchant-sim/incident")
def msim_incident(body: MSimIncidentIn) -> dict[str, Any]:
    try:
        return msim.inject_incident(body.incident)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/merchant-sim/incidents")
def msim_incidents() -> dict[str, Any]:
    return {"incidents": msim.INCIDENTS, "active": msim.STATE.active_incident}


@app.post("/api/merchant-sim/tick")
def msim_tick(speed: int = 1, generation: int | None = None) -> dict[str, Any]:
    return msim.tick(speed, generation=generation)


@app.post("/api/merchant-sim/scenario/upi-failure-recovery")
def msim_scenario_upi() -> dict[str, Any]:
    return msim.run_upi_failure_scenario()


class VoiceScriptIn(BaseModel):
    action: str
    amount: float = Field(..., gt=0)
    event_type: str = "PAYMENT_FAILURE"
    failure_type: str | None = None
    event_id: str | None = None


@app.post("/api/voice/script")
def voice_script(body: VoiceScriptIn) -> dict[str, Any]:
    """Preview the Hinglish recovery script for a given action/context.

    This does not place a call or contact anyone — it deterministically
    composes the script the voice channel would use, for review or for
    client-side browser text-to-speech playback.
    """
    return generate_hinglish_script(
        action=body.action,
        amount=body.amount,
        event_type=body.event_type,
        failure_type=body.failure_type,
        seed=body.event_id,
    )


# ---------------------------------------------------------------------------
# FEATURE 1 — Counterfactual Recovery Simulator
# ---------------------------------------------------------------------------

@app.get("/api/counterfactual/sample-events")
def counterfactual_sample_events(n: int = 12) -> dict[str, Any]:
    return {"events": cf_module.sample_event_ids(n)}


@app.get("/api/counterfactual/{event_id}")
def counterfactual_for_event(event_id: str) -> dict[str, Any]:
    payload_dict = cf_module.payload_dict_for_event(event_id)
    if payload_dict is None:
        raise HTTPException(status_code=404, detail=f"Unknown evaluation event_id: {event_id}")
    payload = PaymentEvent(**payload_dict)
    decision = score_event(payload, persist=False)
    oracle = cf_module.oracle_for_event(event_id)
    result = cf_module.build_counterfactual(decision, oracle)
    result["event_id"] = event_id
    result["decision"] = decision
    return result


# ---------------------------------------------------------------------------
# FEATURE 2 — Adaptive Multi-Step Recovery Sequencer
# ---------------------------------------------------------------------------

@app.post("/api/sequence/run")
def sequence_run(payload: PaymentEvent) -> dict[str, Any]:
    try:
        return run_sequence(
            payload_cls=PaymentEvent,
            initial_payload=payload,
            score_event=lambda p, guardrail_engine: score_event(p, guardrail_engine=guardrail_engine),
            base_guardrail_engine=apply_guardrails,
            execute_bounded_workflow=execute_bounded_workflow,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/sequence/{sequence_id}")
def sequence_get(sequence_id: str) -> dict[str, Any]:
    record = get_sequence(sequence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sequence not found.")
    return record


@app.get("/api/sequence-log")
def sequence_log(limit: int = 20) -> dict[str, Any]:
    return {"records": sequence_records(limit)}


# ---------------------------------------------------------------------------
# UPI Mandate Retry Sequencer (domain-specific: e-mandate / UPI Autopay)
# ---------------------------------------------------------------------------

@app.post("/api/mandate/run")
def mandate_run(payload: PaymentEvent) -> dict[str, Any]:
    mandate_payload = payload.model_copy(update={
        "event_type": "MANDATE_FAILURE",
        "payment_method": "UPI_AUTOPAY",
        "preferred_payment_method": "UPI_AUTOPAY",
    })
    try:
        return run_mandate_sequence(
            initial_payload=mandate_payload,
            score_event=lambda p, guardrail_engine: score_event(p, guardrail_engine=guardrail_engine),
            base_guardrail_engine=apply_guardrails,
            execute_bounded_workflow=execute_bounded_workflow,
            payload_cls=PaymentEvent,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/mandate/{mandate_sequence_id}")
def mandate_get(mandate_sequence_id: str) -> dict[str, Any]:
    record = db_repo.get_mandate_sequence(mandate_sequence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Mandate sequence not found.")
    return record


@app.get("/api/mandate-log")
def mandate_log(limit: int = 20) -> dict[str, Any]:
    return {"records": db_repo.list_mandate_sequences(limit)}


# ---------------------------------------------------------------------------
# B2B Receivables Chaser (overdue invoice pathway)
# ---------------------------------------------------------------------------

class InvoiceEvent(BaseModel):
    amount: float = Field(..., gt=0)
    days_overdue: float = Field(15.0, ge=0)
    invoice_number: str | None = None
    customer_display_name: str | None = None
    historical_success_rate: float = Field(0.8, ge=0, le=1)
    merchant_success_rate: float | None = Field(None, ge=0, le=1)
    retry_count: int = Field(0, ge=0, le=10)


@app.post("/api/b2b/chase")
def b2b_chase_run(invoice: InvoiceEvent) -> dict[str, Any]:
    payload = PaymentEvent(
        event_type="INVOICE_OVERDUE",
        amount=invoice.amount,
        days_overdue=invoice.days_overdue,
        invoice_number=invoice.invoice_number,
        customer_display_name=invoice.customer_display_name,
        historical_success_rate=invoice.historical_success_rate,
        merchant_success_rate=invoice.merchant_success_rate,
        retry_count=invoice.retry_count,
        failure_type=None,
    )
    try:
        return run_b2b_chase(
            initial_payload=payload,
            score_event=lambda p, guardrail_engine: score_event(p, guardrail_engine=guardrail_engine),
            base_guardrail_engine=apply_guardrails,
            execute_bounded_workflow=execute_bounded_workflow,
            payload_cls=PaymentEvent,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/b2b/chase/{chase_id}")
def b2b_chase_get(chase_id: str) -> dict[str, Any]:
    record = db_repo.get_b2b_chase(chase_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Chase not found.")
    return record


@app.get("/api/b2b/chase-log")
def b2b_chase_log(limit: int = 20) -> dict[str, Any]:
    return {"records": db_repo.list_b2b_chases(limit)}


# ---------------------------------------------------------------------------
# Promise-to-Pay Tracker
# ---------------------------------------------------------------------------

class PromiseCreateIn(BaseModel):
    decision_id: str | None = None
    execution_id: str | None = None
    amount: float = Field(..., gt=0)
    promised_date: str  # ISO date/datetime string; may be in the past to demo BROKEN behavior
    event_type: str = "PAYMENT_FAILURE"
    failure_type: str | None = "TIMEOUT"
    historical_success_rate: float = Field(0.8, ge=0, le=1)
    retry_count: int = Field(0, ge=0, le=10)
    merchant_success_rate: float | None = Field(None, ge=0, le=1)


class PromiseKeepIn(BaseModel):
    actual_recovered: float = Field(..., ge=0)


def _promise_resolver_kwargs() -> dict[str, Any]:
    return {
        "payload_cls": PaymentEvent,
        "score_event": lambda p, guardrail_engine: score_event(p, guardrail_engine=guardrail_engine),
        "base_guardrail_engine": apply_guardrails,
        "execute_bounded_workflow": execute_bounded_workflow,
    }


@app.post("/api/promise/create")
def promise_create(body: PromiseCreateIn) -> dict[str, Any]:
    context = {
        "amount": body.amount,
        "event_type": body.event_type,
        "failure_type": body.failure_type,
        "historical_success_rate": body.historical_success_rate,
        "retry_count": body.retry_count,
        "merchant_success_rate": body.merchant_success_rate,
    }
    return promise_tracker.create_promise(body.decision_id, body.execution_id, body.amount, body.promised_date, context)


@app.get("/api/promise/{promise_id}")
def promise_get(promise_id: str) -> dict[str, Any]:
    record = promise_tracker.get_and_resolve(promise_id, **_promise_resolver_kwargs())
    if record is None:
        raise HTTPException(status_code=404, detail="Promise not found.")
    return record


@app.post("/api/promise/{promise_id}/keep")
def promise_keep(promise_id: str, body: PromiseKeepIn) -> dict[str, Any]:
    existing = db_repo.get_promise(promise_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Promise not found.")
    updated = db_repo.mark_promise_kept(promise_id, body.actual_recovered)
    return updated


@app.get("/api/promises")
def promises_list(limit: int = 100) -> dict[str, Any]:
    records = promise_tracker.list_and_resolve(limit, **_promise_resolver_kwargs())
    pending = [p for p in records if p["status"] == "PENDING"]
    kept = [p for p in records if p["status"] == "KEPT"]
    broken = [p for p in records if p["status"] == "BROKEN"]
    return {
        "promises": records,
        "summary": {
            "total": len(records),
            "pending": len(pending),
            "kept": len(kept),
            "broken": len(broken),
            "kept_rate": round(len(kept) / (len(kept) + len(broken)), 4) if (kept or broken) else None,
        },
    }


# ---------------------------------------------------------------------------
# FEATURE 3 — Revenue-at-Risk Early Warning
# ---------------------------------------------------------------------------

@app.post("/api/risk-score")
def risk_score(payload: PaymentEvent) -> dict[str, Any]:
    try:
        return assess_risk(payload, artifact_loader=artifact, feature_builder=build_features, actions=ACTIONS, guardrail_engine=apply_guardrails)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# FEATURE 4 & 5 — Policy What-If Lab and A/B Comparison
# ---------------------------------------------------------------------------

class PolicyParamsIn(BaseModel):
    name: str = "New Policy"
    retry_limit: int = Field(3, ge=0, le=10)
    escalation_min_amount: float = Field(25000.0, ge=0)
    escalation_min_success_rate: float = Field(0.85, ge=0, le=1)
    high_value_threshold: float = Field(10000.0, ge=0)
    retry_cooldown_hours: float = Field(0.0, ge=0)
    reminder_cooldown_hours: float = Field(0.0, ge=0)


@app.post("/api/policy/what-if")
def policy_what_if(params: PolicyParamsIn) -> dict[str, Any]:
    try:
        result = policy_lab.what_if(policy_lab.PolicyParams(**params.model_dump()))
        db_repo.insert_policy_experiment("what_if", params.model_dump(), result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class PolicyCompareIn(BaseModel):
    policy_a: PolicyParamsIn
    policy_b: PolicyParamsIn


@app.post("/api/policy/compare")
def policy_compare(body: PolicyCompareIn) -> dict[str, Any]:
    try:
        result = policy_lab.compare(
            policy_lab.PolicyParams(**body.policy_a.model_dump()),
            policy_lab.PolicyParams(**body.policy_b.model_dump()),
        )
        db_repo.insert_policy_experiment("compare", body.model_dump(), result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/policy/experiments")
def policy_experiments(limit: int = 20) -> dict[str, Any]:
    return {"records": db_repo.list_policy_experiments(limit)}


@app.get("/api/policy/defaults")
def policy_defaults() -> dict[str, Any]:
    return policy_lab.PolicyParams(name="Current Policy").to_dict()


# ---------------------------------------------------------------------------
# FEATURE 6 & 8 — Outcome Feedback Loop and Revenue Recovery Ledger
# ---------------------------------------------------------------------------

@app.get("/api/ledger")
def get_ledger(limit: int = 100) -> dict[str, Any]:
    live = ledger_module.build_ledger(limit)
    live["dataset_summary"] = dashboard_metrics()
    return live


@app.get("/api/feedback")
def get_feedback() -> dict[str, Any]:
    return ledger_module.build_feedback()


# ---------------------------------------------------------------------------
# Held-out evaluation runner

@app.post("/api/evaluation/run")
def evaluation_run() -> dict[str, Any]:
    """Recompute the frozen August holdout from the trained model artifact.

    This is an offline evaluation only: it never changes production policy or
    contacts an external provider. Outcomes are joined only after action
    selection, so the evaluator remains leakage-safe.
    """
    try:
        result = evaluation_runner.run_heldout_evaluation()
        return {"status": "COMPLETED", "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/evaluation/status")
def evaluation_status() -> dict[str, Any]:
    path = PROCESSED / "v3_100k_policy_summary.json"
    if not path.exists():
        return {"status": "NOT_RUN", "result": None}
    try:
        return {"status": "READY", "result": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# FEATURES 9 & 10 — Budget-Constrained Intervention Planning + Scenario Simulation
# ---------------------------------------------------------------------------

class BudgetOptimizeIn(BaseModel):
    budget: float = Field(..., ge=0)
    population_limit: int | None = Field(None, ge=1, le=100000)
    amount_multiplier: float = Field(1.0, gt=0, le=5)
    recovery_multiplier: float = Field(1.0, gt=0, le=2)


@app.post("/api/budget/optimize")
def budget_optimize(body: BudgetOptimizeIn) -> dict[str, Any]:
    try:
        result = planner_module.optimize_budget(
            budget=body.budget,
            population_limit=body.population_limit,
            amount_multiplier=body.amount_multiplier,
            recovery_multiplier=body.recovery_multiplier,
        )
        db_repo.insert_policy_experiment("budget_optimizer", body.model_dump(), result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class DigitalTwinIn(BaseModel):
    volume_multiplier: float = Field(1.0, gt=0, le=10)
    amount_multiplier: float = Field(1.0, gt=0, le=5)
    recovery_multiplier: float = Field(1.0, gt=0, le=2)
    budget: float | None = Field(None, ge=0)


@app.post("/api/digital-twin")
def digital_twin(body: DigitalTwinIn) -> dict[str, Any]:
    try:
        result = planner_module.digital_twin(**body.model_dump())
        db_repo.insert_policy_experiment("digital_twin", body.model_dump(), result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/planner/experiments")
def planner_experiments(limit: int = 20) -> dict[str, Any]:
    records = db_repo.list_policy_experiments(limit)
    return {"records": [r for r in records if r.get("kind") in {"budget_optimizer", "digital_twin"}]}


# ---------------------------------------------------------------------------
# FEATURES 11-15 — Revenue Detective, Root Cause, Anomaly Watch, Impact Discovery
# and real external execution adapters

@app.get("/api/revenue-intelligence/merchant-incidents")
def revenue_merchant_incidents(include_simulator: bool = False, window_hours: int = 24) -> dict[str, Any]:
    try:
        result = incident_platform.detect_and_persist_incidents(include_simulator=include_simulator, window_hours=max(1, min(window_hours, 168)))
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/revenue-intelligence/incidents/{incident_id}/blast-radius")
def revenue_incident_blast_radius(incident_id: str) -> dict[str, Any]:
    return incident_platform.blast_radius(incident_id)


@app.get("/api/revenue-intelligence/incidents/{incident_id}/cohorts")
def revenue_incident_cohorts(incident_id: str) -> dict[str, Any]:
    return incident_platform.customer_cohorts(incident_id)


@app.get("/api/revenue-intelligence/incidents/{incident_id}/analytics")
def revenue_incident_analytics(incident_id: str) -> dict[str, Any]:
    return incident_platform.recovery_outcome_analytics(incident_id)


@app.get("/api/revenue-intelligence/outcome-analytics")
def revenue_outcome_analytics() -> dict[str, Any]:
    return incident_platform.recovery_outcome_analytics()


@app.post("/api/revenue-intelligence/incidents/{incident_id}/monitor")
def revenue_incident_monitor(incident_id: str) -> dict[str, Any]:
    return incident_platform.monitor_incident(incident_id)


@app.get("/api/revenue-intelligence/health")
def revenue_merchant_health() -> dict[str, Any]:
    return incident_platform.merchant_health()


@app.get("/api/revenue-intelligence/feedback-analytics")
def revenue_feedback_analytics() -> dict[str, Any]:
    return incident_platform.feedback_analytics()


@app.get("/api/revenue-intelligence/audit")
def revenue_platform_audit(limit: int = 100) -> dict[str, Any]:
    return {"records": db_repo.list_platform_records("AUDIT", max(1, min(limit, 500)))}


@app.post("/api/revenue-intelligence/demo")
def revenue_full_demo() -> dict[str, Any]:
    try:
        return incident_platform.demo_run()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/revenue-intelligence/safety-audit")
def revenue_safety_audit() -> dict[str, Any]:
    return incident_platform.production_safety_audit()


@app.get("/api/revenue-intelligence/scan")
def revenue_intelligence_scan(include_simulator: bool = False) -> dict[str, Any]:
    try:
        return intelligence.scan(include_simulator=include_simulator)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/revenue-intelligence/autopilot")
def revenue_intelligence_autopilot() -> dict[str, Any]:
    """Run the complete Detect → Diagnose → Prioritize → Recover → Verify cycle.

    Autopilot recovery is deliberately bounded to SAFE_SIMULATION. This makes the
    Recover step real and auditable without silently contacting customers or a
    payment provider when an operator merely clicks the dashboard button.
    Explicit live execution remains available through Decision Lab.
    """
    try:
        # Do not run merchant intelligence/autopilot concurrently with a
        # simulator mutation. This prevents SQLite contention and mixed
        # merchant generations while the simulator is producing events.
        with msim.STATE.operation_lock:
            started = datetime.now(timezone.utc)
            # Phase 2: Autopilot consumes the live in-process NovaCart event stream
            # in addition to the canonical historical dataset. Recovery outcomes
            # from the simulator are excluded by the intelligence ingestion layer,
            # so the decision still uses pre-action evidence only.
            scan = intelligence.scan(include_simulator=True)
            merchant_watch = incident_platform.detect_and_persist_incidents(include_simulator=True)
            incidents = merchant_watch.get("incidents", [])
            # Prioritize customers belonging to a detected merchant/payment-rail incident
            # first, while leaving the individual action decision to the existing Decision Agent.
            candidates = scan["affected_customers"]
            incident_methods = {i.get("payment_method") for i in incidents if i.get("status") in {"DETECTED", "ANALYZING", "MITIGATING", "MONITORING"}}
            incident_customer_ids = {
                r.get("customer_id") for r in msim.intelligence_events()
                if r.get("event_type") == "PAYMENT_FAILURE" and r.get("payment_method") in incident_methods
            }
            incident_customer_ids.discard(None)
            scoped_candidates = candidates.get("customers", [])
            if incident_customer_ids:
                incident_candidates = [c for c in scoped_candidates if c.get("customer_id") in incident_customer_ids]
                if incident_candidates:
                    scoped_candidates = incident_candidates
            ranked_candidates = sorted(
                scoped_candidates,
                key=lambda c: (str(c.get("payment_method")) in incident_methods, float(c.get("amount_at_risk", 0) or 0), float(c.get("risk_score", 0) or 0)),
                reverse=True,
            )
            candidates = {**candidates, "customers": ranked_candidates, "count": len(ranked_candidates)}
            execution_cap = 10
            if incidents:
                for incident in incidents:
                    incident_platform.transition_incident(incident["incident_id"], "MITIGATING", "Autopilot began incident-aware recovery orchestration.")
            executions: list[dict[str, Any]] = []
            providers: set[str] = set()

            for candidate in ranked_candidates[:execution_cap]:
                payload = PaymentEvent(
                    event_id=candidate.get("latest_event_id"),
                    amount=float(candidate.get("amount", candidate.get("amount_at_risk", 0))),
                    event_type=candidate.get("event_type", "PAYMENT_FAILURE"),
                    payment_method=candidate.get("payment_method", "UPI"),
                    device_type=candidate.get("device_type", "MOBILE"),
                    failure_type=candidate.get("failure_type"),
                    retry_count=int(candidate.get("retry_count", 0)),
                    previous_attempt_hours=float(candidate.get("previous_attempt_hours", 0) or 0),
                    checkout_duration_seconds=float(candidate.get("checkout_duration_seconds", 60) or 60),
                    payment_page_reached=int(candidate.get("payment_page_reached", 1)),
                    payment_attempted=int(candidate.get("payment_attempted", 1)),
                    subscription_age_days=float(candidate.get("subscription_age_days", 0) or 0),
                    successful_cycles=int(candidate.get("successful_cycles", 0) or 0),
                    failed_cycles=int(candidate.get("failed_cycles", 0) or 0),
                    customer_tenure_days=float(candidate.get("customer_tenure_days", 365) or 365),
                    total_transactions=int(candidate.get("total_transactions", 10) or 10),
                    successful_transactions=int(candidate.get("successful_transactions", 0) or 0),
                    failed_transactions=int(candidate.get("failed_transactions", 0) or 0),
                    historical_success_rate=float(candidate.get("historical_success_rate", 0.8)),
                    avg_transaction_amount=float(candidate.get("avg_transaction_amount", 5000) or 5000),
                    previous_recovery_success_rate=float(candidate.get("previous_recovery_success_rate", 0.5) or 0.5),
                    days_since_last_success=float(candidate.get("days_since_last_success", 7) or 7),
                    preferred_payment_method=candidate.get("preferred_payment_method", "UPI"),
                    merchant_category=candidate.get("merchant_category", "E_COMMERCE"),
                    merchant_size=candidate.get("merchant_size", "MEDIUM"),
                    merchant_avg_transaction_amount=float(candidate.get("merchant_avg_transaction_amount", 5000) or 5000),
                    merchant_success_rate=float(candidate.get("merchant_success_rate", 0.9)),
                    merchant_failure_rate=float(candidate.get("merchant_failure_rate", 0.1)),
                )
                # Autopilot needs the same Decision Agent ranking, but not the heavy
                # counterfactual/feature-attribution diagnostics rendered by Decision Lab.
                decision = score_event(payload, persist=False, diagnostics=False)
                action = decision["recommended_action"]
                if action == "STOP":
                    stop_execution = {
                        "execution_id": f"AUTO-STOP-{uuid.uuid4().hex[:10].upper()}",
                        "decision_id": decision.get("decision_id"),
                        "action": action,
                        "state": "STOPPED",
                        "outcome": "STOPPED_BY_POLICY",
                        "amount": payload.amount,
                        "revenue_recovered": 0.0,
                        "intervention_cost": 0.0,
                        "expected_recovery": decision.get("expected_revenue", {}).get(action, 0.0),
                        "expected_probability": decision.get("probabilities", {}).get(action, 0.0),
                    }
                    feedback = incident_platform.record_feedback(stop_execution, None, {
                        "merchant_id": candidate.get("merchant_id", "NOVACART-SIM"),
                        "customer_id": candidate.get("customer_id"),
                        "payment_method": payload.payment_method,
                        "failure_type": payload.failure_type,
                        "expected_net_value": decision.get("expected_net_value", {}).get(action),
                    })
                    executions.append({
                        "customer_id": candidate["customer_id"], "event_id": payload.event_id,
                        "action": action, "execution_state": "STOPPED",
                        "verification_status": "VERIFIED_NO_ACTION",
                        "feedback_id": feedback.get("feedback_id"),
                        "reason": "Decision Agent selected the safe STOP fallback.",
                    })
                    continue
                execution = execute_bounded_workflow(payload, decision, apply_guardrails, live=False, channel="auto")
                provider = "local_bounded_simulator"
                providers.add(provider)
                state = execution.get("state")
                if state == "RECOVERED":
                    verification_status = "VERIFIED_RECOVERED"
                elif state in {"SCHEDULED", "ESCALATED"}:
                    verification_status = "VERIFIED_ACCEPTED_PENDING"
                elif state == "STOPPED":
                    verification_status = "VERIFIED_NO_ACTION"
                else:
                    verification_status = "VERIFIED_FAILED"
                incident = next((i for i in incidents if i.get("payment_method") == payload.payment_method and i.get("merchant_id") == "NOVACART-SIM"), None)
                feedback = incident_platform.record_feedback(
                    execution,
                    incident_id=incident.get("incident_id") if incident else None,
                    context={
                        "merchant_id": candidate.get("merchant_id", "NOVACART-SIM"),
                        "customer_id": candidate.get("customer_id"),
                        "payment_method": payload.payment_method,
                        "failure_type": payload.failure_type,
                        "expected_net_value": decision.get("expected_net_value", {}).get(action),
                    },
                )
                executions.append({
                    "customer_id": candidate["customer_id"], "event_id": payload.event_id,
                    "action": action, "execution_state": state,
                    "verification_status": verification_status,
                    "amount": payload.amount,
                    "revenue_recovered": execution.get("revenue_recovered", 0.0),
                    "intervention_cost": execution.get("intervention_cost", 0.0),
                    "execution_id": execution.get("execution_id"),
                    "incident_id": incident.get("incident_id") if incident else None,
                    "incident_strategy": incident.get("recommended_action") if incident else None,
                    "feedback_id": feedback.get("feedback_id"),
                    "reason": execution.get("outcome_reason", ""),
                })

            if incidents:
                for incident in incidents:
                    incident_platform.transition_incident(incident["incident_id"], "MONITORING", "Bounded recovery actions completed; continue observing payment health.")
            recovered = sum(float(x.get("revenue_recovered", 0) or 0) for x in executions)
            cost = sum(float(x.get("intervention_cost", 0) or 0) for x in executions)
            verified_recovered = sum(1 for x in executions if x.get("verification_status") == "VERIFIED_RECOVERED")
            verified_pending = sum(1 for x in executions if x.get("verification_status") == "VERIFIED_ACCEPTED_PENDING")
            return {
                "run_id": scan["run_id"],
                "data_source": scan.get("data_source", "HISTORICAL_DATASET"),
                "simulator_events_ingested": scan.get("simulator_events_ingested", 0),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 1),
                "status": scan["status"],
                "pipeline": [
                    {"stage": "DETECT", "status": "COMPLETED", "detail": f"{scan['summary']['anomalies']} anomalies; {scan['summary'].get('merchant_incidents', 0)} merchant incidents"},
                    {"stage": "DIAGNOSE", "status": "COMPLETED", "detail": f"{scan['summary']['root_causes']} deteriorating root-cause segments"},
                    {"stage": "PRIORITIZE", "status": "COMPLETED", "detail": f"{scan['summary']['affected_customers']} affected customers ranked; top {min(execution_cap, scan['summary']['affected_customers'])} sent to bounded recovery"},
                    {"stage": "EXECUTE", "status": "COMPLETED", "detail": f"{len(executions)} bounded recovery actions executed in SAFE_SIMULATION"},
                    {"stage": "VERIFY", "status": "COMPLETED", "detail": f"{verified_recovered} recovered, {verified_pending} accepted/pending, {len(executions)-verified_recovered-verified_pending} failed/no-action"},
                ],
                "anomalies": scan["anomalies"],
                "root_causes": scan["root_causes"],
                "merchant_incidents": merchant_watch,
                "incident_blast_radius": incident_platform.blast_radius(incidents[0]["incident_id"] if incidents else None),
                "merchant_health": incident_platform.merchant_health(),
                "affected_customer_cohorts": incident_platform.customer_cohorts(incidents[0]["incident_id"] if incidents else None),
                "outcome_analytics": incident_platform.recovery_outcome_analytics(incidents[0]["incident_id"] if incidents else None),
                "feedback_analytics": incident_platform.feedback_analytics(),
                "incident_monitoring": incident_platform.monitor_incident(incidents[0]["incident_id"] if incidents else None) if incidents else {"status": "NO_INCIDENT"},
                "affected_customers": candidates,
                "execution": {
                    "mode": "SAFE_SIMULATION",
                    "provider": "local_bounded_simulator",
                    "candidates_considered": len(candidates.get("customers", [])),
                    "execution_cap": execution_cap,
                    "executed": len(executions),
                    "revenue_recovered": round(recovered, 2),
                    "intervention_cost": round(cost, 2),
                    "net_recovery": round(recovered - cost, 2),
                    "providers_used": sorted(providers) or ["none"],
                    "external_execution": "NOT_PERFORMED",
                    "message": "Recover and Verify are real bounded simulation stages. No customer or external payment provider was contacted by Autopilot.",
                },
                "executions": executions,
                "summary": {
                    **scan["summary"],
                    "execution_candidates": min(execution_cap, scan["summary"]["affected_customers"]),
                    "executed": len(executions),
                    "verified_recovered": verified_recovered,
                    "verified_pending": verified_pending,
                    "revenue_recovered": round(recovered, 2),
                    "intervention_cost": round(cost, 2),
                    "net_recovery": round(recovered - cost, 2),
                    "execution_providers": len(providers),
                },
                "methodology": {
                    "anomalies": scan["anomalies"].get("methodology"),
                    "root_causes": scan["root_causes"].get("methodology"),
                    "affected_customers": candidates.get("methodology"),
                    "execution": "Top 10 risk-ranked customers are scored by the Decision Agent; each selected action is re-checked against guardrails and executed through the same bounded simulator used by Decision Lab. Verification classifies the resulting execution state and never converts provider acceptance into recovered revenue.",
                },
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/revenue-intelligence/anomalies")
def revenue_anomalies(hours: int = 24, z_threshold: float = 2.5, include_simulator: bool = False) -> dict[str, Any]:
    try:
        return intelligence.detect_anomalies(hours=max(1, min(hours, 168)), z_threshold=max(0.5, min(z_threshold, 10.0)), include_simulator=include_simulator)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/revenue-intelligence/root-causes")
def revenue_root_causes(top_n: int = 8, include_simulator: bool = False) -> dict[str, Any]:
    try:
        return intelligence.root_causes(top_n=max(1, min(top_n, 25)), include_simulator=include_simulator)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/revenue-intelligence/customers")
def affected_customers(limit: int = 25, min_amount: float = 0.0, include_simulator: bool = False) -> dict[str, Any]:
    try:
        return intelligence.affected_customers(limit=max(1, min(limit, 100)), min_amount=max(0.0, min_amount), include_simulator=include_simulator)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/integrations/status")
def integration_status() -> dict[str, Any]:
    return integrations.status()


class ExecutionEnvironmentIn(BaseModel):
    environment: str = Field(..., pattern="^(DEMO|SANDBOX|PRODUCTION)$")
    admin_token: str | None = None
    confirm_live: bool = False


@app.post("/api/integrations/environment")
def set_integration_environment(body: ExecutionEnvironmentIn) -> dict[str, Any]:
    try:
        return integrations.set_execution_environment(body.environment, body.admin_token, body.confirm_live)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class IntegrationExecuteIn(BaseModel):
    action: str
    amount: float = Field(..., gt=0)
    event_id: str = "DEMO-EVENT"
    email: str | None = None
    phone: str | None = None
    channel: str = "auto"
    simulate_failure: bool = False
    live_confirmation: bool = False


@app.post("/api/integrations/execute")
def integration_execute(body: IntegrationExecuteIn) -> dict[str, Any]:
    # Failure injection intentionally exercises the same breaker path without
    # requiring real credentials or risking a real customer contact.
    if body.simulate_failure:
        breaker = integrations.BREAKERS["webhook" if body.action in {"RETRY_LATER", "HUMAN_ESCALATION"} else ("payment" if body.action == "ALTERNATIVE_PAYMENT" else "email")]
        breaker.failure()
        return {"mode": "FAILURE_INJECTION", "status": "FAILED", "error": "Injected provider failure for circuit-breaker demonstration.", "circuit_breaker": {"state": breaker.state, "failures": breaker.failures}}
    if integrations.execution_environment() == "PRODUCTION" and not body.live_confirmation:
        raise HTTPException(status_code=400, detail="LIVE PRODUCTION execution requires explicit confirmation.")
    return integrations.execute(body.action, body.model_dump(), channel=body.channel)


@app.post("/api/integrations/circuit-breaker/reset")
def integration_breaker_reset() -> dict[str, Any]:
    return integrations.reset_breakers()

class KillSwitchIn(BaseModel):
    enabled: bool
    admin_token: str | None = None

@app.post("/api/integrations/kill-switch")
def integration_kill_switch(body: KillSwitchIn) -> dict[str, Any]:
    try:
        return integrations.set_kill_switch(body.enabled, body.admin_token)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/integrations/events")
def integration_events(limit: int = 50) -> dict[str, Any]:
    return {"records": db_repo.list_integration_events(limit)}


class ProductionArmIn(BaseModel):
    enabled: bool
    admin_token: str | None = None
    confirm_live: bool = False


class RazorpayTestOrderIn(BaseModel):
    amount: float = Field(..., gt=0, le=100000)
    customer_name: str | None = None
    email: str | None = None
    phone: str | None = None


@app.post("/api/razorpay/test/order")
def create_razorpay_test_order(body: RazorpayTestOrderIn) -> dict[str, Any]:
    """Create a Razorpay Standard Checkout order using TEST credentials only.

    This endpoint is deliberately sandbox-only. It never accepts live keys and
    never changes the execution environment. The resulting order is tagged so
    webhook events can be correlated without treating a direct test payment as
    recovered revenue.
    """
    if integrations.execution_environment() != "SANDBOX":
        raise HTTPException(
            status_code=400,
            detail="Razorpay Test Checkout is available only in the RAZORPAY TEST environment.",
        )
    key = os.getenv("RAZORPAY_KEY_ID", "")
    secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    if not key.startswith("rzp_test_") or not secret:
        raise HTTPException(
            status_code=400,
            detail="Razorpay Test Checkout requires a configured rzp_test_* key and Razorpay key secret.",
        )
    amount_minor = int(round(float(body.amount) * 100))
    receipt = f"RA-TEST-{uuid.uuid4().hex[:16].upper()}"
    order_request: dict[str, Any] = {
        "amount": amount_minor,
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "recoverai_test_payment": "1",
            "recoverai_source": "RecoverAI Test Checkout",
        },
    }
    try:
        auth = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("ascii")
        req = urllib.request.Request(
            "https://api.razorpay.com/v1/orders",
            data=json.dumps(order_request, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            created = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Razorpay Test Orders API failed: {exc}") from exc

    order_id = str(created.get("id") or "")
    if not order_id:
        raise HTTPException(status_code=502, detail="Razorpay Test Orders API returned no order_id.")

    db_repo.insert_integration_event({
        "integration_event_id": f"RP-TEST-ORDER-{order_id}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "razorpay",
        "event_type": "TEST_ORDER_CREATED",
        "status": "CREATED",
        "payload": {
            "order_id": order_id,
            "amount": float(body.amount),
            "currency": "INR",
            "receipt": receipt,
            "customer": {
                "name": body.customer_name,
                "email": body.email,
                "phone": body.phone,
            },
            "test_only": True,
        },
    })
    return {
        "test_only": True,
        "key_id": key,
        "order": created,
        "customer": {
            "name": body.customer_name,
            "email": body.email,
            "phone": body.phone,
        },
        "message": "Razorpay Test order created. Complete it in Standard Checkout; server-side recovery remains unverified until webhook confirmation.",
    }


@app.get("/api/razorpay/test/order/{order_id}")
def razorpay_test_order_status(order_id: str) -> dict[str, Any]:
    """Return correlated Razorpay test-order/webhook events for the UI."""
    order_id = order_id.strip()
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required.")
    events = db_repo.list_integration_events(200)
    matches: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") or {}
        event_order_id = str(payload.get("order_id") or "")
        body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
        nested_payload = body.get("payload") if isinstance(body, dict) else {}
        payment = ((nested_payload.get("payment") or {}).get("entity") or {}) if isinstance(nested_payload, dict) else {}
        order = ((nested_payload.get("order") or {}).get("entity") or {}) if isinstance(nested_payload, dict) else {}
        payment_order_id = str(payment.get("order_id") or "")
        nested_order_id = str(order.get("id") or "")
        if event_order_id == order_id or payment_order_id == order_id or nested_order_id == order_id:
            matches.append(event)
    matches.sort(key=lambda x: str(x.get("timestamp", "")))
    return {
        "order_id": order_id,
        "events": matches,
        "latest": matches[-1] if matches else None,
    }


@app.get("/api/production/status")
def production_status() -> dict[str, Any]:
    status = integrations.status()
    return {
        "environment": status.get("environment"),
        "live_enabled": status.get("live_enabled"),
        "production_execution_armed": status.get("production_execution_armed", False),
        "kill_switch": status.get("kill_switch", False),
        "razorpay_key_mode": status.get("razorpay_key_mode"),
        "webhook_hmac_configured": status.get("provider_security", {}).get("razorpay_webhook_hmac", False),
        "providers": status.get("providers", {}),
        "max_live_amount": status.get("max_live_amount"),
        "daily_live_budget": status.get("daily_live_budget"),
    }


@app.post("/api/production/arm")
def production_arm(body: ProductionArmIn) -> dict[str, Any]:
    if not body.admin_token:
        raise HTTPException(status_code=403, detail="Production arming requires RECOVERAI_ADMIN_TOKEN.")
    expected = os.getenv("RECOVERAI_ADMIN_TOKEN", "")
    if not expected or not hmac.compare_digest(body.admin_token, expected):
        raise HTTPException(status_code=403, detail="Invalid production admin token.")
    if body.enabled:
        if not body.confirm_live:
            raise HTTPException(status_code=400, detail="Production arming requires explicit live confirmation.")
        if integrations.execution_environment() != "PRODUCTION":
            raise HTTPException(status_code=400, detail="Set the execution environment to PRODUCTION before arming live execution.")
        key = os.getenv("RAZORPAY_KEY_ID", "")
        if not key.startswith("rzp_live_") or not os.getenv("RAZORPAY_KEY_SECRET"):
            raise HTTPException(status_code=400, detail="Production arming requires Razorpay LIVE credentials (rzp_live_*).")
        if not os.getenv("RAZORPAY_WEBHOOK_SECRET"):
            raise HTTPException(status_code=400, detail="Production arming requires RAZORPAY_WEBHOOK_SECRET for verified recovery events.")
    os.environ["RECOVERAI_PRODUCTION_EXECUTION_ARMED"] = "1" if body.enabled else "0"
    if body.enabled:
        os.environ["RECOVERAI_LIVE_EXECUTION"] = "1"
    return production_status()


def _razorpay_event_key(event_id: str, raw: bytes) -> str:
    value = event_id.strip() if event_id else hashlib.sha256(raw).hexdigest()
    return "RP-EVT-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24].upper()


def _razorpay_failure_to_payment_event(body: dict[str, Any], event_id: str) -> PaymentEvent:
    payload = body.get("payload") or {}
    payment = ((payload.get("payment") or {}).get("entity") or {})
    amount_minor = payment.get("amount")
    if amount_minor is None:
        raise ValueError("payment.failed webhook does not contain payment.amount")
    amount = float(amount_minor) / 100.0
    if amount <= 0:
        raise ValueError("payment.failed webhook contains a non-positive amount")
    method = str(payment.get("method") or "UPI").upper()
    description = " ".join(str(payment.get(k) or "") for k in ("error_description", "error_reason", "error_code")).strip()
    upper = description.upper()
    if "INSUFFICIENT" in upper or "BALANCE" in upper:
        failure_type = "INSUFFICIENT_BALANCE"
    elif "EXPIRED" in upper:
        failure_type = "EXPIRED_PAYMENT_METHOD"
    elif "LIMIT" in upper:
        failure_type = "PAYMENT_LIMIT"
    elif "NETWORK" in upper or "TIMEOUT" in upper:
        failure_type = "NETWORK_ERROR"
    elif "DECLIN" in upper:
        failure_type = "ISSUER_DECLINE"
    else:
        failure_type = "BANK_TECHNICAL_ERROR"
    email = payment.get("email")
    phone = payment.get("contact")
    return PaymentEvent(
        event_id=event_id or f"RAZORPAY-{uuid.uuid4().hex}",
        email=str(email) if email else None,
        phone=str(phone) if phone else None,
        currency=str(payment.get("currency") or "INR"),
        event_type="PAYMENT_FAILURE",
        amount=amount,
        payment_method=method,
        failure_type=failure_type,
        retry_count=0,
        payment_page_reached=1,
        payment_attempted=1,
        merchant_category="E_COMMERCE",
        merchant_size="MEDIUM",
        merchant_avg_transaction_amount=amount,
        avg_transaction_amount=amount,
        total_transactions=1,
        successful_transactions=0,
        failed_transactions=1,
        historical_success_rate=0.8,
        merchant_success_rate=0.9,
        merchant_failure_rate=0.1,
        preferred_payment_method=method,
        customer_display_name=None,
    )


@app.post("/api/integrations/razorpay/webhook")
async def razorpay_webhook(request: Request) -> dict[str, Any]:
    """Verify Razorpay's raw-body HMAC and reconcile a Payment Link payment.

    Razorpay documents ``payment_link.paid`` as the Payment Link success event
    and requires the signature to be calculated over the raw request body.
    """
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="RAZORPAY_WEBHOOK_SECRET is not configured.")
    raw = await request.body()
    supplied = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid Razorpay webhook signature.")

    event_id = request.headers.get("X-Razorpay-Event-Id", "") or request.headers.get("X-Razorpay-Request-Id", "")
    try:
        body = json.loads(raw.decode("utf-8"))
        event = str(body.get("event", ""))
        payload = body.get("payload") or {}
        payment_link = ((payload.get("payment_link") or {}).get("entity") or {})
        order = ((payload.get("order") or {}).get("entity") or {})
        payment = ((payload.get("payment") or {}).get("entity") or {})
        execution_id = str(payment_link.get("reference_id") or order.get("reference_id") or "")
        integration_event_id = _razorpay_event_key(event_id, raw)
        if db_repo.get_integration_event(integration_event_id) is not None:
            return {"status": "DUPLICATE_IGNORED", "event": event, "event_id": event_id}
        if event == "payment.failed":
            payment_event = _razorpay_failure_to_payment_event(body, event_id)
            decision = score_event(payment_event)
            db_repo.insert_integration_event({
                "integration_event_id": integration_event_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": "razorpay", "event_type": event, "status": "RECEIVED",
                "payload": {
                    "event_id": event_id,
                    "environment": integrations.execution_environment(),
                    "body": body,
                    "decision": decision,
                    "payment_event": payment_event.model_dump(),
                },
            })
            if integrations.execution_environment() != "PRODUCTION":
                return {
                    "status": "OBSERVED",
                    "event": event,
                    "decision": decision,
                    "payment_event": payment_event.model_dump(),
                    "message": "Real-time failure ingestion is production-bound; TEST/DEMO webhook failures are observed without automatic live recovery execution.",
                }
            if not integrations.live_enabled():
                return {
                    "status": "OBSERVED",
                    "event": event,
                    "decision": decision,
                    "payment_event": payment_event.model_dump(),
                    "message": "Production execution is disarmed or unavailable; no external recovery action was executed.",
                }
            action = decision.get("recommended_action", "STOP")
            if action == "STOP":
                return {
                    "status": "NO_ACTION",
                    "event": event,
                    "decision": decision,
                    "payment_event": payment_event.model_dump(),
                    "message": "Decision Agent selected STOP.",
                }
            execution = execute_bounded_workflow(
                payment_event, decision, apply_guardrails, live=True, channel="auto", selected_action=action
            )
            return {
                "status": "EXECUTED",
                "event": event,
                "decision": decision,
                "payment_event": payment_event.model_dump(),
                "execution": execution,
            }
        if event not in {"payment_link.paid", "payment.captured", "order.paid"}:
            db_repo.insert_integration_event({
                "integration_event_id": f"INT-{uuid.uuid4().hex[:10].upper()}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": "razorpay", "event_type": event or "UNKNOWN", "status": "IGNORED",
                "payload": {"event_id": event_id, "body": body},
            })
            return {"status": "IGNORED", "event": event}
        if not execution_id.startswith("EXE-"):
            # payment.captured/order.paid can arrive for a Payment Link before
            # (or without) the Payment Link success event. Those events do not
            # reliably carry the Payment Link reference_id, so they must not be
            # treated as malformed webhooks. Keep them auditable and return 2xx;
            # payment_link.paid is the correlation event that verifies a RecoverAI
            # recovery execution.
            if event in {"payment.captured", "order.paid"}:
                order_id = str(order.get("id") or payment.get("order_id") or "")
                if order_id:
                    known_test = db_repo.get_integration_event(f"RP-TEST-ORDER-{order_id}")
                    if known_test is not None:
                        paid_minor = payment.get("amount") or order.get("amount_paid") or order.get("amount") or 0
                        verified_amount = float(paid_minor) / 100.0
                        if verified_amount <= 0:
                            raise ValueError("Test webhook contains no positive paid amount.")
                        db_repo.insert_integration_event({
                            "integration_event_id": _razorpay_event_key(event_id, raw),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "provider": "razorpay",
                            "event_type": event,
                            "status": "VERIFIED_TEST_PAYMENT",
                            "payload": {
                                "event_id": event_id,
                                "order_id": order_id,
                                "amount": verified_amount,
                                "test_only": True,
                                "body": body,
                            },
                        })
                        return {
                            "status": "TEST_PAYMENT_VERIFIED",
                            "event": event,
                            "order_id": order_id,
                            "amount": verified_amount,
                            "test_only": True,
                            "message": "Razorpay Test payment verified. This direct checkout payment is not counted as RecoverAI recovered revenue.",
                        }
                db_repo.insert_integration_event({
                    "integration_event_id": integration_event_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "provider": "razorpay",
                    "event_type": event,
                    "status": "PENDING_CORRELATION",
                    "payload": {
                        "event_id": event_id,
                        "body": body,
                        "reason": "Payment event has no RecoverAI execution reference_id; waiting for payment_link.paid for Payment Link correlation.",
                    },
                })
                return {
                    "status": "PENDING_CORRELATION",
                    "event": event,
                    "event_id": event_id,
                    "message": "Payment captured/paid without a RecoverAI execution reference. Waiting for payment_link.paid; no revenue is counted yet.",
                }
            # A Payment Link success event must carry the RecoverAI execution
            # reference. Without it, do not guess which execution to recover.
            raise ValueError("Missing RecoverAI execution reference_id in payment_link.paid webhook.")
        paid_minor = (
            payment_link.get("amount_paid")
            or order.get("amount_paid")
            or payment.get("amount")
            or payment_link.get("amount")
            or order.get("amount")
            or 0
        )
        recovered_amount = float(paid_minor) / 100.0
        if recovered_amount <= 0:
            raise ValueError("Webhook contains no positive paid amount.")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Razorpay webhook payload: {exc}") from exc

    # mark_execution_recovered is idempotent at the state level: repeated
    # delivery of the same verified event leaves the execution recovered.
    updated = db_repo.mark_execution_recovered(execution_id, recovered_amount, verification_event=body)
    if updated is None:
        raise HTTPException(status_code=404, detail="RecoverAI execution not found for Razorpay reference_id.")
    db_repo.insert_integration_event({
        "integration_event_id": _razorpay_event_key(event_id, raw),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "razorpay", "event_type": event, "status": "VERIFIED",
        "payload": {"event_id": event_id, "execution_id": execution_id, "amount": recovered_amount, "body": body},
    })
    return {"status": "VERIFIED", "execution": updated}


@app.post("/api/integrations/recovery-webhook")
async def recovery_webhook(request: Request) -> dict[str, Any]:
    """Verify an authenticated orchestration callback and reconcile recovery.

    Send ``X-RecoverAI-Signature: HMAC-SHA256(raw_body, secret)`` using
    RECOVERAI_WEBHOOK_SECRET. This endpoint is intentionally separate from the
    outbound orchestration webhook URL.
    """
    secret = os.getenv("RECOVERAI_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Recovery webhook verification is not configured.")
    raw = await request.body()
    supplied = request.headers.get("X-RecoverAI-Signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid recovery webhook signature.")
    try:
        body = json.loads(raw.decode("utf-8"))
        execution_id = str(body["execution_id"])
        recovered_amount = float(body.get("recovered_amount", body.get("amount", 0)))
        if recovered_amount <= 0:
            raise ValueError("recovered_amount must be positive")
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid recovery webhook payload: {exc}") from exc
    updated = db_repo.mark_execution_recovered(execution_id, recovered_amount, verification_event=body)
    if updated is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    db_repo.insert_integration_event({
        "integration_event_id": f"INT-{uuid.uuid4().hex[:10].upper()}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "payment_webhook",
        "event_type": "RECOVERY_VERIFICATION",
        "status": "VERIFIED",
        "payload": body,
    })
    return {"status": "VERIFIED", "execution": updated}


@app.post("/api/integrations/twilio/status")
async def twilio_status(request: Request) -> dict[str, Any]:
    """Record Twilio delivery status callbacks without treating delivery as payment."""
    raw = await request.body()
    data = urllib.parse.parse_qs(raw.decode("utf-8", errors="replace"))
    flat = {k: v[-1] for k, v in data.items()}
    # Twilio signs incoming webhooks. Verification is optional in local/demo,
    # but required when an explicit validation token is configured.
    validation_url = os.getenv("TWILIO_STATUS_CALLBACK_URL")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    supplied = request.headers.get("X-Twilio-Signature", "")
    if auth_token and supplied and validation_url:
        # For a form POST, Twilio signs URL + sorted parameter key/value pairs.
        signing = validation_url + "".join(f"{k}{flat[k]}" for k in sorted(flat))
        expected = base64.b64encode(hmac.new(auth_token.encode(), signing.encode(), hashlib.sha1).digest()).decode()
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="Invalid Twilio status callback signature.")
    db_repo.insert_integration_event({
        "integration_event_id": f"INT-{uuid.uuid4().hex[:10].upper()}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "twilio",
        "event_type": "MESSAGE_STATUS",
        "status": str(flat.get("MessageStatus", "UNKNOWN")).upper(),
        "payload": flat,
    })
    return {"status": "RECORDED", "message_status": flat.get("MessageStatus"), "message_sid": flat.get("MessageSid")}


# ---------------------------------------------------------------------------
# FEATURE 7 — Model Monitoring / Drift
# ---------------------------------------------------------------------------

@app.get("/api/model-health")
def model_health() -> dict[str, Any]:
    metrics_path = PROCESSED / "models" / "recoverai_v3_100k_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    health = drift_module.model_health(metrics, ACTIONS)
    features = tuple(artifact()["features"])
    for m in health["per_action_metrics"]:
        try:
            m["global_feature_importance"] = global_importance(m["action"], features)
        except Exception:
            m["global_feature_importance"] = []
    return health
