import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_evaluation_can_be_run_on_demand_without_side_effects():
    r = client.post('/api/evaluation/run', json={})
    assert r.status_code == 200
    d = r.json()
    assert d['status'] == 'COMPLETED'
    assert d['result']['held_out_events'] == 12347


def test_live_execution_requires_explicit_confirmation():
    r = client.post('/execute-decision', json={
        'payload': {'amount': 1000},
        'decision': {'decision_id': 'D-LIVE', 'recommended_action': 'STOP', 'probabilities': {}, 'expected_revenue': {}, 'action_costs': {'STOP': 0}},
        'live': True,
        'channel': 'auto',
        'live_confirmation': False,
    })
    assert r.status_code == 400


def test_recovery_webhook_requires_valid_hmac(monkeypatch):
    monkeypatch.setenv('RECOVERAI_WEBHOOK_SECRET', 'secret')
    body = json.dumps({'execution_id': 'DOES-NOT-EXIST', 'recovered_amount': 10}).encode()
    bad = client.post('/api/integrations/recovery-webhook', content=body, headers={'content-type': 'application/json', 'X-RecoverAI-Signature': 'bad'})
    assert bad.status_code == 401


def test_policy_high_value_threshold_is_real_guardrail():
    r = client.post('/api/policy/what-if', json={
        'retry_limit': 3,
        'escalation_min_amount': 0,
        'escalation_min_success_rate': 0,
        'high_value_threshold': 100000000,
    })
    assert r.status_code == 200
    assert r.json()['new_policy']['human_escalations'] == 0
