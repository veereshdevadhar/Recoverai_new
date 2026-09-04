from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_budget_optimizer_respects_budget_and_returns_mix():
    r = client.post('/api/budget/optimize', json={'budget': 10000})
    assert r.status_code == 200
    d = r.json()
    assert d['budget_used'] <= 10000 + 1e-6
    assert d['expected_net_value'] >= 0
    assert d['model_version'].lower().startswith('v3')
    assert d['action_mix']


def test_budget_zero_is_safe_stop_plan():
    r = client.post('/api/budget/optimize', json={'budget': 0})
    assert r.status_code == 200
    d = r.json()
    assert d['budget_used'] == 0
    assert d['expected_recovery'] == 0
    assert any(x['action'] == 'STOP' and x['events'] == d['events_planned'] for x in d['action_mix'])


def test_digital_twin_is_scenario_not_realized_revenue():
    r = client.post('/api/digital-twin', json={
        'volume_multiplier': 1.2,
        'amount_multiplier': 1.1,
        'recovery_multiplier': 0.95,
    })
    assert r.status_code == 200
    d = r.json()
    assert d['events_planned'] == round(12347 * 1.2)
    assert d['expected_recovery'] >= 0
    assert 'modelled planning scenario' in d['methodology']


def test_risk_score_excludes_blocked_actions_from_best_action():
    r = client.post('/api/risk-score', json={
        'amount': 12000,
        'event_type': 'PAYMENT_FAILURE',
        'failure_type': 'ISSUER_DECLINE',
        'retry_count': 4,
        'historical_success_rate': 0.2,
        'merchant_success_rate': 0.9,
    })
    assert r.status_code == 200
    d = r.json()
    assert 'RETRY_LATER' in d['blocked_actions']
    assert d['recommended_preventive_action'] != 'RETRY_LATER'


def test_digital_twin_budget_is_a_total_cap_even_when_volume_scales():
    r = client.post('/api/digital-twin', json={
        'volume_multiplier': 2.0,
        'amount_multiplier': 1.0,
        'recovery_multiplier': 1.0,
        'budget': 10000,
    })
    assert r.status_code == 200
    d = r.json()
    assert d['budget_used'] <= 10000 + 1e-6
    assert d['events_planned'] == 24694
