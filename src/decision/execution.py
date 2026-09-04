from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import uuid
from typing import Any, Callable

from src.db import repository as db_repo
from src.integrations import execute as execute_external, status as integration_status
from src.voice import generate_hinglish_script

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "data" / "runtime"

TERMINAL = {"RECOVERED", "FAILED", "STOPPED", "ESCALATED", "EXECUTED", "NOT_AVAILABLE"}


def execution_records(limit: int = 50) -> list[dict[str, Any]]:
    return db_repo.get_executions(limit)


def _stable_success(decision_id: str, action: str, probability: float) -> bool:
    """Deterministic local execution simulation; never calls an external API."""
    digest = hashlib.sha256(f"{decision_id}:{action}".encode()).hexdigest()
    draw = int(digest[:12], 16) / float(16**12)
    return draw < max(0.0, min(1.0, probability))


def execute_bounded_workflow(
    payload: Any,
    decision: dict[str, Any],
    guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    live: bool = False,
    channel: str = "auto",
    selected_action: str | None = None,
    simulation_success: bool | None = None,
) -> dict[str, Any]:
    """Execute the selected intervention in a bounded *simulation*.

    The execution layer deliberately re-checks guardrails so a stale or tampered
    decision cannot bypass policy. No real payment, email, SMS, or human system is
    contacted; the execution is an auditable local simulation suitable for the
    synthetic hackathon environment.
    """
    execution_id = f"EXE-{uuid.uuid4().hex[:10].upper()}"
    decision_id = decision["decision_id"]
    recommended_action = decision["recommended_action"]
    action = selected_action or recommended_action
    if action not in {"STOP", "ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION"}:
        raise RuntimeError(f"Unsupported execution action: {action}")
    # Integration-test selection is independent of the AI recommendation. The
    # selected action is intentionally allowed to differ from the recommendation;
    # the authoritative policy check happens below against the current payload.
    # This avoids stale decision.guardrails state preventing a valid test action.
    now = datetime.now(timezone.utc).isoformat()

    # Live idempotency: never create a second external side effect for the same
    # decision/action pair. This protects against double-clicks and retries.
    if live and integration_status().get("environment") == "PRODUCTION":
        if str(__import__("os").getenv("RECOVERAI_PRODUCTION_EXECUTION_ARMED", "0")).strip().lower() not in {"1", "true", "yes", "on"}:
            raise RuntimeError("LIVE PRODUCTION execution is disarmed. Explicitly arm production before executing real recovery actions.")
    if live:
        existing = db_repo.find_existing_live_execution(decision_id, action)
        if existing is not None:
            existing["idempotent_replay"] = True
            existing["outcome_reason"] = "Existing live execution returned; no second provider call was made."
            return existing
        stats = db_repo.get_live_execution_stats_today()
        safety = integration_status()
        if float(payload.amount) > float(safety["max_live_amount"]):
            raise RuntimeError(f"Live amount exceeds safety limit ₹{safety['max_live_amount']:,.2f}.")
        projected_cost = float(decision.get("action_costs", {}).get(action, 0.0) or 0.0)
        if stats["intervention_cost"] + projected_cost > float(safety["daily_live_budget"]):
            raise RuntimeError("Daily live intervention budget exhausted; execution blocked.")

    expected_probability = decision.get("probabilities", {}).get(action)
    expected_recovery = decision.get("expected_revenue", {}).get(action)
    intervention_cost = decision.get("action_costs", {}).get(action, 0.0)

    record: dict[str, Any] = {
        "execution_id": execution_id,
        "decision_id": decision_id,
        "timestamp": now,
        "execution_mode": "LIVE_EXTERNAL" if live else "SIMULATED_BOUNDED",
        "environment": integration_status().get("environment", "DEMO") if live else "DEMO",
        "state_history": [
            {"state": "DETECTED", "timestamp": now},
            {"state": "DECIDED", "timestamp": now},
            {"state": "EXECUTING", "timestamp": now},
        ],
        "action": action,
        "recommended_action": recommended_action,
        "selection_source": "INTEGRATION_TEST" if selected_action else "AI_RECOMMENDATION",
        "amount": float(payload.amount),
        "event_type": payload.event_type,
        "reason": decision.get("reason", ""),
        "expected_probability": round(expected_probability, 4) if expected_probability is not None else None,
        "expected_recovery": round(expected_recovery, 2) if expected_recovery is not None else None,
        "intervention_cost": intervention_cost,
        "simulation_outcome_override": simulation_success,
    }

    # Second policy check at execution time is intentional.
    guardrails = guardrail_engine(payload)
    policy = guardrails.get(action, {"allowed": False, "reasons": ["Unknown action"]})
    record["execution_guardrail"] = policy

    if not policy["allowed"]:
        record["state"] = "FAILED"
        record["outcome"] = "BLOCKED_BY_GUARDRAIL"
        record["outcome_reason"] = "Execution-time policy recheck blocked the selected action."
    elif action == "STOP":
        record["state"] = "STOPPED"
        record["outcome"] = "STOPPED_BY_POLICY"
        record["outcome_reason"] = "Safe fallback: no permitted positive-value recovery intervention was selected."
    elif action in {"HUMAN_ESCALATION", "RETRY_LATER", "ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER"}:
        probability = float(decision.get("probabilities", {}).get(action, 0.0))
        integration_payload = {
            "event_id": getattr(payload, "event_id", None),
            "amount": float(payload.amount),
            "currency": getattr(payload, "currency", "INR"),
            "email": getattr(payload, "email", None),
            "phone": getattr(payload, "phone", None),
            "event_type": getattr(payload, "event_type", "PAYMENT_FAILURE"),
            "failure_type": getattr(payload, "failure_type", None),
            "subject": "RecoverAI payment recovery reminder",
            "body": f"Please complete your payment of INR {float(payload.amount):,.2f}.",
            "description": f"RecoverAI recovery for {getattr(payload, 'event_id', decision_id)}",
            "action": action,
            "execution_id": execution_id,
        }
        if channel == "voice":
            record["voice"] = generate_hinglish_script(
                action=action,
                amount=float(payload.amount),
                event_type=integration_payload["event_type"],
                failure_type=integration_payload["failure_type"],
                seed=execution_id,
            )
        if live:
            integration = execute_external(action, integration_payload, channel=channel)
            record["integration"] = integration
            if integration.get("status") == "SUCCEEDED" and isinstance(integration.get("response"), dict):
                provider_response = integration["response"]
                if provider_response.get("short_url"):
                    record["payment_link"] = {
                        "id": provider_response.get("id"),
                        "short_url": provider_response.get("short_url"),
                        "status": provider_response.get("status", "created"),
                        "amount": float(provider_response.get("amount", round(float(payload.amount) * 100))) / 100.0,
                        "currency": provider_response.get("currency", "INR"),
                        "reference_id": provider_response.get("reference_id"),
                    }
            if integration.get("status") == "SUCCEEDED":
                record["state"] = "SCHEDULED" if action == "RETRY_LATER" else "ESCALATED" if action == "HUMAN_ESCALATION" else "EXECUTED"
                record["outcome"] = "LIVE_PROVIDER_ACCEPTED"
                record["revenue_recovered"] = 0.0
                record["outcome_reason"] = "External provider accepted the intervention; revenue recovery is still unverified until a payment/provider status event confirms success."
            elif integration.get("status") == "NOT_AVAILABLE":
                record["state"] = "NOT_AVAILABLE"
                record["outcome"] = "CHANNEL_NOT_CONFIGURED"
                record["revenue_recovered"] = 0.0
                record["outcome_reason"] = integration.get("message", "This delivery channel is not configured in the current environment.")
            else:
                record["state"] = "FAILED"
                record["outcome"] = "EXTERNAL_PROVIDER_FAILED"
                record["revenue_recovered"] = 0.0
                record["outcome_reason"] = integration.get("error", "External provider rejected the recovery intervention.")
        else:
            if action == "HUMAN_ESCALATION":
                record["state"] = "ESCALATED"
                record["outcome"] = "CASE_CREATED"
                record["outcome_reason"] = "Bounded human-escalation case created in simulation."
                record["revenue_recovered"] = 0.0
            elif action == "RETRY_LATER":
                record["state"] = "SCHEDULED"
                record["outcome"] = "RETRY_SCHEDULED"
                record["outcome_reason"] = "Retry scheduled in the local simulation without an immediate payment attempt."
                record["revenue_recovered"] = 0.0
            else:
                success = (
                    bool(simulation_success)
                    if simulation_success is not None
                    else _stable_success(decision_id, action, probability)
                )
                if success:
                    record["state"] = "RECOVERED"
                    record["outcome"] = "SIMULATED_RECOVERY_SUCCESS"
                    record["revenue_recovered"] = float(payload.amount)
                    record["outcome_reason"] = f"Bounded simulation succeeded at model probability {probability:.3f}."
                else:
                    record["state"] = "FAILED"
                    record["outcome"] = "SIMULATED_RECOVERY_FAILED"
                    record["revenue_recovered"] = 0.0
                    record["outcome_reason"] = f"Bounded simulation did not recover the payment at model probability {probability:.3f}."

    record["state_history"].append({"state": record["state"], "timestamp": datetime.now(timezone.utc).isoformat()})
    record["terminal"] = record["state"] in TERMINAL or record["state"] == "SCHEDULED"
    record["net_recovery"] = round(float(record.get("revenue_recovered", 0.0) or 0.0) - intervention_cost, 2)
    db_repo.insert_execution(record)
    return record
