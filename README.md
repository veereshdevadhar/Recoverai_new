# RecoverAI — AI-Powered Revenue Recovery & Payment Reliability Platform

> **RecoverAI turns payment failures into recoverable revenue.**
>
> It detects merchant-level payment incidents, identifies affected customers, estimates recovery opportunities, chooses the best recovery action using ML + contextual policy, executes bounded interventions, verifies the actual payment outcome, and records only verified recovered revenue.

---

## 🚀 What is RecoverAI?

RecoverAI is an end-to-end **AI-powered payment recovery and revenue protection platform** designed for digital merchants.

When payments start failing, most systems stop at:

```text
Payment Failed
      ↓
Retry Payment
      ↓
Done
```

RecoverAI treats payment failure as a **merchant-level incident and revenue recovery problem**.

Instead, the system asks:

```text
Why are payments failing?
        ↓
Is this an isolated failure or a merchant-wide incident?
        ↓
How much revenue is exposed?
        ↓
Which customers are affected?
        ↓
Which customers should be prioritized?
        ↓
Which recovery action has the highest expected value?
        ↓
Can that action safely be executed?
        ↓
Did the customer actually pay?
        ↓
Can the payment be independently verified?
        ↓
How much revenue was actually recovered?
```

The result is a complete closed-loop recovery system:

```text
DETECTION
   ↓
DIAGNOSIS
   ↓
REVENUE EXPOSURE
   ↓
CUSTOMER PRIORITIZATION
   ↓
AI DECISION
   ↓
GUARDRAILS
   ↓
RECOVERY EXECUTION
   ↓
PAYMENT
   ↓
VERIFICATION
   ↓
RECOVERED REVENUE
   ↓
ANALYTICS
   ↓
FEEDBACK
   ↓
INCIDENT RESOLUTION
```

---

# 🎯 The Problem

Payment failures create two different problems.

### 1. Payment reliability problem

A merchant may suddenly experience:

- UPI failures
- bank-side timeouts
- network failures
- checkout failures
- repeated payment attempts
- payment-method-specific degradation
- temporary provider problems

### 2. Revenue recovery problem

Every failed payment can represent revenue that may still be recoverable.

For example:

```text
Customer wants to purchase ₹12,499 product

        ↓

UPI payment attempted

        ↓

Payment fails

        ↓

Merchant loses a potential ₹12,499 sale
```

A naive system might retry UPI repeatedly.

RecoverAI instead evaluates:

```text
Retry later?
      OR
Switch payment method?
      OR
Send recovery reminder?
      OR
Escalate to human?
      OR
Stop intervention?
```

The correct answer depends on:

- failure type
- retry count
- transaction amount
- customer history
- payment method
- merchant context
- incident severity
- recovery probability
- expected recovery value
- intervention cost
- available recovery channels
- safety constraints

---

# 💡 RecoverAI's Core Idea

RecoverAI separates the problem into two levels.

## Merchant level

RecoverAI asks:

> "Is something going wrong with the merchant's payment system?"

It detects abnormal payment behavior and creates an incident.

## Customer level

RecoverAI asks:

> "Given this incident, what should we do for this particular failed customer?"

The Decision Agent evaluates available recovery actions.

This separation is important because a merchant-wide UPI incident should not be treated like an isolated customer mistake.

---

# 🏗️ Complete Architecture

The complete RecoverAI architecture is:

<img width="2720" height="3016" alt="novacart_recovery_pipeline updated" src="https://github.com/user-attachments/assets/19f27f8e-f244-4d85-82bf-08d6340a14ae" />


---

# 🔄 End-to-End Flow

A typical RecoverAI flow looks like this:

## Step 1 — Merchant operates normally

NovaCart generates normal commerce and payment activity.

RecoverAI observes events such as:

```text
checkout_started
payment_attempted
payment_failed
payment_success
order_created
order_paid
```

---

## Step 2 — Payment failure occurs

Example:

```text
Customer: CUS_001867
Product: Smart Watch
Amount: ₹12,499
Payment method: UPI
Result: FAILED
```

The failed payment becomes an event inside RecoverAI.

---

## Step 3 — Revenue Intelligence observes merchant behavior

RecoverAI does not immediately assume that one failed payment means a merchant incident.

It looks at the broader payment behavior.

It can analyze:

- payment-method failure rates
- failure types
- recent payment history
- merchant behavior
- event distributions
- temporal changes
- affected payment methods

---

## Step 4 — Merchant anomaly detection

If the observed behavior becomes abnormal, RecoverAI creates a merchant incident.

For example:

```text
Normal UPI failure rate
        ↓
       12%

Observed UPI failure rate
        ↓
       48%

        ↓

Merchant-level anomaly detected
```

---

## Step 5 — Incident diagnosis

RecoverAI determines the likely cause.

Example:

```text
Incident:
UPI reliability degradation

Root cause:
BANK_TIMEOUT

Affected method:
UPI

Severity:
HIGH
```

---

## Step 6 — Revenue exposure

RecoverAI estimates the amount of revenue exposed by the incident.

Important distinction:

```text
Revenue Exposed
≠
Expected Recovery
≠
Recovered Revenue
```

