from __future__ import annotations

"""Isolated NovaCart merchant/payment-stack simulation.

The simulator is the business world around RecoverAI.  It deliberately reuses
RecoverAI's real Decision Agent, guardrails and bounded execution layer while
keeping every payment and customer interaction synthetic.

The important invariant is the closed event loop:

  simulated PSP -> payment event -> RecoverAI -> recovery action
  -> simulated customer/payment response -> simulated PSP -> payment event
  -> RecoverAI verification -> order/revenue state.

No path in this module can invoke LIVE execution.
"""

import hashlib
import random
import threading
import uuid
from functools import wraps
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CUSTOMERS_PATH = ROOT / "data" / "raw" / "customers.csv"

PRODUCTS = [
    {"id": "PRD_HEADPHONES", "name": "Wireless Headphones", "price": 8999.0},
    {"id": "PRD_SMARTWATCH", "name": "Smart Watch", "price": 12499.0},
    {"id": "PRD_LAPTOP", "name": "Ultrabook Laptop", "price": 64999.0},
    {"id": "PRD_SHOES", "name": "Running Shoes", "price": 3499.0},
    {"id": "PRD_SPEAKER", "name": "Bluetooth Speaker", "price": 2299.0},
    {"id": "PRD_BACKPACK", "name": "Travel Backpack", "price": 1899.0},
]

FAILURE_TYPES = ["TIMEOUT", "NETWORK_ERROR", "BANK_TECHNICAL_ERROR", "INSUFFICIENT_BALANCE", "ISSUER_DECLINE"]
PAYMENT_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
BASE_FAILURE_RATE = {"UPI": 0.16, "CARD": 0.13, "NETBANKING": 0.20, "WALLET": 0.11}

INCIDENTS = {
    "UPI_DEGRADATION": {"label": "UPI provider degradation", "method": "UPI", "multiplier": 4.2, "failure_type": "TIMEOUT"},
    "CARD_SPIKE": {"label": "Card issuer decline spike", "method": "CARD", "multiplier": 3.5, "failure_type": "ISSUER_DECLINE"},
    "BANK_TIMEOUT": {"label": "Netbanking bank-side timeout", "method": "NETBANKING", "multiplier": 3.8, "failure_type": "BANK_TECHNICAL_ERROR"},
    "GATEWAY_DEGRADATION": {"label": "Payment gateway degradation (all methods)", "method": None, "multiplier": 2.4, "failure_type": "NETWORK_ERROR"},
}


# ----------------------------- data/state ---------------------------------

def _load_customers() -> pd.DataFrame:
    df = pd.read_csv(CUSTOMERS_PATH)
    return df.sample(n=min(60, len(df)), random_state=7).reset_index(drop=True)


@dataclass
class SimState:
    # RLock is intentional: a simulation tick may advance a scheduled recovery
    # and call the same purchase/payment primitives without deadlocking.
    lock: threading.RLock = field(default_factory=threading.RLock)
    # Serialize high-level simulator mutations so continuous ticks, reset,
    # deterministic scenarios, and the full demo cannot race on shared state.
    operation_lock: threading.RLock = field(default_factory=threading.RLock)
    customers: pd.DataFrame = field(default_factory=_load_customers)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    active_incident: str | None = None
    rng: random.Random = field(default_factory=lambda: random.Random(2026))
    order_seq: int = 92800
    simulation_tick: int = 0
    pending_recoveries: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Presentation clock for the simulated event stream. This is deliberately
    # separate from wall-clock time so high-speed simulation still has a
    # believable, strictly ordered timeline with millisecond precision.
    timeline_clock: datetime | None = None
    timeline_speed: int = 1
    simulation_generation: int = 0


STATE = SimState()


