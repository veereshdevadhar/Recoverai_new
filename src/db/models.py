from __future__ import annotations

from sqlalchemy import String, Float, Integer, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.db.database import Base


class DecisionRecord(Base):
    __tablename__ = "decisions"

    decision_id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[float] = mapped_column(Float)
    event_type: Mapped[str] = mapped_column(String)
    failure_type: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer)
    customer_success_rate: Mapped[float] = mapped_column(Float)
    recommended_action: Mapped[str] = mapped_column(String)
    confidence: Mapped[str] = mapped_column(String)
    model_version: Mapped[str] = mapped_column(String)
    guardrail_blocked_actions_json: Mapped[str] = mapped_column(Text)
    feature_attribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExecutionRecord(Base):
    __tablename__ = "executions"

    execution_id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[str] = mapped_column(String, index=True)
    execution_mode: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    event_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revenue_recovered: Mapped[float] = mapped_column(Float, default=0.0)
    expected_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_recovery: Mapped[float | None] = mapped_column(Float, nullable=True)
    intervention_cost: Mapped[float] = mapped_column(Float, default=0.0)
    net_recovery: Mapped[float] = mapped_column(Float, default=0.0)
    terminal: Mapped[bool] = mapped_column(Boolean, default=True)
    state_history_json: Mapped[str] = mapped_column(Text)


class SequenceRecord(Base):
    __tablename__ = "sequences"

    sequence_id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[str] = mapped_column(String, index=True)
    completed_at: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    failure_type: Mapped[str | None] = mapped_column(String, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer)
    stop_reason: Mapped[str] = mapped_column(Text)
    total_revenue_recovered: Mapped[float] = mapped_column(Float)
    total_intervention_cost: Mapped[float] = mapped_column(Float)
    net_recovery: Mapped[float] = mapped_column(Float)
    final_state: Mapped[str | None] = mapped_column(String, nullable=True)
    steps_json: Mapped[str] = mapped_column(Text)


class MandateSequenceRecord(Base):
    __tablename__ = "mandate_sequences"

    mandate_sequence_id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[str] = mapped_column(String, index=True)
    completed_at: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    requires_afa: Mapped[bool] = mapped_column(Boolean)
    step_count: Mapped[int] = mapped_column(Integer)
    stop_reason: Mapped[str] = mapped_column(Text)
    total_revenue_recovered: Mapped[float] = mapped_column(Float)
    total_intervention_cost: Mapped[float] = mapped_column(Float)
    net_recovery: Mapped[float] = mapped_column(Float)
    final_state: Mapped[str | None] = mapped_column(String, nullable=True)
    mandate_reauth_required: Mapped[bool] = mapped_column(Boolean, default=False)
    steps_json: Mapped[str] = mapped_column(Text)


class B2BChaseRecord(Base):
    __tablename__ = "b2b_chases"

    chase_id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[str] = mapped_column(String, index=True)
    completed_at: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    invoice_number: Mapped[str | None] = mapped_column(String, nullable=True)
    starting_days_overdue: Mapped[float] = mapped_column(Float)
    step_count: Mapped[int] = mapped_column(Integer)
    stop_reason: Mapped[str] = mapped_column(Text)
    total_revenue_recovered: Mapped[float] = mapped_column(Float)
    total_intervention_cost: Mapped[float] = mapped_column(Float)
    net_recovery: Mapped[float] = mapped_column(Float)
    final_state: Mapped[str | None] = mapped_column(String, nullable=True)
    steps_json: Mapped[str] = mapped_column(Text)


class PromiseRecord(Base):
    __tablename__ = "promises"

    promise_id: Mapped[str] = mapped_column(String, primary_key=True)
    decision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    promised_date: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING | KEPT | BROKEN
    actual_recovered: Mapped[float | None] = mapped_column(Float, nullable=True)
    broken_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_decision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    escalation_execution_id: Mapped[str | None] = mapped_column(String, nullable=True)
    context_json: Mapped[str] = mapped_column(Text)


class PolicyExperimentRecord(Base):
    __tablename__ = "policy_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    params_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)


class IntegrationEventRecord(Base):
    __tablename__ = "integration_events"

    integration_event_id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)


class PlatformRecord(Base):
    __tablename__ = "platform_records"

    record_id: Mapped[str] = mapped_column(String, primary_key=True)
    record_type: Mapped[str] = mapped_column(String, index=True)
    updated_at: Mapped[str] = mapped_column(String, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
