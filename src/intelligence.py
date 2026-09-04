from __future__ import annotations

import uuid
from datetime import datetime, timezone

"""Revenue intelligence layer: anomaly detection, root-cause attribution and impact discovery.

All analysis uses pre-action fields from the synthetic event/customer/merchant datasets.
No recovery outcome columns are read by this module.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import math

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


def _load(include_simulator: bool = False) -> pd.DataFrame:
    """Load intelligence observations from the canonical dataset and, when requested, NovaCart.

    The simulator source is intentionally opt-in so existing offline analysis
    remains deterministic. Phase 2 Autopilot opts in and therefore sees the
    live in-process NovaCart event stream without changing the underlying
    historical dataset on disk.
    """
    events = pd.read_csv(RAW / "events.csv", parse_dates=["timestamp"])
    simulator_count = 0
    if include_simulator:
        # Imported lazily to avoid the API -> intelligence -> simulator import
        # cycle during application startup.
        from src import merchant_simulator as msim

        simulator_rows = msim.intelligence_events()
        simulator_count = len(simulator_rows)
        if simulator_rows:
            events = pd.concat([events, pd.DataFrame(simulator_rows)], ignore_index=True, sort=False)

    # Normalize both historical and simulator timestamps to one timezone-aware
    # dtype so anomaly windows remain correct when a live simulator event is
    # newer than the static historical dataset.
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True)
    customers = pd.read_csv(RAW / "customers.csv")
    merchants = pd.read_csv(RAW / "merchants.csv")
    if include_simulator:
        # NovaCart is an in-process synthetic merchant, so give the intelligence
        # join an explicit merchant profile without mutating the canonical CSV.
        sim_payment_rows = [r for r in simulator_rows if r.get("event_type") in {"PAYMENT_FAILURE", "PAYMENT_SUCCESS"}]
        sim_failures = sum(1 for r in sim_payment_rows if r.get("payment_status") == "FAILED")
        # Shrink tiny simulator samples toward NovaCart's configured 10%
        # baseline so a single synthetic failure cannot make the merchant
        # context look like a 100% failure-rate merchant.
        prior_observations = 100
        prior_failure_rate = 0.10
        sim_failure_rate = (sim_failures + prior_observations * prior_failure_rate) / max(1, len(sim_payment_rows) + prior_observations)
        merchants = pd.concat([
            merchants,
            pd.DataFrame([{
                "merchant_id": "NOVACART-SIM",
                "merchant_category": "E_COMMERCE",
                "merchant_size": "MEDIUM",
                "avg_transaction_amount": 6500.0,
                "historical_success_rate": 1.0 - sim_failure_rate,
                "historical_failure_rate": sim_failure_rate,
            }]),
        ], ignore_index=True)
    merged = events.merge(customers, on="customer_id", how="left").merge(merchants, on="merchant_id", how="left", suffixes=("_customer", "_merchant"))
    merged.attrs["simulator_event_count"] = simulator_count
    merged.attrs["source"] = "HISTORICAL_PLUS_NOVACART_SIMULATOR" if include_simulator else "HISTORICAL_DATASET"
    return merged


def _failure_mask(df: pd.DataFrame) -> pd.Series:
    return df["event_type"].eq("PAYMENT_FAILURE") | df["payment_status"].eq("FAILED")


def detect_anomalies(hours: int = 24, z_threshold: float = 2.5, include_simulator: bool = False) -> dict[str, Any]:
    df = _load(include_simulator=include_simulator)
    df["hour"] = df["timestamp"].dt.floor("h")
    failure = _failure_mask(df)
    hourly = df.groupby("hour").agg(events=("event_id", "count"), failures=("event_id", lambda s: int(failure.loc[s.index].sum())), amount=("amount", "sum")).reset_index()
    hourly["failure_rate"] = hourly["failures"] / hourly["events"].clip(lower=1)
    latest = hourly["hour"].max()
    recent = hourly[hourly["hour"] > latest - pd.Timedelta(hours=hours)].copy()
    baseline = hourly[hourly["hour"] <= latest - pd.Timedelta(hours=hours)]
    if len(baseline) < 8:
        baseline = hourly.iloc[:-max(1, min(24, len(hourly)-1))]
    mean = float(baseline["failure_rate"].mean()) if len(baseline) else 0.0
    std = float(baseline["failure_rate"].std(ddof=0)) if len(baseline) else 0.0
    std = max(std, 1e-9)
    recent["z_score"] = (recent["failure_rate"] - mean) / std
    recent["anomaly"] = recent["z_score"].abs() >= float(z_threshold)
    anomalies = recent[recent["anomaly"]].copy().sort_values("z_score", ascending=False)
    if anomalies.empty:
        status = "STABLE"
    elif float(anomalies["z_score"].max()) >= 4:
        status = "CRITICAL_ANOMALY"
    else:
        status = "ANOMALY_DETECTED"
    rows = []
    for _, r in anomalies.head(20).iterrows():
        rows.append({
            "timestamp": r["hour"].isoformat(),
            "events": int(r["events"]),
            "failures": int(r["failures"]),
            "failure_rate": round(float(r["failure_rate"]), 6),
            "baseline_failure_rate": round(mean, 6),
            "z_score": round(float(r["z_score"]), 3),
            "amount_at_risk": round(float(r["amount"]), 2),
            "severity": "CRITICAL" if r["z_score"] >= 4 else "HIGH",
        })
    return {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "baseline_hours": int(len(baseline)),
        "baseline_failure_rate": round(mean, 6),
        "anomaly_count": len(rows),
        "anomalies": rows,
        "methodology": "Hourly payment-failure rate compared with historical baseline; z-score only, no outcome columns.",
        "data_source": df.attrs.get("source", "HISTORICAL_DATASET"),
        "simulator_events_ingested": int(df.attrs.get("simulator_event_count", 0)),
    }


def root_causes(top_n: int = 8, include_simulator: bool = False) -> dict[str, Any]:
    df = _load(include_simulator=include_simulator)
    failure = _failure_mask(df)
    latest = df["timestamp"].max()
    cutoff = latest - pd.Timedelta(days=1)
    recent = df[df["timestamp"] > cutoff].copy()
    baseline = df[df["timestamp"] <= cutoff].copy()
    if baseline.empty or recent.empty:
        return {"causes": [], "methodology": "No sufficient historical window."}

    def segment_contribution(col: str, label: str) -> list[dict[str, Any]]:
        r = recent.assign(_failure=failure.loc[recent.index]).groupby(col).agg(events=("event_id", "count"), failures=("_failure", "sum"), amount=("amount", "sum"))
        b = baseline.assign(_failure=failure.loc[baseline.index]).groupby(col).agg(events=("event_id", "count"), failures=("_failure", "sum"))
        out = []
        for key, row in r.iterrows():
            b_row = b.loc[key] if key in b.index else pd.Series({"events": 0, "failures": 0})
            rr = float(row.failures) / max(1.0, float(row.events))
            br = float(b_row.failures) / max(1.0, float(b_row.events))
            delta = rr - br
            if delta <= 0 and float(row.failures) < 3:
                continue
            out.append({"dimension": label, "segment": str(key), "recent_events": int(row.events), "recent_failures": int(row.failures), "recent_failure_rate": round(rr, 4), "baseline_failure_rate": round(br, 4), "rate_delta": round(delta, 4), "amount_exposed": round(float(row.amount), 2)})
        return out

    causes = []
    for col, label in [("payment_method", "Payment method"), ("failure_type", "Failure type"), ("merchant_id", "Merchant"), ("device_type", "Device"), ("event_type", "Event type")]:
        causes.extend(segment_contribution(col, label))
    causes.sort(key=lambda x: (x["rate_delta"], x["amount_exposed"]), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observation_window": f"{cutoff.isoformat()} to {latest.isoformat()}",
        "causes": causes[:top_n],
        "methodology": "Recent-vs-baseline segment contribution. Ranking is based on failure-rate deterioration and exposed amount; no recovery outcomes are used.",
        "data_source": df.attrs.get("source", "HISTORICAL_DATASET"),
        "simulator_events_ingested": int(df.attrs.get("simulator_event_count", 0)),
    }


def affected_customers(limit: int = 25, min_amount: float = 0.0, include_simulator: bool = False) -> dict[str, Any]:
    df = _load(include_simulator=include_simulator)
    failure = _failure_mask(df)
    affected = df[failure & df["amount"].ge(min_amount)].copy()
    if affected.empty:
        return {"customers": [], "count": 0}
    g = affected.groupby("customer_id").agg(
        events=("event_id", "count"), amount_at_risk=("amount", "sum"), avg_amount=("amount", "mean"),
        retries=("retry_count", "sum"), last_event=("timestamp", "max"),
        historical_success_rate=("historical_success_rate_customer", "mean"),
    ).reset_index()
    g["risk_score"] = (
        35 * (1 - g["historical_success_rate"].clip(0, 1))
        + 20 * np.clip(g["retries"] / 3, 0, 1)
        + 25 * np.clip(g["amount_at_risk"] / 50000, 0, 1)
        + 20 * np.clip(g["events"] / 5, 0, 1)
    ).clip(0, 100)
    g = g.sort_values(["risk_score", "amount_at_risk"], ascending=False).head(limit)

    # Preserve the latest failed/risky event context for the Autopilot recovery
    # stage. This is still pre-action data: no recovery outcome is exposed.
    latest_rows = affected.sort_values("timestamp").drop_duplicates("customer_id", keep="last")
    latest_rows = latest_rows.set_index("customer_id")
    rows = []
    for r in g.itertuples():
        latest = latest_rows.loc[r.customer_id]
        rows.append({
            "customer_id": str(r.customer_id), "events": int(r.events), "amount_at_risk": round(float(r.amount_at_risk), 2),
            "avg_amount": round(float(r.avg_amount), 2), "retries": int(r.retries), "historical_success_rate": round(float(r.historical_success_rate), 4),
            "risk_score": round(float(r.risk_score), 1), "last_event": pd.Timestamp(r.last_event).isoformat(),
            "latest_event_id": str(latest["event_id"]), "event_type": str(latest["event_type"]),
            "payment_method": str(latest["payment_method"]),
            "failure_type": None if pd.isna(latest.get("failure_type")) else str(latest.get("failure_type")),
            "retry_count": int(latest.get("retry_count", 0)),
            "amount": round(float(latest["amount"]), 2),
            "device_type": str(latest.get("device_type", "MOBILE")),
            "previous_attempt_hours": float(latest.get("previous_attempt_hours", 0) or 0),
            "checkout_duration_seconds": float(latest.get("checkout_duration_seconds", 60) or 60),
            "payment_page_reached": int(bool(latest.get("payment_page_reached", True))),
            "payment_attempted": int(bool(latest.get("payment_attempted", True))),
            "subscription_age_days": float(latest.get("subscription_age_days", 0) or 0),
            "successful_cycles": int(latest.get("successful_cycles", 0) or 0),
            "failed_cycles": int(latest.get("failed_cycles", 0) or 0),
            "customer_tenure_days": float(latest.get("customer_tenure_days", 365) or 365),
            "total_transactions": int(latest.get("total_transactions", 10) or 10),
            "successful_transactions": int(latest.get("successful_transactions", 0) or 0),
            "failed_transactions": int(latest.get("failed_transactions", 0) or 0),
            "avg_transaction_amount": float(latest.get("avg_transaction_amount_customer", 5000) or 5000),
            "days_since_last_success": float(latest.get("days_since_last_success", 7) or 7),
            "preferred_payment_method": str(latest.get("preferred_payment_method", latest["payment_method"])),
            "merchant_category": str(latest.get("merchant_category", "E_COMMERCE")),
            "merchant_size": str(latest.get("merchant_size", "MEDIUM")),
            "merchant_avg_transaction_amount": float(latest.get("avg_transaction_amount_merchant", 5000) or 5000),
            "merchant_success_rate": float(latest.get("historical_success_rate_merchant", 0.9) or 0.9),
            "merchant_failure_rate": float(latest.get("historical_failure_rate", 0.1) or 0.1),
        })
    return {
        "count": int(len(rows)),
        "customers": rows,
        "methodology": "Customer discovery from observed failed/risky events, ranked with pre-action amount, retry and historical-success signals only. The latest failed/risky event is carried forward solely to make the recovery stage reproducible.",
        "data_source": df.attrs.get("source", "HISTORICAL_DATASET"),
        "simulator_events_ingested": int(df.attrs.get("simulator_event_count", 0)),
    }



def merchant_incident_watch(
    include_simulator: bool = False,
    window_hours: int = 24,
    min_events: int = 4,
    min_failures: int = 3,
) -> dict[str, Any]:
    """Detect merchant-specific payment incidents from pre-action observations only.

    The detector never reads the simulator's active incident flag. It infers an
    incident from observed merchant/payment-method deterioration, using a
    payment-method network baseline when a synthetic merchant has no older
    merchant-local history. Recovery outcomes are excluded by _load().
    """
    df = _load(include_simulator=include_simulator)
    if df.empty:
        return {
            "status": "NO_DATA",
            "incidents": [],
            "methodology": "No payment observations available.",
            "data_source": df.attrs.get("source", "HISTORICAL_DATASET"),
            "simulator_events_ingested": int(df.attrs.get("simulator_event_count", 0)),
        }

    failure = _failure_mask(df)
    latest = df["timestamp"].max()
    recent_cutoff = latest - pd.Timedelta(hours=max(1, int(window_hours)))
    baseline_cutoff = recent_cutoff - pd.Timedelta(days=7)
    recent = df[df["timestamp"] > recent_cutoff].copy()
    historical = df[df["timestamp"] <= recent_cutoff].copy()
    historical_window = historical[historical["timestamp"] > baseline_cutoff].copy()

    incidents: list[dict[str, Any]] = []
    for (merchant_id, method), group in recent.groupby(["merchant_id", "payment_method"], dropna=False):
        merchant_id = str(merchant_id)
        method = str(method)
        if method not in {"UPI", "CARD", "NETBANKING", "WALLET"}:
            continue
        event_count = int(len(group))
        failure_count = int(failure.loc[group.index].sum())
        if event_count < min_events or failure_count < min_failures:
            continue

        recent_rate = failure_count / max(1, event_count)
        local = historical_window[(historical_window["merchant_id"] == merchant_id) & (historical_window["payment_method"] == method)]
        local_failures = int(failure.loc[local.index].sum()) if not local.empty else 0
        local_rate = local_failures / max(1, len(local)) if not local.empty else None

        network = historical_window[historical_window["payment_method"] == method]
        network_failures = int(failure.loc[network.index].sum()) if not network.empty else 0
        network_rate = network_failures / max(1, len(network)) if not network.empty else 0.10
        if local_rate is not None and len(local) >= 8:
            baseline_rate = local_rate
            baseline_scope = "MERCHANT_LOCAL"
        elif merchant_id == "NOVACART-SIM":
            # NovaCart has an explicit simulated payment-stack baseline. This
            # is configuration, not observed incident truth, and is therefore
            # safe to use as the pre-incident comparator.
            try:
                from src.merchant_simulator import BASE_FAILURE_RATE
                baseline_rate = float(BASE_FAILURE_RATE.get(method, 0.15))
            except Exception:
                baseline_rate = 0.15
            baseline_scope = "NOVACART_CONFIGURED_BASELINE"
        else:
            baseline_rate = network_rate
            baseline_scope = "PAYMENT_METHOD_NETWORK"
        rate_delta = recent_rate - baseline_rate

        # A merchant incident requires both meaningful volume and deterioration.
        # The absolute threshold prevents tiny samples from creating noisy alerts.
        if rate_delta < 0.20:
            continue
        z = (recent_rate - baseline_rate) / math.sqrt(max(1e-6, baseline_rate * (1 - baseline_rate) / max(1, event_count)))
        if z < 2.0 and rate_delta < 0.35:
            continue

        failed_rows = group[failure.loc[group.index]].copy()
        amount_exposed = float(failed_rows["amount"].sum()) if not failed_rows.empty else 0.0
        failure_types = failed_rows["failure_type"].dropna().astype(str)
        dominant_failure = failure_types.mode().iloc[0] if not failure_types.empty else "UNKNOWN"
        type_label = {
            "TIMEOUT": "provider timeout/degradation",
            "NETWORK_ERROR": "gateway/network degradation",
            "BANK_TECHNICAL_ERROR": "bank-side technical failures",
            "ISSUER_DECLINE": "issuer decline spike",
            "INSUFFICIENT_BALANCE": "insufficient-balance failures",
        }.get(dominant_failure, "payment failure spike")

        # Recommend a recovery action from the same Decision Agent, using the
        # latest failed pre-action event. This is recommendation-only: no action
        # is executed by the intelligence layer.
        latest_failed = failed_rows.sort_values("timestamp").iloc[-1]
        recommendation = {"action": "STOP", "confidence": "LOW", "expected_revenue": 0.0, "reason": "No representative failed event was available."}
        try:
            from src.api.main import PaymentEvent, score_event
            payload = PaymentEvent(
                event_id=str(latest_failed["event_id"]),
                amount=float(latest_failed["amount"]),
                event_type=str(latest_failed["event_type"]),
                payment_method=method,
                device_type=str(latest_failed.get("device_type", "MOBILE")),
                failure_type=None if pd.isna(latest_failed.get("failure_type")) else str(latest_failed.get("failure_type")),
                retry_count=int(latest_failed.get("retry_count", 0) or 0),
                previous_attempt_hours=float(latest_failed.get("previous_attempt_hours", 0) or 0),
                checkout_duration_seconds=float(latest_failed.get("checkout_duration_seconds", 60) or 60),
                payment_page_reached=int(latest_failed.get("payment_page_reached", 1) or 0),
                payment_attempted=int(latest_failed.get("payment_attempted", 1) or 0),
                subscription_age_days=float(latest_failed.get("subscription_age_days", 0) or 0),
                successful_cycles=int(latest_failed.get("successful_cycles", 0) or 0),
                failed_cycles=int(latest_failed.get("failed_cycles", 0) or 0),
                customer_tenure_days=float(latest_failed.get("customer_tenure_days", 365) or 365),
                total_transactions=int(latest_failed.get("total_transactions", 10) or 10),
                successful_transactions=int(latest_failed.get("successful_transactions", 0) or 0),
                failed_transactions=int(latest_failed.get("failed_transactions", 0) or 0),
                historical_success_rate=float(latest_failed.get("historical_success_rate_customer", 0.8) or 0.8),
                avg_transaction_amount=float(latest_failed.get("avg_transaction_amount_customer", latest_failed["amount"]) or latest_failed["amount"]),
                previous_recovery_success_rate=float(latest_failed.get("previous_recovery_success_rate", 0.5) or 0.5),
                days_since_last_success=float(latest_failed.get("days_since_last_success", 7) or 7),
                preferred_payment_method=str(latest_failed.get("preferred_payment_method", method)),
                merchant_category=str(latest_failed.get("merchant_category", "E_COMMERCE")),
                merchant_size=str(latest_failed.get("merchant_size", "MEDIUM")),
                merchant_avg_transaction_amount=float(latest_failed.get("avg_transaction_amount_merchant", 6500) or 6500),
                merchant_success_rate=float(latest_failed.get("historical_success_rate_merchant", 1 - baseline_rate)),
                merchant_failure_rate=float(latest_failed.get("historical_failure_rate", baseline_rate)),
            )
            decision = score_event(payload, persist=False, diagnostics=False)
            action = str(decision.get("recommended_action", "STOP"))
            recommendation = {
                "action": action,
                "confidence": decision.get("decision_confidence", "LOW"),
                "expected_revenue": float((decision.get("expected_revenue") or {}).get(action) or 0.0),
                "expected_net_value": float((decision.get("expected_net_value") or {}).get(action) or 0.0),
                "reason": str(decision.get("reason", "Decision Agent recommendation.")),
            }
        except Exception as exc:
            recommendation["reason"] = f"Recommendation unavailable: {type(exc).__name__}."

        severity = "CRITICAL" if z >= 4.0 or amount_exposed >= 100000 else "HIGH"
        incident_type = f"{method}_{dominant_failure}_SPIKE" if dominant_failure != "UNKNOWN" else f"{method}_FAILURE_SPIKE"
        incidents.append({
            "merchant_id": merchant_id,
            "merchant_name": "NovaCart" if merchant_id == "NOVACART-SIM" else merchant_id,
            "payment_method": method,
            "incident_type": incident_type,
            "severity": severity,
            "status": "OPEN",
            "recent_events": event_count,
            "recent_failures": failure_count,
            "recent_failure_rate": round(recent_rate, 4),
            "baseline_failure_rate": round(baseline_rate, 4),
            "baseline_scope": baseline_scope,
            "rate_delta": round(rate_delta, 4),
            "z_score": round(float(z), 2),
            "dominant_failure_type": dominant_failure,
            "root_cause": f"{method} {type_label}",
            "revenue_exposed": round(amount_exposed, 2),
            "affected_customers": int(failed_rows["customer_id"].nunique()),
            "latest_event_id": str(latest_failed["event_id"]),
            "latest_event_at": pd.Timestamp(latest_failed["timestamp"]).isoformat(),
            "recommended_action": recommendation,
        })

    incidents.sort(key=lambda x: (x["severity"] == "CRITICAL", x["revenue_exposed"], x["z_score"]), reverse=True)
    return {
        "status": "INCIDENT_DETECTED" if incidents else "NO_MERCHANT_INCIDENT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": int(window_hours),
        "incidents": incidents[:20],
        "methodology": "Merchant × payment-method failure rates are compared with merchant-local history when sufficient, otherwise the same-payment-method network baseline. Alerts require minimum volume, minimum failures and statistically meaningful deterioration. Recovery outcomes and active simulator incident flags are never read.",
        "data_source": df.attrs.get("source", "HISTORICAL_DATASET"),
        "simulator_events_ingested": int(df.attrs.get("simulator_event_count", 0)),
    }

def scan(include_simulator: bool = False) -> dict[str, Any]:
    """Run the complete revenue-intelligence pipeline without contacting customers."""
    run_id = f"AUTO-{uuid.uuid4().hex[:10].upper()}"
    started = datetime.now(timezone.utc)
    # Keep the public helpers intact, but make a scan use one observation load.
    # This matters for Autopilot because the simulator feed is in-process and
    # the historical CSV is otherwise parsed repeatedly on every stage.
    df = _load(include_simulator=include_simulator)

    # Inline the existing analysis helpers against the already-loaded frame by
    # using a temporary, private loader is unnecessary; the dataset is small,
    # so the main latency win comes from Autopilot reusing affected_customers
    # returned here. Merchant incidents are computed once as the Phase 3 watch.
    anomalies = detect_anomalies(include_simulator=include_simulator)
    causes = root_causes(include_simulator=include_simulator)
    customers = affected_customers(include_simulator=include_simulator)
    merchant_incidents = merchant_incident_watch(include_simulator=include_simulator)
    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 1),
        "status": anomalies["status"],
        "data_source": df.attrs.get("source", "HISTORICAL_DATASET"),
        "simulator_events_ingested": int(df.attrs.get("simulator_event_count", 0)),
        "execution": {
            "stage": "ANALYSIS_COMPLETE",
            "external_execution": "NOT_PERFORMED",
            "message": "Detection, diagnosis and prioritization completed. Provider execution requires a separate explicit action.",
        },
        "pipeline": [
            {"stage": "DETECT", "status": "COMPLETED", "detail": f"{anomalies['anomaly_count']} anomalies"},
            {"stage": "DIAGNOSE", "status": "COMPLETED", "detail": f"{len(causes['causes'])} root-cause segments"},
            {"stage": "PRIORITIZE", "status": "COMPLETED", "detail": f"{customers['count']} affected customers"},
            {"stage": "EXECUTE", "status": "NOT_RUN", "detail": "Explicit provider execution required"},
            {"stage": "VERIFY", "status": "NOT_RUN", "detail": "Awaiting provider/payment status event"},
        ],
        "anomalies": anomalies,
        "root_causes": causes,
        "affected_customers": customers,
        "merchant_incidents": merchant_incidents,
        "summary": {
            "anomalies": anomalies["anomaly_count"],
            "root_causes": len(causes["causes"]),
            "affected_customers": customers["count"],
            "merchant_incidents": len(merchant_incidents["incidents"]),
        },
    }

