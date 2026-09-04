RecoverAI

RecoverAI is a revenue-recovery platform for payment failures. It observes payment events, identifies why revenue is at risk, chooses a bounded recovery action, executes it through a controlled execution layer, and verifies the outcome before counting it as recovered revenue.

The project combines a merchant/payment simulator, a decision agent, revenue-intelligence analytics, recovery execution and verification, policy/evaluation tooling, and an optional Razorpay Test Mode integration.

Core idea: a failed payment should not automatically become a blind retry. RecoverAI asks what happened, which recovery action makes sense, whether it is safe to execute, and whether the recovery actually succeeded.

1. The problem

A failed payment does not always mean permanently lost revenue.

A timeout, bank technical error, issuer decline, repeated failure, or payment-method problem can have different recovery opportunities. Blind retries can create unnecessary attempts and costs.

RecoverAI treats a failed payment as an event that needs to be:

Detected

Diagnosed

Prioritized

Recovered using a bounded action

Verified using an actual outcome signal

The result is a closed-loop recovery system rather than a simple payment-retry script.

2. How RecoverAI works

                    PAYMENT / MERCHANT EVENTS
                              |
                              v
                    +-------------------+
                    | Revenue           |
                    | Intelligence      |
                    +---------+---------+
                              |
                    anomalies / root causes
                              |
                              v
                    +-------------------+
                    | Customer /        |
                    | Revenue Ranking   |
                    +---------+---------+
                              |
                              v
                    +-------------------+
                    | Decision Agent    |
                    | diagnose + rank   |
                    | recovery actions  |
                    +---------+---------+
                              |
                              v
                    +-------------------+
                    | Guardrails /      |
                    | Execution Policy  |
                    +---------+---------+
                              |
                              v
                    +-------------------+
                    | Recovery          |
                    | Execution         |
                    +---------+---------+
                              |
                              v
                    +-------------------+
                    | Verification      |
                    | confirmed outcome |
                    +---------+---------+
                              |
                    +---------+---------+
                    |                   |
                    v                   v
              Audit / Ledger      Analytics /
              / Execution Log     Feedback

The main intelligence loop is:

DETECT -> DIAGNOSE -> PRIORITIZE -> RECOVER -> VERIFY

3. Main components

3.1 Merchant Simulator

The Merchant Simulator creates a realistic local merchant environment without contacting real customers or payment providers.

It can simulate:

customers

products

orders

checkouts

payment attempts

payment successes and failures

failure types

abandoned checkouts

recovery actions

recovery outcomes

merchant incidents

timeline events

repeated payment behavior

A typical flow is:

Customer
   |
Product / Order
   |
Checkout
   |
Payment attempt
   |
   +---- SUCCESS
   |
   +---- FAILURE
           |
           v
   RecoverAI event
           |
           v
   Decision Agent
           |
           v
   Recovery action
           |
           v
   Verification

The simulator is intentionally separate from live payment execution. It is the recommended environment for demonstrations and repeated testing.

3.2 Revenue Intelligence

Revenue Intelligence looks at payment behavior over time instead of treating every failure independently.

It provides capabilities for:

anomaly detection

failure-rate deterioration

root-cause segmentation

affected-customer discovery

revenue-at-risk calculations

merchant health

incident monitoring

blast-radius analysis

outcome analytics

audit and safety views

Recent behavior can be compared against historical baselines to identify segments whose payment reliability is deteriorating.

3.3 Decision Agent

The Decision Agent evaluates payment and customer context and ranks allowed recovery actions.

Depending on the situation, actions can include:

RETRY_LATER

ALTERNATIVE_PAYMENT

RECOVERY_REMINDER

other bounded actions supported by the current policy

The decision takes into account the available event/customer/payment context, recovery probability, expected value and policy/guardrail constraints.

RecoverAI therefore does not treat every failure as an automatic retry.

The Decision Agent also produces an explanation for the selected action so the recommendation can be inspected.

3.4 Recovery Execution

The execution layer is separate from the decision layer:

Decision
   |
   v
Is the action allowed?
   |
   v
Guardrails
   |
   v
Execute

