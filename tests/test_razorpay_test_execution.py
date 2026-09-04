from fastapi.testclient import TestClient

from src.api.main import app
from src import integrations

client = TestClient(app)


def _reset(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_unit")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "unit-secret")
    monkeypatch.delenv("RECOVERAI_SANDBOX_EMAIL", raising=False)
    monkeypatch.delenv("RECOVERAI_SANDBOX_PHONE", raising=False)


def test_sandbox_selected_alternative_payment_returns_payment_link(monkeypatch):
    _reset(monkeypatch)

    decision = client.post(
        "/predict",
        json={
            "event_id": "TEST-ALTERNATIVE-1",
            "amount": 1130,
            "event_type": "PAYMENT_FAILURE",
            "payment_method": "CARD",
            "failure_type": "TIMEOUT",
            "retry_count": 5,
            "historical_success_rate": 0.85,
            "total_transactions": 200,
            "avg_transaction_amount": 50000,
            "merchant_success_rate": 0.90,
        },
    ).json()
    assert decision["recommended_action"] == "ALTERNATIVE_PAYMENT"

    monkeypatch.setattr(
        integrations,
        "_razorpay_payment_link",
        lambda payload: {
            "id": "plink_test_123",
            "short_url": "https://rzp.io/i/test123",
            "status": "created",
            "amount": 113000,
            "currency": "INR",
            "reference_id": payload["execution_id"],
        },
    )

    result = client.post(
        "/execute-decision",
        json={
            "payload": {
                "event_id": "TEST-ALTERNATIVE-1",
                "amount": 1130,
                "event_type": "PAYMENT_FAILURE",
                "payment_method": "CARD",
                "failure_type": "TIMEOUT",
                "retry_count": 5,
                "historical_success_rate": 0.85,
                "total_transactions": 200,
                "avg_transaction_amount": 50000,
                "merchant_success_rate": 0.90,
            },
            "decision": decision,
            "live": True,
            "live_confirmation": True,
            "selected_action": "ALTERNATIVE_PAYMENT",
        },
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["state"] == "EXECUTED"
    # The endpoint received an explicit selected_action, so execution records
    # the truthful source even when the selected action equals the AI recommendation.
    assert data["selection_source"] == "INTEGRATION_TEST"
    assert data["payment_link"]["short_url"] == "https://rzp.io/i/test123"
    assert data["integration"]["environment"] == "SANDBOX"
    assert data["integration"]["provider_mode"] == "TEST"


def test_sandbox_can_execute_an_allowed_non_recommended_action_without_changing_ai_decision(monkeypatch):
    _reset(monkeypatch)
    decision = client.post(
        "/predict",
        json={
            "event_id": "TEST-SELECTED-1",
            "amount": 12000,
            "event_type": "PAYMENT_FAILURE",
            "payment_method": "UPI",
            "failure_type": "TIMEOUT",
            "retry_count": 0,
            "historical_success_rate": 0.85,
            "total_transactions": 20,
            "avg_transaction_amount": 5000,
            "merchant_success_rate": 0.90,
        },
    ).json()
    assert decision["recommended_action"] == "RECOVERY_REMINDER"
    assert decision["guardrails"]["ALTERNATIVE_PAYMENT"]["allowed"] is True

    monkeypatch.setattr(
        integrations,
        "_razorpay_payment_link",
        lambda payload: {"id": "plink_test_456", "short_url": "https://rzp.io/i/test456", "status": "created", "amount": 1200000, "currency": "INR", "reference_id": payload["execution_id"]},
    )
    result = client.post(
        "/execute-decision",
        json={
            "payload": {
                "event_id": "TEST-SELECTED-1",
                "amount": 12000,
                "event_type": "PAYMENT_FAILURE",
                "payment_method": "UPI",
                "failure_type": "TIMEOUT",
                "retry_count": 0,
                "historical_success_rate": 0.85,
                "total_transactions": 20,
                "avg_transaction_amount": 5000,
                "merchant_success_rate": 0.90,
            },
            "decision": decision,
            "live": True,
            "live_confirmation": True,
            "selected_action": "ALTERNATIVE_PAYMENT",
        },
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["recommended_action"] == "RECOVERY_REMINDER"
    assert data["action"] == "ALTERNATIVE_PAYMENT"
    assert data["selection_source"] == "INTEGRATION_TEST"
    assert data["payment_link"]["short_url"] == "https://rzp.io/i/test456"


def test_production_activation_rejects_test_keys(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("RECOVERAI_ADMIN_TOKEN", "admin-secret")
    response = client.post(
        "/api/integrations/environment",
        json={
            "environment": "PRODUCTION",
            "admin_token": "admin-secret",
            "confirm_live": True,
        },
    )
    assert response.status_code == 403
    assert "production credentials" in response.json()["detail"].lower()
