import os
import json
import hmac
import hashlib
from fastapi.testclient import TestClient


def _client():
    os.environ["RECOVERAI_EXECUTION_ENV"] = "DEMO"
    os.environ["RECOVERAI_LIVE_EXECUTION"] = "0"
    os.environ.pop("RAZORPAY_WEBHOOK_SECRET", None)
    from src.api.main import app
    return TestClient(app)

def test_payment_success_is_safe_stop():
    c = _client()
    p = {"event_id":"TEST-SUCCESS", "amount":12000, "event_type":"PAYMENT_SUCCESS", "payment_method":"UPI", "failure_type":"TIMEOUT", "retry_count":0, "historical_success_rate":0.85, "total_transactions":20, "avg_transaction_amount":5000, "merchant_success_rate":0.9}
    r = c.post("/predict", json=p)
    assert r.status_code == 200
    d = r.json()
    assert d["recommended_action"] == "STOP"
    assert d["guardrails"]["RETRY_LATER"]["allowed"] is False

def test_demo_cannot_be_used_as_live():
    c = _client()
    p = {"event_id":"TEST-LIVE-BLOCK", "amount":12000, "event_type":"PAYMENT_FAILURE", "payment_method":"UPI", "failure_type":"TIMEOUT", "retry_count":0, "historical_success_rate":0.85, "total_transactions":20, "avg_transaction_amount":5000, "merchant_success_rate":0.9}
    d = c.post("/predict", json=p).json()
    r = c.post("/execute-decision", json={"payload":p,"decision":d,"live":True,"channel":"auto","live_confirmation":True})
    assert r.status_code == 400

def test_razorpay_webhook_signature_and_verification(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "unit-test-secret")
    from src.api.main import app
    from src.db import repository as repo
    from datetime import datetime, timezone
    eid = "EXE-UNIT-WEBHOOK"
    repo.insert_execution({"execution_id":eid,"decision_id":"DEC-UNIT","timestamp":datetime.now(timezone.utc).isoformat(),"execution_mode":"LIVE_EXTERNAL","action":"ALTERNATIVE_PAYMENT","amount":12000,"event_type":"PAYMENT_FAILURE","reason":"test","state":"EXECUTED","outcome":"LIVE_PROVIDER_ACCEPTED","outcome_reason":"test","revenue_recovered":0,"expected_probability":.8,"expected_recovery":9600,"intervention_cost":10,"net_recovery":-10,"terminal":False,"state_history":[]})
    body = {"event":"payment_link.paid","payload":{"payment_link":{"entity":{"reference_id":eid,"amount_paid":1200000}}}}
    raw = json.dumps(body,separators=(",",":")).encode()
    sig = hmac.new(b"unit-test-secret", raw, hashlib.sha256).hexdigest()
    c = TestClient(app)
    ok = c.post("/api/integrations/razorpay/webhook", content=raw, headers={"X-Razorpay-Signature":sig})
    assert ok.status_code == 200
    assert ok.json()["execution"]["state"] == "RECOVERED"
    bad = c.post("/api/integrations/razorpay/webhook", content=raw, headers={"X-Razorpay-Signature":"bad"})
    assert bad.status_code == 401
