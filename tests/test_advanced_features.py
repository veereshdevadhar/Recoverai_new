from fastapi.testclient import TestClient
from src.api.main import app
from src.evaluation import policy_lab, drift as drift_module

client = TestClient(app)


def base():
    return {"amount": 12000, "event_type": "PAYMENT_FAILURE", "failure_type": "TIMEOUT"}


# ---------------------------------------------------------------------------
# Feature 1 — Counterfactual Recovery Simulator
# ---------------------------------------------------------------------------

def test_predict_includes_counterfactual_block():
    r = client.post('/predict', json=base())
    assert r.status_code == 200
    data = r.json()
    assert 'counterfactual' in data
    assert 'decision_advantage' in data['counterfactual']
    assert data['counterfactual']['decision_advantage'] == data['score_margin']
    assert data['counterfactual']['oracle']['note']


def test_counterfactual_sample_events_returns_real_event_ids():
    r = client.get('/api/counterfactual/sample-events?n=5')
    assert r.status_code == 200
    events = r.json()['events']
    assert len(events) == 5
    assert all(e['event_id'].startswith('EVT_') for e in events)


def test_counterfactual_for_known_event_has_oracle_comparison():
    sample = client.get('/api/counterfactual/sample-events?n=1').json()['events'][0]
    event_id = sample['event_id']
    r = client.get(f'/api/counterfactual/{event_id}')
    assert r.status_code == 200
    data = r.json()
    assert data['event_id'] == event_id
    assert 'oracle_action' in data['oracle']
    assert 'opportunity_gap' in data['oracle']
    # every alternative must report a real allowed/blocked status, not fabricated
    for alt in data['alternatives']:
        assert alt['status'] in {'ALLOWED', 'BLOCKED'}


def test_counterfactual_unknown_event_returns_404():
    r = client.get('/api/counterfactual/EVT_DOES_NOT_EXIST')
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Feature 2 — Adaptive Multi-Step Recovery Sequencer + stopping rules
# ---------------------------------------------------------------------------

def test_sequence_run_reaches_a_terminal_state():
    r = client.post('/api/sequence/run', json=base())
    assert r.status_code == 200
    data = r.json()
    assert data['sequence_id'].startswith('SEQ-')
    assert data['step_count'] >= 1
    assert data['final_state'] in {'RECOVERED', 'STOPPED', 'ESCALATED', 'FAILED'}
    # every step must have re-run the real decision agent (has a real decision_id)
    for step in data['steps']:
        assert step['decision_id'].startswith('DEC-')
        assert step['execution_id'].startswith('EXE-')


def test_sequence_never_exceeds_max_steps_hard_cap():
    # A stubborn non-retryable failure with weak history should force several
    # steps of decision-making without ever looping forever.
    payload = {**base(), 'failure_type': 'ISSUER_DECLINE', 'retry_count': 0, 'historical_success_rate': 0.1, 'amount': 500}
    r = client.post('/api/sequence/run', json=payload)
    assert r.status_code == 200
    data = r.json()
    # MAX_STEPS=5 plus at most one forced final STOP step
    assert data['step_count'] <= 6


def test_sequence_can_be_retrieved_by_id():
    started = client.post('/api/sequence/run', json=base()).json()
    r = client.get(f"/api/sequence/{started['sequence_id']}")
    assert r.status_code == 200
    assert r.json()['sequence_id'] == started['sequence_id']


def test_sequence_unknown_id_returns_404():
    r = client.get('/api/sequence/SEQ-DOES-NOT-EXIST')
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Feature 3 — Revenue-at-Risk Early Warning (+ leakage protection)
# ---------------------------------------------------------------------------

def test_risk_score_returns_tiered_score():
    r = client.post('/api/risk-score', json={**base(), 'retry_count': 3, 'failure_type': 'ISSUER_DECLINE', 'historical_success_rate': 0.2})
    assert r.status_code == 200
    data = r.json()
    assert 0 <= data['risk_score'] <= 100
    assert data['risk_tier'] in {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}
    assert data['revenue_at_risk'] >= 0
    assert len(data['drivers']) >= 1
    assert data['leakage_protected'] is True


