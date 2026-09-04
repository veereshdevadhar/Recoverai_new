from __future__ import annotations

"""Data-access layer over the SQLite database.

Every function here mirrors the exact return shape the rest of the app
(``src/api/main.py``, ``src/decision/execution.py``,
``src/decision/sequencer.py``, ``src/evaluation/ledger.py``) already
expects, so migrating from JSONL files to SQLite required no changes to
any API response contract or any existing test.
"""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, delete

from src.db.database import get_session, init_db
from src.db.models import (
    DecisionRecord, ExecutionRecord, SequenceRecord,
    MandateSequenceRecord, PolicyExperimentRecord,
    B2BChaseRecord, PromiseRecord, IntegrationEventRecord, PlatformRecord,
)

init_db()


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def insert_decision(record: dict[str, Any]) -> None:
    with get_session() as s:
        s.merge(DecisionRecord(
            decision_id=record["decision_id"],
            timestamp=record["timestamp"],
            amount=record["amount"],
            event_type=record["event_type"],
            failure_type=record.get("failure_type"),
            retry_count=record["retry_count"],
            customer_success_rate=record["customer_success_rate"],
            recommended_action=record["recommended_action"],
            confidence=record["confidence"],
            model_version=record["model_version"],
            guardrail_blocked_actions_json=json.dumps(record.get("guardrail_blocked_actions", [])),
            feature_attribution_json=json.dumps(record["feature_attribution"]) if record.get("feature_attribution") is not None else None,
        ))
        s.commit()


def _decision_to_dict(r: DecisionRecord) -> dict[str, Any]:
    return {
        "decision_id": r.decision_id,
        "timestamp": r.timestamp,
        "amount": r.amount,
        "event_type": r.event_type,
        "failure_type": r.failure_type,
        "retry_count": r.retry_count,
        "customer_success_rate": r.customer_success_rate,
        "recommended_action": r.recommended_action,
        "confidence": r.confidence,
        "model_version": r.model_version,
        "guardrail_blocked_actions": json.loads(r.guardrail_blocked_actions_json),
        "feature_attribution": json.loads(r.feature_attribution_json) if r.feature_attribution_json else None,
    }


def get_decisions(limit: int = 50) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            select(DecisionRecord).order_by(DecisionRecord.timestamp.desc()).limit(max(1, min(limit, 200)))
        ).scalars().all()
        return [_decision_to_dict(r) for r in rows]


