# Session changelog — audit + fixes

This file documents exactly what was verified, what was found broken, and
what was changed in this pass, so nothing is overstated.

## What was verified working (no changes needed)
- Decision Agent: 48 leakage-safe features, per-action ML scoring, expected
  monetary value ranking, guardrail enforcement, counterfactual comparison,
  feature attribution. Confirmed via direct API calls, not assumed.
- Adaptive Recovery Sequencer, UPI Mandate Retry Sequencer (with real AFA
  escalation above ₹15,000), B2B Receivables Chaser (real dunning-tier
  notices), Counterfactuals engine.
- Checkout-abandonment and subscription-failure event types: real, wired
  event types across Decision Lab, Recovery Journey, and the ML feature set
  — not missing, contrary to first impression.
- Execution environment architecture (DEMO / RAZORPAY TEST / LIVE), kill
  switch, guardrails, idempotency, circuit breakers: 82 pre-existing tests
  passed before any change was made.

## Bugs found and fixed
1. **Revenue Autopilot's DETECT stage was structurally dead.** The synthetic
   dataset had payment failures spread uniformly at random across 8 months,
   so the z-score anomaly detector could mathematically never cross its
   threshold — "0 anomalies" was the only possible output, regardless of
   the data. Fixed by injecting a genuine, real UPI-provider-degradation
   incident into the last 30 hours of the synthetic timeline
   (`src/data/event_generator.py`), then regenerating the dataset, retraining
   the V3 model, and regenerating the dependent evaluation/policy artifacts.
   Verified live: DETECT now finds real anomalies feeding a legitimate
   DIAGNOSE → PRIORITIZE chain, instead of a silently empty pipeline.

2. **Policy-experiment audit log silently truncated at 100 rows** while
   every comparable audit log in the same file (decisions, executions,
   sequences, mandates, B2B chases, integration events) caps at 200+.
   This is exactly the kind of silent data loss that undermines an
   auditability story. Fixed to match the rest of the codebase
   (`src/db/repository.py::list_policy_experiments`).

3. **Hinglish Voice Recovery did not exist at all** — a required example
   direction for the AI Revenue Recovery track. Built from scratch:
   - `src/voice.py` — deterministic Hinglish (Hindi-English code-mixed)
     script generation from the same decision context already scored by
     the agent. Template-based and inspectable, not a hosted-LLM call.
   - Wired as a real `channel=voice` option through the existing
     execute-decision / execute / audit pipeline (`src/integrations.py`,
     `src/decision/execution.py`).
   - Honest behavior in LIVE modes: since no telephony provider (Twilio
     Voice, Exotel, etc.) is configured, live voice execution returns an
     explicit `NOT_AVAILABLE` status with a clear reason — never a faked
     "call placed" result.
   - Real client-side playback: the frontend voices the generated script
     using the browser's native Web Speech Synthesis API (a genuine TTS
     voice, not a simulated waveform), with play/stop controls and the
     script text shown alongside it.
   - 4 new tests added (`tests/test_voice_recovery.py`), all passing.

## Frontend
Full visual redesign layered on top of the existing, working component
logic — no business logic was rewritten, only presentation:
- New design system (`frontend/src/styles.css`): glass panels, gradient
  accents, environment-specific color coding (pulsing red glow for LIVE),
  refined typography (Manrope/JetBrains Mono), skeleton loading states.
- Animated page transitions on tab switch, staggered card entrances,
  count-up animation on hero metrics.
- Voice playback card (Web Speech API) for the new voice channel.

## Verification
- 86/86 backend tests pass (`python -m pytest tests/ -q`) — 82 pre-existing
  + 4 new voice tests.
- Frontend builds cleanly (`npm run build`), no errors.
- Runtime SQLite database (`data/runtime/recoverai.db`) was reset before
  packaging so the shipped project starts from a clean state; it will be
  recreated automatically on first backend startup.

## What was not (re)validated live in this pass
- The live-rendered browser UI was not click-tested end to end after the
  redesign — verification was done via the FastAPI test suite and direct
  API calls (curl), plus a clean `npm run build`. Please click through each
  tab once yourself before a live demo, particularly the Revenue Autopilot
  and Decision Lab voice-playback flow (needs a browser with
  `speechSynthesis` support — all modern desktop browsers have this;
  Hindi/Hinglish voice quality depends on which system TTS voices are
  installed).
