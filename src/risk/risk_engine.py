from __future__ import annotations

"""Revenue-at-Risk Early Warning engine.

This module estimates how much revenue is at risk *before* a recovery action
is chosen, using strictly the same leakage-safe pre-action features the
decision models already use (see ``src/features/feature_builder.py`` and the
``LEAKAGE`` set in ``src/models/train_v2.py``). It never reads outcome
columns such as ``revenue_recovered`` or ``recovery_success`` — those simply
don't exist on the incoming ``PaymentEvent`` payload, and this module takes
no other data source.

The risk score is derived from the *same* trained action-specific models
used by the Decision Agent: risk is framed as "how likely is it that none of
our allowed recovery actions succeeds", not a separate, hand-tuned model.
This keeps the number honest and reproducible rather than an invented
heuristic disconnected from the rest of the system.
"""

from typing import Any, Callable


def _tier(risk_score: float) -> str:
    if risk_score >= 75:
        return "CRITICAL"
    if risk_score >= 55:
        return "HIGH"
    if risk_score >= 30:
        return "MEDIUM"
    return "LOW"


def _drivers(payload: Any, probabilities: dict[str, float]) -> list[dict[str, str]]:
    """Data-driven contributing factors, derived only from pre-action fields."""
    drivers: list[dict[str, str]] = []

    if payload.retry_count >= 2:
        drivers.append({
            "factor": "Repeated payment failures",
            "detail": f"{payload.retry_count} prior retries recorded before this event.",
        })
    if payload.failure_type in {"ISSUER_DECLINE", "INSUFFICIENT_BALANCE", "PAYMENT_LIMIT", "EXPIRED_PAYMENT_METHOD"}:
        drivers.append({
            "factor": "Non-retryable failure type",
            "detail": f"{payload.failure_type.replace('_', ' ').title()} rarely resolves on its own.",
        })
    if payload.historical_success_rate < 0.6:
        drivers.append({
            "factor": "Weak customer payment history",
            "detail": f"Historical success rate is {payload.historical_success_rate:.0%}.",
        })
    if (payload.merchant_success_rate is not None) and payload.merchant_success_rate < 0.7:
        drivers.append({
            "factor": "Below-average merchant success rate",
            "detail": f"This merchant recovers only {payload.merchant_success_rate:.0%} of similar events.",
        })
    if payload.amount >= 25000:
        drivers.append({
            "factor": "High transaction value",
            "detail": f"₹{payload.amount:,.0f} is a high-value transaction, raising the financial stakes of non-recovery.",
        })
    if payload.event_type == "CHECKOUT_ABANDONMENT":
        drivers.append({
            "factor": "Checkout abandonment",
            "detail": "Customer left checkout before completing payment; intent signal is weaker than an active failed payment.",
        })
    if payload.event_type == "SUBSCRIPTION_FAILURE" and payload.failed_cycles >= 1:
        drivers.append({
            "factor": "Subscription billing instability",
            "detail": f"{payload.failed_cycles} failed billing cycle(s) already recorded on this subscription.",
        })
    if payload.days_since_last_success >= 30:
        drivers.append({
            "factor": "Stale recovery history",
            "detail": f"{payload.days_since_last_success:.0f} days since this customer's last successful recovery.",
        })

    if not drivers:
        drivers.append({
            "factor": "No elevated risk factors detected",
            "detail": "Customer and merchant history are within normal ranges for this event.",
        })
    return drivers[:5]


def assess_risk(
    payload: Any,
    artifact_loader: Callable[[], dict[str, Any]],
    feature_builder: Callable[[Any], Any],
    actions: list[str],
    guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    a = artifact_loader()
    X = feature_builder(payload)

    probabilities = {
        action: float(a["models"][action].predict_proba(X)[0, 1])
        for action in actions
    }
    guardrails = guardrail_engine(payload) if guardrail_engine is not None else {
        action: {"allowed": True} for action in actions
    }
    eligible = [action for action in actions if guardrails.get(action, {}).get("allowed", True)]
    best_action = max(eligible, key=probabilities.get) if eligible else "STOP"
    best_recovery_probability = probabilities[best_action] if best_action != "STOP" else 0.0
    loss_probability = max(0.0, 1.0 - best_recovery_probability)

    risk_score = round(100 * loss_probability, 1)
    tier = _tier(risk_score)
    revenue_at_risk = round(payload.amount * loss_probability, 2)

    drivers = _drivers(payload, probabilities)

    return {
        "risk_score": risk_score,
        "risk_tier": tier,
        "amount": round(float(payload.amount), 2),
        "revenue_at_risk": revenue_at_risk,
        "best_recovery_probability": round(best_recovery_probability, 4),
        "recommended_preventive_action": best_action,
        "eligible_actions": eligible,
        "blocked_actions": [action for action in actions if action not in eligible],
        "recommended_preventive_action_note": (
            f"Model-preferred intervention if acted on now: {best_action.replace('_', ' ').title()} "
            f"(estimated {best_recovery_probability:.0%} recovery probability)."
        ),
        "drivers": drivers,
        "model_version": a.get("version", "V3"),
        "leakage_protected": True,
        "note": "Computed from pre-action features only; no outcome data is used or available at this stage.",
    }