### Revenue exposed

Money potentially lost because of payment failure.

### Expected recovery

Model estimate of how much can potentially be recovered.

### Recovered revenue

Money that was **actually paid and independently verified**.

---

# 🤖 Decision Agent

The Decision Agent is the core customer-level decision engine.

It does not simply implement:

```text
UPI failure → retry
```

Instead it evaluates the available recovery actions.

Possible actions include:

```text
ALTERNATIVE_PAYMENT
RECOVERY_REMINDER
RETRY_LATER
HUMAN_ESCALATION
STOP
```

---

# 🧠 ML + Policy Decisioning

RecoverAI combines predictive modeling with contextual policy.

Conceptually:

```text
Customer / Payment Context
          ↓
     ML Prediction
          ↓
Recovery Probability
          ↓
Expected Recovery Value
          ↓
Contextual Policy Adjustment
          ↓
Policy-Adjusted Expected Value
          ↓
Guardrails
          ↓
Final Action
```

The model provides the predictive signal.

The policy layer adds context.

The guardrails provide hard safety boundaries.

---

# 📊 Decision Features

Decisioning can consider information such as:

- transaction amount
- payment method
- failure type
- retry count
- customer history
- merchant reliability
- incident context
- recovery action
- predicted recovery probability
- intervention cost
- expected net value
- eligibility constraints

---

# 🛡️ Guardrails

RecoverAI does not allow the ML model to freely execute arbitrary actions.

Some rules are hard constraints.

For example:

```text
retry_count >= retry_limit
        ↓
RETRY_LATER BLOCKED
```

or:

```text
All available recovery actions
have non-positive expected value
        ↓
STOP
```

or:

```text
High-value customer
+
eligible escalation
        ↓
HUMAN_ESCALATION may become competitive
```

The model recommends.

The guardrails constrain.

The execution layer enforces.

---

# 💰 Expected Value

The decision system evaluates recovery actions using expected value.

Conceptually:

```text
Expected Recovery
=
Recovery Probability × Transaction Value
```

Then intervention cost can be considered:

```text
Expected Net Value
=
Expected Recovery - Intervention Cost
```

RecoverAI can therefore compare:

```text
RETRY_LATER
       vs
ALTERNATIVE_PAYMENT
       vs
RECOVERY_REMINDER
       vs
HUMAN_ESCALATION
```

instead of blindly retrying.

---

# 🏪 Merchant Simulator

The Merchant Simulator is one of the most important parts of RecoverAI.

It provides a controlled environment representing a merchant's commerce and payment system.

The simulator allows the complete architecture to be demonstrated without depending on real customers or real payment infrastructure.

Conceptually:

```text
NovaCart
   ↓
Customer
   ↓
Product
   ↓
Checkout
   ↓
Payment Attempt
   ↓
Failure / Success
   ↓
RecoverAI
```

---

# Why the Merchant Simulator exists

Without a simulator, demonstrating the full architecture would require:

- a real merchant
- real customer traffic
- real payment failures
- real incidents
- real recovery actions

That is unsafe and impractical.

The Merchant Simulator provides deterministic synthetic activity instead.

It allows us to reproduce scenarios such as:

```text
Normal merchant activity
        ↓
Payment failure spike
        ↓
Merchant incident
        ↓
Customer affected
        ↓
RecoverAI decision
        ↓
Recovery
        ↓
Payment success
```

---

# 🎬 Deterministic Demo

The demo is designed to be reproducible.

A representative scenario is:

```text
1. NovaCart operates normally
2. Customer selects a product
3. Checkout begins
4. Customer chooses UPI
5. UPI payment is attempted
6. Payment fails
7. Event enters RecoverAI
8. Revenue Intelligence observes merchant behavior
9. Merchant anomaly is detected
10. Incident is created
11. Root cause is identified
12. Revenue exposure is calculated
13. Affected customer is identified
14. Customer is prioritized
15. Decision Agent evaluates recovery actions
16. Guardrails are evaluated
17. Recovery action is selected
18. Recovery executes in simulation
19. Customer responds
20. Second payment attempt occurs
21. Payment succeeds
22. RecoverAI verifies the outcome
23. Order becomes PAID
24. Revenue Ledger records verified recovery
25. Recovery analytics update
26. Feedback is recorded
27. Incident monitoring observes improvement
28. Incident reaches RESOLVED
```

This makes the entire causal chain visible:

```text
Merchant event
→ anomaly
→ incident
→ diagnosis
→ revenue exposure
→ affected customer
→ recovery decision
→ execution
→ payment
→ verification
→ recovered revenue
→ analytics
→ feedback
→ resolution
```

---

# 💳 Razorpay Integration

RecoverAI includes a real Razorpay Test Mode integration.

The project deliberately separates:

```text
DEMO
RAZORPAY TEST / SANDBOX
LIVE PRODUCTION
```

These are not interchangeable.

---

# 🟦 DEMO Mode

DEMO is the safest mode.

```text
DEMO
 ↓
Local simulation
 ↓
No external payment provider
 ↓
No real money
```

It is intended for:

- development
- UI demonstrations
- deterministic scenarios
- architecture demonstrations
- automated tests

---

# 🟨 RAZORPAY TEST / SANDBOX

SANDBOX uses Razorpay Test Mode.

```text
SANDBOX
   ↓
Razorpay Test APIs
   ↓
rzp_test_* credentials
   ↓
No real money
```

The application can create a Razorpay Test order and open Razorpay Standard Checkout.

The test checkout can then produce payment events such as:

```text
payment.failed
payment.captured
order.paid
```

The backend receives the signed webhook and processes the event.

---

# 🔐 Razorpay Webhook Verification

RecoverAI does not trust a payment event simply because a provider says it happened.

The webhook is verified using the configured Razorpay webhook secret.

Conceptually:

```text
Razorpay
   ↓
Signed webhook
   ↓
RecoverAI webhook endpoint
   ↓
Signature verification
   ↓
Event validation
   ↓
RecoverAI execution reference
   ↓
Payment verification
```

Only verified payment success is allowed to become recovered revenue.

---

# 🚨 Critical Revenue Rule

This is one of the most important architectural rules in RecoverAI:

```text
Provider accepted request
        ≠
Recovered Revenue
```

For example:

```text
Razorpay Payment Link created
        ↓
NOT recovered revenue
```

Instead:

```text
Payment Link created
        ↓
Customer pays
        ↓
Razorpay webhook received
        ↓
Webhook verified
        ↓
Payment amount verified
        ↓
RecoverAI execution identified
        ↓
Execution marked recovered
        ↓
Revenue Ledger updated
```

Therefore:

```text
VERIFIED_PAYMENT_SUCCESS
        ↓
VERIFIED_RECOVERED
```

---

# 🧪 Razorpay Test Checkout

The frontend provides a Razorpay Test Payment workflow.

The flow is:

```text
RecoverAI UI
      ↓
Create server-side Razorpay TEST order
      ↓
Open Razorpay Standard Checkout
      ↓
Customer completes test payment
      ↓
Razorpay emits event
      ↓
RecoverAI webhook receives event
      ↓
Signature verified
      ↓
Payment state updated
```

For test checkout, Razorpay's test credentials can be used to simulate successful and failed payments.

The UI also exposes the resulting webhook/decision state.

---

# 🔁 Recovery Payment Link

When RecoverAI selects:

```text
ALTERNATIVE_PAYMENT
```

the execution layer can create a Razorpay Payment Link in the configured execution environment.

Important:

```text
Payment Link created
        ↓
Recovery execution created
        ↓
Customer pays
        ↓
Webhook verification
        ↓
Recovery execution becomes RECOVERED
```

The link creation itself is not treated as revenue recovery.

---

# 🌐 Execution Environments

RecoverAI supports three explicit execution environments.

| Environment | External Calls | Real Money | Purpose |
|---|---:|---:|---|
| `DEMO` | No | No | Local simulation |
| `SANDBOX` | Test providers | No | Razorpay Test / integration testing |
| `PRODUCTION` | Production providers | Possible | Controlled live execution |

---

# 🟢 DEMO

Default and safest environment.

```env
RECOVERAI_EXECUTION_ENV=DEMO
RECOVERAI_LIVE_EXECUTION=0
```

No external provider is contacted.

---

# 🟡 SANDBOX

Used for Razorpay Test Mode and explicitly configured sandbox integrations.

```env
RECOVERAI_EXECUTION_ENV=SANDBOX
RECOVERAI_LIVE_EXECUTION=1
```

For Razorpay:

```text
RAZORPAY_KEY_ID must begin with:

rzp_test_
```

Sandbox payment execution is therefore hard-bound to Razorpay Test credentials.

---

# 🔴 PRODUCTION

Production is intentionally difficult to activate.

Production requires:

- production environment
- admin authorization
- explicit live confirmation
- Razorpay LIVE credentials
- Razorpay webhook secret
- production execution arming
- action allow-list
- amount limits
- daily budget
- kill-switch protection
- per-execution confirmation

Production Razorpay credentials must use:

```text
rzp_live_
```

Test credentials are blocked from production activation.

---

# 🛑 Production Safety

RecoverAI includes multiple safety layers.

## Admin authorization

Production changes require:

```env
RECOVERAI_ADMIN_TOKEN
```

## Explicit confirmation

Production cannot be enabled silently.

The operator must explicitly confirm live execution.

## Production arming

Production execution requires:

```env
RECOVERAI_PRODUCTION_EXECUTION_ARMED=1
```

and server-side validation.

## Kill switch

Live execution can be stopped using the kill switch.

```text
Kill switch ACTIVE
        ↓
Live execution blocked
```

## Per-action allow-list

Recovery actions can be explicitly enabled.

Supported action controls include:

```env
RECOVERAI_ALLOW_ALTERNATIVE_PAYMENT
RECOVERAI_ALLOW_RECOVERY_REMINDER
RECOVERAI_ALLOW_RETRY_LATER
RECOVERAI_ALLOW_HUMAN_ESCALATION
```

## Amount limits

Live actions are bounded by:

```env
RECOVERAI_MAX_LIVE_AMOUNT
```

## Daily budget

Production execution is bounded by:

```env
RECOVERAI_DAILY_LIVE_BUDGET
```

The default daily live budget is:

```text
₹50,000
```

The default production per-action amount limit is:

```text
₹10,000
```

Sandbox has a larger default per-action limit for testing.

---

# 📬 Recovery Channels

RecoverAI's execution layer supports multiple recovery channels.

## Alternative Payment

```text
ALTERNATIVE_PAYMENT
        ↓
Razorpay Payment Link
```

Used when switching payment method can improve recovery probability.

---

## Recovery Reminder

```text
RECOVERY_REMINDER
        ↓
Email / SMS / supported channel
```

Email can use SMTP.

SMS can use Twilio.

The exact channel is selected based on configuration and customer contact availability.

---

## Retry Later

```text
RETRY_LATER
        ↓
Retry scheduling / orchestration webhook
```

RecoverAI itself does not blindly charge a customer again.

The retry action can send a scheduling/orchestration command to the configured execution webhook.

---

## Human Escalation

```text
HUMAN_ESCALATION
        ↓
Bounded escalation case
```

Useful for eligible high-value or otherwise sensitive cases.

---

# 📧 Email Integration

SMTP can be configured for recovery reminders.

Relevant configuration includes:

```env
SMTP_HOST
SMTP_PORT
SMTP_USERNAME
SMTP_PASSWORD
SMTP_FROM
SMTP_USE_SSL
SMTP_STARTTLS
```

In SANDBOX, email execution is restricted to the configured test destination:

```env
RECOVERAI_SANDBOX_EMAIL
```

This prevents accidental emails to arbitrary addresses during testing.

---

# 📱 Twilio Integration

SMS execution can be configured using Twilio.

Production-style configuration can use:

```env
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM
```

Sandbox test credentials can use:

```env
TWILIO_TEST_ACCOUNT_SID
TWILIO_TEST_AUTH_TOKEN
```

Sandbox SMS is restricted to:

```env
RECOVERAI_SANDBOX_PHONE
```

---

# 🔊 Voice

RecoverAI can generate recovery/communication content suitable for voice interaction and browser playback.

However, the application deliberately does not pretend that a real outbound telephone call occurred when a telephony provider is not configured.

If no voice provider is configured, the system reports the channel as unavailable rather than fabricating execution success.

---

# 🗃️ Data Architecture

The project separates source data, processed artifacts, runtime state and application code.

```text
data/
├── raw/
│   ├── customers.csv
│   ├── events.csv
│   ├── merchants.csv
│   └── recovery_actions.csv
│
├── processed/
│   ├── models/
│   ├── action_performance.csv
│   ├── event_distribution.csv
│   ├── failure_distribution.csv
│   ├── failure_recovery_analysis.csv
│   ├── monthly_analysis.csv
│   ├── payment_method_analysis.csv
│   ├── policy_analysis.csv
│   ├── recovery_probability_by_event.csv
│   ├── retry_analysis.csv
│   ├── revenue_by_event.csv
│   └── ...
│
└── runtime/
    └── .gitkeep
```

---

# 🤖 Machine Learning Artifacts

The repository contains processed model artifacts and evaluation outputs under:

```text
data/processed/models/
```

Examples include:

```text
baseline_logistic_regression.joblib
recoverai_v1.joblib
recoverai_v2_action_models.joblib
recoverai_v3_100k_action_models.joblib
```

Associated metrics and evaluation artifacts are stored alongside them.

---

# 📈 Evaluation & Policy Lab

RecoverAI includes an evaluation layer for analyzing decision quality.

The project contains modules for:

```text
baselines
calibration
counterfactual analysis
drift
EDA
ledger analysis
offline policy evaluation
planning
policy lab
policy regret
policy versions
```

This makes it possible to evaluate the system beyond a single successful demo.

---

# 🔬 Counterfactual Analysis

RecoverAI can compare alternative recovery strategies.

For example:

```text
Scenario A:
Continue retrying UPI

vs.

Scenario B:
Switch eligible customers to alternative payment
```

Counterfactual analysis is intended for post-hoc evaluation.

Actual recovery outcomes must not leak into decision-time model features.

This separation is important to avoid data leakage.

---

# 📊 Recovery Analytics

RecoverAI tracks more than payment success.

Important metrics include:

### Revenue exposed

Amount at risk because of payment failure.

### Revenue recovered

Actual verified successful payment.

### Recovery rate

```text
Recovered Revenue
-----------------
Revenue Exposed
```

### Incremental recovery

Recovery attributable to the intervention relative to the relevant baseline.

### Intervention cost

Cost of executing the recovery action.

### Net recovery

```text
Recovered Revenue - Intervention Cost
```

Additional analysis can include:

- affected customers
- recovered customers
- failed interventions
- escalations
- retries
- payment-method switches
- recovery lift
- recovery ROI
- action-level performance
- merchant-level performance
- incident-level performance

---

# 🔄 Feedback / Learning Loop

After a recovery action executes, RecoverAI can record the actual outcome.

A feedback record can contain:

```text
event_id
merchant_id
customer_id
incident_id
payment_method
failure_type
amount
selected_action
predicted_probability
expected_recovery
expected_net_value
actual_recovered_amount
actual_outcome
intervention_cost
verified
incident_context
timestamp
```

Possible outcomes include:

```text
RECOVERED
FAILED
STOPPED
ESCALATED
SCHEDULED
EXPIRED
```

This enables:

```text
Predicted outcome
       vs
Actual outcome
```

and supports:

- prediction error analysis
- calibration
- action effectiveness
- merchant performance
- incident performance
- model evaluation
- future policy improvement

The feedback layer does not automatically retrain the production model.

---

# 🧱 Backend Architecture

The backend is implemented in Python using FastAPI.

Important backend areas include:

```text
src/
├── api/
├── data/
├── db/
├── decision/
├── evaluation/
├── features/
├── models/
├── risk/
│
├── incident_platform.py
├── integrations.py
├── intelligence.py
├── merchant_simulator.py
└── voice.py
```

---

# 🔌 API Layer

The FastAPI application exposes the platform through HTTP endpoints.

The API layer handles:

- simulation
- payment events
- incidents
- decisioning
- recovery execution
- execution logs
- integration status
- Razorpay webhooks
- production controls
- analytics
- recovery verification

The application is started from:

```text
src.api.main
```

---

# 🗄️ Database Layer

Database functionality is separated into:

```text
src/db/
├── database.py
├── models.py
└── repository.py
```

This keeps persistence concerns separate from:

- decision logic
- execution
- API routing
- analytics
- simulation

Runtime database files are excluded from Git.

---

# 🎨 Frontend

The frontend is a React application using Vite.

```text
frontend/
├── src/
│   ├── App.jsx
│   ├── main.jsx
│   └── styles.css
│
├── index.html
├── package.json
├── package-lock.json
└── vite.config.js
```

The dashboard exposes the major parts of the RecoverAI workflow.

---

# 🖥️ Dashboard Capabilities

The UI provides visibility into:

- merchant metrics
- payment attempts
- revenue at risk
- recovered revenue
- simulation controls
- event timeline
- customer selection
- product selection
- failure injection
- merchant incidents
- AI decisioning
- recovery execution
- execution environment
- Razorpay Test Checkout
- verification state
- recovery analytics
- integration status
- safety controls

---

# 📡 Live Event Timeline

The dashboard provides a live event timeline so the user can observe the causal chain.

Typical events can include:

```text
Order created
      ↓
Checkout started
      ↓
Payment attempted
      ↓
Payment failed
      ↓
Incident injected
      ↓
Incident detected
      ↓
Decision made
      ↓
Recovery executed
      ↓
Payment verified
      ↓
Revenue recovered
```

This is particularly useful during demonstrations because the judge can see what is happening instead of only seeing a final number.

---

# 🧪 Testing

RecoverAI includes a comprehensive automated test suite.

Tests cover areas such as:

```text
merchant simulator
payment behavior
decision agent
execution
Razorpay integration
Razorpay webhooks
production safety
production realtime behavior
revenue autopilot
voice recovery
planner
league / evaluation behavior
external integrations
```

Run the complete suite with:

```powershell
pytest -q
```

For verbose output:

```powershell
pytest -v
```

Run a specific test file:

```powershell
pytest tests/test_merchant_simulator.py -v
```

Example:

```powershell
pytest tests/test_razorpay_test_checkout.py -v
```

---

# 🧪 Testing Philosophy

The project should be tested at multiple levels.

## Unit tests

Validate individual components.

```text
Decision Agent
Simulator
Guardrails
Repository
Evaluation
```

## Integration tests

Validate interactions between:

```text
API
Database
Decision Agent
Execution
Integrations
Webhooks
```

## End-to-end tests

Validate:

```text
Event
→ Incident
→ Decision
→ Execution
→ Verification
→ Recovery
```

## Safety tests

Validate:

```text
DEMO cannot make live calls
SANDBOX requires test credentials
PRODUCTION requires authorization
Test credentials cannot activate LIVE
Kill switch blocks execution
Amount limits are enforced
Daily budgets are enforced
Invalid webhooks are rejected
Repeated events are handled safely
```

---

# 🛠️ Prerequisites

Before running RecoverAI locally, install:

### Required

- Python 3.10+ recommended
- Node.js
- npm
- Git

### Optional / Integration dependent

- Razorpay account for Test Mode
- SMTP provider
- Twilio account
- external execution webhook endpoint

---

# 📥 Clone the Repository

```powershell
git clone https://github.com/veereshdevadhar/Recoverai_new.git
cd Recoverai_new
```

---

# 🐍 Backend Setup — Windows

Create a virtual environment:

```powershell
python -m venv venv
```

Activate it:

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then:

```powershell
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

---

# 🐧 Backend Setup — Linux / macOS

Create environment:

```bash
python3 -m venv venv
```

Activate:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# 🔐 Environment Configuration

Copy:

```text
.env.example
```

to:

```text
.env
```

Windows:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

Then edit:

```text
.env
```

Never commit the real `.env`.

The repository's `.gitignore` excludes:

```text
.env
venv/
.venv/
node_modules/
.pytest_cache/
__pycache__/
runtime databases
```

---

# 🔑 Required Environment Variables

For normal DEMO mode, external API keys are not required.

The application can run using simulation.

Important configuration variables include:

```env
RECOVERAI_EXECUTION_ENV=DEMO
RECOVERAI_LIVE_EXECUTION=0
```

---

# 💳 Razorpay Test Mode Configuration

For Razorpay Test Mode:

```env
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=xxxxxxxxxxxxxxxx
```

The key must begin with:

```text
rzp_test_
```

Do not use LIVE keys for Sandbox.

---

# 🔐 Production Configuration

Production requires:

```env
RECOVERAI_EXECUTION_ENV=PRODUCTION
RECOVERAI_LIVE_EXECUTION=1
RECOVERAI_PRODUCTION_EXECUTION_ARMED=0

RECOVERAI_ADMIN_TOKEN=<strong-secret>

RAZORPAY_KEY_ID=rzp_live_xxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=<production-secret>
RAZORPAY_WEBHOOK_SECRET=<production-webhook-secret>

RECOVERAI_MAX_LIVE_AMOUNT=10000
RECOVERAI_DAILY_LIVE_BUDGET=50000
```

Production execution should only be armed after all safety requirements are satisfied.

---

# 📧 Sandbox Email

For sandbox email testing:

```env
RECOVERAI_SANDBOX_EMAIL=your-test-email@example.com
```

Configure SMTP:

```env
SMTP_HOST=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_USE_SSL=
SMTP_STARTTLS=
```

Only the configured sandbox destination should receive sandbox email actions.

---

# 📱 Sandbox SMS

Configure the allowed test number:

```env
RECOVERAI_SANDBOX_PHONE=+91XXXXXXXXXX
```

Twilio test credentials:

```env
TWILIO_TEST_ACCOUNT_SID=
TWILIO_TEST_AUTH_TOKEN=
```

Production credentials:

```env
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM=
```

---

# 🔗 Execution Webhook

For retry scheduling or human escalation workflows:

```env
RECOVERAI_EXECUTION_WEBHOOK_URL=
RECOVERAI_EXECUTION_WEBHOOK_SECRET=
```

The execution webhook is protected using HMAC signing.

RecoverAI includes:

```text
X-RecoverAI-Signature
X-RecoverAI-Event
X-RecoverAI-Delivery-Id
```

This allows the receiving orchestration system to verify that the request came from RecoverAI.

---

# ▶️ Running the Backend

From the project root:

```powershell
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

Backend:

```text
http://127.0.0.1:8000
```

Health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

API documentation:

```text
http://127.0.0.1:8000/docs
```

---

# 🎨 Running the Frontend

Open another terminal.

Go to:

```powershell
cd frontend
```

Install packages:

```powershell
npm install
```

Start Vite:

```powershell
npm run dev
```

The frontend normally runs at:

```text
http://localhost:5173
```

---

# ⚡ Quick Start — Windows

From the project root:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

Then in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

---

# 🧪 Run the Complete Test Suite

From the project root:

```powershell
.\venv\Scripts\Activate.ps1
pytest -q
```

Or:

```powershell
python -m pytest -q
```

---

# 🎬 How to Run the Demo

For the safest demonstration, use:

```text
DEMO
```

Make sure:

```env
RECOVERAI_EXECUTION_ENV=DEMO
RECOVERAI_LIVE_EXECUTION=0
```

Then:

1. Start backend.
2. Start frontend.
3. Open the dashboard.
4. Confirm execution environment is `DEMO`.
5. Use the simulation controls.
6. Start the simulation.
7. Observe the event timeline.
8. Inject or trigger the deterministic failure scenario.
9. Observe merchant anomaly detection.
10. Observe incident creation.
11. Inspect root-cause diagnosis.
12. Inspect exposed revenue.
13. Inspect affected customers.
14. Inspect Decision Agent output.
15. Inspect guardrail decisions.
16. Run the recovery scenario.
17. Observe payment outcome.
18. Observe verification.
19. Observe recovered revenue.
20. Inspect analytics and feedback.

---

# 🎯 Recommended Judge Demonstration

For a short technical demonstration, show this sequence:

```text
1. Dashboard
      ↓
2. Merchant metrics
      ↓
3. Trigger UPI failure scenario
      ↓
4. Event timeline
      ↓
5. Merchant incident
      ↓
6. Root cause
      ↓
7. Revenue exposed
      ↓
8. Affected customer
      ↓
9. Decision Agent
      ↓
10. Recovery action
      ↓
11. Guardrails
      ↓
12. Execution
      ↓
13. Payment
      ↓
14. Verification
      ↓
15. Recovered revenue
      ↓
16. Analytics
```

This demonstrates the architecture rather than only the UI.

---

# 🧪 Razorpay Test Demonstration

To demonstrate the real payment integration:

## 1. Configure Razorpay Test credentials

```env
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

## 2. Start the backend

```powershell
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

## 3. Start the frontend

```powershell
cd frontend
npm run dev
```