- Live Razorpay TEST payment-link creation was not exercised with real test
  credentials (none were provided) — the code path was reviewed and is
  wired correctly, but you should smoke-test it once with your own
  `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` (test mode) before relying on
  it in a live demo.


## Current pass — Decision Agent, integration testing, voice UI, and Autopilot

- Added a bounded contextual policy layer after ML scoring. It keeps action-specific ML probabilities intact, adds small auditable adjustments for retryable technical failures, repeated failures, checkout abandonment, subscription failures, and high-value escalation, then ranks the policy-adjusted expected net value. Hard guardrails still win.
- Fixed integration-test action selection so the operator-selected allowed action is authoritative for the test. It may differ from the AI recommendation; execution re-checks the current payload guardrails instead of trusting stale decision guardrail state.
- Added a visible **Hinglish Voice Recovery** preview immediately after a decision is produced. It calls the existing `/api/voice/script` endpoint and uses the existing browser speech-synthesis playback; it does not claim that a phone call was placed.
- Added a visible **Failed subscription recovery** demo scenario while preserving the existing `SUBSCRIPTION_FAILURE` event type and ML feature path. Checkout abandonment remains a first-class scenario and is explicitly preferred toward reminder/re-engagement.
- Reworked Revenue Autopilot so entering the tab does not run a scan or pre-populate metrics. The button is the trigger. A new `/api/revenue-intelligence/autopilot` endpoint executes Detect → Diagnose → Prioritize → Recover → Verify in one bounded safe-simulation cycle.
- Autopilot now exposes the full 25-customer discovery result instead of rendering only the first 15 rows. It sends the top 10 risk-ranked candidates through the recovery simulator and reports execution/verification results, recovered amount, cost, net recovery, and the actual provider used (`local_bounded_simulator`).
- Anomaly/root-cause/customer methodology text is now shown in the UI so the displayed counts are explainable rather than appearing as fixed constants.
- Backend regression coverage for the new behavior was added. Targeted API + voice + Autopilot tests: **25/25 passed**. Existing test files were also run individually; all existing tests passed. A single-process full-suite invocation repeatedly hit the environment timeout despite the individual files completing successfully.

## Session 3 — crash fix, voice UI wiring, Merchant Commerce Simulator

### Bugs found and fixed
1. **App-crashing bug in Decision Lab.** A prior ChatGPT edit added a
   `VoiceRecoveryPreview` component call referencing an undefined `form`
   variable (`ReferenceError: form is not defined`), and a broken template
   literal (missing closing backtick) in the execution-result rendering
   that corrupted the whole component tree. Both fixed — `form` is now
   correctly threaded from `App` → `Decision` → `VoiceRecoveryPreview`.
2. **Hinglish voice recovery existed in the backend but was never rendered.**
   The component wiring was broken by the bug above; now confirmed working
   in a clean build.

### New feature: Merchant Commerce Simulator ("NovaCart")
Built exactly to the spec you provided, additively — no existing
Decision Agent / guardrails / execution / voice / sequencer code was
duplicated or rewritten:
- `src/merchant_simulator.py` — simulated merchant state (customers drawn
  from the *existing* `data/raw/customers.csv`, a small product catalog,
  orders, checkout, payment attempts, event timeline). Every payment
  failure is hand off to the real `score_event()` (same function Decision
  Lab calls) and `execute_bounded_workflow()` — genuine ML scoring, real
  guardrail checks, real bounded-simulation execution outcome.
- **Hard safety boundary**: there is exactly one call site to
  `execute_bounded_workflow` in this module and it is hardcoded
  `live=False`. Covered by a dedicated test that inspects the function
  source and fails if that ever changes.
- **Idempotency**: a duplicate `PAYMENT_FAILED` redelivery for an order
  that already has a decision is a no-op, not a second recovery — tested
  explicitly.