For demonstrations, execution can use the local bounded simulator.

Production-style execution has additional controls such as explicit arming, environment checks, budgets and kill-switch/circuit-breaker controls.

3.5 Verification

RecoverAI does not assume that an attempted recovery was successful.

Verification classifies the execution using available outcome evidence.

Recovery action
      |
      v
Payment/provider outcome
      |
      v
SUCCESS CONFIRMED
      |
      v
Recovered revenue

If there is no successful payment confirmation, the result remains failed or pending rather than being counted as recovered.

A recovery attempt is not the same thing as recovered revenue.

Verified recovery is therefore kept separate from predicted or expected recovery.

3.6 Revenue Recovery Autopilot

The Autopilot runs the complete bounded revenue-intelligence cycle:

01 DETECT
     |
02 DIAGNOSE
     |
03 PRIORITIZE
     |
04 EXECUTE
     |
05 VERIFY

Autopilot is operator-triggered. It does not continuously execute customer/payment actions by itself.

In Safe Simulation mode, execution uses the local bounded simulator.

A run can report:

detected anomalies

deteriorating root-cause segments

affected customers

selected recovery actions

execution results

verified recoveries

revenue exposed

revenue recovered

intervention cost

net recovery

recovery rate

recovery ROI

merchant health

Customer discovery and execution are bounded so a single run cannot turn into uncontrolled bulk execution.

4. Merchant Simulator vs Razorpay integration

These are separate parts of the project.

Merchant Simulator

Local synthetic merchant
        |
        v
Synthetic payment events
        |
        v
RecoverAI
        |
        v
Bounded simulated recovery

Use it for:

demos

repeated experiments

failure scenarios

Autopilot

revenue-intelligence testing

safe recovery evaluation

No real customer or payment provider is contacted.

Razorpay Test Mode

Razorpay Test Mode
        |
        v
Test payment / webhook
        |
        v
RecoverAI integration
        |
        v
Verification / recovery flow

Use this to demonstrate integration with an actual payment platform in a sandbox/test environment.

Use Razorpay Test Mode credentials for this workflow.

Production

Production is a separate deployment boundary:

Live credentials
      +
Explicit production authorization
      +
Production guardrails
      +
Live provider integration

Do not use live credentials for the local simulator or normal demo testing.

5. Project structure

RecoverAI/
|
+-- src/
|   +-- api/
|   |   +-- main.py
|   |
|   +-- data/
|   |   +-- customer_generator.py
|   |   +-- event_generator.py
|   |   +-- merchant_generator.py
|   |   +-- recovery_simulator.py
|   |   +-- validator.py
|   |
|   +-- db/
|   |   +-- database.py
|   |   +-- models.py
|   |   +-- repository.py
|   |
|   +-- decision/
|   |   +-- agent.py
|   |   +-- attribution.py
|   |   +-- b2b_chaser.py
|   |   +-- execution.py
|   |   +-- explanation.py
|   |   +-- mandate_sequencer.py
|   |   +-- promise_tracker.py
|   |   +-- sequencer.py
|   |
|   +-- evaluation/
|       +-- baselines.py
|       +-- calibration.py
|       +-- counterfactual.py
|       +-- drift.py
|       +-- eda.py
|       +-- ledger.py
|       +-- offline_policy.py
|       +-- planner.py
|       +-- policy_lab.py
|       +-- policy_* files
|
+-- frontend/
|   +-- src/
|   |   +-- App.jsx
|   |   +-- main.jsx
|   |   +-- styles.css
|   +-- package.json
|   +-- vite.config.js
|
+-- data/
|   +-- raw/
|   +-- processed/
|   +-- runtime/
|
+-- tests/
|
+-- requirements.txt
+-- .env.example
+-- .gitignore
+-- run_backend.ps1
+-- run_frontend.ps1
+-- run_tests.ps1
+-- run_backend.sh
+-- run_frontend.sh
+-- run_tests.sh
+-- README.md

6. Prerequisites

Install:

Python 3.10+ recommended

Node.js and npm

Git

A modern browser

For Razorpay Test Mode, you also need the appropriate Razorpay test credentials.

