# RecoverAI — Intelligent Payment Failure Recovery & Revenue Recovery Engine

RecoverAI is a **free, local, end-to-end ML decision engine** for recovering revenue from failed or at-risk payments. It does not merely predict whether a payment will recover; it evaluates multiple possible recovery actions, converts predicted probability into expected money, applies hard business guardrails, and recommends the highest-value allowed action.

## 1. The problem

When a payment fails, blindly retrying is not always the best move. A merchant may instead:

- switch the customer to another payment method,
- send a recovery reminder,
- retry after a delay,
- escalate a valuable case to a human, or
- stop when further intervention is not economically justified.

The core question is:

> **Given everything known before the next recovery action, which action maximizes expected recovered revenue while respecting business policy?**

## 2. How RecoverAI solves it

```text
Payment / revenue-risk context
            |
            v
   Action-specific ML models
            |
            v
 Recovery probability per action
            |
            v
Expected recovered money = probability × amount
            |
            v
     subtract action cost
            |
            v
       Apply guardrails
            |
            v
   Rank allowed actions + STOP
            |
            v
 Explain + audit the decision
```

## 3. ML methodology

The project uses synthetic but structured payment, customer, merchant, and recovery-outcome data.

- Temporal split: January–June train, July validation, August held-out test.
- One action-specific classifier per recovery action.
- V1–V7 experiments are preserved in `src/models` and `src/evaluation`.
- V3-100k is the current champion policy used by the live Decision Agent and held-out dashboard evaluation.
- The August holdout is not used as a training feature source.
- Outcome/post-action fields are explicitly excluded from model features.

Forbidden leakage fields include:

- `true_recovery_probability`
- `simulated_success_probability`
- `recovery_success`
- `revenue_recovered`
- future/post-action information

## 4. Business objective

For each action:

`expected_revenue = predicted_recovery_probability × transaction_amount`

`expected_net_value = expected_revenue − action_cost`

The policy chooses the highest expected net value among actions that pass guardrails. `STOP` is always available with value 0, so the engine has a safe fallback instead of forcing an intervention.

## 5. Guardrails

The current policy intentionally demonstrates real blocking behavior:

| Action | Policy |
|---|---|
| STOP | Always allowed as safe fallback |
| RETRY_LATER | Blocked after 3+ retries or for non-retryable failures |
| HUMAN_ESCALATION | Requires ₹25,000+ and customer success rate ≥85% |
| RECOVERY_REMINDER | Allowed; especially natural for checkout abandonment |
| ALTERNATIVE_PAYMENT | Allowed; abandonment is deprioritized rather than hard-blocked |

Non-retryable examples: issuer decline, insufficient balance, payment limit, expired payment method.

The UI shows **all action guardrails**, not only the selected action. Therefore a green `Allowed` recommendation does not mean every action is allowed.

## 6. What is included in the final product

### ML / evaluation
- V1–V7 experiments
- held-out August business evaluation
- static baselines
- oracle upper bound
- policy regret artifacts
- calibration artifacts
- leakage tests
- model-card endpoint

### Backend
- FastAPI
- `/health`
- `/api/metrics`
- `/api/analysis`
- `/api/model-card`
- `/api/guardrails`
- `/api/audit-log`
- `/predict`

### Frontend
- Overview dashboard
- revenue-at-risk / recovered / uplift / oracle capture cards
- recovery-by-action chart
- recovery-by-event chart
- Decision Lab
- action probabilities
- expected monetary value
- action costs
- confidence and score margin
- visible per-action guardrail status
- STOP fallback
- preset demo scenarios
- Evaluation / Model Card page
- Guardrails policy page
- Audit Log page

### Auditability
Every live decision is written locally to:

`data/runtime/recoverai.db`

No external database service is required; the application uses a local SQLite database at `data/runtime/recoverai.db`.

## 7. Run locally — Windows PowerShell

### Backend

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/docs

### Frontend

Open a second PowerShell:

```powershell
cd frontend
npm install
npm run dev
```

Open:

- http://localhost:5173

Convenience scripts are also included:

```powershell
.\run_backend.ps1
.\run_frontend.ps1
```

## 8. Test everything

Backend tests:

```powershell
python -m pytest -q
```

The six test modules contain **66 tests** and each module has been independently verified as passing. The combined run can be slow because model-health tests perform real permutation-based feature-importance work.

The project pins `scikit-learn==1.8.0`, matching the V3-100k model artifact.

## 9. Demo flow for judges

1. Start backend and frontend.
2. Open **Overview** and explain the business problem and held-out metrics.
3. Open **Decision Lab**.
4. Run the “First timeout · strong customer” scenario.
5. Change retry count to `4` and failure type to `ISSUER_DECLINE`; show `RETRY_LATER` becoming **Blocked**.
6. Set amount to `50000` and customer success rate to `0.92`; show that human escalation becomes **Allowed** even if the ML ranking does not select it.
7. Use “Checkout abandonment” to explain why reminder is naturally preferred.
8. Open **Evaluation** to show temporal evaluation, leakage protection, baseline uplift and oracle capture.
9. Open **Guardrails** to explain policy decisions.
10. Open **Audit Log** to prove every live decision is traceable.