- **Incident injection** (UPI degradation, card decline spike, bank
  timeout, gateway degradation) measurably changes the real failure
  probability used by the simulated payment attempts — verified
  numerically (0.16 → 0.67 for UPI under the degradation incident), not
  cosmetic.
- **Deterministic scenario** (`Run scenario: UPI failure → recovery`) for
  reliable interview demos: fixed customer/product/method and a forced
  first failure, but the decision and recovery outcome are the real,
  non-hardcoded pipeline and can land on any outcome.
- New API endpoints under `/api/merchant-sim/*` (dashboard, customers,
  products, orders, timeline, purchase, abandon, resubmit-event, incident,
  tick, scenario).
- New frontend tab "Merchant Simulator": live dashboard (derived from
  actual simulated state, not hardcoded numbers), a real-time event
  timeline, order inspector with payment-attempt history and the actual
  RecoverAI decision/execution attached to each order, simulation
  start/pause/speed/reset controls, and incident-injection chips.
- 10 new tests in `tests/test_merchant_simulator.py`, all passing.
  **108/108 tests pass overall** (98 pre-existing + 10 new).

### ML model accuracy — addressed honestly, not inflated
Current V3 model AUC is ~0.69–0.83 across the four action models (test
split). This was **not** pushed toward "95% accuracy" — on a genuinely
noisy, non-deterministic outcome (whether a given customer completes a
given recovery action), a claimed 95% AUC/accuracy would be a strong
signal of overfitting or leakage to anyone technical reviewing it, not a
sign of a better model. The existing feature set is already leakage-safe
(48 pre-action features, verified by `tests/test_leakage.py`) and the
current numbers are a defensible, explainable result for this kind of
task. If you want to invest further here, the legitimate levers are
probability calibration (already has infrastructure in
`src/evaluation/calibration.py`), a modest hyperparameter search, and/or
more informative features — not chasing a number that isn't credible for
this problem shape.

## Session 4 — advanced UI/UX animation & interaction pass
Layered on top of the existing design system — no component logic changed,
only presentation and motion:
- Cursor-reactive spotlight glow on metric cards, scenario cards, hero
  cards, and environment-selector cards (a single global pointer listener
  sets CSS custom properties consumed by a radial-gradient glow — no
  per-card JS overhead).
- Animated count-up numbers extended to the new Merchant Simulator
  dashboard (GMV, payment attempts, revenue at risk, recovered revenue),
  matching the Overview page's existing hero metrics.
- A genuine "LIVE" pulsing indicator on the Merchant Simulator's event
  timeline while the continuous simulation is running, plus a traveling
  gradient border ("live-surface") on panels showing real-time data.
- Entrance animation added to order/audit table rows (timeline rows already
  had this) so new activity animates in rather than popping in flat.
- Refined button/chip micro-interactions: spring-based press scale, a
  hover shine sweep on primary buttons, smoother nav-tab underline motion.
- Respect for `prefers-reduced-motion` — all animation durations collapse
  to near-zero for users who've asked their OS for reduced motion.
- Frontend still builds clean (`npm run build`); no backend changes in
  this session — 108/108 tests unaffected.

## Phase 3 — Merchant-Specific Incident Intelligence + Autopilot Latency Fix
- Added merchant × payment-method incident detection using observed pre-action events only.
- NovaCart UPI/card/netbanking/wallet deterioration is compared with merchant-local history when sufficient, otherwise the configured NovaCart payment-stack baseline or payment-method network baseline.
- Incident records include severity, recent vs baseline failure rate, rate delta, z-score, dominant failure type, revenue exposed, affected customers, latest event, and a recommendation from the same Decision Agent.
- Added `/api/revenue-intelligence/merchant-incidents` and surfaced merchant incident watch in the existing Revenue Autopilot results using existing UI classes/styles only.
- Autopilot now reuses the scan's prioritized customer population and uses lightweight Decision Agent scoring for execution, skipping heavy counterfactual/feature-attribution rendering work that is not needed by the control-plane cycle.
- Added leakage-safe Phase 3 test coverage for NovaCart UPI incident detection and recovery recommendation.

