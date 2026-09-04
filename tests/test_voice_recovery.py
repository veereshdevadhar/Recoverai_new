from fastapi.testclient import TestClient
from src.api.main import app
from src.voice import generate_hinglish_script

client = TestClient(app)


def test_generate_hinglish_script_is_deterministic_and_code_mixed():
    a = generate_hinglish_script(action="ALTERNATIVE_PAYMENT", amount=12000, event_type="PAYMENT_FAILURE", failure_type="TIMEOUT", seed="EVT-1")
    b = generate_hinglish_script(action="ALTERNATIVE_PAYMENT", amount=12000, event_type="PAYMENT_FAILURE", failure_type="TIMEOUT", seed="EVT-1")
    assert a["script"] == b["script"]
    assert a["language"] == "hi-IN"
    assert a["word_count"] > 0
    assert a["estimated_duration_seconds"] > 0
    assert "12,000" in a["script"]
    # Should never claim a real call was placed.
    assert "call" not in a["note"].lower() or "no outbound telephony call is made" in a["note"].lower()


def test_voice_script_preview_endpoint():
    r = client.post("/api/voice/script", json={"action": "RECOVERY_REMINDER", "amount": 5000, "event_type": "PAYMENT_FAILURE", "failure_type": "NETWORK_ERROR", "event_id": "EVT-2"})
    assert r.status_code == 200
    d = r.json()
    assert d["script"]
    assert d["language_label"].startswith("Hinglish")


def test_execute_decision_voice_channel_attaches_script_in_demo(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "DEMO")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "0")
    payload = {
        "event_id": "T-VOICE-1", "amount": 12000, "event_type": "PAYMENT_FAILURE",
        "payment_method": "UPI", "failure_type": "TIMEOUT", "retry_count": 0,
        "historical_success_rate": 0.85, "total_transactions": 20,
        "avg_transaction_amount": 5000, "merchant_success_rate": 0.90,
        "phone": "+919999999999",
    }
    decision = client.post("/predict", json=payload).json()
    r = client.post("/execute-decision", json={"payload": payload, "decision": decision, "live": False, "channel": "voice"})
    assert r.status_code == 200
    d = r.json()
    assert "voice" in d
    assert d["voice"]["language"] == "hi-IN"
    assert d["execution_mode"] == "SIMULATED_BOUNDED"


def test_live_voice_channel_is_honestly_unavailable_not_faked(monkeypatch):
    monkeypatch.setenv("RECOVERAI_EXECUTION_ENV", "SANDBOX")
    monkeypatch.setenv("RECOVERAI_LIVE_EXECUTION", "1")
    from src import integrations
    result = integrations.execute("RECOVERY_REMINDER", {"amount": 5000, "phone": "+919999999999", "event_type": "PAYMENT_FAILURE", "failure_type": "TIMEOUT"}, channel="voice")
    assert result["status"] == "NOT_AVAILABLE"
    assert result["status"] != "SUCCEEDED"
    assert "voice" in result


def test_subscription_failure_and_checkout_abandonment_are_first_class_decision_contexts():
    for event_type in ('CHECKOUT_ABANDONMENT', 'SUBSCRIPTION_FAILURE'):
        payload = {
            'event_id': f'CTX-{event_type}', 'amount': 2500, 'event_type': event_type,
            'payment_method': 'UPI', 'failure_type': 'NETWORK_ERROR', 'retry_count': 0,
            'historical_success_rate': 0.88, 'total_transactions': 18,
            'avg_transaction_amount': 2200, 'merchant_success_rate': 0.93,
        }
        d = client.post('/predict', json=payload).json()
        assert d['recommended_action'] in {'ALTERNATIVE_PAYMENT', 'RECOVERY_REMINDER', 'RETRY_LATER', 'STOP'}
        assert d['agent']['trace'][0]['details']['event_type'] == event_type


def test_voice_script_is_action_specific_not_one_generic_script():
    """Each supported recovery action must produce a distinguishable script,
    and the script content must match that action's intent — not a single
    generic message reused for every action."""
    actions = ["RECOVERY_REMINDER", "ALTERNATIVE_PAYMENT", "RETRY_LATER", "HUMAN_ESCALATION"]
    scripts = {}
    for action in actions:
        r = client.post("/api/voice/script", json={
            "action": action, "amount": 9000, "event_type": "PAYMENT_FAILURE",
            "failure_type": "TIMEOUT", "event_id": f"EVT-{action}",
        })
        assert r.status_code == 200
        scripts[action] = r.json()["script"]

    # No two actions may share the same script text.
    assert len(set(scripts.values())) == len(actions)

    # Each script must reflect the semantics of its own action.
    assert "naya" in scripts["ALTERNATIVE_PAYMENT"].lower() or "dusre" in scripts["ALTERNATIVE_PAYMENT"].lower()
    assert "interrupt" in scripts["RECOVERY_REMINDER"].lower() or "phir se" in scripts["RECOVERY_REMINDER"].lower()
    assert "baad" in scripts["RETRY_LATER"].lower() or "dobara" in scripts["RETRY_LATER"].lower()
    assert "team" in scripts["HUMAN_ESCALATION"].lower() or "contact" in scripts["HUMAN_ESCALATION"].lower()


def test_voice_script_changes_when_selected_action_changes():
    """Simulates the Integration Test control: changing only the selected
    action (same amount/context) must change the returned script."""
    base = {"amount": 9000, "event_type": "PAYMENT_FAILURE", "failure_type": "TIMEOUT", "event_id": "SAME-EVENT-ID"}
    a = client.post("/api/voice/script", json={**base, "action": "RECOVERY_REMINDER"}).json()
    b = client.post("/api/voice/script", json={**base, "action": "ALTERNATIVE_PAYMENT"}).json()
    assert a["script"] != b["script"]


def test_stop_action_produces_no_recovery_intervention_script_by_ui_contract():
    """STOP is a valid script for direct API preview, but the UI never
    requests or renders it — the merged frontend explicitly treats STOP as
    'no voice recovery UI'. This test locks the backend contract that a STOP
    script (if ever requested directly) is clearly distinct from every real
    recovery-action script, so it can never be mistaken for one of them."""
    r = client.post("/api/voice/script", json={"action": "STOP", "amount": 9000, "event_type": "PAYMENT_FAILURE", "failure_type": "TIMEOUT", "event_id": "EVT-STOP"})
    stop_script = r.json()["script"]
    for action in ["RECOVERY_REMINDER", "ALTERNATIVE_PAYMENT", "RETRY_LATER", "HUMAN_ESCALATION"]:
        other = client.post("/api/voice/script", json={"action": action, "amount": 9000, "event_type": "PAYMENT_FAILURE", "failure_type": "TIMEOUT", "event_id": "EVT-STOP"}).json()["script"]
        assert stop_script != other