## 4. Select

```text
RAZORPAY TEST
```

in the execution environment.

## 5. Open Razorpay Test Checkout.

The application creates the order server-side.

## 6. Trigger a test failure or success.

The Razorpay Test webhook is then sent to RecoverAI.

## 7. Observe:

```text
Razorpay event
      ↓
Webhook
      ↓
Signature verification
      ↓
RecoverAI decision
      ↓
Recovery
      ↓
Payment verification
```

---

# 🔎 What Makes RecoverAI Different?

RecoverAI is not simply:

```text
Payment Retry System
```

It is a:

```text
Merchant Incident
+
Revenue Intelligence
+
AI Decision
+
Recovery Execution
+
Payment Verification
+
Revenue Ledger
+
Feedback Loop
```

platform.

---

# 🧠 Key Design Principles

## 1. Merchant-aware recovery

Payment failures are analyzed at the merchant level.

---

## 2. Customer-aware decisions

Individual customers are evaluated within the incident context.

---

## 3. ML does not operate without constraints

The Decision Agent provides predictions and rankings.

Guardrails enforce hard limits.

---

## 4. Execution is separated from decisioning

The system distinguishes:

```text
Decision
```

from:

```text
Execution
```

This makes it possible to test decision quality independently from external side effects.

---

## 5. Provider acceptance is not recovery

Creating a payment link does not mean money was recovered.

Only verified payment success counts.

---

## 6. Simulation is safe by default

The default execution environment is:

```text
DEMO
```

with no external provider calls.

---

## 7. Production is deliberately difficult to activate

Production requires multiple independent safety conditions.

---

## 8. Actual outcomes are separated from predictions

Decision-time models should not use future recovery outcomes as features.

This prevents leakage.

---

## 9. Everything important should be auditable

Important transitions should be reconstructable.

Examples:

```text
incident detected
root cause identified
customer prioritized
decision made
guardrail evaluated
recovery started
payment attempted
payment failed/succeeded
verification completed
revenue recovered
incident resolved
```

---

# 🔐 Security & Safety Checklist

Before production execution, verify:

```text
[ ] RECOVERAI_EXECUTION_ENV=PRODUCTION
[ ] RECOVERAI_ADMIN_TOKEN configured
[ ] Production confirmation required
[ ] Razorpay LIVE credentials configured
[ ] Razorpay LIVE key starts with rzp_live_
[ ] Razorpay webhook secret configured
[ ] RECOVERAI_PRODUCTION_EXECUTION_ARMED=1
[ ] Live action allow-list configured
[ ] Maximum live amount configured
[ ] Daily live budget configured
[ ] Kill switch operational
[ ] Webhook verification operational
[ ] Idempotency verified
[ ] Bounded retries enabled
[ ] Execution timeouts enabled
[ ] Circuit breakers operational
[ ] Revenue verification operational
[ ] Recovery outcomes are not used as decision-time features
```

---

# 🚫 What RecoverAI Must Never Do

RecoverAI must never:

```text
Treat a created payment link as recovered revenue.

Treat an unverified webhook as a successful payment.

Use Razorpay TEST credentials for LIVE production execution.

Allow production execution without authorization.

Ignore the production kill switch.

Ignore amount limits.

Ignore daily budget limits.

Retry forever.

Execute the same recovery action multiple times accidentally.

Leak post-action recovery outcomes into decision-time features.

Claim an external action succeeded when the provider was unavailable.
```

---

# 📁 Repository Structure

```text
RecoverAI/
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── runtime/
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── styles.css
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.js
│
├── src/
│   ├── api/
│   │   ├── main.py
│   │   └── ...
│   │
│   ├── data/
│   │   ├── customer_generator.py
│   │   ├── event_generator.py
│   │   ├── generate_dataset.py
│   │   ├── merchant_generator.py
│   │   ├── recovery_simulator.py
│   │   └── validator.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repository.py
│   │
│   ├── decision/
│   │   ├── agent.py
│   │   ├── attribution.py
│   │   ├── b2b_chaser.py
│   │   ├── execution.py
│   │   ├── explanation.py
│   │   ├── mandate_sequencer.py
│   │   ├── promise_tracker.py
│   │   └── sequencer.py
│   │
│   ├── evaluation/
│   │   ├── baselines.py
│   │   ├── calibration.py
│   │   ├── counterfactual.py
│   │   ├── drift.py
│   │   ├── eda.py
│   │   ├── ledger.py
│   │   ├── offline_policy.py
│   │   ├── planner.py
│   │   ├── policy_lab.py
│   │   └── ...
│   │
│   ├── features/
│   ├── models/
│   ├── risk/
│   │
│   ├── incident_platform.py
│   ├── integrations.py
│   ├── intelligence.py
│   ├── merchant_simulator.py
│   └── voice.py
│
├── tests/
│
├── .env.example
├── .gitignore
├── requirements.txt
├── pytest.ini
│
├── ADVANCED_FEATURES.md
├── BUILD_STATUS.md
├── PRODUCTION_REALTIME_GUIDE.md
├── RAZORPAY_TESTING_GUIDE.md
├── SESSION_CHANGELOG.md
└── WINDOWS_QUICKSTART.md
```

