from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_execution_environment_is_explicit_and_ui_safe(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "DEMO")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "0")
    d = client.get("/api/integrations/status").json()
    assert d["environment"] == "DEMO"
    assert d["environment_metadata"]["real_money"] is False
    assert d["live_enabled"] is False

    d = client.post("/api/integrations/environment", json={"environment": "SANDBOX"}).json()
    assert d["environment"] == "SANDBOX"
    assert d["environment_metadata"]["label"] == "RAZORPAY TEST"
    assert d["environment_metadata"]["real_money"] is False
    assert d["live_enabled"] is True

    d = client.post("/api/integrations/environment", json={"environment": "DEMO"}).json()
    assert d["environment"] == "DEMO"
    assert d["live_enabled"] is False


def test_sandbox_rejects_non_test_razorpay_key_without_network(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_not_allowed")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    monkeypatch.setenv("RECOVERAI_ALLOW_ALTERNATIVE_PAYMENT", "1")
    d = client.post(
        "/api/integrations/execute",
        json={
            "action": "ALTERNATIVE_PAYMENT",
            "amount": 1000,
            "email": "demo@example.com",
            "live_confirmation": True,
        },
    ).json()
    assert d["mode"] == "LIVE"
    assert d["status"] == "FAILED"
    assert "test mode" in d["error"].lower()


def test_production_requires_server_side_confirmation(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "PRODUCTION")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RECOVERAI_ALLOW_ALTERNATIVE_PAYMENT", "1")
    d = client.post(
        "/api/integrations/execute",
        json={"action": "ALTERNATIVE_PAYMENT", "amount": 1000, "email": "demo@example.com"},
    )
    assert d.status_code == 400
    assert "explicit confirmation" in d.json()["detail"].lower()
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "DEMO")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "0")