## 10. Planning and scenario analysis

The Evaluation page exposes two planning tools:

- **Budget-Constrained Intervention Planner** (`POST /api/budget/optimize`) allocates a finite intervention-cost budget across the August population using model-predicted expected net value and the same production guardrails. It returns spend, expected recovery, expected net value, action mix and a shadow price.
- **Revenue Recovery Scenario Simulator** (`POST /api/digital-twin`) stress-tests the policy by scaling event volume, transaction amount and modelled recovery odds, with an optional budget cap. It is a deterministic scenario model, not a live replica of a payment processor.

Neither planner uses realized recovery outcomes to choose actions, and neither performs external execution.

## 10. Honest limitations

The data is synthetic. The displayed ₹ recovery numbers are evaluation results for this project and **must not be presented as Razorpay production results**. A production rollout would require real labeled recovery outcomes, online experimentation/A-B testing, monitoring, model governance, security, authentication, rate limits, and integration with a real payment system.

## 12. Free-only stack

Python, Pandas, NumPy, scikit-learn, Joblib, FastAPI, Uvicorn, React, Vite, Recharts and Lucide React.

No paid API key, cloud account, paid database, GPU or external SaaS is required.

## Advanced Revenue Autopilot (V4)

RecoverAI now includes a Revenue Autopilot intelligence layer in addition to the existing ML Decision Agent, adaptive recovery, UPI mandate, B2B receivables, Promise-to-Pay, counterfactuals, budget optimizer and digital twin.

### Revenue Detective / Root Cause / Customer Impact

- `GET /api/revenue-intelligence/scan` runs a real scan over `data/raw/events.csv`, `customers.csv` and `merchants.csv`.
- Hourly anomaly detection compares recent payment-failure rates with a historical baseline using a z-score.
- Root-cause ranking compares recent vs baseline failure rates by payment method, failure type, merchant, device and event type.
- Affected-customer discovery ranks real customer IDs by amount exposure, repeated failures and historical payment behavior.
- These analytics deliberately do not read recovery outcome columns.
- The React Revenue Autopilot page is idle on tab entry and runs the full cycle only after the operator clicks **Run Autopilot Cycle**.

### Real external execution adapters

Safe simulation remains the default. Real integrations activate only when explicitly enabled:

```powershell
$env:RECOVERAI_LIVE_EXECUTION="1"
```

Optional provider configuration:

- `RAZORPAY_KEY_ID` + `RAZORPAY_KEY_SECRET` — creates a real Razorpay Payment Link for `ALTERNATIVE_PAYMENT`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` — sends a real recovery email.
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` — sends a real SMS when the SMS channel is selected.
- `RECOVERAI_EXECUTION_WEBHOOK_URL` — sends retry/escalation actions to a configured external orchestration webhook.

The `/api/integrations/status` endpoint shows which providers are configured. Every external provider is protected by an in-memory circuit breaker (3 failures opens the circuit; a cooldown permits a half-open probe). The UI and API never claim revenue was recovered merely because a provider accepted a request; payment success must be verified separately.

### Circuit-breaker demonstration without credentials

The integration endpoint supports a deliberate failure-injection flag for a safe judge demo:

```json
POST /api/integrations/execute
{"action":"RECOVERY_REMINDER","amount":1000,"simulate_failure":true}
```

Repeat three times and `/api/integrations/status` will show the email circuit as `OPEN`. Reset with:

```text
POST /api/integrations/circuit-breaker/reset
```

### Live execution endpoint

The existing `/execute-decision` endpoint accepts:

```json
{"payload": {...}, "decision": {...}, "live": true, "channel": "auto"}
```

`live=false` preserves the original deterministic bounded simulation and is the recommended mode for the hackathon demo unless real provider credentials are intentionally configured.

## 11. Production-oriented execution, evaluation and planning behavior

### Execution modes

RecoverAI has two deliberately separate execution modes:

- **SAFE_SIMULATION**: the default. Decisions and bounded outcomes are simulated locally; no customer or payment provider is contacted.
- **LIVE**: disabled unless `RECOVERAI_LIVE_EXECUTION=1`, the required provider credentials are present, and the user explicitly confirms the live action in the UI.

Live adapters are action-specific:

- `ALTERNATIVE_PAYMENT` → Razorpay Payment Link creation. Creating the link is **not** treated as a recovered payment.
- `RECOVERY_REMINDER` → SMTP email or Twilio SMS, selected explicitly or through `Auto` routing.
- `RETRY_LATER` / `HUMAN_ESCALATION` → configured orchestration webhook.

Customer email/phone are therefore optional at decision time because STOP, retry scheduling and human escalation do not inherently require a customer contact. When a live reminder or payment-link delivery is requested, the required contact channel is validated before the provider is called.

A successful provider request never becomes revenue by itself. `/api/integrations/recovery-webhook` accepts an HMAC-SHA256 authenticated verification callback and marks the execution as recovered only after an authenticated payment/status event confirms the amount.

### Evaluation is executable, not decorative

