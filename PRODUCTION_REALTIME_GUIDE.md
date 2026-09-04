# RecoverAI — Real-Time Production Path

RecoverAI keeps the existing NovaCart synthetic demo and adds an isolated production event path.

## Environments
- DEMO: local synthetic/NovaCart bounded simulation; no external provider calls.
- SANDBOX: Razorpay Test credentials and test destinations.
- PRODUCTION: an authorized merchant, Razorpay Live credentials, verified Razorpay webhooks, and explicit production arming.

## Real-time flow
`payment.failed` → verified webhook → idempotency → normalized `PaymentEvent` → existing Decision Agent → existing guardrails → production execution adapter → provider result → verified payment event → real recovery ledger.

`payment_link.paid` and `payment.captured` continue to verify recovery for RecoverAI-created payment links.

## Production safety
Production execution requires:
- `RECOVERAI_EXECUTION_ENV=PRODUCTION`
- `RECOVERAI_LIVE_EXECUTION=1`
- `RECOVERAI_PRODUCTION_EXECUTION_ARMED=1`
- Razorpay `rzp_live_*` credentials
- `RAZORPAY_WEBHOOK_SECRET`
- admin authorization and explicit live confirmation
- amount/daily-budget limits
- action allow-list
- kill switch/circuit breakers
- idempotency

The distributed `.env` is DEMO and disarmed. Put real secrets only in your local untracked `.env`.

## Important revenue semantics
A provider response such as accepted SMS, Payment Link creation, or orchestration acceptance is not recovered revenue. Real revenue is recorded only after an authenticated payment-status event verifies successful payment. Demo/simulated recovery remains separate from production revenue.

## Production arming
Use the existing environment control to select PRODUCTION, then call `POST /api/production/arm` with the server-side admin token and explicit confirmation. The endpoint refuses to arm unless Razorpay LIVE credentials and the webhook secret are configured.

## Local validation
```bash
pip install -r requirements.txt
python -m pytest -q
cd frontend
npm install
npm run build
```

Production use requires a properly onboarded/authorized merchant and appropriate provider configuration. Do not test with arbitrary customers or real money without authorization.
