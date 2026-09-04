from __future__ import annotations

"""Hinglish (Hindi-English code-mixed) voice recovery script generation.

This module is intentionally scoped and labeled honestly: it deterministically
composes a natural, code-mixed Hinglish script for a recovery call/notification
from the same decision context already scored by the agent (action, amount,
failure reason, customer tone). It does NOT place a real outbound phone call —
RecoverAI has no telephony provider (Twilio Voice / Exotel / etc.) configured,
and this module never claims otherwise.

The generated script is designed to be handed to:
  - the browser's native Web Speech Synthesis API for an audible client-side
    playback (a real TTS voice, not a simulated waveform), or
  - a real telephony provider's TTS/IVR leg, if one is ever configured.

Template composition (not a call to a hosted LLM) keeps this deterministic,
inspectable and auditable, matching the rest of the decision/execution stack.
"""

from typing import Any
import random

_ACTION_LINES = {
    "ALTERNATIVE_PAYMENT": (
        "Maine dekha ki aapka payment complete nahi ho paya. Koi baat nahi — "
        "main aapko ek naya secure payment link bhej rahi hoon jisse aap dusre "
        "method se turant payment kar sakte hain."
    ),
    "RECOVERY_REMINDER": (
        "Ye ek chhota sa reminder hai — aapka checkout/payment beech mein "
        "interrupt ho gaya tha aur abhi tak complete nahi hua hai. "
        "Hum chahte hain ki aap ise ek baar phir se complete karne ki koshish "
        "karein — jab bhi aapko convenient ho."
    ),
    "RETRY_LATER": (
        "Aapka payment thodi der ke liye hold par gaya hai kyunki abhi kuch "
        "technical issue tha. Hum thodi der baad automatically dobara try "
        "karenge, aapko kuch karne ki zaroorat nahi hai."
    ),
    "HUMAN_ESCALATION": (
        "Kyunki ye ek high-value transaction hai, humari team is issue ko "
        "personally dekhegi aur aapse jald hi contact karegi taaki hum aapki "
        "sahi tarah se madad kar sakein."
    ),
    "STOP": (
        "Filhaal hum is payment ke liye aur koi follow-up nahi bhej rahe hain. "
        "Agar aapko kabhi madad chahiye, aap humein kabhi bhi contact kar sakte hain."
    ),
}

_FAILURE_CONTEXT = {
    "TIMEOUT": "Lagta hai connection thoda slow tha jiski wajah se payment complete nahi hua.",
    "NETWORK_ERROR": "Network issue ki wajah se aapka payment beech mein reh gaya.",
    "BANK_TECHNICAL_ERROR": "Aapke bank ki taraf se ek technical glitch aaya tha.",
    "INSUFFICIENT_BALANCE": "Aisa lagta hai ki us waqt account mein balance kam tha.",
    "EXPIRED_PAYMENT_METHOD": "Aapka payment method shayad expire ho chuka hai, isliye transaction fail hua.",
    "PAYMENT_LIMIT": "Aapki payment limit us waqt cross ho gayi thi.",
    "ISSUER_DECLINE": "Aapke card issuer ne is transaction ko decline kar diya tha.",
}

_OPENERS = [
    "Namaste! Main RecoverAI ki taraf se baat kar rahi hoon.",
    "Hello ji, ye ek recovery assistant se ek chhota sa update hai.",
]


def generate_hinglish_script(
    *,
    action: str,
    amount: float,
    event_type: str = "PAYMENT_FAILURE",
    failure_type: str | None = None,
    merchant_name: str = "the merchant",
    seed: str | None = None,
) -> dict[str, Any]:
    """Compose a deterministic Hinglish recovery script for the given decision.

    `seed` (e.g. a decision_id or event_id) makes opener selection stable for
    a given event instead of re-rolling every call, without needing real
    randomness/state.
    """
    rng = random.Random(seed or f"{action}-{amount}")
    opener = rng.choice(_OPENERS)
    action_line = _ACTION_LINES.get(action, _ACTION_LINES["RECOVERY_REMINDER"])
    amount_str = f"{amount:,.0f}"

    parts = [opener]
    if event_type == "PAYMENT_FAILURE" and failure_type and failure_type in _FAILURE_CONTEXT:
        parts.append(_FAILURE_CONTEXT[failure_type])
    parts.append(f"Ye rupees {amount_str} ka payment {merchant_name} ke liye tha.")
    parts.append(action_line)
    if action not in {"STOP", "RETRY_LATER", "HUMAN_ESCALATION"}:
        parts.append("Agar koi problem aa rahi hai to aap humse kabhi bhi reply kar sakte hain. Dhanyavaad!")
    else:
        parts.append("Dhanyavaad, aapka time lene ke liye.")

    script = " ".join(parts)
    # ~2.4 spoken words/second for a natural Hinglish delivery pace.
    word_count = len(script.split())
    estimated_seconds = max(4, round(word_count / 2.4))

    return {
        "script": script,
        "language": "hi-IN",
        "language_label": "Hinglish (Hindi-English code-mixed)",
        "voice_locale_hint": "hi-IN",
        "word_count": word_count,
        "estimated_duration_seconds": estimated_seconds,
        "generation_method": "deterministic_template",
        "note": (
            "Generated locally by template composition from the decision context. "
            "No outbound telephony call is made by RecoverAI; playback happens via "
            "the browser's speech-synthesis engine, or a configured telephony "
            "provider if one is added."
        ),
    }
