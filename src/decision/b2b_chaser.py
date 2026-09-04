from __future__ import annotations

"""B2B Receivables Chaser.

A domain-specific adaptive sequencer for **overdue B2B invoices** —
distinct from both the consumer ad-hoc sequencer and the UPI mandate
sequencer, because chasing an unpaid invoice is governed by different
real-world conventions than retrying a card/UPI payment:

  * **No blind retry loop.** There is nothing to "retry" about an unpaid
    invoice the way there is for a declined card — ``RETRY_LATER`` is
    always guardrail-blocked for this pathway.
  * **Dunning tiers by days overdue.** Standard B2B collections practice
    escalates tone and channel by how overdue an invoice is. This module
    uses a common, representative staging (0-15 / 16-30 / 31-60 / 60+ days)
    — documented as a representative convention, since exact thresholds
    vary by company policy, not a cited regulation.
  * **Escalate to an account manager, not a generic agent queue.** Once an
    invoice is significantly overdue or high-value, the correct escalation
    target is the account manager who owns that customer relationship, not
    a generic support/collections queue.

As with the mandate sequencer, action *scoring* still comes from the real
trained Decision Agent models — this module only overlays a domain-specific
guardrail layer and generates the actual dunning notice content, rather
than retraining a dedicated B2B model (no B2B training data exists in this
dataset).
"""

from datetime import datetime, timezone
from typing import Any, Callable
import uuid

from src.db import repository as db_repo

MAX_STEPS = 4
DUNNING_STEP_DAYS = 15.0  # each step models roughly one billing/collections checkpoint

ACCOUNT_MANAGER_DAYS_THRESHOLD = 45.0
ACCOUNT_MANAGER_AMOUNT_THRESHOLD = 100000.0

TERMINAL_STATES = {"RECOVERED", "STOPPED", "ESCALATED"}


def dunning_tier(days_overdue: float) -> str:
    if days_overdue <= 15:
        return "FRIENDLY_REMINDER"
    if days_overdue <= 30:
        return "FIRM_NOTICE"
    if days_overdue <= 60:
        return "FORMAL_DUNNING"
    return "COLLECTIONS_ESCALATION"


_TIER_COPY = {
    "FRIENDLY_REMINDER": {
        "subject": "Friendly reminder: invoice {invoice_number} is due",
        "tone": "warm, assumes oversight",
        "body": (
            "Hi {customer_name}, just a quick note that invoice {invoice_number} for ₹{amount:,.0f} "
            "was due {days_overdue:.0f} day(s) ago. If you've already paid, please disregard this message — "
            "otherwise, a payment link is attached for your convenience."
        ),
    },
    "FIRM_NOTICE": {
        "subject": "Payment overdue: invoice {invoice_number} — action needed",
        "tone": "firm but courteous",
        "body": (
            "Dear {customer_name}, invoice {invoice_number} for ₹{amount:,.0f} is now {days_overdue:.0f} days "
            "past due. Please arrange payment at your earliest convenience or contact us if there is an issue "
            "we should be aware of."
        ),
    },
    "FORMAL_DUNNING": {
        "subject": "Formal notice: invoice {invoice_number} seriously overdue",
        "tone": "formal, states consequence",
        "body": (
            "Dear {customer_name}, invoice {invoice_number} for ₹{amount:,.0f} remains unpaid after "
            "{days_overdue:.0f} days. Continued non-payment may affect your account standing and future service. "
            "Please contact our accounts team immediately to resolve this."
        ),
    },
    "COLLECTIONS_ESCALATION": {
        "subject": "Final notice: invoice {invoice_number} referred for escalation",
        "tone": "final, references escalation",
        "body": (
            "Dear {customer_name}, invoice {invoice_number} for ₹{amount:,.0f} is now {days_overdue:.0f} days "
            "overdue and has been referred to your account manager for resolution."
        ),
    },
}


def generate_dunning_notice(payload: Any, tier: str) -> dict[str, str]:
    copy = _TIER_COPY[tier]
    context = {
        "customer_name": payload.customer_display_name or "Customer",
        "invoice_number": payload.invoice_number or "N/A",
        "amount": payload.amount,
        "days_overdue": payload.days_overdue,
    }
    return {
        "tier": tier,
        "subject": copy["subject"].format(**context),
        "tone": copy["tone"],
        "body": copy["body"].format(**context),
    }