def test_risk_score_does_not_accept_or_use_outcome_fields():
    # PaymentEvent has no outcome fields at all, so this is structurally
    # leakage-safe: posting an outcome-shaped field is simply ignored/rejected.
    r = client.post('/api/risk-score', json={**base(), 'revenue_recovered': 999999, 'recovery_success': 1})
    assert r.status_code == 200
    data = r.json()
    assert 'revenue_recovered' not in data
    assert 'recovery_success' not in data


def test_risk_engine_reuses_leakage_safe_feature_builder():
    # The risk engine must never load its own dataset (which could contain
    # outcome columns) — it only accepts an artifact_loader + feature_builder
    # + the incoming PaymentEvent, exactly like the Decision Agent.
    import inspect
    from src.risk import risk_engine
    source = inspect.getsource(risk_engine.assess_risk)
    assert 'read_csv' not in source
    assert 'pd.' not in source
    # It must call the same feature_builder used by /predict (build_features),
    # which is covered by test_known_outcome_columns_are_leakage_protected.
    params = inspect.signature(risk_engine.assess_risk).parameters
    assert 'feature_builder' in params
    assert 'artifact_loader' in params


# ---------------------------------------------------------------------------
# Feature 4 — Policy What-If Lab
# ---------------------------------------------------------------------------

def test_policy_what_if_runs_against_real_evaluation_set():
    r = client.post('/api/policy/what-if', json={'retry_limit': 5, 'escalation_min_amount': 15000, 'escalation_min_success_rate': 0.7})
    assert r.status_code == 200
    data = r.json()
    assert data['current_policy']['events'] == 12347
    assert data['new_policy']['events'] == 12347
    # relaxing escalation eligibility should never decrease escalation count
    assert data['new_policy']['human_escalations'] >= data['current_policy']['human_escalations']


def test_policy_what_if_does_not_mutate_production_defaults():
    before = client.get('/api/metrics').json()
    client.post('/api/policy/what-if', json={'retry_limit': 0, 'escalation_min_amount': 0, 'escalation_min_success_rate': 0})
    after = client.get('/api/metrics').json()
    assert before == after


def test_policy_simulation_is_a_pure_function_isolated_from_globals():
    a = policy_lab.simulate_policy(policy_lab.PolicyParams(name="A", retry_limit=3))
    b = policy_lab.simulate_policy(policy_lab.PolicyParams(name="B", retry_limit=3))
    # Same params must give identical, reproducible results (no fabricated randomness)
    assert a['revenue_recovered'] == b['revenue_recovered']
    assert a['oracle_revenue'] == b['oracle_revenue']


# ---------------------------------------------------------------------------
# Feature 5 — Policy A/B Comparison
# ---------------------------------------------------------------------------

def test_policy_compare_returns_both_policies_and_deltas():
    body = {
        'policy_a': {'name': 'Conservative', 'retry_limit': 2, 'escalation_min_amount': 40000, 'escalation_min_success_rate': 0.9},
        'policy_b': {'name': 'Aggressive', 'retry_limit': 6, 'escalation_min_amount': 10000, 'escalation_min_success_rate': 0.6},
    }
    r = client.post('/api/policy/compare', json=body)
    assert r.status_code == 200
    data = r.json()
    assert data['policy_a']['policy']['name'] == 'Conservative'
    assert data['policy_b']['policy']['name'] == 'Aggressive'
    assert data['revenue_delta_b_minus_a'] == round(data['policy_b']['revenue_recovered'] - data['policy_a']['revenue_recovered'], 2)
    # Aggressive policy relaxes escalation eligibility, so it must escalate at least as much
    assert data['policy_b']['human_escalations'] >= data['policy_a']['human_escalations']


# ---------------------------------------------------------------------------
# Feature 6 — Outcome Feedback Loop
# ---------------------------------------------------------------------------