def get_decision(decision_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(DecisionRecord, decision_id)
        return _decision_to_dict(r) if r else None


# ---------------------------------------------------------------------------
# Executions
# ---------------------------------------------------------------------------

def insert_execution(record: dict[str, Any]) -> None:
    with get_session() as s:
        s.merge(ExecutionRecord(
            execution_id=record["execution_id"],
            decision_id=record["decision_id"],
            timestamp=record["timestamp"],
            execution_mode=record["execution_mode"],
            action=record["action"],
            amount=record["amount"],
            event_type=record.get("event_type"),
            reason=record.get("reason", ""),
            state=record["state"],
            outcome=record.get("outcome"),
            outcome_reason=record.get("outcome_reason"),
            revenue_recovered=float(record.get("revenue_recovered", 0.0) or 0.0),
            expected_probability=record.get("expected_probability"),
            expected_recovery=record.get("expected_recovery"),
            intervention_cost=float(record.get("intervention_cost", 0.0) or 0.0),
            net_recovery=float(record.get("net_recovery", 0.0) or 0.0),
            terminal=bool(record.get("terminal", True)),
            state_history_json=json.dumps(record.get("state_history", [])),
        ))
        s.commit()


def _execution_to_dict(r: ExecutionRecord) -> dict[str, Any]:
    return {
        "execution_id": r.execution_id,
        "decision_id": r.decision_id,
        "timestamp": r.timestamp,
        "execution_mode": r.execution_mode,
        "action": r.action,
        "amount": r.amount,
        "event_type": r.event_type,
        "reason": r.reason,
        "state": r.state,
        "outcome": r.outcome,
        "outcome_reason": r.outcome_reason,
        "revenue_recovered": r.revenue_recovered,
        "expected_probability": r.expected_probability,
        "expected_recovery": r.expected_recovery,
        "intervention_cost": r.intervention_cost,
        "net_recovery": r.net_recovery,
        "terminal": r.terminal,
        "state_history": json.loads(r.state_history_json),
    }




def get_live_execution_stats_today() -> dict[str, Any]:
    """Return today's live execution count/cost/amount for safety budgets."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    with get_session() as s:
        rows = s.execute(select(ExecutionRecord).where(ExecutionRecord.execution_mode == "LIVE_EXTERNAL")).scalars().all()
        rows = [r for r in rows if str(r.timestamp).startswith(today)]
        return {
            "count": len(rows),
            "intervention_cost": round(sum(float(r.intervention_cost or 0) for r in rows), 2),
            "amount": round(sum(float(r.amount or 0) for r in rows), 2),
        }

def find_existing_live_execution(decision_id: str, action: str) -> dict[str, Any] | None:
    """Idempotency lookup: one live execution per decision/action."""
    with get_session() as s:
        rows = s.execute(
            select(ExecutionRecord).where(
                ExecutionRecord.decision_id == decision_id,
                ExecutionRecord.action == action,
                ExecutionRecord.execution_mode == "LIVE_EXTERNAL",
            ).order_by(ExecutionRecord.timestamp.desc())
        ).scalars().all()
        return _execution_to_dict(rows[0]) if rows else None

def get_executions(limit: int = 50) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            select(ExecutionRecord).order_by(ExecutionRecord.timestamp.desc()).limit(max(1, min(limit, 200)))
        ).scalars().all()
        return [_execution_to_dict(r) for r in rows]


def get_all_executions_for_ledger() -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(select(ExecutionRecord).order_by(ExecutionRecord.timestamp.desc())).scalars().all()
        return [_execution_to_dict(r) for r in rows]

def mark_execution_recovered(execution_id: str, recovered_amount: float, verification_event: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(ExecutionRecord, execution_id)
        if r is None:
            return None
        amount = max(0.0, min(float(recovered_amount), float(r.amount)))
        r.revenue_recovered = amount
        r.net_recovery = round(amount - float(r.intervention_cost or 0.0), 2)
        r.state = "RECOVERED"
        r.outcome = "VERIFIED_PAYMENT_SUCCESS"
        r.outcome_reason = "Recovery verified by an authenticated provider/payment status event."
        history = json.loads(r.state_history_json)
        history.append({"state": "RECOVERED", "timestamp": datetime.now(timezone.utc).isoformat(), "verification_event": verification_event or {}})
        r.state_history_json = json.dumps(history, default=str)
        r.terminal = True
        s.commit()
        return _execution_to_dict(r)


# ---------------------------------------------------------------------------
# Adaptive recovery sequences
# ---------------------------------------------------------------------------

def insert_sequence(record: dict[str, Any]) -> None:
    with get_session() as s:
        s.merge(SequenceRecord(
            sequence_id=record["sequence_id"],
            started_at=record["started_at"],
            completed_at=record["completed_at"],
            event_type=record["initial_context"]["event_type"],
            amount=record["initial_context"]["amount"],
            failure_type=record["initial_context"].get("failure_type"),
            step_count=record["step_count"],
            stop_reason=record["stop_reason"],
            total_revenue_recovered=record["total_revenue_recovered"],
            total_intervention_cost=record["total_intervention_cost"],
            net_recovery=record["net_recovery"],
            final_state=record.get("final_state"),
            steps_json=json.dumps(record["steps"]),
        ))
        s.commit()


def _sequence_to_dict(r: SequenceRecord) -> dict[str, Any]:
    return {
        "sequence_id": r.sequence_id,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "initial_context": {"event_type": r.event_type, "amount": r.amount, "failure_type": r.failure_type},
        "step_count": r.step_count,
        "stop_reason": r.stop_reason,
        "total_revenue_recovered": r.total_revenue_recovered,
        "total_intervention_cost": r.total_intervention_cost,
        "net_recovery": r.net_recovery,
        "final_state": r.final_state,
        "steps": json.loads(r.steps_json),
    }


def get_sequence(sequence_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(SequenceRecord, sequence_id)
        return _sequence_to_dict(r) if r else None


def list_sequences(limit: int = 20) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            select(SequenceRecord).order_by(SequenceRecord.started_at.desc()).limit(max(1, min(limit, 200)))
        ).scalars().all()
        return [_sequence_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# UPI Mandate retry sequences
# ---------------------------------------------------------------------------

def insert_mandate_sequence(record: dict[str, Any]) -> None:
    with get_session() as s:
        s.merge(MandateSequenceRecord(
            mandate_sequence_id=record["mandate_sequence_id"],
            started_at=record["started_at"],
            completed_at=record["completed_at"],
            amount=record["amount"],
            requires_afa=record["requires_afa"],
            step_count=record["step_count"],
            stop_reason=record["stop_reason"],
            total_revenue_recovered=record["total_revenue_recovered"],
            total_intervention_cost=record["total_intervention_cost"],
            net_recovery=record["net_recovery"],
            final_state=record.get("final_state"),
            mandate_reauth_required=record.get("mandate_reauth_required", False),
            steps_json=json.dumps(record["steps"]),
        ))
        s.commit()


def _mandate_to_dict(r: MandateSequenceRecord) -> dict[str, Any]:
    return {
        "mandate_sequence_id": r.mandate_sequence_id,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "amount": r.amount,
        "requires_afa": r.requires_afa,
        "step_count": r.step_count,
        "stop_reason": r.stop_reason,
        "total_revenue_recovered": r.total_revenue_recovered,
        "total_intervention_cost": r.total_intervention_cost,
        "net_recovery": r.net_recovery,
        "final_state": r.final_state,
        "mandate_reauth_required": r.mandate_reauth_required,
        "steps": json.loads(r.steps_json),
    }


def get_mandate_sequence(mandate_sequence_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(MandateSequenceRecord, mandate_sequence_id)
        return _mandate_to_dict(r) if r else None


def list_mandate_sequences(limit: int = 20) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            select(MandateSequenceRecord).order_by(MandateSequenceRecord.started_at.desc()).limit(max(1, min(limit, 200)))
        ).scalars().all()
        return [_mandate_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Policy experiments (every What-If / A-B run is itself persisted)
# ---------------------------------------------------------------------------

def insert_policy_experiment(kind: str, params: dict[str, Any], result: dict[str, Any]) -> None:
    with get_session() as s:
        s.add(PolicyExperimentRecord(
            created_at=datetime.now(timezone.utc).isoformat(),
            kind=kind,
            params_json=json.dumps(params),
            result_json=json.dumps(result),
        ))
        s.commit()


def list_policy_experiments(limit: int = 20) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            select(PolicyExperimentRecord).order_by(PolicyExperimentRecord.created_at.desc()).limit(max(1, min(limit, 200)))
        ).scalars().all()
        return [{
            "id": r.id,
            "created_at": r.created_at,
            "kind": r.kind,
            "params": json.loads(r.params_json),
            "result": json.loads(r.result_json),
        } for r in rows]


# ---------------------------------------------------------------------------
# B2B Receivables Chases
# ---------------------------------------------------------------------------

def insert_b2b_chase(record: dict[str, Any]) -> None:
    with get_session() as s:
        s.merge(B2BChaseRecord(
            chase_id=record["chase_id"],
            started_at=record["started_at"],
            completed_at=record["completed_at"],
            amount=record["amount"],
            invoice_number=record.get("invoice_number"),
            starting_days_overdue=record["starting_days_overdue"],
            step_count=record["step_count"],
            stop_reason=record["stop_reason"],
            total_revenue_recovered=record["total_revenue_recovered"],
            total_intervention_cost=record["total_intervention_cost"],
            net_recovery=record["net_recovery"],
            final_state=record.get("final_state"),
            steps_json=json.dumps(record["steps"]),
        ))
        s.commit()


def _b2b_chase_to_dict(r: B2BChaseRecord) -> dict[str, Any]:
    return {
        "chase_id": r.chase_id,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "amount": r.amount,
        "invoice_number": r.invoice_number,
        "starting_days_overdue": r.starting_days_overdue,
        "step_count": r.step_count,
        "stop_reason": r.stop_reason,
        "total_revenue_recovered": r.total_revenue_recovered,
        "total_intervention_cost": r.total_intervention_cost,
        "net_recovery": r.net_recovery,
        "final_state": r.final_state,
        "steps": json.loads(r.steps_json),
    }


def get_b2b_chase(chase_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(B2BChaseRecord, chase_id)
        return _b2b_chase_to_dict(r) if r else None


def list_b2b_chases(limit: int = 20) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            select(B2BChaseRecord).order_by(B2BChaseRecord.started_at.desc()).limit(max(1, min(limit, 200)))
        ).scalars().all()
        return [_b2b_chase_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Promise-to-Pay Tracker
# ---------------------------------------------------------------------------

def insert_promise(record: dict[str, Any]) -> dict[str, Any]:
    with get_session() as s:
        row = PromiseRecord(
            promise_id=record["promise_id"],
            decision_id=record.get("decision_id"),
            execution_id=record.get("execution_id"),
            amount=record["amount"],
            promised_date=record["promised_date"],
            created_at=record["created_at"],
            status="PENDING",
            actual_recovered=None,
            broken_escalated=False,
            escalation_decision_id=None,
            escalation_execution_id=None,
            context_json=json.dumps(record.get("context", {})),
        )
        s.add(row)
        s.commit()
        return _promise_to_dict(row)


def _promise_to_dict(r: PromiseRecord) -> dict[str, Any]:
    return {
        "promise_id": r.promise_id,
        "decision_id": r.decision_id,
        "execution_id": r.execution_id,
        "amount": r.amount,
        "promised_date": r.promised_date,
        "created_at": r.created_at,
        "status": r.status,
        "actual_recovered": r.actual_recovered,
        "broken_escalated": r.broken_escalated,
        "escalation_decision_id": r.escalation_decision_id,
        "escalation_execution_id": r.escalation_execution_id,
        "context": json.loads(r.context_json),
    }


def get_promise_row(promise_id: str):
    with get_session() as s:
        return s.get(PromiseRecord, promise_id)


def mark_promise_kept(promise_id: str, actual_recovered: float) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(PromiseRecord, promise_id)
        if r is None:
            return None
        r.status = "KEPT"
        r.actual_recovered = actual_recovered
        s.commit()
        return _promise_to_dict(r)


def mark_promise_broken_and_escalated(promise_id: str, escalation_decision_id: str, escalation_execution_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(PromiseRecord, promise_id)
        if r is None:
            return None
        r.status = "BROKEN"
        r.broken_escalated = True
        r.escalation_decision_id = escalation_decision_id
        r.escalation_execution_id = escalation_execution_id
        s.commit()
        return _promise_to_dict(r)


def mark_promise_broken_no_escalation(promise_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(PromiseRecord, promise_id)
        if r is None:
            return None
        r.status = "BROKEN"
        s.commit()
        return _promise_to_dict(r)


def get_promise(promise_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        r = s.get(PromiseRecord, promise_id)
        return _promise_to_dict(r) if r else None


def list_promises(limit: int = 100) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(
            select(PromiseRecord).order_by(PromiseRecord.promised_date.asc()).limit(max(1, min(limit, 500)))
        ).scalars().all()
        return [_promise_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# External integration events

def get_integration_event(integration_event_id: str) -> dict[str, Any] | None:
    """Return one integration event by deterministic provider event key."""
    with get_session() as s:
        r = s.get(IntegrationEventRecord, integration_event_id)
        if r is None:
            return None
        return {
            "integration_event_id": r.integration_event_id,
            "timestamp": r.timestamp,
            "provider": r.provider,
            "event_type": r.event_type,
            "status": r.status,
            "payload": json.loads(r.payload_json),
        }


def insert_integration_event(record: dict[str, Any]) -> None:
    with get_session() as s:
        s.merge(IntegrationEventRecord(
            integration_event_id=record["integration_event_id"],
            timestamp=record["timestamp"],
            provider=record["provider"],
            event_type=record["event_type"],
            status=record["status"],
            payload_json=json.dumps(record.get("payload", {}), default=str),
        ))
        s.commit()


def list_integration_events(limit: int = 50) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(select(IntegrationEventRecord).order_by(IntegrationEventRecord.timestamp.desc()).limit(max(1, min(limit, 200)))).scalars().all()
        return [{"integration_event_id": r.integration_event_id, "timestamp": r.timestamp, "provider": r.provider, "event_type": r.event_type, "status": r.status, "payload": json.loads(r.payload_json)} for r in rows]


# ---------------------------------------------------------------------------
# Test / dev utility
# ---------------------------------------------------------------------------

def reset_all() -> None:
    """Used only by the test suite to guarantee a clean database per run."""
    with get_session() as s:
        for model in (DecisionRecord, ExecutionRecord, SequenceRecord, MandateSequenceRecord,
                      PolicyExperimentRecord, B2BChaseRecord, PromiseRecord, IntegrationEventRecord):
            s.execute(delete(model))
        s.commit()


# ---------------------------------------------------------------------------
# Platform control-plane records (incidents / feedback / demo state)
# ---------------------------------------------------------------------------

def upsert_platform_record(record_type: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        row = s.get(PlatformRecord, record_id)
        if row is None:
            row = PlatformRecord(record_id=record_id, record_type=record_type, updated_at=now, payload_json=json.dumps(payload, default=str))
            s.add(row)
        else:
            row.record_type = record_type
            row.updated_at = now
            row.payload_json = json.dumps(payload, default=str)
        s.commit()
        return json.loads(row.payload_json)


def list_platform_records(record_type: str, limit: int = 200) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.execute(select(PlatformRecord).where(PlatformRecord.record_type == record_type).order_by(PlatformRecord.updated_at.desc()).limit(max(1, min(limit, 1000)))).scalars().all()
        return [json.loads(r.payload_json) for r in rows]


def get_platform_record(record_type: str, record_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = s.get(PlatformRecord, record_id)
        if row is None or row.record_type != record_type:
            return None
        return json.loads(row.payload_json)
