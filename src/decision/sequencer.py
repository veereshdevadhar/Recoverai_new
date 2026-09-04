from __future__ import annotations

"""Adaptive Multi-Step Recovery Sequencer.

Runs the *real* Decision Agent repeatedly against an evolving payment
context, re-checking guardrails at every step, until a terminal outcome is
reached or a hard stopping rule fires. Nothing about the sequence of actions
is hardcoded: each step independently scores every action, applies
guardrails and picks the highest expected-value allowed action, exactly like
a single `/predict` call. Only the context passed into that call evolves
between steps (retry count increases, elapsed time increases, actions that
already failed twice in this sequence become ineligible).

Two independent safeguards prevent infinite loops:
  1. A hard cap on the number of steps (``MAX_STEPS``).
  2. Per-action exhaustion: once an action has failed twice within one
     sequence, it is added to the guardrail-blocked set for the rest of the
     sequence, so the agent cannot keep re-selecting a losing action.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import uuid

from src.db import repository as db_repo

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "data" / "runtime"

MAX_STEPS = 5
MAX_ATTEMPTS_PER_ACTION = 2

# Terminal states that end the sequence immediately (no further steps needed).
TERMINAL_STATES = {"RECOVERED", "STOPPED", "ESCALATED"}


def sequence_records(limit: int = 50) -> list[dict[str, Any]]:
    return db_repo.list_sequences(limit)


def get_sequence(sequence_id: str) -> dict[str, Any] | None:
    return db_repo.get_sequence(sequence_id)


def _wrap_guardrail_with_exhaustion(
    base_guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    exhausted: set[str],
) -> Callable[[Any], dict[str, dict[str, Any]]]:
    def wrapped(payload: Any) -> dict[str, dict[str, Any]]:
        result = base_guardrail_engine(payload)
        for action in exhausted:
            if action in result and result[action]["allowed"]:
                result[action] = {
                    "allowed": False,
                    "reasons": result[action]["reasons"] + [
                        f"Exhausted within this recovery sequence after {MAX_ATTEMPTS_PER_ACTION} attempts."
                    ],
                    "severity": "block",
                }
        return result
    return wrapped


def run_sequence(
    payload_cls: Callable[..., Any],
    initial_payload: Any,
    score_event: Callable[[Any], dict[str, Any]],
    base_guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    execute_bounded_workflow: Callable[[Any, dict[str, Any], Callable], dict[str, Any]],
    max_steps: int = MAX_STEPS,
) -> dict[str, Any]:
    sequence_id = f"SEQ-{uuid.uuid4().hex[:10].upper()}"
    started_at = datetime.now(timezone.utc).isoformat()

    context = initial_payload.model_dump()
    attempts: dict[str, int] = {}
    steps: list[dict[str, Any]] = []
    stop_reason = None
    total_recovered = 0.0
    total_cost = 0.0

    for step_number in range(1, max_steps + 1):
        exhausted = {a for a, n in attempts.items() if n >= MAX_ATTEMPTS_PER_ACTION}
        guardrail_engine = _wrap_guardrail_with_exhaustion(base_guardrail_engine, exhausted)

        payload = payload_cls(**context)

        # Re-run the *real* decision agent from scratch, using score_event's
        # own scoring but with the exhaustion-aware guardrail engine. We call
        # the module-level score_event, which internally uses the standard
        # guardrail engine, so for sequencing we replicate the same decision
        # path directly here with the wrapped guardrail engine.
        decision = score_event(payload, guardrail_engine)

        execution = execute_bounded_workflow(payload, decision, guardrail_engine)

        action = decision["recommended_action"]
        attempts[action] = attempts.get(action, 0) + 1

        expected_probability = decision.get("probabilities", {}).get(action)
        expected_recovery = decision.get("expected_revenue", {}).get(action)
        intervention_cost = decision.get("action_costs", {}).get(action, 0.0)
        recovered_this_step = float(execution.get("revenue_recovered", 0.0) or 0.0)
        total_recovered += recovered_this_step
        if execution["state"] not in {"SCHEDULED"}:
            total_cost += intervention_cost

        step_record = {
            "step_number": step_number,
            "context_snapshot": {
                "retry_count": context["retry_count"],
                "previous_attempt_hours": context["previous_attempt_hours"],
                "failure_type": context["failure_type"],
            },
            "decision_id": decision["decision_id"],
            "execution_id": execution["execution_id"],
            "action": action,
            "expected_probability": round(expected_probability, 4) if expected_probability is not None else None,
            "expected_recovery": round(expected_recovery, 2) if expected_recovery is not None else None,
            "intervention_cost": intervention_cost,
            "execution_state": execution["state"],
            "execution_outcome": execution["outcome"],
            "revenue_recovered": recovered_this_step,
            "reason": decision.get("reason"),
        }
        steps.append(step_record)

        state = execution["state"]
        if state in TERMINAL_STATES:
            stop_reason = {
                "RECOVERED": "Payment recovered — sequence complete.",
                "STOPPED": "Policy selected STOP as the safe fallback — sequence complete.",
                "ESCALATED": "Case escalated to a human agent — sequence hands off here.",
            }[state]
            break
        if execution["outcome"] == "BLOCKED_BY_GUARDRAIL":
            stop_reason = "Execution-time guardrail recheck blocked the action — sequence halted for safety."
            break

        # Non-terminal: FAILED (simulated recovery attempt failed) or SCHEDULED
        # (a retry was scheduled). Either way we advance the clock and try
        # again on the next step, unless we've hit the hard step cap.
        context["retry_count"] = min(10, context["retry_count"] + 1)
        context["previous_attempt_hours"] = context["previous_attempt_hours"] + 6.0

        if step_number == max_steps:
            # Hard stopping rule: force a safe STOP rather than looping forever.
            forced_payload = payload_cls(**context)
            forced_guardrail_engine = _wrap_guardrail_with_exhaustion(
                base_guardrail_engine, {a for a, n in attempts.items() if n >= MAX_ATTEMPTS_PER_ACTION}
            )
            forced_decision = {
                "decision_id": f"DEC-{uuid.uuid4().hex[:10].upper()}",
                "recommended_action": "STOP",
                "probabilities": {},
                "expected_revenue": {"STOP": 0.0},
                "action_costs": {"STOP": 0.0},
                "reason": "Maximum recovery sequence steps reached; forcing the safe STOP fallback.",
            }
            forced_execution = execute_bounded_workflow(forced_payload, forced_decision, forced_guardrail_engine)
            steps.append({
                "step_number": step_number + 1,
                "context_snapshot": {
                    "retry_count": context["retry_count"],
                    "previous_attempt_hours": context["previous_attempt_hours"],
                    "failure_type": context["failure_type"],
                },
                "decision_id": forced_decision["decision_id"],
                "execution_id": forced_execution["execution_id"],
                "action": "STOP",
                "expected_probability": None,
                "expected_recovery": 0.0,
                "intervention_cost": 0.0,
                "execution_state": forced_execution["state"],
                "execution_outcome": forced_execution["outcome"],
                "revenue_recovered": 0.0,
                "reason": forced_decision["reason"],
            })
            stop_reason = "Maximum recovery steps reached (stopping rule) — forced safe STOP."

    record = {
        "sequence_id": sequence_id,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "initial_context": {
            "event_type": initial_payload.event_type,
            "amount": initial_payload.amount,
            "failure_type": initial_payload.failure_type,
        },
        "steps": steps,
        "step_count": len(steps),
        "stop_reason": stop_reason or "Sequence ended.",
        "total_revenue_recovered": round(total_recovered, 2),
        "total_intervention_cost": round(total_cost, 2),
        "net_recovery": round(total_recovered - total_cost, 2),
        "final_state": steps[-1]["execution_state"] if steps else None,
    }
    db_repo.insert_sequence(record)
    return record