def serialized_operation(fn):
    """Serialize high-level simulator mutations without changing the API/UI."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with STATE.operation_lock:
            return fn(*args, **kwargs)
    return wrapper


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Base simulated latency between event types at 1x. The latency is scaled by
# the simulator speed, but never below 5 ms, so events remain visibly ordered
# even at 20x. This affects presentation timestamps only; it does not sleep or
# delay the backend request.
_TIMELINE_LATENCY_MS = {
    "SIMULATION_RESET": 0,
    "ORDER_CREATED": 120,
    "CHECKOUT_STARTED": 180,
    "PAYMENT_ATTEMPTED": 240,
    "PAYMENT_FAILED": 220,
    "PAYMENT_SUCCESS": 260,
    "RECOVERAI_EVENT_RECEIVED": 180,
    "RECOVERAI_DIAGNOSIS": 220,
    "RECOVERY_DECISION": 220,
    "RECOVERY_ACTION_STARTED": 180,
    "SCENARIO_OUTCOME_LOCKED": 80,
    "RECOVERY_CUSTOMER_RESPONSE": 900,
    "RECOVERY_SCHEDULED": 120,
    "RECOVERY_RESUMED": 700,
    "HUMAN_CASE_RESOLVED": 800,
    "RECOVERAI_VERIFICATION_RECEIVED": 160,
    "RECOVERY_VERIFIED": 160,
    "RECOVERY_ATTEMPT_FAILED": 180,
    "ORDER_PAID": 120,
}


def _timeline_timestamp(event_type: str) -> str:
    now = datetime.now(timezone.utc)
    if STATE.timeline_clock is None:
        STATE.timeline_clock = now
    if event_type != "SIMULATION_RESET":
        base_ms = _TIMELINE_LATENCY_MS.get(event_type, 100)
        speed = max(1, min(20, int(STATE.timeline_speed or 1)))
        delta_ms = max(5, round(base_ms / speed))
        STATE.timeline_clock = STATE.timeline_clock + pd.Timedelta(milliseconds=delta_ms).to_pytimedelta()
    else:
        STATE.timeline_clock = now
    return STATE.timeline_clock.isoformat(timespec="milliseconds")


def _emit(order_id: str | None, event_type: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "event_id": f"MSIM-{uuid.uuid4().hex[:10].upper()}",
        "timestamp": _timeline_timestamp(event_type),
        "merchant_id": "NOVACART-SIM",
        "event_type": event_type,
        "order_id": order_id,
        "detail": detail or {},
    }
    STATE.events.append(row)
    STATE.events[:] = STATE.events[-400:]
    return row


@serialized_operation
def reset() -> dict[str, Any]:
    with STATE.lock:
        STATE.orders.clear()
        STATE.events.clear()
        STATE.active_incident = None
        STATE.order_seq = 92800
        STATE.simulation_tick = 0
        STATE.pending_recoveries.clear()
        STATE.rng = random.Random(2026)
        STATE.timeline_clock = datetime.now(timezone.utc)
        STATE.timeline_speed = 1
        STATE.simulation_generation += 1
    _emit(None, "SIMULATION_RESET", {"merchant": "NovaCart"})
    return {"status": "RESET", "merchant": "NovaCart"}


def list_customers() -> list[dict[str, Any]]:
    rows = STATE.customers.to_dict("records")
    return [{
        "customer_id": r["customer_id"],
        "preferred_payment_method": r["preferred_payment_method"],
        "historical_success_rate": round(float(r["historical_success_rate"]), 3),
        "total_transactions": int(r["total_transactions"]),
        "avg_transaction_amount": round(float(r["avg_transaction_amount"]), 2),
    } for r in rows]


def get_customer_row(customer_id: str) -> dict[str, Any] | None:
    match = STATE.customers[STATE.customers.customer_id == customer_id]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def customer_orders(customer_id: str) -> list[dict[str, Any]]:
    return [o for o in STATE.orders.values() if o["customer_id"] == customer_id]


def list_products() -> list[dict[str, Any]]:
    return PRODUCTS


def list_orders(limit: int = 50) -> list[dict[str, Any]]:
    return list(STATE.orders.values())[-limit:][::-1]


def get_order(order_id: str) -> dict[str, Any] | None:
    return STATE.orders.get(order_id)


def get_timeline(limit: int = 80) -> list[dict[str, Any]]:
    return STATE.events[-limit:][::-1]


@serialized_operation
def inject_incident(kind: str | None) -> dict[str, Any]:
    if kind is not None and kind not in INCIDENTS:
        raise ValueError(f"Unknown incident: {kind}")
    with STATE.lock:
        STATE.active_incident = kind
    if kind is None:
        _emit(None, "INCIDENT_CLEARED", {})
        return {"active_incident": None}
    info = INCIDENTS[kind]
    _emit(None, "INCIDENT_INJECTED", {"incident": kind, **info})
    return {"active_incident": kind, **info}


def _failure_probability(method: str) -> tuple[float, str]:
    base = BASE_FAILURE_RATE.get(method, 0.15)
    failure_type = STATE.rng.choice(FAILURE_TYPES)
    if STATE.active_incident:
        info = INCIDENTS[STATE.active_incident]
        if info["method"] is None or info["method"] == method:
            base = min(0.95, base * info["multiplier"])
            failure_type = info["failure_type"]
    return base, failure_type


def dashboard() -> dict[str, Any]:
    orders = list(STATE.orders.values())
    attempts = sum(len(o["payment_attempts"]) for o in orders)
    successes = sum(1 for o in orders if o["status"] == "PAID")
    failed_orders = [o for o in orders if o["status"] in ("PAYMENT_FAILED", "LOST")]
    abandoned = sum(1 for o in orders if o["status"] == "ABANDONED")
    revenue_recovered = sum(o["amount"] for o in orders if o.get("recovered"))
    revenue_at_risk = sum(o["amount"] for o in orders if o["status"] in ("PAYMENT_FAILED", "RECOVERY_IN_PROGRESS"))
    gmv = sum(o["amount"] for o in orders if o["status"] == "PAID")
    active_recoveries = sum(1 for o in orders if o["status"] == "RECOVERY_IN_PROGRESS")
    return {
        "merchant": "NovaCart",
        "label": "Simulated E-commerce Merchant",
        "gmv": round(gmv, 2),
        "payment_attempts": attempts,
        "successful_payments": successes,
        "failed_payments": len(failed_orders),
        "checkout_abandonments": abandoned,
        "revenue_at_risk": round(revenue_at_risk, 2),
        "recovered_revenue": round(revenue_recovered, 2),
        "active_recoveries": active_recoveries,
        "total_orders": len(orders),
        "active_incident": STATE.active_incident,
        "simulation_tick": STATE.simulation_tick,
        "pending_recoveries": len(STATE.pending_recoveries),
        # Callers (continuous simulation ticks in particular) can pass this
        # value back on their next mutation request so a tick dispatched
        # before a reset/full-demo cannot land its mutation afterward. See
        # `tick()` below.
        "simulation_generation": STATE.simulation_generation,
    }


# ------------------------- simulated payment stack ------------------------

def _new_order(customer_id: str, product_id: str) -> dict[str, Any]:
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if product is None:
        raise ValueError(f"Unknown product: {product_id}")
    customer = get_customer_row(customer_id)
    if customer is None:
        raise ValueError(f"Unknown customer: {customer_id}")
    STATE.order_seq += 1
    order_id = f"ORD{STATE.order_seq}"
    order = {
        "order_id": order_id,
        "merchant_id": "NOVACART-SIM",
        "customer_id": customer_id,
        "product_id": product["id"],
        "product_name": product["name"],
        "amount": product["price"],
        "currency": "INR",
        "status": "CHECKOUT_STARTED",
        "created_at": _now(),
        "payment_attempts": [],
        "payment_state": "CREATED",
        "state_history": [{"state": "CREATED", "timestamp": _now()}],
        "decision": None,
        "execution": None,
        "recovered": False,
        "recovery_action": None,
        "recovery_attempts": 0,
    }
    STATE.orders[order_id] = order
    _emit(order_id, "ORDER_CREATED", {"customer_id": customer_id, "product": product["name"], "amount": product["price"]})
    _emit(order_id, "CHECKOUT_STARTED", {"amount": product["price"]})
    return order


def _set_order_state(order: dict[str, Any], state: str) -> None:
    order["payment_state"] = state
    order["state_history"].append({"state": state, "timestamp": _now()})


def _payment_event_detail(attempt: dict[str, Any], **extra: Any) -> dict[str, Any]:
    data = {
        "payment_attempt_id": attempt["payment_attempt_id"],
        "attempt_no": attempt["attempt_no"],
        "method": attempt["method"],
        "status": attempt["status"],
        "payment_event_id": attempt["event_id"],
    }
    if attempt.get("failure_type"):
        data["failure_type"] = attempt["failure_type"]
    data.update(extra)
    return data


def _attempt_payment(order: dict[str, Any], method: str, force_fail: bool = False, reason: str = "CUSTOMER_CHECKOUT", force_success: bool = False) -> bool:
    """Simulated PSP operation. Every attempt produces a unique payment event."""
    method = str(method).upper()
    if method not in PAYMENT_METHODS:
        raise ValueError(f"Unsupported payment method: {method}")
    order["status"] = "PAYMENT_PENDING"
    _set_order_state(order, "ATTEMPTED")
    prob_fail, failure_type = _failure_probability(method)
    succeeded = (not force_fail) and (force_success or STATE.rng.random() > prob_fail)
    attempt_no = len(order["payment_attempts"]) + 1
    attempt = {
        "payment_attempt_id": f"PAY-{uuid.uuid4().hex[:10].upper()}",
        "attempt_no": attempt_no,
        "method": method,
        "status": "SUCCESS" if succeeded else "FAILED",
        "failure_type": None if succeeded else failure_type,
        "timestamp": _now(),
        "reason": reason,
        "event_id": f"PAYEVT-{uuid.uuid4().hex[:10].upper()}",
    }
    order["payment_attempts"].append(attempt)
    attempt_event = _emit(order["order_id"], "PAYMENT_ATTEMPTED", _payment_event_detail(attempt))
    # Keep the order-inspector attempt timestamp aligned with the same
    # millisecond-resolution simulated clock used by the live event timeline.
    attempt["timestamp"] = attempt_event["timestamp"]
    if succeeded:
        _set_order_state(order, "SUCCESS")
        _emit(order["order_id"], "PAYMENT_SUCCESS", _payment_event_detail(attempt))
    else:
        _set_order_state(order, "FAILED")
        _emit(order["order_id"], "PAYMENT_FAILED", _payment_event_detail(attempt))
    return succeeded


def _build_payment_event_payload(order: dict[str, Any], method: str, failure_type: str | None, event_id: str | None = None, event_type: str = "PAYMENT_FAILURE"):
    """Build the exact PaymentEvent shape consumed by Decision Lab."""
    from src.api.main import PaymentEvent

    customer = get_customer_row(order["customer_id"])
    retry_count = sum(1 for a in order["payment_attempts"] if a["status"] == "FAILED") - 1
    return PaymentEvent(
        event_id=event_id or order["order_id"],
        amount=order["amount"],
        event_type=event_type,
        payment_method=method,
        failure_type=failure_type,
        retry_count=max(0, retry_count),
        total_transactions=int(customer["total_transactions"]),
        avg_transaction_amount=float(customer["avg_transaction_amount"]),
        historical_success_rate=float(customer["historical_success_rate"]),
        customer_tenure_days=float(customer["customer_tenure_days"]),
        previous_recovery_success_rate=float(customer["previous_recovery_success_rate"]),
        days_since_last_success=float(customer["days_since_last_success"]),
        preferred_payment_method=str(customer["preferred_payment_method"]),
        merchant_category="E_COMMERCE",
        merchant_size="MEDIUM",
        merchant_avg_transaction_amount=6500.0,
        phone="+919900000000",
        email=f"{order['customer_id'].lower()}@novacart.example",
    )


def _stable_bool(key: str, probability: float) -> bool:
    digest = hashlib.sha256(key.encode()).hexdigest()
    draw = int(digest[:12], 16) / float(16 ** 12)
    return draw < max(0.0, min(1.0, probability))


def _alternate_method(order: dict[str, Any], original_method: str) -> str:
    customer = get_customer_row(order["customer_id"])
    preferred = str(customer["preferred_payment_method"]).upper() if customer is not None else "CARD"
    candidates = [preferred, "CARD", "UPI", "NETBANKING", "WALLET"]
    for candidate in candidates:
        if candidate in PAYMENT_METHODS and candidate != original_method:
            return candidate
    return "CARD"


# ------------------------- RecoverAI integration --------------------------

def _run_recovery(order: dict[str, Any], method: str, failure_type: str, event_id: str | None = None, deterministic_demo: bool = False) -> dict[str, Any]:
    """Hand the failed payment event to the REAL RecoverAI pipeline."""
    from src.api.main import score_event, apply_guardrails
    from src.decision.execution import execute_bounded_workflow

    payload = _build_payment_event_payload(order, method, failure_type, event_id=event_id)
    _emit(order["order_id"], "RECOVERAI_EVENT_RECEIVED", {
        "payment_event_id": payload.event_id,
        "amount": order["amount"],
        "method": method,
        "failure_type": failure_type,
    })
    decision = score_event(payload, guardrail_engine=apply_guardrails, persist=True)
    _emit(order["order_id"], "RECOVERAI_DIAGNOSIS", {
        "reason": decision.get("reason"),
        "ranked_top": decision.get("recommended_action"),
    })
    _emit(order["order_id"], "RECOVERY_DECISION", {
        "decision_id": decision.get("decision_id"),
        "action": decision["recommended_action"],
        "confidence": decision.get("decision_confidence"),
    })
    order["decision"] = decision
    order["recovery_action"] = decision["recommended_action"]
    _emit(order["order_id"], "RECOVERY_ACTION_STARTED", {
        "action": decision["recommended_action"],
        "decision_id": decision.get("decision_id"),
    })
    # HARD SAFETY BOUNDARY: the Merchant Simulator can never reach LIVE.
    if deterministic_demo:
        _emit(order["order_id"], "SCENARIO_OUTCOME_LOCKED", {
            "mode": "DETERMINISTIC_DEMO",
            "reason": "The one-click presentation scenario locks only the bounded simulation outcome; the real Decision Agent and guardrails still determine the action."
        })
    execution = execute_bounded_workflow(
        payload,
        decision,
        apply_guardrails,
        live=False,
        channel="auto",
        simulation_success=True if deterministic_demo else None,
    )
    return execution


def _verify_payment_success(order: dict[str, Any], attempt: dict[str, Any], action: str, execution: dict[str, Any]) -> bool:
    """Send the simulated PSP success event back through RecoverAI.

    `score_event` has an explicit PAYMENT_SUCCESS path that produces a STOP
    decision and records that no further recovery is required. We use that same
    path as the simulator's authoritative verification acknowledgement.
    """
    from src.api.main import score_event, apply_guardrails

    payload = _build_payment_event_payload(
        order,
        attempt["method"],
        None,
        event_id=attempt["event_id"],
        event_type="PAYMENT_SUCCESS",
    )
    _emit(order["order_id"], "RECOVERAI_VERIFICATION_RECEIVED", {
        "payment_event_id": attempt["event_id"],
        "payment_attempt_id": attempt["payment_attempt_id"],
        "action": action,
    })
    verification = score_event(payload, guardrail_engine=apply_guardrails, persist=True)
    verified = verification.get("recommended_action") == "STOP" and "already succeeded" in str(verification.get("reason", "")).lower()
    execution["verification_decision_id"] = verification.get("decision_id")
    execution["payment_event_id"] = attempt["event_id"]
    if verified:
        # Persist the authoritative outcome into the EXISTING RecoverAI revenue
        # ledger. This is the same repository-backed ledger used by the rest
        # of the application; the simulator does not maintain a second ledger.
        from src.db import repository as db_repo
        persisted = db_repo.mark_execution_recovered(
            execution["execution_id"],
            float(order["amount"]),
            verification_event={
                "payment_event_id": attempt["event_id"],
                "payment_attempt_id": attempt["payment_attempt_id"],
                "order_id": order["order_id"],
            },
        )
        if persisted:
            execution.update(persisted)
        execution["verification_state"] = "VERIFIED_RECOVERED"
        execution["payment_event_id"] = attempt["event_id"]
        execution["revenue_recovered"] = float(order["amount"])
    else:
        execution["verification_state"] = "VERIFICATION_FAILED"
        execution["revenue_recovered"] = 0.0
    return verified


def _simulate_recovery_payment(order: dict[str, Any], action: str, original_method: str, execution: dict[str, Any], force_success: bool = False) -> bool:
    """Turn a successful bounded intervention into a real simulated PSP loop.

    The bounded execution says the recovery intervention itself was accepted by
    the simulator. The simulated PSP then performs a NEW payment attempt. Only
    its PAYMENT_SUCCESS event is allowed to move the order to PAID.
    """
    if execution.get("state") != "RECOVERED":
        return False

    if action == "ALTERNATIVE_PAYMENT":
        method = _alternate_method(order, original_method)
        response = "CUSTOMER_SWITCHED_PAYMENT_METHOD"
        _emit(order["order_id"], "RECOVERY_CUSTOMER_RESPONSE", {
            "action": action,
            "response": response,
            "selected_method": method,
        })
    elif action == "RECOVERY_REMINDER":
        method = original_method
        _emit(order["order_id"], "RECOVERY_CUSTOMER_RESPONSE", {
            "action": action,
            "response": "CUSTOMER_RETURNED_TO_CHECKOUT",
            "selected_method": method,
        })
    else:
        return False

    order["recovery_attempts"] += 1
    # The bounded execution has already sampled the model outcome. We keep that
    # outcome authoritative for this synthetic customer response, then let the
    # simulated PSP emit the actual success/failure event.
    succeeded = _attempt_payment(order, method, force_fail=False, reason=f"RECOVERAI_{action}", force_success=force_success)
    if succeeded:
        attempt = order["payment_attempts"][-1]
        verified = _verify_payment_success(order, attempt, action, execution)
        if verified:
            order["status"] = "PAID"
            order["recovered"] = True
            _set_order_state(order, "VERIFIED")
            _emit(order["order_id"], "RECOVERY_VERIFIED", {
                "action": action,
                "payment_event_id": attempt["event_id"],
                "verification": "PAYMENT_SUCCESS_CONFIRMED_BY_RECOVERAI",
            })
            _emit(order["order_id"], "ORDER_PAID", {
                "amount": order["amount"],
                "recovered": True,
                "payment_attempt_id": attempt["payment_attempt_id"],
            })
            return True
        order["status"] = "PAYMENT_FAILED"
        _emit(order["order_id"], "RECOVERY_ATTEMPT_FAILED", {"action": action, "reason": "Payment succeeded at the simulated PSP but RecoverAI verification did not acknowledge the success."})
        return False

    order["status"] = "PAYMENT_FAILED"
    execution["verification_state"] = "VERIFIED_FAILED"
    execution["payment_event_id"] = order["payment_attempts"][-1]["event_id"]
    execution["revenue_recovered"] = 0.0
    _emit(order["order_id"], "RECOVERY_ATTEMPT_FAILED", {
        "action": action,
        "payment_event_id": order["payment_attempts"][-1]["event_id"],
        "reason": "Simulated PSP rejected the recovery payment attempt.",
    })
    return False


def _schedule_recovery(order: dict[str, Any], action: str, original_method: str, execution: dict[str, Any], force_success: bool = False) -> None:
    due = STATE.simulation_tick + (2 if action == "RETRY_LATER" else 3)
    STATE.pending_recoveries[order["order_id"]] = {
        "order_id": order["order_id"],
        "action": action,
        "method": original_method,
        "due_tick": due,
        "execution": execution,
        "force_success": force_success,
    }
    order["status"] = "RECOVERY_IN_PROGRESS"
    _set_order_state(order, "RECOVERY_PENDING")
    _emit(order["order_id"], "RECOVERY_SCHEDULED", {
        "action": action,
        "due_tick": due,
        "simulation_tick": STATE.simulation_tick,
    })


def _process_pending_recoveries(force: bool = False) -> list[str]:
    completed: list[str] = []
    for order_id, pending in list(STATE.pending_recoveries.items()):
        if not force and STATE.simulation_tick < pending["due_tick"]:
            continue
        order = STATE.orders.get(order_id)
        if order is None:
            STATE.pending_recoveries.pop(order_id, None)
            continue
        action = pending["action"]
        _emit(order_id, "RECOVERY_RESUMED", {"action": action, "simulation_tick": STATE.simulation_tick})
        if action == "RETRY_LATER":
            order["recovery_attempts"] += 1
            succeeded = _attempt_payment(order, pending["method"], force_fail=False, reason="RECOVERAI_RETRY", force_success=bool(pending.get("force_success")))
            if succeeded:
                attempt = order["payment_attempts"][-1]
                verified = _verify_payment_success(order, attempt, action, pending["execution"])
                if verified:
                    order["status"] = "PAID"
                    order["recovered"] = True
                    _set_order_state(order, "VERIFIED")
                    _emit(order_id, "RECOVERY_VERIFIED", {"action": action, "payment_event_id": attempt["event_id"], "verification": "PAYMENT_SUCCESS_CONFIRMED_BY_RECOVERAI"})
                    _emit(order_id, "ORDER_PAID", {"amount": order["amount"], "recovered": True})
                else:
                    order["status"] = "PAYMENT_FAILED"
                    _emit(order_id, "RECOVERY_ATTEMPT_FAILED", {"action": action, "reason": "Payment succeeded at the simulated PSP but RecoverAI verification did not acknowledge the success."})
            else:
                order["status"] = "PAYMENT_FAILED"
                pending["execution"]["verification_state"] = "VERIFIED_FAILED"
                pending["execution"]["revenue_recovered"] = 0.0
                _emit(order_id, "RECOVERY_ATTEMPT_FAILED", {"action": action, "reason": "Scheduled retry did not succeed."})
        elif action == "HUMAN_ESCALATION":
            _emit(order_id, "HUMAN_CASE_RESOLVED", {"action": action, "resolution": "CUSTOMER_CONTACTED_IN_SIMULATION"})
            order["recovery_attempts"] += 1
            method = _alternate_method(order, pending["method"])
            succeeded = _attempt_payment(order, method, force_fail=False, reason="SIMULATED_HUMAN_ESCALATION", force_success=bool(pending.get("force_success")))
            if succeeded:
                attempt = order["payment_attempts"][-1]
                verified = _verify_payment_success(order, attempt, action, pending["execution"])
                if verified:
                    order["status"] = "PAID"
                    order["recovered"] = True
                    _set_order_state(order, "VERIFIED")
                    _emit(order_id, "RECOVERY_VERIFIED", {"action": action, "payment_event_id": attempt["event_id"], "verification": "PAYMENT_SUCCESS_CONFIRMED_BY_RECOVERAI"})
                    _emit(order_id, "ORDER_PAID", {"amount": order["amount"], "recovered": True})
                else:
                    order["status"] = "PAYMENT_FAILED"
                    _emit(order_id, "RECOVERY_ATTEMPT_FAILED", {"action": action, "reason": "Payment succeeded at the simulated PSP but RecoverAI verification did not acknowledge the success."})
            else:
                order["status"] = "PAYMENT_FAILED"
                pending["execution"]["verification_state"] = "VERIFIED_FAILED"
                pending["execution"]["revenue_recovered"] = 0.0
                _emit(order_id, "RECOVERY_ATTEMPT_FAILED", {"action": action, "reason": "Simulated customer payment after human escalation failed."})
        STATE.pending_recoveries.pop(order_id, None)
        completed.append(order_id)
    return completed


def _apply_execution_outcome(order: dict[str, Any], execution: dict[str, Any], original_method: str, force_success: bool = False) -> None:
    state = execution.get("state")
    action = execution.get("action")
    if state == "RECOVERED":
        # Important: execution success is NOT itself the payment success. The
        # simulated PSP must produce PAYMENT_SUCCESS, which verification consumes.
        if not _simulate_recovery_payment(order, action, original_method, execution, force_success=force_success):
            if order.get("status") != "PAYMENT_FAILED":
                order["status"] = "PAYMENT_FAILED"
    elif state == "SCHEDULED":
        _schedule_recovery(order, action, original_method, execution, force_success=force_success)
    elif state == "ESCALATED":
        _schedule_recovery(order, action, original_method, execution, force_success=force_success)
        _emit(order["order_id"], "RECOVERY_ESCALATED_TO_HUMAN", {"action": action, "due_tick": STATE.pending_recoveries[order["order_id"]]["due_tick"]})
    elif state == "STOPPED":
        order["status"] = "LOST"
        _set_order_state(order, "STOPPED")
        _emit(order["order_id"], "RECOVERY_STOPPED", {"reason": execution.get("outcome_reason")})
    else:
        order["status"] = "PAYMENT_FAILED"
        _set_order_state(order, "FAILED")
        _emit(order["order_id"], "RECOVERY_ATTEMPT_FAILED", {"action": action, "reason": execution.get("outcome_reason")})


# ------------------------------- public flows -----------------------------

@serialized_operation
def resubmit_failure_event(order_id: str) -> dict[str, Any]:
    """Simulate duplicate delivery of the original failure event."""
    with STATE.lock:
        order = STATE.orders.get(order_id)
        if order is None:
            raise ValueError(f"Unknown order: {order_id}")
        last = order["payment_attempts"][-1] if order["payment_attempts"] else None
        _emit(order_id, "PAYMENT_FAILED", {
            "redelivered": True,
            "payment_event_id": last.get("event_id") if last else None,
        })
        if order.get("decision") is not None:
            _emit(order_id, "DUPLICATE_EVENT_IGNORED", {"reason": "Payment failure already processed by RecoverAI."})
            return order
        if last is None:
            raise ValueError("Order has no payment attempt to redeliver")
        execution = _run_recovery(order, last["method"], last.get("failure_type") or "TIMEOUT", event_id=last.get("event_id"))
        order["execution"] = execution
        _apply_execution_outcome(order, execution, last["method"])
        return order


@serialized_operation
def purchase(customer_id: str, product_id: str, method: str | None = None, force_fail: bool = False) -> dict[str, Any]:
    with STATE.lock:
        order = _new_order(customer_id, product_id)
        customer = get_customer_row(customer_id)
        chosen_method = (method or str(customer["preferred_payment_method"])).upper()
        succeeded = _attempt_payment(order, chosen_method, force_fail=force_fail)
        if succeeded:
            order["status"] = "PAID"
            _emit(order["order_id"], "ORDER_PAID", {"amount": order["amount"], "recovered": False, "payment_attempt_id": order["payment_attempts"][-1]["payment_attempt_id"]})
            return order

        order["status"] = "PAYMENT_FAILED"
        last_attempt = order["payment_attempts"][-1]
        if order.get("decision") is not None:
            _emit(order["order_id"], "DUPLICATE_EVENT_IGNORED", {"reason": "Order already has an active RecoverAI decision."})
            return order
        execution = _run_recovery(order, chosen_method, last_attempt["failure_type"], event_id=last_attempt["event_id"])
        order["execution"] = execution
        _apply_execution_outcome(order, execution, chosen_method)
        return order


@serialized_operation
def abandon_checkout(customer_id: str, product_id: str) -> dict[str, Any]:
    with STATE.lock:
        order = _new_order(customer_id, product_id)
        order["status"] = "ABANDONED"
        _set_order_state(order, "ABANDONED")
        _emit(order["order_id"], "CHECKOUT_ABANDONED", {"customer_id": customer_id, "amount": order["amount"]})
        return order


@serialized_operation
def tick(speed: int = 1, generation: int | None = None) -> dict[str, Any]:
    """Advance real simulated business activity and scheduled recoveries.

    `generation` is the `simulation_generation` the caller last observed
    (e.g. the continuous-simulation loop's last known dashboard read). A
    reset or full demo run bumps `STATE.simulation_generation`. If a tick
    request was already in flight when a reset/full-demo happened, it would
    otherwise still mutate state *after* that reset, leaving stray
    orders/events mixed into what should be a clean post-reset or
    post-full-demo state. When the caller's generation is stale, this tick
    is a safe no-op: it reports the current dashboard without touching
    STATE, and the caller can drop or restart its loop.
    """
    with STATE.lock:
        if generation is not None and generation != STATE.simulation_generation:
            return {
                "orders_touched": [],
                "processed_recoveries": [],
                "dashboard": dashboard(),
                "stale": True,
                "simulation_generation": STATE.simulation_generation,
            }
        n_events = max(1, min(20, speed))
        produced: list[dict[str, Any]] = []
        STATE.timeline_speed = n_events
        for _ in range(n_events):
            STATE.simulation_tick += 1
            _process_pending_recoveries()
            customer = STATE.rng.choice(STATE.customers.to_dict("records"))
            product = STATE.rng.choice(PRODUCTS)
            roll = STATE.rng.random()
            if roll < 0.12:
                produced.append(abandon_checkout(customer["customer_id"], product["id"]))
            else:
                produced.append(purchase(customer["customer_id"], product["id"]))
        _process_pending_recoveries()
    return {
        "orders_touched": [o["order_id"] for o in produced],
        "processed_recoveries": [o["order_id"] for o in STATE.orders.values() if o.get("status") == "PAID" and o.get("recovered")],
        "dashboard": dashboard(),
        "stale": False,
        "simulation_generation": STATE.simulation_generation,
    }


SCENARIO_CUSTOMER_ID = "CUS_000482"


def intelligence_events() -> list[dict[str, Any]]:
    """Return a normalized, pre-action event stream for Revenue Intelligence.

    Only commerce/payment observations available before a recovery decision are
    exported. Recovery-attempt events are deliberately excluded so Autopilot
    cannot learn from the outcome it is about to choose. This keeps the Phase 2
    ingestion path leakage-safe while allowing NovaCart activity to participate
    in anomaly detection, root-cause analysis and customer prioritization.
    """
    rows: list[dict[str, Any]] = []
    with STATE.lock:
        orders = STATE.orders
        for event in STATE.events:
            if event["event_type"] not in {"PAYMENT_FAILED", "PAYMENT_SUCCESS", "CHECKOUT_ABANDONED"}:
                continue
            order = orders.get(event.get("order_id"))
            if order is None:
                continue

            detail = event.get("detail") or {}
            attempt_id = detail.get("payment_attempt_id")
            attempt = next((a for a in order.get("payment_attempts", []) if a.get("payment_attempt_id") == attempt_id), None)

            # Recovery outcomes must not feed the pre-action intelligence
            # layer. Normal first-attempt successes remain valid commerce
            # observations; failures are valid risk observations.
            reason = str((attempt or {}).get("reason", ""))
            if reason.startswith("RECOVERAI_") or reason.startswith("SIMULATED_HUMAN_"):
                continue

            customer = get_customer_row(order["customer_id"]) or {}
            payment_status = "FAILED" if event["event_type"] == "PAYMENT_FAILED" else ("SUCCESS" if event["event_type"] == "PAYMENT_SUCCESS" else "ABANDONED")
            rows.append({
                # Event-time commerce fields only. Customer/merchant attributes
                # are joined from the canonical datasets by Revenue Intelligence.
                "event_id": detail.get("payment_event_id") or event["event_id"],
                "event_type": "PAYMENT_FAILURE" if event["event_type"] == "PAYMENT_FAILED" else ("PAYMENT_SUCCESS" if event["event_type"] == "PAYMENT_SUCCESS" else "CHECKOUT_ABANDONMENT"),
                "timestamp": event["timestamp"],
                "customer_id": order["customer_id"],
                "merchant_id": "NOVACART-SIM",
                "amount": float(order["amount"]),
                "currency": "INR",
                "payment_method": str(detail.get("method") or (attempt or {}).get("method") or customer.get("preferred_payment_method", "UPI")),
                "device_type": "MOBILE",
                "payment_status": payment_status,
                "failure_type": detail.get("failure_type"),
                "retry_count": max(0, int(detail.get("attempt_no", 1)) - 1),
                "previous_attempt_hours": 0.0,
                "checkout_duration_seconds": 60.0,
                "payment_page_reached": 1,
                "payment_attempted": 1 if event["event_type"] != "CHECKOUT_ABANDONED" else 0,
                "subscription_age_days": 0.0,
                "successful_cycles": 0,
                "failed_cycles": 0,
            })

    return rows


@serialized_operation
def run_upi_failure_scenario() -> dict[str, Any]:
    """Deterministic UPI failure scenario with the closed payment/recovery loop."""
    with STATE.lock:
        # Keep the one-click scenario visually readable while still using the
        # same millisecond-resolution simulated clock as continuous mode.
        STATE.timeline_speed = 1
        customer_id = SCENARIO_CUSTOMER_ID if get_customer_row(SCENARIO_CUSTOMER_ID) is not None else STATE.customers.iloc[0]["customer_id"]
        product = PRODUCTS[0]
        order = _new_order(customer_id, product["id"])
        _attempt_payment(order, "UPI", force_fail=True, reason="DETERMINISTIC_SCENARIO")
        order["status"] = "PAYMENT_FAILED"
        last_attempt = order["payment_attempts"][-1]
        execution = _run_recovery(
            order,
            "UPI",
            last_attempt["failure_type"],
            event_id=last_attempt["event_id"],
            deterministic_demo=True,
        )
        order["execution"] = execution
        _apply_execution_outcome(order, execution, "UPI", force_success=True)
        # The scenario is a presentation-grade single click. If the selected
        # action is scheduled, advance only the scheduled recovery phase so the
        # caller receives the complete end-to-end trace in one response.
        if order["order_id"] in STATE.pending_recoveries:
            STATE.simulation_tick = max(STATE.simulation_tick, STATE.pending_recoveries[order["order_id"]]["due_tick"])
            _process_pending_recoveries(force=True)
        return {
            "order": order,
            "timeline": [e for e in STATE.events if e["order_id"] == order["order_id"]],
        }
