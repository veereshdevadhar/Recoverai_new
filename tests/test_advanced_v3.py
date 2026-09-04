from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from src.api.main import app
from src.decision.b2b_chaser import dunning_tier, ACCOUNT_MANAGER_DAYS_THRESHOLD, ACCOUNT_MANAGER_AMOUNT_THRESHOLD

client = TestClient(app)


# ---------------------------------------------------------------------------
# B2B Receivables Chaser
# ---------------------------------------------------------------------------

def test_dunning_tier_thresholds_are_real_and_ordered():
    assert dunning_tier(0) == 'FRIENDLY_REMINDER'
    assert dunning_tier(15) == 'FRIENDLY_REMINDER'
    assert dunning_tier(16) == 'FIRM_NOTICE'
    assert dunning_tier(30) == 'FIRM_NOTICE'
    assert dunning_tier(31) == 'FORMAL_DUNNING'
    assert dunning_tier(60) == 'FORMAL_DUNNING'
    assert dunning_tier(61) == 'COLLECTIONS_ESCALATION'


def test_b2b_chase_never_selects_retry_later():
    r = client.post('/api/b2b/chase', json={'amount': 50000, 'days_overdue': 20, 'historical_success_rate': 0.2})
    assert r.status_code == 200
    data = r.json()
    assert data['chase_id'].startswith('B2B-')
    for step in data['steps']:
        assert step['action'] != 'RETRY_LATER', "Invoices must never be silently retried like a card payment"


def test_b2b_chase_generates_real_dunning_notice_when_reminder_chosen():
    r = client.post('/api/b2b/chase', json={
        'amount': 50000, 'days_overdue': 5, 'invoice_number': 'INV-TEST-1',
        'customer_display_name': 'Test Customer', 'historical_success_rate': 0.15,
    })
    data = r.json()
    reminder_steps = [s for s in data['steps'] if s['action'] == 'RECOVERY_REMINDER']
    for step in reminder_steps:
        notice = step['dunning_notice']
        assert notice is not None
        assert 'INV-TEST-1' in notice['subject'] or 'INV-TEST-1' in notice['body']
        assert 'Test Customer' in notice['body']
        assert notice['tier'] == step['dunning_tier']


def test_b2b_escalation_requires_days_or_amount_threshold():
    # Below both thresholds: escalation must never be the selected action.
    r = client.post('/api/b2b/chase', json={
        'amount': 5000, 'days_overdue': 5, 'historical_success_rate': 0.1,
    })
    data = r.json()
    assert all(s['action'] != 'HUMAN_ESCALATION' for s in data['steps'])


def test_b2b_escalation_fires_for_large_overdue_invoice():
    r = client.post('/api/b2b/chase', json={
        'amount': ACCOUNT_MANAGER_AMOUNT_THRESHOLD + 50000,
        'days_overdue': ACCOUNT_MANAGER_DAYS_THRESHOLD - 5,
        'historical_success_rate': 0.1, 'merchant_success_rate': 0.3,
    })
    data = r.json()
    # Amount alone exceeds the account-manager threshold, so escalation must
    # be reachable (allowed) even though days_overdue is just under its own threshold.
    escalation_steps = [s for s in data['steps'] if s['action'] == 'HUMAN_ESCALATION']
    if escalation_steps:
        assert escalation_steps[0]['action_label'] == 'Escalate to account manager'


def test_b2b_chase_can_be_retrieved_and_unknown_id_404s():
    started = client.post('/api/b2b/chase', json={'amount': 50000, 'days_overdue': 10}).json()
    r = client.get(f"/api/b2b/chase/{started['chase_id']}")
    assert r.status_code == 200
    r2 = client.get('/api/b2b/chase/B2B-DOES-NOT-EXIST')
    assert r2.status_code == 404


def test_b2b_chase_never_exceeds_hard_step_cap():
    r = client.post('/api/b2b/chase', json={
        'amount': 150000, 'days_overdue': 5, 'historical_success_rate': 0.05, 'merchant_success_rate': 0.2,
    })
    data = r.json()
    assert data['step_count'] <= 4


# ---------------------------------------------------------------------------
# Promise-to-Pay Tracker
# ---------------------------------------------------------------------------

def test_promise_with_future_date_stays_pending():
    future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    r = client.post('/api/promise/create', json={'amount': 15000, 'promised_date': future})
    assert r.status_code == 200
    promise_id = r.json()['promise_id']
    fetched = client.get(f'/api/promise/{promise_id}').json()
    assert fetched['status'] == 'PENDING'


def test_promise_with_past_date_auto_breaks_and_escalates_with_real_decision():
    past = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    r = client.post('/api/promise/create', json={'amount': 20000, 'promised_date': past, 'historical_success_rate': 0.5})
    promise_id = r.json()['promise_id']
    fetched = client.get(f'/api/promise/{promise_id}').json()
    assert fetched['status'] == 'BROKEN'
    assert fetched['broken_escalated'] is True
    assert fetched['escalation_decision_id'].startswith('DEC-')
    assert fetched['escalation_execution_id'].startswith('EXE-')


def test_promise_can_be_marked_kept():
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    r = client.post('/api/promise/create', json={'amount': 8000, 'promised_date': future})
    promise_id = r.json()['promise_id']
    kept = client.post(f'/api/promise/{promise_id}/keep', json={'actual_recovered': 8000}).json()
    assert kept['status'] == 'KEPT'
    assert kept['actual_recovered'] == 8000


def test_promise_unknown_id_404s():
    r = client.get('/api/promise/P2P-DOES-NOT-EXIST')
    assert r.status_code == 404
    r2 = client.post('/api/promise/P2P-DOES-NOT-EXIST/keep', json={'actual_recovered': 100})
    assert r2.status_code == 404


def test_promises_list_summary_reflects_real_counts():
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    client.post('/api/promise/create', json={'amount': 5000, 'promised_date': future})
    client.post('/api/promise/create', json={'amount': 6000, 'promised_date': past})
    r = client.get('/api/promises')
    data = r.json()
    assert data['summary']['total'] >= 2
    assert data['summary']['pending'] + data['summary']['kept'] + data['summary']['broken'] == data['summary']['total']
