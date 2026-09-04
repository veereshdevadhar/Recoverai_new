from __future__ import annotations

"""Optional live execution adapters with a real circuit breaker.

Default mode is SAFE_SIMULATION. Live integrations activate only when explicitly
configured with environment variables. Tests never make network calls.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
import base64
import hashlib
import hmac
import json
import os
import smtplib
import ssl
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid
from src.db import repository as db_repo
from src.voice import generate_hinglish_script


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is not None:
            if time.time() - self.opened_at >= self.recovery_seconds:
                return "HALF_OPEN"
            return "OPEN"
        return "CLOSED"

    def before_call(self) -> None:
        if self.state == "OPEN":
            raise RuntimeError("Circuit breaker OPEN: external provider temporarily blocked")

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.time()

    def reset(self) -> None:
        self.failures = 0
        self.opened_at = None


BREAKERS = {name: CircuitBreaker() for name in ("payment", "email", "sms", "webhook")}


class VoiceProviderUnavailable(RuntimeError):
    """Raised when voice channel is requested but no telephony provider is configured."""

# Production safety plane. DEMO is local-only; SANDBOX permits only explicitly
# allow-listed test destinations and Razorpay test keys; PRODUCTION requires
# live keys and explicit action allow-lists.
_LIVE_KILL_SWITCH = False

def execution_environment() -> str:
    return os.getenv("RECOVERAI_EXECUTION_ENV", "DEMO").strip().upper()

def _truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

def _max_live_amount() -> float:
    default = "100000" if execution_environment() == "SANDBOX" else "10000"
    return float(os.getenv("RECOVERAI_MAX_LIVE_AMOUNT", default))

def _daily_budget() -> float:
    return float(os.getenv("RECOVERAI_DAILY_LIVE_BUDGET", "50000"))

def _admin_authorized(token: str | None) -> bool:
    expected = os.getenv("RECOVERAI_ADMIN_TOKEN")
    return bool(expected and token and __import__("hmac").compare_digest(token, expected))

def kill_switch_active() -> bool:
    return _LIVE_KILL_SWITCH or _truthy("RECOVERAI_LIVE_KILL_SWITCH")

def set_kill_switch(enabled: bool, token: str | None = None) -> dict[str, Any]:
    global _LIVE_KILL_SWITCH
    if not _admin_authorized(token):
        raise PermissionError("Live kill-switch changes require RECOVERAI_ADMIN_TOKEN.")
    _LIVE_KILL_SWITCH = bool(enabled)
    return status()

def _provider_action_allowed(action: str) -> bool:
    # Razorpay TEST is intentionally usable for the payment-link integration
    # without requiring a production-style allow-list toggle. It is still
    # hard-bound to rzp_test_* credentials by _validate_live_request().
    # Other sandbox providers remain opt-in because they can contact external
    # destinations even though they are not real-money payment providers.
    if execution_environment() == "SANDBOX" and action == "ALTERNATIVE_PAYMENT":
        return True
    return _truthy(f"RECOVERAI_ALLOW_{action}", "0")

def _sandbox_destination_ok(payload: dict[str, Any], field: str) -> bool:
    allowed = os.getenv(f"RECOVERAI_SANDBOX_{field.upper()}", "").strip()
    return bool(allowed and payload.get(field) and payload[field].strip().lower() == allowed.lower())

def _sandbox_credentials_ok(provider: str) -> bool:
    if execution_environment() != "SANDBOX":
        return True
    if provider == "razorpay":
        return (os.getenv("RAZORPAY_KEY_ID", "").startswith("rzp_test_") and
                bool(os.getenv("RAZORPAY_KEY_SECRET")))
    return True


def production_execution_armed() -> bool:
    return _truthy("RECOVERAI_PRODUCTION_EXECUTION_ARMED", "0")


def live_enabled() -> bool:
    base = _truthy("RECOVERAI_LIVE_EXECUTION") and execution_environment() in {"SANDBOX", "PRODUCTION"} and not kill_switch_active()
    if execution_environment() == "PRODUCTION":
        return base and production_execution_armed()
    return base


def _http_json(
    url: str,
    method: str,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """POST/HTTP helper that fails closed and preserves provider diagnostics."""
    encoded = json.dumps(body, separators=(",", ":"), default=str).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw[:4000]}
            if isinstance(parsed, dict):
                parsed.setdefault("status_code", response.status)
            return parsed if isinstance(parsed, dict) else {"status_code": response.status, "response": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(f"External provider returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"External provider connection failed: {exc.reason}") from exc


def _razorpay_payment_link(payload: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("RAZORPAY_KEY_ID")
    secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key or not secret:
        raise RuntimeError("Razorpay execution requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET")
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    reference_id = str(payload.get("execution_id") or payload.get("event_id") or f"RR-{uuid.uuid4().hex[:10]}")[:40]
    body = {
        "amount": int(round(float(payload["amount"]) * 100)),
        "currency": payload.get("currency", "INR"),
        "accept_partial": False,
        "upi_link": False,
        "description": payload.get("description", f"RecoverAI recovery for {payload.get('event_id', 'payment')}"),
        "reference_id": reference_id,
        "expire_by": int(time.time()) + 86400,
        "notes": {
            "recoverai_environment": execution_environment(),
            "recoverai_action": str(payload.get("action", "ALTERNATIVE_PAYMENT")),
            "recoverai_execution_id": str(payload.get("execution_id", "")),
        },
    }
    customer = {}
    if payload.get("email"):
        customer["email"] = payload["email"]
    if payload.get("phone"):
        customer["contact"] = payload["phone"]
    if customer:
        body["customer"] = customer
    return _http_json(
        "https://api.razorpay.com/v1/payment_links",
        "POST",
        body,
        {"Authorization": f"Basic {token}"},
    )


def _smtp_email(payload: dict[str, Any]) -> dict[str, Any]:
    """Send a recovery email with explicit TLS and provider diagnostics."""
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user or "recoverai@localhost").strip()
    recipient = str(payload.get("email") or "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    use_ssl = _truthy("SMTP_USE_SSL", "1" if port == 465 else "0")
    starttls = _truthy("SMTP_STARTTLS", "1" if port != 465 else "0")
    if not host or not recipient:
        raise RuntimeError("SMTP execution requires SMTP_HOST and a recipient email")
    if execution_environment() == "PRODUCTION" and not use_ssl and not starttls and not _truthy("SMTP_ALLOW_INSECURE", "0"):
        raise RuntimeError("Production SMTP requires TLS. Use SMTP_STARTTLS=1 or SMTP_USE_SSL=1.")

    msg = EmailMessage()
    msg["Subject"] = payload.get("subject", "Payment recovery reminder")
    msg["From"] = sender
    msg["To"] = recipient
    msg["Message-ID"] = f"<{payload.get('execution_id', uuid.uuid4().hex)}@recoverai.local>"
    msg.set_content(payload.get("body", "Please complete your payment."))

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=10, context=context) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            if starttls:
                smtp.starttls(context=context)
                smtp.ehlo()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
    return {"provider": "smtp", "recipient": recipient, "accepted": True}


def _twilio_credentials() -> tuple[str, str, str, bool]:
    """Return credentials, sender and whether the sandbox test credentials are used."""
    sandbox = execution_environment() == "SANDBOX"
    if sandbox and os.getenv("TWILIO_TEST_ACCOUNT_SID") and os.getenv("TWILIO_TEST_AUTH_TOKEN"):
        sid = os.getenv("TWILIO_TEST_ACCOUNT_SID", "")
        token = os.getenv("TWILIO_TEST_AUTH_TOKEN", "")
        sender = os.getenv("TWILIO_TEST_FROM", "+15005550006")
        return sid, token, sender, True
    return (
        os.getenv("TWILIO_ACCOUNT_SID", ""),
        os.getenv("TWILIO_AUTH_TOKEN", ""),
        os.getenv("TWILIO_FROM", ""),
        False,
    )


def _twilio_sms(payload: dict[str, Any]) -> dict[str, Any]:
    sid, token, sender, test_credentials = _twilio_credentials()
    phone = str(payload.get("phone") or "").strip()
    if not sid or not token or not sender or not phone:
        raise RuntimeError("Twilio execution requires Account SID, Auth Token, From and phone")
    # Twilio Trial accounts do not allow arbitrary SMS bodies. In trial mode,
    # the Messages API expects the value of Body itself to be one of Twilio's
    # predefined trial template identifiers (for example, sms_account_alerts).
    # Keep this behavior isolated to the Twilio adapter so the rest of RecoverAI
    # (Decision Agent, execution flow, audit trail, UI, etc.) remains unchanged.
    #
    # Set TWILIO_TRIAL_MODE=0 after upgrading Twilio if you want RecoverAI's
    # generated custom SMS body to be sent instead.
    trial_mode = _truthy("TWILIO_TRIAL_MODE", "1" if execution_environment() == "SANDBOX" else "0")
    trial_template = os.getenv("TWILIO_TRIAL_TEMPLATE", "sms_account_alerts").strip()

    if trial_mode:
        allowed_templates = {
            "sms_2fa",
            "sms_appointment_reminders",
            "sms_order_confirmation",
            "sms_delivery_updates",
            "sms_customer_support",
            "sms_marketing_promotions",
            "sms_event_notifications",
            "sms_account_alerts",
            "sms_feedback_surveys",
            "sms_internal_alerts",
        }
        if trial_template not in allowed_templates:
            raise RuntimeError(
                "Invalid TWILIO_TRIAL_TEMPLATE. Use one of Twilio's predefined "
                "trial SMS templates, such as sms_account_alerts."
            )
        message_body = trial_template
    else:
        message_body = payload.get("body", "Please complete your payment.")

    params = {
        "To": phone,
        "From": sender,
        "Body": message_body,
    }
    callback = os.getenv("TWILIO_STATUS_CALLBACK_URL", "").strip()
    if callback:
        params["StatusCallback"] = callback
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=data,
        method="POST",
        headers={"Accept": "application/json"},
    )
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = {"raw": raw[:4000]}
            return {
                "provider": "twilio",
                "status_code": response.status,
                "message_sid": result.get("sid") if isinstance(result, dict) else None,
                "message_status": result.get("status") if isinstance(result, dict) else None,
                "test_credentials": test_credentials,
                "trial_mode": trial_mode,
                "trial_template": trial_template if trial_mode else None,
                "response": result,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(f"Twilio returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Twilio connection failed: {exc.reason}") from exc


def _webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Send an authenticated, idempotent orchestration command."""
    url = os.getenv("RECOVERAI_EXECUTION_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("RECOVERAI_EXECUTION_WEBHOOK_URL is not configured")
    secret = os.getenv("RECOVERAI_EXECUTION_WEBHOOK_SECRET") or os.getenv("RECOVERAI_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("Webhook execution requires RECOVERAI_EXECUTION_WEBHOOK_SECRET or RECOVERAI_WEBHOOK_SECRET")
    delivery_id = str(payload.get("execution_id") or uuid.uuid4().hex)
    event_name = str(payload.get("action", "RECOVERY_ACTION")).lower()
    body = {
        "schema_version": "1.0",
        "event": event_name,
        "delivery_id": delivery_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": execution_environment(),
        "data": payload,
    }
    raw = json.dumps(body, separators=(",", ":"), default=str).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {
        "X-RecoverAI-Signature": signature,
        "X-RecoverAI-Event": event_name,
        "X-RecoverAI-Delivery-Id": delivery_id,
        "User-Agent": "RecoverAI/2.0",
    }
    result = _http_json(url, "POST", body, headers=headers, timeout=10)
    return {
        "provider": "execution_webhook",
        "accepted": True,
        "delivery_id": delivery_id,
        "response": result,
    }


def environment_metadata() -> dict[str, Any]:
    """Return a UI-safe description of the active execution environment."""
    env = execution_environment()
    if env not in {"DEMO", "SANDBOX", "PRODUCTION"}:
        env = "DEMO"
    razorpay_key = os.getenv("RAZORPAY_KEY_ID", "")
    if razorpay_key.startswith("rzp_test_"):
        razorpay_mode = "TEST"
    elif razorpay_key.startswith("rzp_live_"):
        razorpay_mode = "LIVE"
    elif razorpay_key:
        razorpay_mode = "UNKNOWN"
    else:
        razorpay_mode = "NOT_CONFIGURED"
    return {
        "environment": env,
        "label": {"DEMO": "DEMO / SIMULATION", "SANDBOX": "RAZORPAY TEST", "PRODUCTION": "LIVE PRODUCTION"}[env],
        "description": {
            "DEMO": "Local-only simulation. No external provider is contacted.",
            "SANDBOX": "Razorpay Test APIs and explicitly allow-listed test destinations only.",
            "PRODUCTION": "Production providers. Explicit confirmation, limits, allow-list and kill switch apply.",
        }[env],
        "real_money": env == "PRODUCTION",
        "external_calls_possible": env in {"SANDBOX", "PRODUCTION"} and _truthy("RECOVERAI_LIVE_EXECUTION"),
        "razorpay_key_mode": razorpay_mode,
    }


def set_execution_environment(environment: str, admin_token: str | None = None, confirm_live: bool = False) -> dict[str, Any]:
    """Change the runtime environment; production requires server-side admin authorization."""
    env = str(environment or "").strip().upper()
    if env not in {"DEMO", "SANDBOX", "PRODUCTION"}:
        raise ValueError("Environment must be DEMO, SANDBOX, or PRODUCTION.")
    if env == "PRODUCTION":
        if not _admin_authorized(admin_token):
            raise PermissionError("Switching to LIVE PRODUCTION requires RECOVERAI_ADMIN_TOKEN.")
        if not confirm_live:
            raise PermissionError("Switching to LIVE PRODUCTION requires explicit confirmation.")
        key = os.getenv("RAZORPAY_KEY_ID", "")
        if key and not key.startswith("rzp_live_"):
            raise PermissionError("LIVE PRODUCTION requires Razorpay production credentials. Test keys cannot activate the production environment.")
        if not key or not os.getenv("RAZORPAY_KEY_SECRET"):
            raise PermissionError("LIVE PRODUCTION requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET configured on the backend.")
    os.environ["RECOVERAI_EXECUTION_ENV"] = env
    if env == "DEMO":
        os.environ["RECOVERAI_LIVE_EXECUTION"] = "0"
    elif env == "SANDBOX":
        # TEST mode is safe to activate from the UI because provider validation
        # below requires Razorpay test keys and allow-listed destinations.
        os.environ["RECOVERAI_LIVE_EXECUTION"] = "1"
    elif env == "PRODUCTION":
        # Production is only enabled after admin authorization + confirmation.
        os.environ["RECOVERAI_LIVE_EXECUTION"] = "1"
    return status()


def status() -> dict[str, Any]:
    providers = {
        "razorpay": bool(os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET")),
        "smtp": bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM")),
        "twilio": bool(
            (execution_environment() == "SANDBOX" and os.getenv("TWILIO_TEST_ACCOUNT_SID") and os.getenv("TWILIO_TEST_AUTH_TOKEN"))
            or (os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN") and os.getenv("TWILIO_FROM"))
        ),
        "execution_webhook": bool(os.getenv("RECOVERAI_EXECUTION_WEBHOOK_URL") and (os.getenv("RECOVERAI_EXECUTION_WEBHOOK_SECRET") or os.getenv("RECOVERAI_WEBHOOK_SECRET"))),
    }
    env = execution_environment()
    meta = environment_metadata()
    return {
        "live_enabled": live_enabled(),
        "mode": env,
        "environment_metadata": meta,
        "live_execution_configured": _truthy("RECOVERAI_LIVE_EXECUTION"),
        "production_execution_armed": production_execution_armed(),
        "razorpay_key_mode": meta["razorpay_key_mode"],
        "environment": env,
        "kill_switch": kill_switch_active(),
        "max_live_amount": _max_live_amount(),
        "daily_live_budget": _daily_budget(),
        "action_allowlist": {a: _provider_action_allowed(a) for a in ("ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION")},
        "sandbox_allowlist": {"email": bool(os.getenv("RECOVERAI_SANDBOX_EMAIL")), "phone": bool(os.getenv("RECOVERAI_SANDBOX_PHONE"))},
        "provider_security": {
            "smtp_tls": bool(_truthy("SMTP_USE_SSL") or _truthy("SMTP_STARTTLS")),
            "twilio_test_credentials": bool(os.getenv("TWILIO_TEST_ACCOUNT_SID") and os.getenv("TWILIO_TEST_AUTH_TOKEN")),
            "webhook_hmac": bool(os.getenv("RECOVERAI_EXECUTION_WEBHOOK_SECRET") or os.getenv("RECOVERAI_WEBHOOK_SECRET")),
            "razorpay_webhook_hmac": bool(os.getenv("RAZORPAY_WEBHOOK_SECRET")),
        },
        "providers": providers,
        "capabilities": {
            "ALTERNATIVE_PAYMENT": {"simulation": True, "live_provider": "razorpay", "configured": providers["razorpay"], "description": "Creates a Razorpay Payment Link; it does not mark a payment recovered."},
            "RECOVERY_REMINDER": {"simulation": True, "live_providers": [x for x in ("smtp", "twilio") if providers[x]], "email_configured": providers["smtp"], "sms_configured": providers["twilio"]},
            "RETRY_LATER": {"simulation": True, "live_provider": "execution_webhook", "configured": providers["execution_webhook"], "description": "Sends a retry-scheduling command to the configured orchestration webhook; no payment is charged by RecoverAI itself."},
            "HUMAN_ESCALATION": {"simulation": True, "live_provider": "execution_webhook", "configured": providers["execution_webhook"], "description": "Creates a bounded escalation case through the configured orchestration webhook."},
        },
        "circuit_breakers": {k: {"state": v.state, "failures": v.failures, "failure_threshold": v.failure_threshold} for k, v in BREAKERS.items()},
        "safety": "Safe simulation is the default. Sandbox calls require TEST-mode provider configuration. Production calls additionally require explicit production arming, provider credentials, limits, kill switch protection and per-execution confirmation.",
    }


def reset_breakers() -> dict[str, Any]:
    for breaker in BREAKERS.values():
        breaker.reset()
    return status()


def _live_spend_today() -> float:
    """Best-effort ledger-backed daily live amount used for safety enforcement."""
    today = datetime.now(timezone.utc).date()
    total = 0.0
    try:
        records = db_repo.list_integration_events(limit=200)
        for record in records:
            if record.get("status") != "SUCCEEDED":
                continue
            try:
                ts = datetime.fromisoformat(str(record.get("timestamp", "")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts.date() != today:
                continue
            if record.get("provider") != "razorpay":
                continue
            request = (record.get("payload") or {}).get("request") or {}
            total += float(request.get("amount", 0) or 0)
    except Exception:
        # A ledger read failure must fail closed for production rather than
        # bypassing a safety budget.
        raise RuntimeError("Unable to verify the daily live budget from the integration ledger.")
    return total


def _validate_live_request(action: str, payload: dict[str, Any], channel: str) -> tuple[str, Any]:
    env = execution_environment()
    if env not in {"SANDBOX", "PRODUCTION"}:
        raise RuntimeError("Live execution environment must be SANDBOX or PRODUCTION.")
    # Voice is deliberately honest: no configured outbound telephony adapter
    # exists in this project, so report NOT_AVAILABLE before any destination
    # allow-list check can turn it into a generic provider failure.
    if channel == "voice" and action in {"ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION"}:
        raise VoiceProviderUnavailable(
            "Voice telephony is not available in the current configuration: "
            "no outbound voice provider (e.g. Twilio Voice) is configured. "
            "The Hinglish script was generated and can be played back via browser text-to-speech."
        )
    if not _provider_action_allowed(action):
        raise RuntimeError(f"Live action {action} is disabled by the execution allow-list.")
    amount = float(payload.get("amount", 0))
    if amount <= 0 or amount > _max_live_amount():
        raise RuntimeError(f"Live execution amount ₹{amount:,.2f} exceeds the configured safety limit of ₹{_max_live_amount():,.2f}.")
    # Enforce the daily spend ceiling for live payment-link executions.
    # We count successful live interventions recorded by the integration ledger.
    if env == "PRODUCTION":
        used_today = _live_spend_today()
        if used_today + amount > _daily_budget():
            raise RuntimeError(
                f"Daily live budget exceeded: ₹{used_today:,.2f} used today; "
                f"₹{_daily_budget():,.2f} maximum."
            )
    if env == "SANDBOX":
        if action == "ALTERNATIVE_PAYMENT" and not _sandbox_credentials_ok("razorpay"):
            raise RuntimeError("SANDBOX payment execution requires Razorpay Test Mode keys (rzp_test_*).")
        if channel == "email" and not _sandbox_destination_ok(payload, "email"):
            raise RuntimeError("SANDBOX email execution is restricted to RECOVERAI_SANDBOX_EMAIL.")
        if channel == "sms" and not _sandbox_destination_ok(payload, "phone"):
            raise RuntimeError("SANDBOX SMS execution is restricted to RECOVERAI_SANDBOX_PHONE.")
    if action == "ALTERNATIVE_PAYMENT":
        # Razorpay Standard Payment Links can be created without customer
        # contact details. RecoverAI therefore does not make email/phone a
        # prerequisite for the link itself; contact details are optional.
        key = os.getenv("RAZORPAY_KEY_ID", "")
        secret = os.getenv("RAZORPAY_KEY_SECRET", "")
        if not key or not secret:
            raise RuntimeError("Razorpay execution requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
        if env == "SANDBOX" and not key.startswith("rzp_test_"):
            raise RuntimeError("RAZORPAY TEST mode requires a Razorpay test key beginning with rzp_test_.")
        if env == "PRODUCTION" and not key.startswith("rzp_live_"):
            raise RuntimeError("LIVE PRODUCTION requires a Razorpay live key beginning with rzp_live_. Test keys are blocked.")
        return "payment", _razorpay_payment_link
    if action == "RECOVERY_REMINDER":
        if channel not in {"auto", "email", "sms", "voice"}:
            raise RuntimeError("Reminder channel must be auto, email, sms, or voice.")
        if channel == "voice":
            # No real telephony provider (Twilio Voice / Exotel / etc.) is
            # configured. Rather than inventing a call result, this is a
            # deliberate, explicit "not available" — matching how every other
            # unconfigured live channel in this file behaves.
            raise VoiceProviderUnavailable(
                "Voice telephony is not available in the current configuration: "
                "no outbound voice provider (e.g. Twilio Voice) is configured. "
                "The Hinglish script was generated and can be played back via "
                "browser text-to-speech."
            )
        if channel == "email":
            if not payload.get("email"):
                raise RuntimeError("Email channel requires a customer email address.")
            return "email", _smtp_email
        if channel == "sms":
            if not payload.get("phone"):
                raise RuntimeError("SMS channel requires a customer phone number.")
            return "sms", _twilio_sms
        # For AUTO routing, prefer SMS when Twilio is configured and the
        # destination is explicitly allow-listed in SANDBOX. This makes the
        # Integration Test exercise the real Twilio SMS adapter when both an
        # email address and phone number are present, while preserving email
        # as a fallback when SMS is unavailable.
        twilio_configured = bool(
            (os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN") and os.getenv("TWILIO_FROM"))
            or (env == "SANDBOX" and os.getenv("TWILIO_TEST_ACCOUNT_SID") and os.getenv("TWILIO_TEST_AUTH_TOKEN"))
        )
        if (
            payload.get("phone")
            and twilio_configured
            and (env == "PRODUCTION" or _sandbox_destination_ok(payload, "phone"))
        ):
            return "sms", _twilio_sms

        if payload.get("email") and os.getenv("SMTP_HOST") and (
            env == "PRODUCTION" or _sandbox_destination_ok(payload, "email")
        ):
            return "email", _smtp_email

        raise RuntimeError(
            "Auto reminder routing found no configured channel with a customer contact. "
            "Provide phone + Twilio or email + SMTP."
        )
    if action in {"RETRY_LATER", "HUMAN_ESCALATION"}:
        if not os.getenv("RECOVERAI_EXECUTION_WEBHOOK_URL"):
            raise RuntimeError("This live workflow requires RECOVERAI_EXECUTION_WEBHOOK_URL to be configured.")
        return "webhook", _webhook
    raise RuntimeError(f"Unsupported live action: {action}")


def execute(action: str, payload: dict[str, Any], channel: str = "auto") -> dict[str, Any]:
    """Execute a permitted recovery action through configured real adapters.

    A successful provider call is *not* treated as revenue recovered. Payment
    recovery is only confirmed by a subsequent payment/provider status event.
    """
    voice_script = None
    if channel == "voice" and action in {"ALTERNATIVE_PAYMENT", "RECOVERY_REMINDER", "RETRY_LATER", "HUMAN_ESCALATION"}:
        voice_script = generate_hinglish_script(
            action=action,
            amount=float(payload.get("amount", 0) or 0),
            event_type=payload.get("event_type", "PAYMENT_FAILURE"),
            failure_type=payload.get("failure_type"),
            seed=payload.get("execution_id") or payload.get("event_id"),
        )

    if not live_enabled():
        details = {"action": action, "channel": channel, "customer_contact_present": bool(payload.get("email") or payload.get("phone")), "environment": execution_environment()}
        result = {"mode": "SAFE_SIMULATION", "provider": "local", "status": "SIMULATED", "message": "No external system was contacted. The recovery action was evaluated and simulated locally.", "details": details}
        if voice_script:
            result["voice"] = voice_script
            result["message"] = "No telephony call was made. A Hinglish recovery script was generated for local browser playback."
        return result
    if action == "STOP":
        return {"mode": "LIVE", "provider": "none", "status": "SKIPPED", "message": "STOP performs no external action."}

    try:
        name, fn = _validate_live_request(action, payload, channel)
    except VoiceProviderUnavailable as exc:
        result = {"mode": "LIVE", "provider": "voice", "status": "NOT_AVAILABLE", "message": str(exc)}
        if voice_script:
            result["voice"] = voice_script
        return result
    except Exception as exc:
        return {"mode": "LIVE", "provider": "unconfigured", "status": "FAILED", "error": str(exc), "verification_required": True}
    breaker = BREAKERS[name]
    breaker.before_call()
    try:
        response = fn(payload)
        breaker.success()
        result = {"mode": "LIVE", "environment": execution_environment(),
                  "provider_mode": environment_metadata()["razorpay_key_mode"] if name == "payment" else None,
                  "provider": name, "status": "SUCCEEDED", "response": response,
                  "revenue_recovered": 0.0,
                  "verification_required": True,
                  "message": "Provider accepted the intervention. Revenue recovery remains unverified until a payment/provider status event confirms success."}
        db_repo.insert_integration_event({"integration_event_id": f"INT-{uuid.uuid4().hex[:10].upper()}", "timestamp": datetime.now(timezone.utc).isoformat(), "provider": name, "event_type": action, "status": "SUCCEEDED", "payload": {"request": payload, "response": response}})
        return result
    except Exception as exc:
        breaker.failure()
        result = {"mode": "LIVE", "environment": execution_environment(),
                  "provider_mode": environment_metadata()["razorpay_key_mode"] if name == "payment" else None,
                  "provider": name, "status": "FAILED", "error": str(exc), "circuit_breaker": {"state": breaker.state, "failures": breaker.failures}}
        db_repo.insert_integration_event({"integration_event_id": f"INT-{uuid.uuid4().hex[:10].upper()}", "timestamp": datetime.now(timezone.utc).isoformat(), "provider": name, "event_type": action, "status": "FAILED", "payload": {"request": payload, "error": str(exc), "circuit_breaker": result["circuit_breaker"]}})
        return result
