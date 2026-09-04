# RecoverAI — Production-Grade Execution Testing Guide

This build keeps the existing UI/design and separates execution into three environments:

- **DEMO / SIMULATION** — local-only, no external calls.
- **RAZORPAY TEST** — real Razorpay API calls using `rzp_test_*` credentials; no real money.
- **LIVE PRODUCTION** — production credentials, explicit confirmation, limits, allow-list, daily budget and kill switch.

## 1. Configure `.env`

Copy the example once:

### PowerShell
```powershell
Copy-Item .env.example .env
```

Then set your Razorpay **Test Mode** credentials:

```dotenv
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx

RECOVERAI_EXECUTION_ENV=DEMO
RECOVERAI_LIVE_EXECUTION=0

RECOVERAI_ADMIN_TOKEN=replace-with-a-long-random-local-admin-token
RECOVERAI_LIVE_KILL_SWITCH=0
RECOVERAI_MAX_LIVE_AMOUNT=10000
RECOVERAI_DAILY_LIVE_BUDGET=50000
```

Do not put live/production keys in the test configuration.

## 2. Start the backend

From `RecoverAI_Final`:

```powershell
.\venv\Scripts\Activate.ps1
python -m uvicorn src.api.main:app --reload --port 8000
```

Or use the existing launcher:

```powershell
.\run_backend.ps1
```

Check:

```text
http://127.0.0.1:8000/health
```

## 3. Start the frontend

Open a second PowerShell terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## 4. Test DEMO first

In the Execution Environment bar select:

**DEMO**

Then open **Decision Lab** and run any scenario.

Use:

**Execute Recommended Action**

Expected behavior:

- `SIMULATED_BOUNDED`
- no Razorpay request
- no email/SMS
- no real payment link
- execution appears in Audit Log

## 5. Test Razorpay TEST mode

Select:

**RAZORPAY TEST**

The environment card should show:

- `RAZORPAY TEST`
- `NO REAL MONEY`
- Razorpay: `Configured · key mode: TEST`
- External calls: `Enabled`

If the key mode says `LIVE` or `UNKNOWN`, stop and fix `.env` before executing anything.

## 6. Test a real Razorpay TEST Checkout

Open **Recovery Journey**. A new **Razorpay Test Payment** panel is provided without changing the existing Recovery Journey design.

Enter a test amount (for example `12000`) and click:

`Open Razorpay Test Checkout`

RecoverAI creates the Razorpay **Orders API** order server-side using `rzp_test_*` credentials and then opens Razorpay Standard Checkout in the browser. The Razorpay documentation requires an order to be created server-side and its `order_id` passed to Checkout. Test Mode uses a mock payment flow and does not deduct real money.

Use these Razorpay test UPI IDs:

```text
failure@razorpay   -> payment failure
success@razorpay   -> payment success
```

The test checkout is deliberately limited to `RECOVERAI_EXECUTION_ENV=SANDBOX`.

## 7. Verify the real-time `payment.failed` path

For a failure test:

1. Open the **Razorpay Test Checkout** from Recovery Journey.
2. Choose **UPI**.
3. Enter `failure@razorpay`.
4. Complete the mock failure flow.
5. Razorpay sends `payment.failed` to the configured public webhook.
6. RecoverAI verifies the Razorpay webhook HMAC signature and persists the event.
7. The same Decision Agent scores the normalized payment event.
8. The UI displays the recommended action and execution-time guardrail result.

The test panel polls the server for the signed webhook result, so the decision shown there is not a browser-only simulation.

## 8. Run the bounded TEST recovery

After `payment.failed` is received, the panel can create a **Razorpay TEST recovery payment** using the existing `ALTERNATIVE_PAYMENT` execution path.

Click:

`Create Razorpay Test Recovery Payment`

This still performs the existing execution-time guardrail check. It is operator-triggered so the Test Checkout cannot unexpectedly send a recovery message or create a second payment.

The resulting flow is:

```text
Razorpay TEST Checkout
        -> payment.failed webhook
        -> HMAC verification
        -> Decision Agent
        -> execution-time guardrails
        -> Razorpay TEST recovery payment link
        -> customer completes TEST payment
        -> payment_link.paid / payment.captured webhook
        -> verified recovery
        -> revenue_recovered updated
```

Creating the recovery payment is **not** counted as recovered revenue. The execution remains unverified until an authenticated Razorpay payment-status webhook confirms success.

To complete the recovery test, open the generated **Razorpay Test Recovery Payment** link and use:

