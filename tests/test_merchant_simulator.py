from fastapi.testclient import TestClient
from src.api.main import app
from src import merchant_simulator as msim

client = TestClient(app)


def _reset_and_get_customer():
    client.post("/api/merchant-sim/reset")
    return client.get("/api/merchant-sim/customers").json()["customers"][0]["customer_id"]


def test_reset_returns_baseline():
    cid = _reset_and_get_customer()
    client.post("/api/merchant-sim/purchase", json={"customer_id": cid, "product_id": "PRD_SHOES"})
    r = client.post("/api/merchant-sim/reset")
    assert r.status_code == 200
    d = client.get("/api/merchant-sim/dashboard").json()
    assert d["total_orders"] == 0
    assert d["gmv"] == 0


def test_successful_purchase_updates_dashboard_from_real_state():
    cid = _reset_and_get_customer()
    r = client.post("/api/merchant-sim/purchase", json={"customer_id": cid, "product_id": "PRD_SHOES", "force_fail": False})
    order = r.json()
    d = client.get("/api/merchant-sim/dashboard").json()
    if order["status"] == "PAID":
        assert d["gmv"] >= order["amount"]
    assert d["total_orders"] == 1
    assert d["payment_attempts"] == 1


def test_failed_payment_reaches_real_decision_agent_and_guardrails():
    cid = _reset_and_get_customer()
    r = client.post("/api/merchant-sim/purchase", json={"customer_id": cid, "product_id": "PRD_HEADPHONES", "force_fail": True})
    order = r.json()
    assert order["decision"] is not None
    # The decision must be a genuine, fully-scored RecoverAI decision, not a stub.
    assert order["decision"]["recommended_action"] in {"ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION", "STOP"}
    assert "guardrails" in order["decision"]
    assert order["execution"] is not None
    assert order["execution"]["execution_mode"] == "SIMULATED_BOUNDED"


def test_recovery_outcome_updates_order_and_revenue_consistently():
    cid = _reset_and_get_customer()
    r = client.post("/api/merchant-sim/purchase", json={"customer_id": cid, "product_id": "PRD_LAPTOP", "force_fail": True})
    order = r.json()
    d = client.get("/api/merchant-sim/dashboard").json()
    if order["status"] == "PAID" and order["recovered"]:
        assert d["recovered_revenue"] >= order["amount"]
    elif order["status"] in ("PAYMENT_FAILED", "LOST"):
        assert d["failed_payments"] >= 1


def test_duplicate_failure_event_does_not_duplicate_recovery():
    cid = _reset_and_get_customer()
    r = client.post("/api/merchant-sim/purchase", json={"customer_id": cid, "product_id": "PRD_SPEAKER", "force_fail": True})
    order_id = r.json()["order_id"]
    client.post("/api/merchant-sim/resubmit-event", json={"order_id": order_id})
    client.post("/api/merchant-sim/resubmit-event", json={"order_id": order_id})
    tl = client.get("/api/merchant-sim/timeline?limit=100").json()["events"]
    decisions = [e for e in tl if e["order_id"] == order_id and e["event_type"] == "RECOVERY_DECISION"]
    dupes = [e for e in tl if e["order_id"] == order_id and e["event_type"] == "DUPLICATE_EVENT_IGNORED"]
    assert len(decisions) == 1
    assert len(dupes) == 2


def test_incident_injection_changes_real_failure_probability():
    msim.reset()
    baseline = msim._failure_probability("UPI")[0]
    msim.inject_incident("UPI_DEGRADATION")
    degraded = msim._failure_probability("UPI")[0]
    assert degraded > baseline
    msim.inject_incident(None)
    cleared = msim._failure_probability("UPI")[0]
    assert cleared == baseline


def test_checkout_abandonment_recorded():
    cid = _reset_and_get_customer()
    r = client.post("/api/merchant-sim/abandon", json={"customer_id": cid, "product_id": "PRD_BACKPACK"})
    assert r.json()["status"] == "ABANDONED"
    d = client.get("/api/merchant-sim/dashboard").json()
    assert d["checkout_abandonments"] == 1


