from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def base():
    return {"amount": 12000, "event_type": "PAYMENT_FAILURE", "failure_type": "TIMEOUT"}


def test_health():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_metrics_match_v2_champion():
    data = client.get('/api/metrics').json()
    assert data['dataset_events'] == 100000
    assert data['events'] == 12347
    assert data['revenue_recovered'] > data['baseline_revenue']
    assert data['oracle_revenue'] > data['revenue_recovered']


def test_prediction_has_all_actions_and_stop():
    r = client.post('/predict', json=base())
    assert r.status_code == 200
    data = r.json()
    assert data['recommended_action'] in {'ALTERNATIVE_PAYMENT', 'RECOVERY_REMINDER', 'RETRY_LATER', 'HUMAN_ESCALATION', 'STOP'}
    assert set(data['probabilities']) == {'ALTERNATIVE_PAYMENT', 'RECOVERY_REMINDER', 'RETRY_LATER', 'HUMAN_ESCALATION'}
    assert set(data['guardrails']) == {'ALTERNATIVE_PAYMENT', 'RECOVERY_REMINDER', 'RETRY_LATER', 'HUMAN_ESCALATION', 'STOP'}


def test_guardrails_can_block_retry_and_human():
    r = client.post('/predict', json={
        **base(), 'amount': 12000, 'retry_count': 4, 'failure_type': 'ISSUER_DECLINE', 'historical_success_rate': 0.20
    })
    assert r.status_code == 200
    data = r.json()
    assert data['guardrails']['RETRY_LATER']['allowed'] is False
    assert data['guardrails']['HUMAN_ESCALATION']['allowed'] is False
    assert data['recommended_action'] != 'RETRY_LATER'


def test_high_value_strong_customer_can_allow_human():
    r = client.post('/predict', json={
        **base(), 'amount': 50000, 'retry_count': 1, 'historical_success_rate': 0.92
    })
    assert r.status_code == 200
    assert r.json()['guardrails']['HUMAN_ESCALATION']['allowed'] is True


def test_model_card_and_guardrail_endpoints():
    assert client.get('/api/model-card').status_code == 200
    rules = client.get('/api/guardrails').json()['rules']
    assert any(r['action'] == 'HUMAN_ESCALATION' for r in rules)


def test_decision_agent_endpoint_exposes_real_pipeline():
    r = client.get('/api/decision-agent')
    assert r.status_code == 200
    data = r.json()
    assert data['name'] == 'RecoverAI Decision Agent'
    assert data['external_llm_required'] is False
    assert [x['id'] for x in data['stages']] == [
        'CONTEXT', 'FEATURES', 'ML_SCORING', 'VALUE_SCORING', 'GUARDRAILS', 'DECISION', 'AUDIT', 'EXECUTION'
    ]


def test_prediction_contains_agent_trace():
    r = client.post('/predict', json=base())
    assert r.status_code == 200
    data = r.json()
    assert data['agent']['name'] == 'RecoverAI Decision Agent'
    assert [x['step'] for x in data['agent']['trace']] == [
        'CONTEXT', 'FEATURES', 'ML_SCORING', 'VALUE_SCORING', 'GUARDRAILS', 'DECISION', 'AUDIT'
    ]


def test_stop_is_safe_fallback_and_always_allowed():
    r = client.post('/predict', json={**base(), 'amount': 1})
    assert r.status_code == 200
    assert r.json()['guardrails']['STOP']['allowed'] is True


def test_bounded_execution_rechecks_policy_and_returns_state():
    r = client.post('/execute-recovery', json=base())
    assert r.status_code == 200
    data = r.json()
    assert data['decision']['decision_id'].startswith('DEC-')
    execution = data['execution']
    assert execution['execution_id'].startswith('EXE-')
    assert execution['execution_mode'] == 'SIMULATED_BOUNDED'
    assert execution['state_history'][0]['state'] == 'DETECTED'
    assert execution['state_history'][1]['state'] == 'DECIDED'
    assert execution['state_history'][2]['state'] == 'EXECUTING'
    assert execution['state'] in {'RECOVERED','FAILED','STOPPED','ESCALATED','SCHEDULED'}


def test_execution_rejects_stale_blocked_decision():
    prediction = client.post('/predict', json={**base(), 'retry_count': 4, 'failure_type': 'ISSUER_DECLINE'}).json()
    prediction['recommended_action'] = 'RETRY_LATER'
    prediction['guardrails']['RETRY_LATER']['allowed'] = True
    r = client.post('/execute-decision', json={'payload': {**base(), 'retry_count': 4, 'failure_type': 'ISSUER_DECLINE'}, 'decision': prediction})
    assert r.status_code == 200
    assert r.json()['state'] == 'FAILED'
    assert r.json()['outcome'] == 'BLOCKED_BY_GUARDRAIL'


def test_integration_test_executes_selected_allowed_action_not_ai_recommendation():
    payload = {
        "event_id": "INTEGRATION-SELECTED-1", "amount": 1000,
        "event_type": "PAYMENT_FAILURE", "payment_method": "UPI",
        "failure_type": "TIMEOUT", "retry_count": 2,
        "historical_success_rate": 0.65, "total_transactions": 20,
        "avg_transaction_amount": 2000, "merchant_success_rate": 0.89,
    }
    decision = client.post('/predict', json=payload).json()
    allowed_nonrecommended = [
        x['action'] for x in decision['ranked_actions']
        if x['allowed'] and x['action'] != decision['recommended_action'] and x['action'] != 'STOP'
    ]
    assert allowed_nonrecommended, 'Need at least one allowed action different from the recommendation for this integration test.'
    selected_action = allowed_nonrecommended[0]
    execution = client.post('/execute-decision', json={
        'payload': payload, 'decision': decision, 'live': False,
        'channel': 'auto', 'selected_action': selected_action,
    })
    assert execution.status_code == 200
    d = execution.json()
    assert d['action'] == selected_action
    assert d['recommended_action'] == decision['recommended_action']
    assert d['selection_source'] == 'INTEGRATION_TEST'
    assert d['action'] != d['recommended_action']