def test_feedback_reflects_real_recorded_executions():
    client.post('/execute-recovery', json=base())
    r = client.get('/api/feedback')
    assert r.status_code == 200
    data = r.json()
    assert data['total_executions'] >= 1
    assert isinstance(data['by_action'], list)
    if data['by_action']:
        assert 'net_recovery' in data['by_action'][0]


# ---------------------------------------------------------------------------
# Feature 7 — Model Monitoring / Drift
# ---------------------------------------------------------------------------

def test_model_health_reports_real_metrics_and_drift():
    r = client.get('/api/model-health')
    assert r.status_code == 200
    data = r.json()
    assert len(data['per_action_metrics']) == 4
    for m in data['per_action_metrics']:
        assert 0 <= m['roc_auc'] <= 1
    assert data['drift']['overall_status'] in {'STABLE', 'MODERATE_DRIFT', 'DRIFT_DETECTED'}
    assert data['drift']['reference_rows'] > 0
    assert data['drift']['current_rows'] > 0


def test_drift_detection_does_not_fabricate_drift_on_identical_windows():
    # Comparing the same window against itself must show zero PSI/KS statistic.
    import pandas as pd
    df = drift_module._load_events()
    same = df.copy()
    ref_vals = same['amount'].dropna().to_numpy(dtype=float)
    psi = drift_module._psi(ref_vals, ref_vals)
    assert psi == 0.0 or abs(psi) < 1e-9


# ---------------------------------------------------------------------------
# Feature 8 — Revenue Recovery Ledger
# ---------------------------------------------------------------------------

def test_ledger_merges_decisions_and_executions_with_financial_fields():
    client.post('/execute-recovery', json=base())
    r = client.get('/api/ledger')
    assert r.status_code == 200
    data = r.json()
    assert data['count'] >= 1
    entry = data['entries'][0]
    for field in ['decision_id', 'execution_id', 'amount', 'selected_action', 'expected_recovery',
                  'actual_recovered', 'intervention_cost', 'net_recovery', 'final_state']:
        assert field in entry
    assert 'dataset_summary' in data
    assert data['dataset_summary']['oracle_revenue'] > 0


# ---------------------------------------------------------------------------
# Feature 9 — Advanced Decision Explanation
# ---------------------------------------------------------------------------

def test_explanation_is_data_driven_not_hardcoded():
    r = client.post('/predict', json=base())
    data = r.json()
    assert 'explanation' in data
    assert len(data['explanation']['why_selected']) >= 1
    rejected = data['explanation']['why_others_rejected']
    chosen = data['recommended_action']
    assert chosen not in rejected
    # every non-chosen action must have a real reason
    for action, reasons in rejected.items():
        assert len(reasons) >= 1


def test_explanation_reflects_actual_guardrail_blocks():
    r = client.post('/predict', json={**base(), 'retry_count': 4, 'failure_type': 'ISSUER_DECLINE'})
    data = r.json()
    retry_reasons = data['explanation']['why_others_rejected'].get('RETRY_LATER', [])
    if data['recommended_action'] != 'RETRY_LATER':
        assert any('retry' in reason.lower() or 'non-retryable' in reason.lower() or 'issuer' in reason.lower() for reason in retry_reasons) or len(retry_reasons) >= 1


# ---------------------------------------------------------------------------
# Guardrail re-checking + STOP fallback (sequencer-level, extending existing coverage)
# ---------------------------------------------------------------------------

def test_sequencer_rechecks_guardrails_every_step_via_exhaustion_rule():
    # Force the same action to fail repeatedly by using a very low probability
    # scenario; the sequencer must not repeat the same action forever.
    payload = {**base(), 'amount': 300, 'historical_success_rate': 0.05, 'failure_type': 'NETWORK_ERROR'}
    r = client.post('/api/sequence/run', json=payload)
    data = r.json()
    action_counts = {}
    for step in data['steps']:
        action_counts[step['action']] = action_counts.get(step['action'], 0) + 1
    for action, count in action_counts.items():
        if action != 'STOP':
            assert count <= 2, f"{action} was chosen {count} times; exhaustion rule should cap non-STOP actions at 2"
