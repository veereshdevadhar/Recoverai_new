import hashlib
import hmac
import json

from fastapi.testclient import TestClient


def _signed(body, secret, event_id):
    raw = json.dumps(body, separators=(",", ":")).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id}


def test_production_failed_webhook_is_observe_only_when_disarmed(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "PRODUCTION")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RECOVERAI_PRODUCTION_EXECUTION_ARMED", "0")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "prod-secret")
    body = {"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay-observe-unique-92731", "amount": 150000, "currency": "INR", "method": "upi", "error_description": "network timeout"}}}}
    raw, headers = _signed(body, "prod-secret", "evt-observe-unique-92731")
    r = TestClient(__import__("src.api.main", fromlist=["app"]).app).post("/api/integrations/razorpay/webhook", content=raw, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "OBSERVED"
    assert r.json()["decision"]["recommended_action"] in {"ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION", "STOP"}


def test_production_webhook_duplicate_is_idempotent(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "PRODUCTION")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RECOVERAI_PRODUCTION_EXECUTION_ARMED", "0")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "prod-secret-2")
    body = {"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay-dup-unique-92731", "amount": 99000, "currency": "INR", "method": "upi", "error_description": "timeout"}}}}
    raw, headers = _signed(body, "prod-secret-2", "evt-dup-unique-92731")
    c = TestClient(__import__("src.api.main", fromlist=["app"]).app)
    assert c.post("/api/integrations/razorpay/webhook", content=raw, headers=headers).status_code == 200
    second = c.post("/api/integrations/razorpay/webhook", content=raw, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "DUPLICATE_IGNORED"


def test_production_arm_requires_live_credentials_and_webhook_secret(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "PRODUCTION")
    monkeypatch.setenv("RECOVERAI_ADMIN_TOKEN", "admin-test")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_not_live")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "secret")
    from src.api.main import app
    r = TestClient(app).post("/api/production/arm", json={"enabled": True, "admin_token": "admin-test", "confirm_live": True})
    assert r.status_code == 400
    assert "live credentials" in r.json()["detail"].lower()