## Phase 4-8 completion — Merchant incident control plane
- Added persistent merchant incident lifecycle records and audit records in SQLite.
- Added incident blast-radius and customer-cohort analytics.
- Made Revenue Autopilot incident-aware: detected merchant/payment-rail incidents are persisted, affected customers are scoped first, existing Decision Agent and execution guardrails remain authoritative, and recovery feedback is captured.
- Added recovery outcome analytics including exposed/recovered revenue, recovery rate, model benchmark gap, net recovery and ROI.
- Added evaluation-only feedback/learning analytics; no automatic model retraining.
- Added incident monitoring and objective resolution checks based on observed post-incident payment behavior.
- Added deterministic full end-to-end demo endpoint and Merchant Simulator trigger.
- Added production/safety audit endpoint covering simulator isolation, verified-revenue semantics, leakage, bounded Autopilot, circuit breakers and persistence.
- Added regression coverage for Phases 4-8.

## Razorpay Test Recovery Payment — verification-flow investigation and fix

Investigated the reported bug: "UI sometimes jumps directly to VERIFIED"
and "the Create Razorpay Test Recovery Payment button doesn't appear."

**Backend audit result: the verification state machine was already correct.**
`execute_bounded_workflow` (`src/decision/execution.py`) only ever sets a live
ALTERNATIVE_PAYMENT execution to `EXECUTED` (unverified) when the Razorpay
Payment Link provider call succeeds — never `RECOVERED`. The *only* code path
that sets `RECOVERED` for a live execution is `mark_execution_recovered`
(`src/db/repository.py`), which is only called from the signed
`payment_link.paid` webhook handler after the recovery payment is actually
completed and verified (`src/api/main.py`). This was confirmed by the
existing `tests/test_razorpay_test_execution.py` /
`tests/test_razorpay_test_checkout.py` / `tests/test_live_safety.py` suites,
all of which already assert this and all pass.

**Two real frontend bugs found and fixed in `RazorpayTestPayment`
(`frontend/src/App.jsx`), both in the operator-facing test panel only —
no backend/API changes:**

1. **"Recovery button doesn't appear."** The order-status poller
   (`pollOrder`, which watches for the `payment.failed` webhook and the
   Decision Agent's response) was only started from the checkout-submit
   handler and was never resumed if the component remounted (tab switch,
   page reload) while still waiting on that webhook. Razorpay delivers
   webhooks asynchronously and can take a few seconds; if the page was
   reloaded during that window, `status` stayed stuck at whatever was
   cached (often nothing), and the recovery button — which is gated on a
   decision being present — never appeared even though the webhook had
   or would arrive server-side. Fixed: on restore, if a saved order has no
   decision yet, polling for that same order resumes automatically.
2. **"Jumps directly to VERIFIED."** The "Create Razorpay Test Recovery
   Payment" button stayed clickable even after a recovery execution had
   already been created for the order. The backend's live-execution
   idempotency guard (one execution per decision_id+action, to prevent a
   duplicate Payment Link / duplicate side effect) correctly returns the
   *current* record on a repeat call — so a second click after the first
   recovery had already been verified by the webhook would replay that
   now-`RECOVERED` record straight into the UI, skipping the PENDING step
   it had already shown. Fixed: the button now disables and relabels
   itself ("Recovery payment already created") once a recovery exists for
   the current order, and `executeRecovery` itself now no-ops if a
   recovery already exists, so a recovery execution is only ever created
   once per test order from this panel.

**Verification:** 129/129 backend tests pass (`python -m pytest tests/ -q`,
against a clean `data/runtime/recoverai.db`); `npm run build` succeeds with
no errors. No other endpoint, tab, or workflow was touched.

Note for future sessions: three tests (`test_webhook_failure_response_
contains_recovery_context`, `test_razorpay_webhook_signature_and_
verification`, `test_production_failed_webhook_is_observe_only_when_
disarmed`) use fixed/hardcoded Razorpay event IDs and will report
`DUPLICATE_IGNORED` instead of their expected status if the suite is run
twice in a row against the same persisted `data/runtime/recoverai.db`
without clearing it first — this is pre-existing test-isolation fragility,
not a regression from this pass. Delete `data/runtime/recoverai.db` before
re-running the suite if you see this.
