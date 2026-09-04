from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import uuid

import numpy as np


@dataclass
class DecisionAgent:
    """Deterministic decision agent that orchestrates ML, value scoring and policy.

    The agent is intentionally model-agnostic and local-only. It does not pretend to
    be an LLM: it observes structured payment context, calls the action models,
    applies hard guardrails, ranks expected net value, explains the result and
    returns an auditable execution trace.
    """

    actions: list[str]
    all_actions: list[str]
    action_costs: dict[str, float]

    def decide(
        self,
        payload: Any,
        artifact_loader: Callable[[], dict[str, Any]],
        feature_builder: Callable[[Any], Any],
        guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
        explainer: Callable[[str, Any, dict[str, Any], dict[str, float]], str],
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []

        def step(name: str, label: str, details: dict[str, Any] | None = None) -> None:
            trace.append({"step": name, "label": label, "status": "completed", "details": details or {}})

        a = artifact_loader()
        step("CONTEXT", "Read payment, customer and merchant context", {
            "event_type": payload.event_type,
            "amount": payload.amount,
            "failure_type": payload.failure_type,
            "retry_count": payload.retry_count,
        })

        X = feature_builder(payload)
        step("FEATURES", "Build leakage-safe pre-action features", {"feature_count": len(X.columns)})

        probabilities = {
            action: float(a["models"][action].predict_proba(X)[0, 1])
            for action in self.actions
        }
        step("ML_SCORING", "Score every recovery action independently", {
            "model_version": a.get("version", "V2"),
            "probabilities": {k: round(v, 4) for k, v in probabilities.items()},
        })

        expected_revenue = {k: probabilities[k] * payload.amount for k in self.actions}
        base_expected_net = {k: expected_revenue[k] - self.action_costs[k] for k in self.actions}
        expected_net = dict(base_expected_net)
        expected_revenue["STOP"] = 0.0
        expected_net["STOP"] = 0.0
        base_expected_net["STOP"] = 0.0

        # A small contextual policy layer keeps the ML probabilities intact while
        # encoding business semantics that are difficult for a generic action
        # classifier to express reliably. Adjustments are bounded and auditable;
        # they never override hard guardrails.
        policy_adjustments: dict[str, float] = {a: 0.0 for a in self.actions}
        failure_type = getattr(payload, "failure_type", None)
        event_type = getattr(payload, "event_type", None)
        retry_count = int(getattr(payload, "retry_count", 0) or 0)
        if failure_type in {"TIMEOUT", "NETWORK_ERROR", "BANK_TECHNICAL_ERROR"} and retry_count < 3:
            policy_adjustments["RETRY_LATER"] += min(250.0, float(payload.amount) * 0.02)
        if retry_count >= 2 and failure_type not in {"ISSUER_DECLINE", "INSUFFICIENT_BALANCE", "PAYMENT_LIMIT", "EXPIRED_PAYMENT_METHOD"}:
            policy_adjustments["ALTERNATIVE_PAYMENT"] += min(300.0, float(payload.amount) * 0.01)
        if event_type == "CHECKOUT_ABANDONMENT":
            policy_adjustments["RECOVERY_REMINDER"] += min(200.0, float(payload.amount) * 0.01)
        if event_type == "SUBSCRIPTION_FAILURE":
            policy_adjustments["RECOVERY_REMINDER"] += min(250.0, float(payload.amount) * 0.015)
            policy_adjustments["ALTERNATIVE_PAYMENT"] += min(150.0, float(payload.amount) * 0.0075)
        if float(payload.amount) >= 25000 and float(getattr(payload, "historical_success_rate", 0.0)) >= 0.85:
            policy_adjustments["HUMAN_ESCALATION"] += min(500.0, float(payload.amount) * 0.01)
        for action, adjustment in policy_adjustments.items():
            expected_net[action] += adjustment

        step("VALUE_SCORING", "Convert probability into expected money and net value", {
            "action_costs": self.action_costs,
            "base_expected_net": {k: round(v, 2) for k, v in base_expected_net.items()},
            "policy_adjustments": {k: round(v, 2) for k, v in policy_adjustments.items() if v},
            "policy_adjusted_expected_net": {k: round(v, 2) for k, v in expected_net.items()},
        })

        guardrails = guardrail_engine(payload)
        blocked = [a for a, g in guardrails.items() if not g["allowed"]]
        for action in self.actions:
            if not guardrails[action]["allowed"]:
                expected_net[action] = -float("inf")
        step("GUARDRAILS", "Apply hard business policy before final ranking", {
            "blocked_actions": blocked,
            "allowed_actions": [a for a in self.all_actions if guardrails[a]["allowed"]],
        })

        ranked = sorted(expected_net.items(), key=lambda x: x[1], reverse=True)
        finite_scores = [v for _, v in ranked if np.isfinite(v)]
        top_score = finite_scores[0] if finite_scores else 0.0
        second_score = finite_scores[1] if len(finite_scores) > 1 else 0.0
        margin = max(0.0, top_score - second_score)
        chosen = ranked[0][0]
        top_probability = probabilities.get(chosen, 0.0)
        confidence = (
            "HIGH" if top_probability >= 0.75 or margin >= max(1000.0, payload.amount * 0.12)
            else ("MEDIUM" if top_probability >= 0.55 else "LOW")
        )
        step("DECISION", "Choose the highest-value allowed action", {
            "recommended_action": chosen,
            "confidence": confidence,
            "score_margin": round(margin, 2),
        })

        reason = explainer(chosen, payload, guardrails[chosen], expected_net)
        if policy_adjustments.get(chosen):
            reason += f" Contextual policy adjustment added ₹{policy_adjustments[chosen]:,.0f} to the {chosen.replace('_', ' ').lower()} ranking."
        decision_id = f"DEC-{uuid.uuid4().hex[:10].upper()}"
        result = {
            "decision_id": decision_id,
            "agent": {
                "name": "RecoverAI Decision Agent",
                "version": "1.0",
                "mode": "deterministic_ml_policy",
                "description": "Context → ML scoring → monetary value → guardrails → ranked decision → audit",
                "trace": trace,
            },
            "recommended_action": chosen,
            "probabilities": {k: round(v, 6) for k, v in probabilities.items()},
            "expected_revenue": {k: round(v, 2) for k, v in expected_revenue.items()},
            "action_costs": self.action_costs,
            "base_expected_net_value": {k: (None if not np.isfinite(v) else round(v, 2)) for k, v in base_expected_net.items()},
            "policy_adjustments": {k: round(v, 2) for k, v in policy_adjustments.items()},
            "expected_net_value": {k: (None if not np.isfinite(v) else round(v, 2)) for k, v in expected_net.items()},
            "ranked_actions": [
                {"action": k, "score": None if not np.isfinite(v) else round(v, 2), "allowed": guardrails[k]["allowed"]}
                for k, v in ranked
            ],
            "guardrails": guardrails,
            "recommended_guardrail": guardrails[chosen],
            "reason": reason,
            "model_version": a.get("version", "V2"),
            "decision_confidence": confidence,
            "score_margin": round(margin, 2),
        }
        return result