```text
success@razorpay
```

The existing webhook reconciliation then marks the corresponding RecoverAI execution:

```text
RECOVERED
VERIFIED_PAYMENT_SUCCESS
```

A direct successful Test Checkout that is not attached to a RecoverAI recovery execution is recorded only as a verified **test payment** and is never counted as RecoverAI recovered revenue.

## 9. Webhook verification

Configure the Razorpay webhook secret in `.env`:

```dotenv
RAZORPAY_WEBHOOK_SECRET=your-webhook-secret
```

The endpoint is:

```text
POST /api/integrations/razorpay/webhook
```

RecoverAI verifies the `X-Razorpay-Signature` HMAC before accepting the event and uses the Razorpay event ID for idempotent processing.

For an externally reachable local webhook, use a secure tunnel and point the Razorpay webhook configuration at:

```text
https://YOUR_PUBLIC_HOST/api/integrations/razorpay/webhook
```

Do not expose the backend publicly without appropriate authentication/network controls.

## 10. LIVE PRODUCTION

Do **not** use Test keys for this.

The UI intentionally refuses production activation unless the backend has:

```text
RAZORPAY_KEY_ID=rzp_live_...
RAZORPAY_KEY_SECRET=...
RECOVERAI_ADMIN_TOKEN=...
```

Production additionally requires explicit confirmation, action allow-listing, per-action amount limits, a daily budget and the kill switch to be ready.

Never test LIVE production with a real customer or an amount you cannot afford to process.

## 11. Run automated tests

From `RecoverAI_Final`:

```powershell
python -m pytest -q
```

For the execution/integration changes specifically:

```powershell
python -m pytest -q tests/test_razorpay_test_execution.py tests/test_execution_environments.py tests/test_live_safety.py tests/test_voice_recovery.py
```

The Razorpay integration tests mock the provider response, so the test suite itself never spends money or makes a real provider call.

## 12. Frontend production build

```powershell
cd frontend
npm install
npm run build
```

## 13. Important safety rules

- Never put Razorpay secrets in React/Vite source code.
- Never expose `RAZORPAY_KEY_SECRET` to the browser.
- Test keys must begin with `rzp_test_`.
- Production keys must begin with `rzp_live_`.
- DEMO never contacts external providers.
- TEST uses only Razorpay Test credentials for the payment-link action.
- Provider acceptance is never counted as recovered revenue.
- Webhook/payment verification is required before marking revenue recovered.
- The integration-test action cannot bypass RecoverAI guardrails.
- A selected action is only executable if it is allowed for the current payment context.

## External recovery providers (SMTP, Twilio, orchestration webhook)

RecoverAI now keeps these providers separate from the Razorpay payment-link path:

- `RECOVERY_REMINDER` + `email` uses SMTP with TLS.
- `RECOVERY_REMINDER` + `sms` uses Twilio REST API.
- `RETRY_LATER` and `HUMAN_ESCALATION` use the configured orchestration webhook.
- Provider acceptance is never counted as recovered revenue. A verified payment/recovery callback is required.

### SANDBOX safety

Set `RECOVERAI_EXECUTION_ENV=SANDBOX`, `RECOVERAI_LIVE_EXECUTION=1`, and configure `RECOVERAI_SANDBOX_EMAIL` / `RECOVERAI_SANDBOX_PHONE` for any external test destination.

For Twilio API-only testing without sending an SMS, use `TWILIO_TEST_ACCOUNT_SID`, `TWILIO_TEST_AUTH_TOKEN`, and the documented magic sender `+15005550006`.

For outbound webhooks, configure both `RECOVERAI_EXECUTION_WEBHOOK_URL` and `RECOVERAI_EXECUTION_WEBHOOK_SECRET` (or the existing `RECOVERAI_WEBHOOK_SECRET`). RecoverAI sends an HMAC-SHA256 `X-RecoverAI-Signature` header over the exact JSON body plus an idempotent `X-RecoverAI-Delivery-Id`.

### Verification callbacks

- Razorpay: `POST /api/integrations/razorpay/webhook` with `X-Razorpay-Signature` and `RAZORPAY_WEBHOOK_SECRET`.
- Generic recovery verification: `POST /api/integrations/recovery-webhook` with `X-RecoverAI-Signature` and `RECOVERAI_WEBHOOK_SECRET`.
- Twilio delivery status: `POST /api/integrations/twilio/status` when `TWILIO_STATUS_CALLBACK_URL` is configured. Delivery status is recorded but is not treated as payment recovery.
