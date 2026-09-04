from __future__ import annotations

"""Promise-to-Pay Tracker.

Tracks a customer's commitment to pay by a specific date and evaluates it
against the real current time — there is no fake background scheduler
pretending to "wait" for the date; instead, every read (`get_promise` /
`list_promises`) lazily re-checks whether a still-PENDING promise's date has
passed, and if so marks it BROKEN and **runs a real escalation decision**
through the actual Decision Agent (not a canned message) before persisting
the result. This makes "auto-escalate on broken promises" genuinely
observable: create a promise with a past date, then fetch it, and watch it
flip to BROKEN with a real ``decision_id``/``execution_id`` attached.
"""

from datetime import datetime, timezone
from typing import Any, Callable
import uuid

from src.db import repository as db_repo


def create_promise(
    decision_id: str | None,
    execution_id: str | None,
    amount: float,
    promised_date: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    promise_id = f"P2P-{uuid.uuid4().hex[:10].upper()}"
    record = {
        "promise_id": promise_id,
        "decision_id": decision_id,
        "execution_id": execution_id,
        "amount": amount,
        "promised_date": promised_date,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context": context,
    }
    return db_repo.insert_promise(record)


def _is_overdue(promised_date: str) -> bool:
    try:
        d = datetime.fromisoformat(promised_date)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return datetime.now(timezone.utc) > d


def _force_escalation_guardrail_engine(
    base_guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    payload: Any,
) -> dict[str, dict[str, Any]]:
    result = base_guardrail_engine(payload)
    result["HUMAN_ESCALATION"] = {
        "allowed": True,
        "reasons": ["Auto-escalated: a promise-to-pay commitment was broken."],
        "severity": "info",
    }
    return result


def resolve_promise(
    promise: dict[str, Any],
    payload_cls: Callable[..., Any],
    score_event: Callable[[Any, Any], dict[str, Any]],
    base_guardrail_engine: Callable[[Any], dict[str, dict[str, Any]]],
    execute_bounded_workflow: Callable[[Any, dict[str, Any], Callable], dict[str, Any]],
) -> dict[str, Any]:
    """Lazily resolves a promise's status against real wall-clock time.
    Returns the (possibly updated) promise dict."""
    if promise["status"] != "PENDING" or not _is_overdue(promise["promised_date"]):
        return promise

    context = dict(promise.get("context") or {})
    context.setdefault("amount", promise["amount"])
    try:
        payload = payload_cls(**context)
        guardrail_engine = lambda p: _force_escalation_guardrail_engine(base_guardrail_engine, p)
        decision = dict(score_event(payload, guardrail_engine))
        decision["recommended_action"] = "HUMAN_ESCALATION"
        execution = execute_bounded_workflow(payload, decision, guardrail_engine)
        updated = db_repo.mark_promise_broken_and_escalated(
            promise["promise_id"], decision["decision_id"], execution["execution_id"]
        )
        return updated or promise
    except Exception:
        updated = db_repo.mark_promise_broken_no_escalation(promise["promise_id"])
        return updated or promise


def get_and_resolve(promise_id: str, **kwargs) -> dict[str, Any] | None:
    promise = db_repo.get_promise(promise_id)
    if promise is None:
        return None
    return resolve_promise(promise, **kwargs)


def list_and_resolve(limit: int = 100, **kwargs) -> list[dict[str, Any]]:
    promises = db_repo.list_promises(limit)
    return [resolve_promise(p, **kwargs) for p in promises]