For public webhook testing from a local machine, a tunneling solution such as zrok can be used.

7. Environment configuration

Create the environment file from the example:

Copy-Item .env.example .env

Open .env and configure the values required for the features you want to test.

These may include:

Razorpay Test credentials

application settings

execution environment

production safety settings

webhook configuration

Important

Never commit .env to Git.

The repository .gitignore excludes:

.env
venv/
.venv/
__pycache__/
.pytest_cache/
node_modules/
dist/
runtime databases

Use .env.example to document configuration without exposing secrets.

8. Start the backend

Open PowerShell in the project directory.

Create and activate the virtual environment if necessary:

python -m venv venv
.env\Scripts\Activate.ps1

Install dependencies:

pip install -r requirements.txt

Start the API:

.
un_backend.ps1

Alternatively:

uvicorn src.api.main:app --host 0.0.0.0 --port 8000

The backend runs on:

http://127.0.0.1:8000

Health check:

Invoke-RestMethod http://127.0.0.1:8000/health

9. Start the frontend

Open a second PowerShell window in:

RecoverAI/frontend

Install dependencies on the first run:

npm install

Start the frontend:

npm run dev

Open the URL printed by Vite, normally:

http://localhost:5173

Keep both the backend and frontend running while using the application.

10. Quick test

With the backend running:

Invoke-RestMethod http://127.0.0.1:8000/health

A successful response confirms that the API is reachable.

The FastAPI application also exposes its API documentation when enabled by the application.

11. Testing the Merchant Simulator

The Merchant Simulator is the recommended first end-to-end test because it does not require external payment credentials.

In the RecoverAI frontend:

Reset the simulation.

Run/create payment activity.

Inspect the order.

Inspect the payment attempt.

Generate or force a failure scenario.

Check the Live Event Timeline.

Confirm that RecoverAI received the failure event.

Inspect the Decision Agent recommendation.

Execute the available recovery action.

Verify the resulting state.

A failed payment should produce an event chain similar to:

Order created
     |
Checkout started
     |
Payment attempted
     |
Payment failed
     |
RecoverAI event received
     |
Recovery decision
     |
Recovery action
     |
Verification

A successful recovery should ultimately show a confirmed successful payment, not merely an attempted recovery.

The important test is therefore the complete:

event -> intelligence -> decision -> execution -> verification

chain.

12. Testing Revenue Recovery Autopilot

Use simulated merchant/payment activity.

Recommended test:

1. Reset the merchant simulation.
2. Generate or run the relevant payment/failure scenario.
3. Confirm events appear in the Live Event Timeline.
4. Open Revenue Recovery Autopilot.
5. Click "Run Autopilot".
6. Inspect DETECT.
7. Inspect DIAGNOSE.
8. Inspect PRIORITIZE.
9. Inspect EXECUTE.
10. Inspect VERIFY.
11. Review recovery outcome analytics.

A useful run should make the reasoning visible:

Observed deterioration
        |
Affected segment
        |
Affected customers
        |
Recovery ranking
        |
Bounded execution
        |
Verified outcome

13. Testing Razorpay Test Mode

Razorpay testing should be performed with Test Mode credentials.

Important endpoint groups include:

/api/razorpay/test/order
/api/razorpay/test/order/{order_id}

/api/integrations/razorpay/webhook
/api/integrations/recovery-webhook

/api/integrations/status
/api/production/status
/api/production/arm

The detailed request payloads and test sequence are documented in:

RAZORPAY_TESTING_GUIDE.md
PRODUCTION_REALTIME_GUIDE.md

Use those guides together with the current API implementation rather than guessing request payloads.

14. Local webhook testing with zrok

If Razorpay needs to reach a local webhook endpoint, start the backend first.

Open PowerShell in the directory containing the downloaded zrok2 executable:

.\zrok2 version
.\zrok2 status

Then expose the local backend:

.\zrok2 share public http://127.0.0.1:8000

zrok will provide a public HTTPS address.

If the generated address is:

https://YOUR-ZROK-SUBDOMAIN.shares.zrok.io

the webhook URL must use the actual RecoverAI webhook route, for example:

https://YOUR-ZROK-SUBDOMAIN.shares.zrok.io/api/integrations/razorpay/webhook

Do not assume that the root URL or /health is the webhook endpoint.

If a public URL returns 404, check:

the backend is running,

PowerShell is using the correct project/backend,

the requested path exists,

zrok is forwarding to port 8000,

the correct webhook route is being used.

15. Important API routes

The backend exposes a broad API surface.

Core

GET  /health
GET  /api/metrics
GET  /api/analysis
GET  /api/model-card
GET  /api/guardrails
GET  /api/audit-log
GET  /api/decision-agent
POST /predict
POST /execute-recovery
POST /execute-decision
GET  /api/execution-log

Merchant Simulator

GET  /api/merchant-sim/dashboard
POST /api/merchant-sim/reset
GET  /api/merchant-sim/customers
GET  /api/merchant-sim/customers/{customer_id}
GET  /api/merchant-sim/products
GET  /api/merchant-sim/orders
GET  /api/merchant-sim/orders/{order_id}
GET  /api/merchant-sim/timeline
POST /api/merchant-sim/purchase
POST /api/merchant-sim/abandon
POST /api/merchant-sim/resubmit-event
POST /api/merchant-sim/incident
GET  /api/merchant-sim/incidents
POST /api/merchant-sim/tick
POST /api/merchant-sim/scenario/upi-failure-recovery

Revenue Intelligence

GET  /api/revenue-intelligence/merchant-incidents
GET  /api/revenue-intelligence/incidents/{incident_id}/blast-radius
GET  /api/revenue-intelligence/incidents/{incident_id}/cohorts
GET  /api/revenue-intelligence/incidents/{incident_id}/analytics
GET  /api/revenue-intelligence/outcome-analytics
POST /api/revenue-intelligence/incidents/{incident_id}/monitor
GET  /api/revenue-intelligence/health
GET  /api/revenue-intelligence/feedback-analytics
GET  /api/revenue-intelligence/audit
POST /api/revenue-intelligence/demo
GET  /api/revenue-intelligence/safety-audit
GET  /api/revenue-intelligence/scan
POST /api/revenue-intelligence/autopilot
GET  /api/revenue-intelligence/anomalies
GET  /api/revenue-intelligence/root-causes
GET  /api/revenue-intelligence/customers

Recovery and policy

GET  /api/counterfactual/sample-events
GET  /api/counterfactual/{event_id}

POST /api/sequence/run
GET  /api/sequence/{sequence_id}
GET  /api/sequence-log

POST /api/mandate/run
GET  /api/mandate/{mandate_sequence_id}
GET  /api/mandate-log

POST /api/b2b/chase
GET  /api/b2b/chase/{chase_id}
GET  /api/b2b/chase-log

POST /api/promise/create
GET  /api/promise/{promise_id}
POST /api/promise/{promise_id}/keep
GET  /api/promises

POST /api/risk-score
POST /api/policy/what-if
POST /api/policy/compare
GET  /api/policy/experiments
GET  /api/policy/defaults

Integrations and production controls

GET  /api/integrations/status
POST /api/integrations/environment
POST /api/integrations/execute
POST /api/integrations/circuit-breaker/reset
POST /api/integrations/kill-switch
GET  /api/integrations/events

POST /api/razorpay/test/order
GET  /api/razorpay/test/order/{order_id}

GET  /api/production/status
POST /api/production/arm

POST /api/integrations/razorpay/webhook
POST /api/integrations/recovery-webhook
POST /api/integrations/twilio/status

The definitive implementation is in:

src/api/main.py

16. Automated tests

Activate the virtual environment and run:

pytest

or:

.
un_tests.ps1

Run the test suite after significant changes to the backend or recovery logic.

17. Safety and execution boundaries

RecoverAI intentionally separates intelligence from execution:

Detection
   |
Diagnosis
   |
Decision
   |
Guardrails
   |
Execution
   |
Verification

The system should never claim that money was recovered merely because a recovery action was attempted.

Important controls include:

Safe Simulation mode

bounded recovery execution

explicit production arming

execution budgets

circuit breaker

kill switch