def _b2b_guardrail_engine(
    base_guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    payload: Any,
) -> dict[str, dict[str, Any]]:
    result = base_guardrail_engine(payload)

    if result.get("RETRY_LATER", {}).get("allowed"):
        result["RETRY_LATER"] = {
            "allowed": False,
            "reasons": ["Overdue invoices are chased on a collections cadence, not retried like a card payment."],
            "severity": "block",
        }

    eligible_for_am = (
        payload.days_overdue >= ACCOUNT_MANAGER_DAYS_THRESHOLD
        or payload.amount >= ACCOUNT_MANAGER_AMOUNT_THRESHOLD
    )
    if eligible_for_am:
        # Override the base consumer-retail rule (which gates escalation on
        # customer payment success rate — not a meaningful signal for a B2B
        # receivables relationship). For invoices, overdue days and invoice
        # size are the real escalation trigger.
        result["HUMAN_ESCALATION"] = {
            "allowed": True,
            "reasons": [
                f"Eligible for account-manager escalation: "
                f"{'≥' + str(int(ACCOUNT_MANAGER_DAYS_THRESHOLD)) + ' days overdue' if payload.days_overdue >= ACCOUNT_MANAGER_DAYS_THRESHOLD else f'invoice ≥₹{ACCOUNT_MANAGER_AMOUNT_THRESHOLD:,.0f}'}."
            ],
            "severity": "prefer",
        }
    else:
        result["HUMAN_ESCALATION"] = {
            "allowed": False,
            "reasons": [
                f"Account-manager escalation reserved for invoices ≥{ACCOUNT_MANAGER_DAYS_THRESHOLD:.0f} days "
                f"overdue or ≥₹{ACCOUNT_MANAGER_AMOUNT_THRESHOLD:,.0f}."
            ],
            "severity": "block",
        }

    return result


def run_b2b_chase(
    initial_payload: Any,
    score_event: Callable[[Any, Any], dict[str, Any]],
    base_guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    execute_bounded_workflow: Callable[[Any, dict[str, Any], Callable], dict[str, Any]],
    payload_cls: Callable[..., Any],
) -> dict[str, Any]:
    chase_id = f"B2B-{uuid.uuid4().hex[:10].upper()}"
    started_at = datetime.now(timezone.utc).isoformat()

    context = initial_payload.model_dump()
    steps: list[dict[str, Any]] = []
    stop_reason = None
    total_recovered = 0.0
    total_cost = 0.0

    guardrail_engine = lambda p: _b2b_guardrail_engine(base_guardrail_engine, p)

    for step_number in range(1, MAX_STEPS + 1):
        payload = payload_cls(**context)
        tier = dunning_tier(payload.days_overdue)
        decision = score_event(payload, guardrail_engine)
        execution = execute_bounded_workflow(payload, decision, guardrail_engine)

        action = decision["recommended_action"]
        expected_recovery = decision.get("expected_revenue", {}).get(action)
        intervention_cost = decision.get("action_costs", {}).get(action, 0.0)
        recovered_this_step = float(execution.get("revenue_recovered", 0.0) or 0.0)
        total_recovered += recovered_this_step
        total_cost += intervention_cost

        dunning_notice = generate_dunning_notice(payload, tier) if action == "RECOVERY_REMINDER" else None

        steps.append({
            "step_number": step_number,
            "days_overdue": payload.days_overdue,
            "dunning_tier": tier,
            "decision_id": decision["decision_id"],
            "execution_id": execution["execution_id"],
            "action": action,
            "action_label": "Escalate to account manager" if action == "HUMAN_ESCALATION" else pretty_action(action),
            "expected_recovery": round(expected_recovery, 2) if expected_recovery is not None else None,
            "intervention_cost": intervention_cost,
            "execution_state": execution["state"],
            "execution_outcome": execution["outcome"],
            "revenue_recovered": recovered_this_step,
            "dunning_notice": dunning_notice,
            "reason": decision.get("reason"),
        })

        state = execution["state"]
        if state in TERMINAL_STATES:
            stop_reason = {
                "RECOVERED": "Invoice paid — chase complete.",
                "STOPPED": "Policy selected STOP as the safe fallback — chase complete.",
                "ESCALATED": "Referred to account manager — chase hands off here.",
            }[state]
            break
        if execution["outcome"] == "BLOCKED_BY_GUARDRAIL":
            stop_reason = "Execution-time guardrail recheck blocked the action — chase halted for safety."
            break

        context["days_overdue"] = context["days_overdue"] + DUNNING_STEP_DAYS

        if step_number == MAX_STEPS:
            stop_reason = "Maximum chase checkpoints reached without resolution (stopping rule)."

    record = {
        "chase_id": chase_id,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "amount": initial_payload.amount,
        "invoice_number": initial_payload.invoice_number,
        "starting_days_overdue": initial_payload.days_overdue,
        "steps": steps,
        "step_count": len(steps),
        "stop_reason": stop_reason or "Chase ended.",
        "total_revenue_recovered": round(total_recovered, 2),
        "total_intervention_cost": round(total_cost, 2),
        "net_recovery": round(total_recovered - total_cost, 2),
        "final_state": steps[-1]["execution_state"] if steps else None,
        "policy_notes": {
            "account_manager_days_threshold": ACCOUNT_MANAGER_DAYS_THRESHOLD,
            "account_manager_amount_threshold": ACCOUNT_MANAGER_AMOUNT_THRESHOLD,
            "dunning_step_days": DUNNING_STEP_DAYS,
        },
    }
    db_repo.insert_b2b_chase(record)
    return record


def pretty_action(action: str) -> str:
    return {
        "ALTERNATIVE_PAYMENT": "Offer alternate payment instructions",
        "RECOVERY_REMINDER": "Send dunning notice",
        "STOP": "Stop chasing",
    }.get(action, action.replace("_", " ").title())
