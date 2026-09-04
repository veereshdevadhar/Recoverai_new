from __future__ import annotations

"""UPI Mandate Retry Sequencer.

A domain-specific adaptive sequencer for **e-mandate / UPI Autopay debit
failures** — distinct from the generic ad-hoc payment sequencer because
recurring-mandate debits are governed by real RBI rules that ad-hoc card/UPI
payments are not:

  * **AFA threshold (₹15,000)** — RBI requires Additional Factor
    Authentication (an OTP-style approval) for recurring e-mandate debits
    above ₹15,000; below that, banks may debit silently after a mandatory
    pre-debit notice. (RBI raised this from ₹5,000 to ₹15,000 in June 2022;
    specific categories such as mutual funds/insurance/credit-card bills
    were later exempted up to ₹1 lakh — this module applies the general
    ₹15,000 threshold, which is the correct one for a typical subscription
    mandate.) This means a *silent* retry of a >₹15,000 mandate that failed
    for lack of authentication will fail again for the same reason — so the
    correct recovery action is prompting the customer to re-authorize, not
    blindly retrying.
  * **24-hour pre-debit notification** — RBI requires banks to notify the
    customer at least 24 hours before an e-mandate debit attempt, which
    this sequencer models as the minimum gap between mandate retry steps
    (mandate debits run on a scheduled/batch cycle, not on demand).
  * **Retry-cap risk** — repeatedly failing mandate executions are a known
    industry signal that can lead an issuing bank to flag or suspend a
    mandate. This is a widely documented operational convention rather
    than a single cited regulation, so this module applies a
    representative cap (``MAX_MANDATE_RETRIES``) and is explicit that it is
    modeled, not an exact regulatory number.

The underlying action scoring still comes from the same real trained
Decision Agent models — this module only adds a domain-specific guardrail
layer and a different step-advancement rule (24h cooldown, AFA-aware
blocking) on top of that real scoring, exactly like the generic sequencer.
"""

from datetime import datetime, timezone
from typing import Any, Callable
import uuid

from src.db import repository as db_repo

AFA_THRESHOLD = 15000.0
PRE_DEBIT_NOTICE_HOURS = 24.0
MAX_MANDATE_RETRIES = 3
MANDATE_RETRY_COOLDOWN_HOURS = 24.0
MAX_STEPS = 5

TERMINAL_STATES = {"RECOVERED", "STOPPED", "ESCALATED"}


def _mandate_guardrail_engine(
    base_guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    payload: Any,
    requires_afa: bool,
    afa_acknowledged: bool,
    retries_used: int,
) -> dict[str, dict[str, Any]]:
    result = base_guardrail_engine(payload)

    if requires_afa and not afa_acknowledged and result.get("RETRY_LATER", {}).get("allowed"):
        result["RETRY_LATER"] = {
            "allowed": False,
            "reasons": [
                f"Amount exceeds the ₹{AFA_THRESHOLD:,.0f} RBI e-mandate AFA threshold; "
                "a silent retry will fail again without renewed customer authorization."
            ],
            "severity": "block",
        }

    if retries_used >= MAX_MANDATE_RETRIES and result.get("RETRY_LATER", {}).get("allowed"):
        result["RETRY_LATER"] = {
            "allowed": False,
            "reasons": [
                f"Mandate retry cap reached ({MAX_MANDATE_RETRIES} attempts); further silent retries "
                "risk the issuing bank flagging or suspending this mandate."
            ],
            "severity": "block",
        }

    return result


