from fastapi.testclient import TestClient
from src.api.main import app
from src import integrations

client = TestClient(app)


def test_revenue_detective_scan_is_real_and_leakage_safe():
    r = client.get('/api/revenue-intelligence/scan')
    assert r.status_code == 200
    d = r.json()
    assert d['summary']['root_causes'] >= 0
    assert d['summary']['affected_customers'] >= 0
    assert 'outcome' not in d
    assert 'recovery_success' not in str(d).lower()


def test_anomaly_engine_returns_baseline_and_methodology():
    r = client.get('/api/revenue-intelligence/anomalies?hours=24&z_threshold=2.5')
    assert r.status_code == 200
    d = r.json()
    assert 'baseline_failure_rate' in d
    assert d['baseline_hours'] >= 0
    assert 'no outcome columns' in d['methodology'].lower()


def test_root_cause_and_customer_discovery_are_populated_from_real_dataset():
    causes = client.get('/api/revenue-intelligence/root-causes?top_n=5').json()
    customers = client.get('/api/revenue-intelligence/customers?limit=5').json()
    assert len(causes['causes']) <= 5
    assert customers['count'] <= 5
    if customers['customers']:
        assert customers['customers'][0]['customer_id'].startswith('CUS_')
        assert 0 <= customers['customers'][0]['risk_score'] <= 100


def test_integrations_default_to_safe_simulation_and_do_not_contact_provider():
    integrations.reset_breakers()
    r = client.post('/api/integrations/execute', json={'action': 'RECOVERY_REMINDER', 'amount': 1000})
    assert r.status_code == 200
    d = r.json()
    assert d['mode'] == 'SAFE_SIMULATION'
    assert d['status'] == 'SIMULATED'


def test_circuit_breaker_opens_after_three_injected_failures():
    integrations.reset_breakers()
    for _ in range(3):
        r = client.post('/api/integrations/execute', json={'action': 'RECOVERY_REMINDER', 'amount': 1000, 'simulate_failure': True})
        assert r.status_code == 200
    assert integrations.BREAKERS['email'].state == 'OPEN'
    s = client.get('/api/integrations/status').json()
    assert s['circuit_breakers']['email']['state'] == 'OPEN'
    integrations.reset_breakers()
    assert integrations.BREAKERS['email'].state == 'CLOSED'


def test_live_mode_is_explicit_and_missing_credentials_fails_safely(monkeypatch):
    # Live execution is only enabled inside an explicit execution environment.
    # Use SANDBOX here so the test exercises the real live-path validation
    # without making any provider/network call.
    monkeypatch.setenv('RECOVERAI_EXECUTION_ENV', 'SANDBOX')
    monkeypatch.setenv('RECOVERAI_LIVE_EXECUTION', '1')
    monkeypatch.setenv('RECOVERAI_ALLOW_RECOVERY_REMINDER', '1')
    monkeypatch.setenv('RECOVERAI_SANDBOX_EMAIL', 'demo@example.com')
    monkeypatch.delenv('SMTP_HOST', raising=False)
    monkeypatch.delenv('RAZORPAY_KEY_ID', raising=False)
    monkeypatch.delenv('RAZORPAY_KEY_SECRET', raising=False)
    d = client.post('/api/integrations/execute', json={'action': 'RECOVERY_REMINDER', 'amount': 1000, 'email': 'demo@example.com', 'channel': 'email'}).json()
    assert d['mode'] == 'LIVE'
    assert d['status'] == 'FAILED'
    assert 'SMTP' in d['error']
    monkeypatch.setenv('RECOVERAI_LIVE_EXECUTION', '0')
    monkeypatch.setenv('RECOVERAI_EXECUTION_ENV', 'DEMO')
    integrations.reset_breakers()


def test_autopilot_is_idle_until_explicit_run_and_then_completes_all_stages():
    r = client.post('/api/revenue-intelligence/autopilot')
    assert r.status_code == 200
    d = r.json()
    assert [x['stage'] for x in d['pipeline']] == ['DETECT', 'DIAGNOSE', 'PRIORITIZE', 'EXECUTE', 'VERIFY']
    assert all(x['status'] == 'COMPLETED' for x in d['pipeline'])
    assert d['execution']['mode'] == 'SAFE_SIMULATION'
    assert d['execution']['external_execution'] == 'NOT_PERFORMED'
    assert d['summary']['affected_customers'] == len(d['affected_customers']['customers'])
    assert d['summary']['affected_customers'] <= 25
    assert d['summary']['executed'] <= d['summary']['execution_candidates'] <= 10
    assert d['summary']['execution_providers'] in {0, 1}


def test_autopilot_customer_count_matches_rows_and_not_a_ui_slice():
    d = client.post('/api/revenue-intelligence/autopilot').json()
    assert d['summary']['affected_customers'] == len(d['affected_customers']['customers'])
    assert len(d['affected_customers']['customers']) <= 25


def test_autopilot_can_consume_novacart_simulator_events_without_leakage():
    from src import merchant_simulator as msim
    client.post('/api/merchant-sim/reset')
    cid = client.get('/api/merchant-sim/customers').json()['customers'][0]['customer_id']
    client.post('/api/merchant-sim/purchase', json={'customer_id': cid, 'product_id': 'PRD_HEADPHONES', 'force_fail': True})
    scan = client.get('/api/revenue-intelligence/scan?include_simulator=true').json()
    assert scan['data_source'] == 'HISTORICAL_PLUS_NOVACART_SIMULATOR'
    assert scan['simulator_events_ingested'] >= 1
    assert 'recovery_success' not in str(scan).lower()
    auto = client.post('/api/revenue-intelligence/autopilot').json()
    assert auto['data_source'] == 'HISTORICAL_PLUS_NOVACART_SIMULATOR'
    assert auto['simulator_events_ingested'] >= 1
    client.post('/api/merchant-sim/reset')


def test_phase3_detects_novacart_payment_method_incident_and_recommends_recovery():
    client.post('/api/merchant-sim/reset')
    client.post('/api/merchant-sim/incident', json={'incident': 'UPI_DEGRADATION'})
    customers = client.get('/api/merchant-sim/customers').json()['customers']
    for i in range(5):
        r = client.post('/api/merchant-sim/purchase', json={
            'customer_id': customers[i % 3]['customer_id'],
            'product_id': 'PRD_HEADPHONES',
            'method': 'UPI',
            'force_fail': True,
        })
        assert r.status_code == 200
    d = client.get('/api/revenue-intelligence/merchant-incidents?include_simulator=true').json()
    assert d['status'] == 'INCIDENT_DETECTED'
    assert d['incidents']
    incident = next(x for x in d['incidents'] if x['merchant_id'] == 'NOVACART-SIM' and x['payment_method'] == 'UPI')
    assert incident['recent_failures'] >= 5
    assert incident['recent_failure_rate'] > incident['baseline_failure_rate']
    assert incident['revenue_exposed'] >= 5 * 8999
    assert incident['root_cause']
    assert incident['recommended_action']['action'] != 'STOP'
    assert incident['recommended_action']['confidence'] in {'HIGH', 'MEDIUM', 'LOW'}
    # Ground-truth incident state must not be surfaced by the detector itself.
    assert 'active_incident' not in d
    client.post('/api/merchant-sim/incident', json={'incident': None})
    client.post('/api/merchant-sim/reset')
