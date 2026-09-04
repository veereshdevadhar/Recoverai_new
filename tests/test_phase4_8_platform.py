from fastapi.testclient import TestClient

from src.api.main import app
from src import merchant_simulator as msim

client = TestClient(app)


def seed_incident():
    client.post('/api/merchant-sim/reset')
    client.post('/api/merchant-sim/incident', json={'incident': 'UPI_DEGRADATION'})
    customers = client.get('/api/merchant-sim/customers').json()['customers']
    for i in range(5):
        client.post('/api/merchant-sim/purchase', json={
            'customer_id': customers[i % 3]['customer_id'],
            'product_id': 'PRD_HEADPHONES',
            'method': 'UPI',
            'force_fail': True,
        })


def test_phase4_incident_aware_autopilot_and_analytics():
    seed_incident()
    d = client.post('/api/revenue-intelligence/autopilot').json()
    assert d['merchant_incidents']['incidents']
    assert d['incident_blast_radius']['affected_unique_customers'] >= 3
    assert d['outcome_analytics']['status'] == 'COMPLETED'
    assert d['feedback_analytics']['learning_status'].endswith('NO_AUTOMATIC_RETRAIN')
    assert all(x.get('incident_id') for x in d['executions'] if x.get('execution_state') != 'STOPPED')


def test_phase5_incident_analytics_endpoint():
    seed_incident()
    incident = client.get('/api/revenue-intelligence/merchant-incidents?include_simulator=true').json()['incidents'][0]
    d = client.get(f"/api/revenue-intelligence/incidents/{incident['incident_id']}/analytics").json()
    assert d['summary']['revenue_exposed'] >= 44995
    assert 'incremental_recovery_vs_model' in d['summary']
    assert 'recovery_roi' in d['summary']


def test_phase6_feedback_is_persistent_and_evaluation_only():
    seed_incident()
    client.post('/api/revenue-intelligence/autopilot')
    d = client.get('/api/revenue-intelligence/feedback-analytics').json()
    assert d['total_feedback'] >= 1
    assert d['learning_status'] == 'EVALUATION_ONLY_NO_AUTOMATIC_RETRAIN'


def test_phase7_demo_closes_and_resolves():
    d = client.post('/api/revenue-intelligence/demo').json()
    assert d['status'] == 'COMPLETED'
    assert d['incident']['severity'] in {'HIGH', 'CRITICAL'}
    assert d['analytics']['summary']['revenue_recovered'] > 0
    assert d['monitoring']['status'] == 'RESOLVED'
    assert any(e['event_type'] == 'ORDER_PAID' for e in d['timeline'])


def test_phase8_safety_audit_passes():
    d = client.get('/api/revenue-intelligence/safety-audit').json()
    assert d['status'] == 'PASS'
    assert all(c['status'] == 'PASS' for c in d['checks'])