---

# 📚 Additional Documentation

The README is the main entry point.

Detailed implementation documentation is also available:

### `ADVANCED_FEATURES.md`

Detailed advanced functionality.

### `BUILD_STATUS.md`

Project build/status information.

### `PRODUCTION_REALTIME_GUIDE.md`

Production and real-time execution guidance.

### `RAZORPAY_TESTING_GUIDE.md`

Detailed Razorpay Test Mode and webhook testing instructions.

### `WINDOWS_QUICKSTART.md`

Windows-specific setup instructions.

### `SESSION_CHANGELOG.md`

Development and implementation history.

---

# 🧭 Development Workflow

Recommended development workflow:

```text
1. Start in DEMO
        ↓
2. Run deterministic simulator
        ↓
3. Run automated tests
        ↓
4. Validate Decision Agent
        ↓
5. Validate guardrails
        ↓
6. Test Razorpay in SANDBOX
        ↓
7. Validate webhook verification
        ↓
8. Validate recovered revenue
        ↓
9. Review execution logs
        ↓
10. Only then consider PRODUCTION
```

---

# 🧪 Useful Commands

## Check Git status

```powershell
git status
```

## Pull latest changes

```powershell
git pull origin main
```

## Run tests

```powershell
pytest -q
```

## Run one test file

```powershell
pytest tests/test_merchant_simulator.py -v
```

## Start backend

```powershell
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

## Start frontend

```powershell
cd frontend
npm run dev
```

## Install backend dependencies

```powershell
pip install -r requirements.txt
```

## Install frontend dependencies

```powershell
cd frontend
npm install
```

---

# 🩺 Troubleshooting

## Backend says connection refused

If:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

returns:

```text
Unable to connect to the remote server
```

the backend is not running.

Start:

```powershell
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

---

## Frontend cannot reach backend

Check:

```text
Backend:
http://127.0.0.1:8000
```

and:

```text
Frontend:
http://localhost:5173
```

Make sure both terminals are running.

---

## Razorpay Test is unavailable

Check:

```env
RECOVERAI_EXECUTION_ENV=SANDBOX
```

and:

```env
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
```

Also verify:

```env
RAZORPAY_WEBHOOK_SECRET=...
```

---

## Production cannot be activated

This is intentional.

Check:

```text
RECOVERAI_ADMIN_TOKEN
RECOVERAI_EXECUTION_ENV
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
RECOVERAI_PRODUCTION_EXECUTION_ARMED
```

Production requires live credentials and explicit authorization.

---

# 🏆 Project Outcome

RecoverAI demonstrates a complete AI-driven revenue recovery architecture rather than a single ML prediction or payment API integration.

The system connects:

```text
Merchant Operations
        +
Payment Intelligence
        +
Anomaly Detection
        +
Incident Management
        +
Revenue Exposure
        +
Customer Prioritization
        +
ML Decisioning
        +
Policy
        +
Safety Guardrails
        +
Recovery Execution
        +
Razorpay
        +
Payment Verification
        +
Revenue Ledger
        +
Analytics
        +
Feedback
```

into one end-to-end platform.

---

# 🌟 The Core Story

Imagine a merchant processing thousands of transactions.

Suddenly:

```text
UPI failures spike
```

RecoverAI notices.

```text
Merchant anomaly
        ↓
Incident created
```

It diagnoses the problem.

```text
UPI / bank-side degradation
```

It calculates:

```text
₹X revenue exposed
```

It identifies the customers affected.

Then the Decision Agent evaluates:

```text
RETRY_LATER
ALTERNATIVE_PAYMENT
RECOVERY_REMINDER
HUMAN_ESCALATION
STOP
```

The system applies guardrails.

The selected recovery action executes.

The customer pays.

Razorpay sends a signed webhook.

RecoverAI verifies it.

Only then:

```text
VERIFIED_RECOVERED
```

is recorded.

The revenue ledger updates.

Analytics update.

The outcome becomes feedback.

And the merchant incident can eventually move toward:

```text
RESOLVED
```

That is the RecoverAI loop.

---

# 🔥 One-Line Summary

> **RecoverAI is an AI-powered merchant revenue recovery platform that detects payment incidents, identifies exposed revenue, intelligently chooses customer-level recovery actions, safely executes them, verifies actual payment outcomes, and measures the revenue truly recovered.**

---

# ⚠️ Security Notice

Never commit:

```text
.env
```

or any file containing:

```text
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
RECOVERAI_ADMIN_TOKEN
SMTP_PASSWORD
TWILIO_AUTH_TOKEN
RECOVERAI_EXECUTION_WEBHOOK_SECRET
```

Use:

```text
.env.example
```

as the public configuration template.

Never place real production credentials in source code, documentation, screenshots, commits, or public repositories.

---

# 📄 License

This project is currently intended as a project/demo implementation.

See the repository for the latest project status and documentation.

---

# 👨‍💻 Author

**Veeresh Devadhar**

GitHub:

https://github.com/veereshdevadhar

Project:

https://github.com/veereshdevadhar/Recoverai_new