def test_deterministic_scenario_runs_full_loop():
    client.post("/api/merchant-sim/reset")
    r = client.post("/api/merchant-sim/scenario/upi-failure-recovery")
    assert r.status_code == 200
    d = r.json()
    order = d["order"]
    assert order["payment_attempts"][0]["method"] == "UPI"
    assert order["payment_attempts"][0]["status"] == "FAILED"
    assert order["decision"] is not None
    assert order["execution"] is not None
    event_types = [e["event_type"] for e in d["timeline"]]
    assert "ORDER_CREATED" in event_types
    assert "PAYMENT_FAILED" in event_types
    assert "RECOVERAI_EVENT_RECEIVED" in event_types
    assert "RECOVERY_DECISION" in event_types
    assert "PAYMENT_SUCCESS" in event_types
    assert "RECOVERAI_VERIFICATION_RECEIVED" in event_types
    assert "RECOVERY_VERIFIED" in event_types
    assert "ORDER_PAID" in event_types
    assert order["status"] == "PAID"
    assert order["recovered"] is True


def test_simulator_never_reaches_live_execution():
    import inspect
    fn_src = inspect.getsource(msim._run_recovery)
    assert "execute_bounded_workflow" in fn_src
    assert "live=False" in fn_src
    assert "live=True" not in fn_src


def test_reset_is_idempotent_and_customers_reload():
    client.post("/api/merchant-sim/reset")
    c1 = client.get("/api/merchant-sim/customers").json()["customers"]
    client.post("/api/merchant-sim/reset")
    c2 = client.get("/api/merchant-sim/customers").json()["customers"]
    assert len(c1) == len(c2) > 0


def test_simulator_timeline_uses_ordered_millisecond_clock():
    client.post("/api/merchant-sim/reset")
    r = client.post("/api/merchant-sim/scenario/upi-failure-recovery")
    timeline = r.json()["timeline"]
    timestamps = [e["timestamp"] for e in timeline if e["event_type"] != "SIMULATION_RESET"]
    assert timestamps == sorted(timestamps)
    assert all("." in ts and len(ts.split(".")[-1].split("+")[0].replace("Z", "")) == 3 for ts in timestamps)


def test_simulator_intelligence_feed_excludes_recovery_outcomes():
    client.post("/api/merchant-sim/reset")
    r = client.post("/api/merchant-sim/scenario/upi-failure-recovery")
    order_id = r.json()["order"]["order_id"]
    rows = msim.intelligence_events()
    order_rows = [x for x in rows if x["event_id"].startswith("PAYEVT-")]
    assert any(x["event_type"] == "PAYMENT_FAILURE" for x in order_rows)
    # The recovery payment is post-action evidence and must not enter the
    # pre-action intelligence feed used by Autopilot.
    recovery_attempt_id = r.json()["order"]["payment_attempts"][-1]["event_id"]
    assert not any(x["event_id"] == recovery_attempt_id for x in order_rows)


def test_full_demo_leaves_only_its_own_clean_orders():
    """Run some unrelated simulator activity first, then run the full demo.
    The full demo must reset first, and the state visible afterward must
    correspond only to the demo's own deterministic run."""
    cid = _reset_and_get_customer()
    client.post("/api/merchant-sim/purchase", json={"customer_id": cid, "product_id": "PRD_SHOES", "force_fail": True})
    client.post("/api/merchant-sim/purchase", json={"customer_id": cid, "product_id": "PRD_SPEAKER"})
    before = client.get("/api/merchant-sim/dashboard").json()
    assert before["total_orders"] >= 2

    r = client.post("/api/revenue-intelligence/demo")
    assert r.status_code == 200
    demo_result = r.json()
    assert demo_result["status"] == "COMPLETED"

    dashboard_after = client.get("/api/merchant-sim/dashboard").json()
    orders_after = client.get("/api/merchant-sim/orders?limit=50").json()["orders"]

    # The deterministic demo produces at most 5 + 1 + 15 = 21 orders. If the
    # pre-demo purchases above leaked through, the count would exceed that.
    assert dashboard_after["total_orders"] <= 21
    assert len(orders_after) <= 21


def test_tick_with_stale_generation_is_a_safe_no_op():
    """A tick dispatched with a generation older than the current one (as
    happens when a reset/full-demo runs while a continuous-simulation tick
    was already in flight) must not mutate simulator state."""
    client.post("/api/merchant-sim/reset")
    dash = client.get("/api/merchant-sim/dashboard").json()
    stale_generation = dash["simulation_generation"] - 1
    r = client.post(f"/api/merchant-sim/tick?speed=1&generation={stale_generation}")
    assert r.status_code == 200
    body = r.json()
    assert body["stale"] is True
    assert body["orders_touched"] == []
    dash_after = client.get("/api/merchant-sim/dashboard").json()
    assert dash_after["total_orders"] == dash["total_orders"]
