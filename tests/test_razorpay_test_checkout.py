
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_razorpay_test_order_requires_sandbox(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "DEMO")
    from src.api.main import app
    r = TestClient(app).post("/api/razorpay/test/order", json={"amount": 1200})
    assert r.status_code == 400
    assert "RAZORPAY TEST" in r.json()["detail"]


def test_razorpay_test_order_uses_test_key_and_tags_order(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_checkout")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test-secret")

    from src.api import main
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps({
                "id": "order_test_checkout_123",
                "entity": "order",
                "amount": 120000,
                "amount_paid": 0,
                "amount_due": 120000,
                "currency": "INR",
                "status": "created",
            }).encode()

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    r = TestClient(main.app).post(
        "/api/razorpay/test/order",
        json={
            "amount": 1200,
            "customer_name": "Test Customer",
            "email": "test@example.com",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["test_only"] is True
    assert data["key_id"] == "rzp_test_checkout"
    assert data["order"]["id"] == "order_test_checkout_123"
    assert captured["url"] == "https://api.razorpay.com/v1/orders"
    assert captured["body"]["amount"] == 120000
    assert captured["body"]["currency"] == "INR"
    assert captured["body"]["notes"]["recoverai_test_payment"] == "1"


def test_razorpay_test_status_correlates_webhook_events(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    from src.api import main
    from src.db import repository as db_repo
    order_id = "order_test_status_123_unique_20260904"
    db_repo.insert_integration_event({
        "integration_event_id": "RP-TEST-ORDER-order_test_status_123_unique_20260904_unique_20260904",
        "timestamp": "2026-09-04T00:00:00+00:00",
        "provider": "razorpay",
        "event_type": "TEST_ORDER_CREATED",
        "status": "CREATED",
        "payload": {"order_id": order_id, "test_only": True},
    })
    db_repo.insert_integration_event({
        "integration_event_id": "RP-EVT-TEST-STATUS",
        "timestamp": "2026-09-04T00:00:01+00:00",
        "provider": "razorpay",
        "event_type": "payment.failed",
        "status": "RECEIVED",
        "payload": {
            "body": {
                "event": "payment.failed",
                "payload": {
                    "payment": {"entity": {"order_id": order_id, "amount": 120000}}
                },
            }
        },
    })
    r = TestClient(main.app).get(f"/api/razorpay/test/order/{order_id}")
    assert r.status_code == 200
    assert len(r.json()["events"]) == 2


def test_webhook_failure_response_contains_recovery_context(monkeypatch):
    import hashlib
    import hmac
    import json
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "rp-test-secret-context")
    body = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_context_unique_20260904",
                    "amount": 120000,
                    "currency": "INR",
                    "method": "upi",
                    "error_description": "network timeout",
                }
            }
        },
    }
    raw = json.dumps(body, separators=(",", ":")).encode()
    sig = hmac.new(b"rp-test-secret-context", raw, hashlib.sha256).hexdigest()
    headers = {
        "X-Razorpay-Signature": sig,
        "X-Razorpay-Event-Id": "evt-context-unique-20260904",
    }
    from src.api.main import app
    r = TestClient(app).post("/api/integrations/razorpay/webhook", content=raw, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "OBSERVED"
    assert data["payment_event"]["event_type"] == "PAYMENT_FAILURE"
    assert "decision_id" in data["decision"]