The Evaluation page now includes **Run Evaluation**. It calls `POST /api/evaluation/run`, recomputes the August held-out policy from the frozen V3-100k model artifact, writes the evaluation artifact and refreshes the dashboard metrics. It is offline-only and cannot modify production policy or contact providers.

### Policy Lab timing controls

Retry/reminder cooldowns belong to the real-time Adaptive Recovery Sequencer. The static August evaluator has one decision point per event, so those timing controls are no longer presented as if they change static held-out results. This prevents a misleading control in the Policy Lab.

The What-If `high_value_threshold` is now a real candidate-policy gate for human escalation, rather than a displayed-but-unused input.

### Budget planner

The former “Recovery Budget Optimizer” is explicitly a **Budget-Constrained Intervention Planner**. It allocates an intervention-cost budget using model-predicted expected net value and production guardrails. Its outputs are planning estimates, not realized revenue. It does not use counterfactual outcomes to choose actions.

### Scenario simulator

The former “Digital Twin” is explicitly a **Revenue Recovery Scenario Simulator**. It is a deterministic model-based stress test over the held-out population, scaling volume/amount/modelled recovery odds. It is not a live replica of a payment processor and never performs external actions.

### Revenue Autopilot

The Autopilot is an orchestration layer, not a magic always-on agent. The dashboard is idle until **Run Autopilot Cycle** is clicked, then executes **DETECT → DIAGNOSE → PRIORITIZE → RECOVER → VERIFY**. Recovery is bounded to the same safe local simulator used by Decision Lab, so the button actually executes and verifies actions without silently contacting customers or providers. The top 25 affected customers are displayed, while a hard cap of 10 risk-ranked candidates is sent through the recovery simulation per cycle.


## Execution environments

RecoverAI exposes three explicit execution environments in the UI and backend:

- **DEMO / SIMULATION** — local-only; external providers are disabled.
- **RAZORPAY TEST** — enables sandbox execution only. Razorpay payment actions require `rzp_test_*` credentials, and email/SMS destinations can be restricted with `RECOVERAI_SANDBOX_EMAIL` / `RECOVERAI_SANDBOX_PHONE`.
- **LIVE PRODUCTION** — requires `RECOVERAI_ADMIN_TOKEN`, explicit UI/API confirmation, production allow-lists, per-action limits, a daily budget, and the kill switch. Razorpay production execution rejects test keys.

The `.env` file is intentionally ignored by Git/archives. Copy `.env.example` to `.env`, add credentials locally, and never commit secrets.

The Revenue Autopilot performs **DETECT → DIAGNOSE → PRIORITIZE → RECOVER → VERIFY** after an explicit button click. Autopilot recovery is always `SAFE_SIMULATION`; live customer/provider execution remains an explicit Decision Lab action. The anomaly count is computed from hourly failure-rate z-scores, root causes from recent-vs-baseline segment deterioration, affected customers from risk-ranked failed events, and execution-provider count from providers actually used by the autopilot recovery run.

### Provider integration testing

Decision Lab keeps the AI recommendation separate from provider integration testing. **Execute Recommended Action** follows the model recommendation. The **Integration test** controls allow an operator to test another action that is allowed by the same guardrails without changing the AI decision. In RAZORPAY TEST, `ALTERNATIVE_PAYMENT` creates a Standard Razorpay Test Payment Link using `rzp_test_*` credentials and returns the hosted `short_url` in the UI. Creating the link does not count revenue as recovered; authenticated payment/webhook verification is still required. See `RAZORPAY_TESTING_GUIDE.md` for the complete local test procedure.

## Production real-time integration

RecoverAI supports three isolated environments without replacing the existing NovaCart demo:

- **DEMO** — synthetic data and bounded NovaCart recovery simulation.
- **SANDBOX / TEST** — Razorpay Test credentials and test webhooks.
- **PRODUCTION** — an authorized merchant's Razorpay Live events and configured production providers.

Production ingestion accepts authenticated Razorpay webhook events. `payment.failed` events are normalized into the existing `PaymentEvent` contract and passed through the same Decision Agent and hard guardrails used by the demo. Production execution is fail-closed unless production is explicitly armed, the environment is PRODUCTION, LIVE Razorpay credentials and the Razorpay webhook secret are configured, and existing safety controls permit the action.

A provider response such as an accepted SMS, Payment Link creation, or orchestration request is **not** counted as recovered revenue. RecoverAI marks real revenue recovered only after a verified payment-status event confirms the successful payment. Duplicate Razorpay webhook deliveries are idempotently ignored.

### Enabling production

Keep these disabled by default:

```text
RECOVERAI_EXECUTION_ENV=DEMO
RECOVERAI_LIVE_EXECUTION=0
RECOVERAI_PRODUCTION_EXECUTION_ARMED=0
```

A properly onboarded merchant must configure Razorpay Live credentials and a Razorpay webhook secret. Production arming requires `RECOVERAI_ADMIN_TOKEN` plus explicit live confirmation. Never commit `.env` or provider secrets.

The production connector does **not** replace the NovaCart simulator or synthetic dataset, and simulated recovery values must never be presented as real production revenue.
