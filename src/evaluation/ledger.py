from __future__ import annotations

"""Revenue Recovery Ledger and Outcome Feedback Loop.

Queries the real SQLite database (decisions + executions tables) that every
live ``/predict`` / ``/execute-recovery`` / sequencer call actually writes
to. Nothing here is fabricated: every row corresponds to a real decision and
a real execution that ran against the trained model and guardrail engine,
and it now survives backend restarts.
"""

from typing import Any

from src.db import repository as db_repo


def build_ledger(limit: int = 100) -> dict[str, Any]:
    executions = db_repo.get_all_executions_for_ledger()
    # One payment decision can be executed more than once (for example after
    # a UI retry). Treat decision_id as the transaction-level key so repeated
    # executions do not double-count revenue-at-risk or recovered revenue.
    unique: dict[str, dict[str, Any]] = {}
    for execution in executions:
        unique.setdefault(execution["decision_id"], execution)
    executions = list(unique.values())

    entries = []
    for execution in executions[:max(1, min(limit, 500))]:
        revenue_at_risk = execution.get("amount", 0.0)
        actual_recovered = float(execution.get("revenue_recovered", 0.0) or 0.0)
        intervention_cost = float(execution.get("intervention_cost", 0.0) or 0.0)
        entries.append({
            "decision_id": execution["decision_id"],
            "execution_id": execution["execution_id"],
            "timestamp": execution["timestamp"],
            "event_type": execution.get("event_type"),
            "amount": revenue_at_risk,
            "revenue_at_risk": revenue_at_risk,
            "selected_action": execution["action"],
            "expected_probability": execution.get("expected_probability"),
            "expected_recovery": execution.get("expected_recovery"),
            "actual_recovered": actual_recovered,
            "intervention_cost": intervention_cost,
            "net_recovery": execution.get("net_recovery", round(actual_recovered - intervention_cost, 2)),
            "final_state": execution["state"],
            "outcome": execution.get("outcome"),
        })

    total_at_risk = sum(e["revenue_at_risk"] for e in entries)
    total_recovered = sum(e["actual_recovered"] for e in entries)
    total_cost = sum(e["intervention_cost"] for e in entries)

    return {
        "entries": entries,
        "count": len(entries),
        "unique_decisions": len(unique),
        "summary": {
            "total_revenue_at_risk": round(total_at_risk, 2),
            "total_recovered": round(total_recovered, 2),
            "recovery_rate": round(total_recovered / total_at_risk, 6) if total_at_risk else 0.0,
            "total_intervention_cost": round(total_cost, 2),
            "net_recovered": round(total_recovered - total_cost, 2),
        },
        "note": "Live session ledger from the SQLite database (data/runtime/recoverai.db), populated by real /predict and /execute-recovery calls (including sequencer steps). Persists across backend restarts. For dataset-scale oracle capture and regret, see /api/metrics.",
    }


def build_feedback() -> dict[str, Any]:
    """Which actions perform well vs. poorly, based on real recorded executions."""
    executions = db_repo.get_all_executions_for_ledger()
    by_action: dict[str, dict[str, Any]] = {}

    for execution in executions:
        action = execution["action"]
        bucket = by_action.setdefault(action, {
            "action": action,
            "attempts": 0,
            "recovered_count": 0,
            "total_recovered": 0.0,
            "total_cost": 0.0,
            "total_expected_recovery": 0.0,
        })
        bucket["attempts"] += 1
        bucket["total_recovered"] += float(execution.get("revenue_recovered", 0.0) or 0.0)
        bucket["total_cost"] += float(execution.get("intervention_cost", 0.0) or 0.0)
        bucket["total_expected_recovery"] += float(execution.get("expected_recovery", 0.0) or 0.0)
        if execution["state"] == "RECOVERED":
            bucket["recovered_count"] += 1

    results = []
    for action, bucket in by_action.items():
        attempts = bucket["attempts"]
        results.append({
            "action": action,
            "attempts": attempts,
            "observed_success_rate": round(bucket["recovered_count"] / attempts, 4) if attempts and action not in {"STOP", "RETRY_LATER", "HUMAN_ESCALATION"} else None,
            "total_recovered": round(bucket["total_recovered"], 2),
            "total_expected_recovery": round(bucket["total_expected_recovery"], 2),
            "calibration_gap": round(bucket["total_recovered"] - bucket["total_expected_recovery"], 2),
            "total_intervention_cost": round(bucket["total_cost"], 2),
            "net_recovery": round(bucket["total_recovered"] - bucket["total_cost"], 2),
        })

    results.sort(key=lambda r: r["net_recovery"], reverse=True)
    return {
        "by_action": results,
        "total_executions": len(executions),
        "note": "Derived from real recorded executions in the SQLite database (data/runtime/recoverai.db).",
    }