audit logging

environment checks

verification before recovered-revenue attribution

For normal development and judging, use the Merchant Simulator or Razorpay Test Mode.

18. Data and models

The repository contains generated and processed data used by the evaluation and intelligence layers:

data/raw/
data/processed/
data/runtime/

Processed artifacts include datasets, evaluation outputs, policy results and trained model artifacts used by the project.

Runtime databases and local environment files should remain outside source control according to .gitignore.

19. Evaluation and policy tooling

RecoverAI also includes an evaluation layer for studying recovery policies rather than treating the Decision Agent as an unexplained black box.

It contains tooling for:

baselines

calibration

counterfactual analysis

drift

EDA

policy evaluation

policy comparison

policy planning

regret analysis

action scoring

ledger analysis

This makes it possible to compare recovery strategies and inspect their outcomes.

20. Recommended first-time demo

If you are evaluating RecoverAI for the first time, use this order:

Step 1 — Start the backend

.
un_backend.ps1

Step 2 — Verify the backend

Invoke-RestMethod http://127.0.0.1:8000/health

Step 3 — Start the frontend

cd frontend
npm install
npm run dev

Step 4 — Open RecoverAI

Use the URL displayed by Vite.

Step 5 — Test the Merchant Simulator

Reset the simulation and create/run payment activity.

Step 6 — Create a failure

Generate a payment failure and inspect the Live Event Timeline.

Step 7 — Inspect the decision

Check the diagnosis, selected action, confidence and explanation.

Step 8 — Execute and verify

Run the bounded recovery action and confirm whether the payment actually succeeds.

Step 9 — Run Revenue Recovery Autopilot

Trigger Autopilot and inspect:

DETECT
DIAGNOSE
PRIORITIZE
EXECUTE
VERIFY

Step 10 — Test Razorpay Test Mode

Only after the local simulator flow is working, configure the Razorpay Test Mode integration.

21. What makes RecoverAI different

RecoverAI is not simply:

payment failed -> retry

It is designed as:

payment failure
      |
      v
understand the failure
      |
      v
identify affected revenue
      |
      v
rank recovery opportunities
      |
      v
choose an appropriate action
      |
      v
apply execution guardrails
      |
      v
execute in a bounded environment
      |
      v
verify the actual outcome
      |
      v
record the result
      |
      v
evaluate recovery performance

This makes the project demonstrate both the decision-making problem and the operational execution problem.

22. Documentation

Additional documentation in the repository includes:

ADVANCED_FEATURES.md
BUILD_STATUS.md
PRODUCTION_REALTIME_GUIDE.md
RAZORPAY_TESTING_GUIDE.md
SESSION_CHANGELOG.md
WINDOWS_QUICKSTART.md

Use this README for the overall system. Use the individual guides for feature-specific procedures.

23. Troubleshooting

git status says "not a git repository"

Make sure PowerShell is inside the project directory containing .git:

cd "C:\path\to\RecoverAI"
git status

zrok is not recognized

If zrok is not on PATH, run it from the directory containing the executable:

.\zrok2 version

Then:

.\zrok2 share public http://127.0.0.1:8000

Backend connection refused

Check that the backend terminal is still running.

Then:

Invoke-RestMethod http://127.0.0.1:8000/health

A route returns 404

Check the actual route in:

src/api/main.py

Do not assume every public tunnel URL maps directly to every endpoint.

Frontend cannot reach the backend

Check:

backend is running on port 8000

frontend is running

API configuration is correct

browser network/console errors for the failing request

Secrets are exposed

Stop using the exposed credential, rotate it, remove it from the repository/history as appropriate, and ensure .env remains ignored.

24. Development principles

The project is intentionally built around three boundaries:

Intelligence != Execution
Prediction  != Verification
Simulation  != Production

These boundaries are central to the architecture.

The Merchant Simulator makes it possible to test the complete recovery loop safely, while the Razorpay integration demonstrates how the same architecture can connect to a real payment platform in Test Mode.

RecoverAI in one sentence

RecoverAI turns payment failures into explainable, bounded and verifiable revenue-recovery decisions instead of blindly retrying failed payments.
