import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.api.main import app
from src import integrations
from src.db import repository as repo

client = TestClient(app)


def test_sandbox_smtp_uses_tls_and_sandbox_recipient(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RECOVERAI_ALLOW_RECOVERY_REMINDER", "1")
    monkeypatch.setenv("RECOVERAI_SANDBOX_EMAIL", "test@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "recoverai@example.com")
    monkeypatch.setenv("SMTP_STARTTLS", "1")
    monkeypatch.setenv("SMTP_USE_SSL", "0")

    calls = {"starttls": 0, "login": 0, "sent": 0}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert host == "smtp.example.com"
            assert port == 587
            assert timeout == 10
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ehlo(self): pass
        def starttls(self, context=None): calls["starttls"] += 1
        def login(self, user, password):
            assert (user, password) == ("user", "secret")
            calls["login"] += 1
        def send_message(self, msg):
            assert msg["To"] == "test@example.com"
            calls["sent"] += 1

    monkeypatch.setattr(integrations.smtplib, "SMTP", FakeSMTP)
    result = integrations.execute(
        "RECOVERY_REMINDER",
        {"amount": 500, "email": "test@example.com", "event_id": "EMAIL-1"},
        channel="email",
    )
    assert result["status"] == "SUCCEEDED"
    assert calls == {"starttls": 1, "login": 1, "sent": 1}


def test_sandbox_smtp_rejects_non_allowlisted_destination(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RECOVERAI_ALLOW_RECOVERY_REMINDER", "1")
    monkeypatch.setenv("RECOVERAI_SANDBOX_EMAIL", "allowed@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    result = integrations.execute(
        "RECOVERY_REMINDER",
        {"amount": 500, "email": "other@example.com", "event_id": "EMAIL-2"},
        channel="email",
    )
    assert result["status"] == "FAILED"
    assert "RECOVERAI_SANDBOX_EMAIL" in result["error"]


def test_sandbox_twilio_test_credentials_use_magic_sender(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RECOVERAI_ALLOW_RECOVERY_REMINDER", "1")
    monkeypatch.setenv("RECOVERAI_SANDBOX_PHONE", "+919999999999")
    monkeypatch.setenv("TWILIO_TEST_ACCOUNT_SID", "AC" + "1" * 32)
    monkeypatch.setenv("TWILIO_TEST_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("TWILIO_TEST_FROM", "+15005550006")

    captured = {}

    class FakeResponse:
        status = 201
        def read(self):
            return json.dumps({"sid": "SM" + "2" * 32, "status": "queued"}).encode()
        def __enter__(self): return self
        def __exit__(self, *args): pass

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["auth"] = req.headers.get("Authorization")
        return FakeResponse()

    monkeypatch.setattr(integrations.urllib.request, "urlopen", fake_urlopen)
    result = integrations.execute(
        "RECOVERY_REMINDER",
        {"amount": 500, "phone": "+919999999999", "event_id": "SMS-1"},
        channel="sms",
    )
    assert result["status"] == "SUCCEEDED"
    assert result["response"]["test_credentials"] is True
    assert "From=%2B15005550006" in captured["data"].decode()


def test_outbound_webhook_is_hmac_signed(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RECOVERAI_ALLOW_RETRY_LATER", "1")
    monkeypatch.setenv("RECOVERAI_EXECUTION_WEBHOOK_URL", "https://example.test/recovery")
    monkeypatch.setenv("RECOVERAI_EXECUTION_WEBHOOK_SECRET", "webhook-secret")

    captured = {}

    class FakeResponse:
        status = 200
        def read(self): return b'{"accepted":true}'
        def __enter__(self): return self
        def __exit__(self, *args): pass

    def fake_urlopen(req, timeout):
        captured["body"] = req.data
        captured["signature"] = req.headers["X-recoverai-signature"]
        captured["delivery"] = req.headers["X-recoverai-delivery-id"]
        return FakeResponse()

    monkeypatch.setattr(integrations.urllib.request, "urlopen", fake_urlopen)
    payload = {"amount": 500, "event_id": "WH-1", "execution_id": "EXE-WH-1", "action": "RETRY_LATER"}
    result = integrations.execute("RETRY_LATER", payload)
    assert result["status"] == "SUCCEEDED"
    expected = hmac.new(b"webhook-secret", captured["body"], hashlib.sha256).hexdigest()
    assert hmac.compare_digest(captured["signature"], expected)
    assert captured["delivery"] == "EXE-WH-1"


def test_generic_recovery_webhook_verifies_hmac_and_updates_execution(monkeypatch):
    monkeypatch.setenv("RECOVERAI_WEBHOOK_SECRET", "callback-secret")
    eid = "EXE-GENERIC-WEBHOOK"
    repo.insert_execution({
        "execution_id": eid,
        "decision_id": "DEC-GENERIC",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "LIVE_EXTERNAL",
        "action": "RETRY_LATER",
        "amount": 500,
        "event_type": "PAYMENT_FAILURE",
        "reason": "test",
        "state": "SCHEDULED",
        "outcome": "RETRY_SCHEDULED",
        "outcome_reason": "test",
        "revenue_recovered": 0,
        "expected_probability": 0.5,
        "expected_recovery": 250,
        "intervention_cost": 5,
        "net_recovery": -5,
        "terminal": True,
        "state_history": [],
    })
    body = json.dumps({"execution_id": eid, "recovered_amount": 500}, separators=(",", ":")).encode()
    sig = hmac.new(b"callback-secret", body, hashlib.sha256).hexdigest()
    response = client.post("/api/integrations/recovery-webhook", content=body, headers={"X-RecoverAI-Signature": sig})
    assert response.status_code == 200
    assert response.json()["execution"]["state"] == "RECOVERED"