def run_mandate_sequence(
    initial_payload: Any,
    score_event: Callable[[Any, Any], dict[str, Any]],
    base_guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    execute_bounded_workflow: Callable[[Any, dict[str, Any], Callable], dict[str, Any]],
    payload_cls: Callable[..., Any],
) -> dict[str, Any]:
    mandate_sequence_id = f"MND-{uuid.uuid4().hex[:10].upper()}"
    started_at = datetime.now(timezone.utc).isoformat()

    context = initial_payload.model_dump()
    requires_afa = context["amount"] > AFA_THRESHOLD
    afa_acknowledged = False
    retries_used = 0
    failed_attempts = 0  # any non-recovering step, action-agnostic — this is what should
                          # trigger the AFA-reauth branch, since RETRY_LATER itself is
                          # guardrail-blocked while AFA is unresolved and would otherwise
                          # never increment (making that branch unreachable).

    steps: list[dict[str, Any]] = []
    stop_reason = None
    mandate_reauth_required = False
    total_recovered = 0.0
    total_cost = 0.0

    for step_number in range(1, MAX_STEPS + 1):
        guardrail_engine = lambda p, _r=retries_used, _a=afa_acknowledged: _mandate_guardrail_engine(
            base_guardrail_engine, p, requires_afa, _a, _r
        )

        payload = payload_cls(**context)
        decision = score_event(payload, guardrail_engine)
        execution = execute_bounded_workflow(payload, decision, guardrail_engine)

        action = decision["recommended_action"]
        expected_probability = decision.get("probabilities", {}).get(action)
        expected_recovery = decision.get("expected_revenue", {}).get(action)
        intervention_cost = decision.get("action_costs", {}).get(action, 0.0)
        recovered_this_step = float(execution.get("revenue_recovered", 0.0) or 0.0)
        total_recovered += recovered_this_step
        if execution["state"] not in {"SCHEDULED"}:
            total_cost += intervention_cost

        afa_ack_this_step = False
        if action == "RECOVERY_REMINDER" and requires_afa and not afa_acknowledged:
            # Models the assumption that the customer completes the
            # re-authorization link before the next scheduled debit window.
            afa_acknowledged = True
            afa_ack_this_step = True
        if action == "RETRY_LATER":
            retries_used += 1
        if execution["state"] == "FAILED":
            failed_attempts += 1

        steps.append({
            "step_number": step_number,
            "context_snapshot": {
                "retry_count": context["retry_count"],
                "previous_attempt_hours": context["previous_attempt_hours"],
                "requires_afa": requires_afa,
                "afa_acknowledged": afa_acknowledged,
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
            "afa_acknowledged_this_step": afa_ack_this_step,
            "reason": decision.get("reason"),
        })

        state = execution["state"]
        if state in TERMINAL_STATES:
            stop_reason = {
                "RECOVERED": "Mandate debit recovered — sequence complete.",
                "STOPPED": "Policy selected STOP as the safe fallback — sequence complete.",
                "ESCALATED": "Case escalated to a human agent — sequence hands off here.",
            }[state]
            break
        if execution["outcome"] == "BLOCKED_BY_GUARDRAIL":
            stop_reason = "Execution-time guardrail recheck blocked the action — sequence halted for safety."
            break

        context["retry_count"] = min(10, context["retry_count"] + 1)
        context["previous_attempt_hours"] = context["previous_attempt_hours"] + MANDATE_RETRY_COOLDOWN_HOURS

        if failed_attempts >= MAX_MANDATE_RETRIES and requires_afa and not afa_acknowledged and step_number < MAX_STEPS:
            # Domain-specific closure: rather than a blunt STOP, a legitimate
            # subscription mandate that keeps failing AFA needs a human/
            # customer re-authorization touchpoint, not abandonment.
            mandate_reauth_required = True
            forced_payload = payload_cls(**context)
            forced_guardrail_engine = lambda p: _mandate_guardrail_engine(
                base_guardrail_engine, p, requires_afa, afa_acknowledged, retries_used
            )
            forced_decision = {
                "decision_id": f"DEC-{uuid.uuid4().hex[:10].upper()}",
                "recommended_action": "HUMAN_ESCALATION",
                "probabilities": {},
                "expected_revenue": {"HUMAN_ESCALATION": 0.0},
                "action_costs": {"HUMAN_ESCALATION": decision.get("action_costs", {}).get("HUMAN_ESCALATION", 500.0)},
                "reason": "Mandate re-authorization required: AFA threshold exceeded and retry cap reached.",
            }
            forced_guardrails = forced_guardrail_engine(forced_payload)
            if not forced_guardrails.get("HUMAN_ESCALATION", {}).get("allowed", False):
                # If escalation itself isn't eligible, fall back to a
                # reminder asking the customer to re-authorize directly.
                forced_decision["recommended_action"] = "RECOVERY_REMINDER"
                forced_decision["expected_revenue"] = {"RECOVERY_REMINDER": 0.0}
                forced_decision["action_costs"] = {"RECOVERY_REMINDER": decision.get("action_costs", {}).get("RECOVERY_REMINDER", 10.0)}
            forced_execution = execute_bounded_workflow(forced_payload, forced_decision, forced_guardrail_engine)
            steps.append({
                "step_number": step_number + 1,
                "context_snapshot": {
                    "retry_count": context["retry_count"],
                    "previous_attempt_hours": context["previous_attempt_hours"],
                    "requires_afa": requires_afa,
                    "afa_acknowledged": afa_acknowledged,
                },
                "decision_id": forced_decision["decision_id"],
                "execution_id": forced_execution["execution_id"],
                "action": forced_decision["recommended_action"],
                "expected_probability": None,
                "expected_recovery": 0.0,
                "intervention_cost": forced_decision["action_costs"].get(forced_decision["recommended_action"], 0.0),
                "execution_state": forced_execution["state"],
                "execution_outcome": forced_execution["outcome"],
                "revenue_recovered": 0.0,
                "afa_acknowledged_this_step": False,
                "reason": forced_decision["reason"],
            })
            stop_reason = "Mandate retry cap reached without AFA completion — customer re-authorization required."
            break

        if step_number == MAX_STEPS:
            stop_reason = "Maximum mandate sequence steps reached (hard stopping rule)."

    record = {
        "mandate_sequence_id": mandate_sequence_id,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "amount": initial_payload.amount,
        "requires_afa": requires_afa,
        "steps": steps,
        "step_count": len(steps),
        "stop_reason": stop_reason or "Sequence ended.",
        "total_revenue_recovered": round(total_recovered, 2),
        "total_intervention_cost": round(total_cost, 2),
        "net_recovery": round(total_recovered - total_cost, 2),
        "final_state": steps[-1]["execution_state"] if steps else None,
        "mandate_reauth_required": mandate_reauth_required,
        "policy_notes": {
            "afa_threshold": AFA_THRESHOLD,
            "pre_debit_notice_hours": PRE_DEBIT_NOTICE_HOURS,
            "max_mandate_retries": MAX_MANDATE_RETRIES,
            "mandate_retry_cooldown_hours": MANDATE_RETRY_COOLDOWN_HOURS,
        },
    }
    db_repo.insert_mandate_sequence(record)
    return record
