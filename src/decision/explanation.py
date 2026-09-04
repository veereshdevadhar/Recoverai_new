from __future__ import annotations

"""Advanced Decision Explanation.

Builds a structured, per-decision explanation directly from the numbers the
Decision Agent already computed (probabilities, expected net value,
guardrail reasons, score margin). Nothing here is a fixed template string
disconnected from the actual decision — every bullet references a real
field from ``decision``.
"""

from typing import Any


def build_explanation(decision: dict[str, Any], payload: Any) -> dict[str, Any]:
    chosen = decision["recommended_action"]
    guardrails = decision["guardrails"]
    expected_net = decision["expected_net_value"]
    probabilities = decision["probabilities"]

    why_selected: list[str] = []
    if chosen == "STOP":
        why_selected.append("No allowed action produced a positive expected net value.")
    else:
        why_selected.append(
            f"Highest allowed expected net value: ₹{expected_net.get(chosen, 0):,.2f}"
            f" (predicted recovery probability {probabilities.get(chosen, 0):.0%})."
        )
        if decision["score_margin"] > 0:
            why_selected.append(
                f"Beat the next-best allowed action by ₹{decision['score_margin']:,.2f} in expected net value."
            )
    if payload.retry_count == 0 and chosen != "STOP":
        why_selected.append("This is the first recovery attempt for this event.")
    elif payload.retry_count >= 2:
        why_selected.append(f"Payment has already failed {payload.retry_count} times, narrowing eligible actions.")
    if payload.event_type == "CHECKOUT_ABANDONMENT":
        why_selected.append("Checkout abandonment is treated as a re-engagement opportunity; reminder is preferred before a more invasive intervention.")
    elif payload.event_type == "SUBSCRIPTION_FAILURE":
        why_selected.append("Subscription failure is handled as a recurring-payment recovery opportunity, with reminder/alternate-channel recovery prioritized without silently retrying a failed mandate.")
    adjustment = float(decision.get("policy_adjustments", {}).get(chosen, 0) or 0)
    if adjustment:
        why_selected.append(f"Contextual policy layer added ₹{adjustment:,.2f} to this action's ranking after ML scoring.")
    if payload.amount >= 25000:
        why_selected.append(f"₹{payload.amount:,.0f} is a high-value transaction.")
    if guardrails.get(chosen, {}).get("reasons"):
        why_selected.extend(guardrails[chosen]["reasons"])

    why_rejected: dict[str, list[str]] = {}
    for action, gr in guardrails.items():
        if action == chosen:
            continue
        reasons: list[str] = []
        if not gr["allowed"]:
            reasons.extend(gr.get("reasons", ["Blocked by policy guardrails."]))
        else:
            net = expected_net.get(action)
            chosen_net = expected_net.get(chosen)
            if net is not None and chosen_net is not None:
                reasons.append(
                    f"Allowed, but lower expected net value (₹{net:,.2f} vs ₹{chosen_net:,.2f} for {chosen})."
                )
            else:
                reasons.append("Allowed, but not selected — lower ranked expected value.")
        why_rejected[action] = reasons

    return {
        "why_selected": why_selected,
        "why_others_rejected": why_rejected,
    }
