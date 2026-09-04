# RecoverAI — Advanced Features Addendum

This document covers the 9 features added on top of the original V3-100k baseline
(Decision Lab, Evaluation, Guardrails, Audit Log). The original README/BUILD_STATUS
describe the baseline and are unchanged; this file describes what's new.

All numbers below are computed live from the real trained model
(`data/processed/models/recoverai_v3_100k_action_models.joblib`) and the real
100K-event dataset — nothing is hardcoded or fabricated. Every new feature is
covered by `tests/test_advanced_features.py` (22 tests) in addition to the
original 12 tests in `tests/test_api.py` and `tests/test_leakage.py`.

## New backend modules

| Module | Purpose |
|---|---|
| `src/risk/risk_engine.py` | Feature 3 — Revenue-at-Risk Early Warning |
| `src/decision/sequencer.py` | Feature 2 — Adaptive Multi-Step Recovery Sequencer |
| `src/decision/explanation.py` | Feature 9 — Advanced Decision Explanation |
| `src/evaluation/counterfactual.py` | Feature 1 — Counterfactual Recovery Simulator |
| `src/evaluation/policy_lab.py` | Features 4 & 5 — Policy What-If Lab and A/B Comparison |
| `src/evaluation/drift.py` | Feature 7 — Model Monitoring / Drift Detection |
| `src/evaluation/ledger.py` | Features 6 & 8 — Outcome Feedback Loop and Revenue Recovery Ledger |

## New API endpoints

```
GET  /api/counterfactual/sample-events?n=8       Sample historical event IDs to explore
GET  /api/counterfactual/{event_id}              Full counterfactual + oracle comparison for a historical event
POST /api/sequence/run                           Run an adaptive multi-step recovery sequence to completion
GET  /api/sequence/{sequence_id}                 Fetch a previously run sequence
GET  /api/sequence-log?limit=20                  Recent sequences
POST /api/risk-score                             Revenue-at-risk score, tier, drivers, recommended preventive action
POST /api/policy/what-if                         Simulate a custom policy vs the current policy over the real eval set
POST /api/policy/compare                         A/B compare two named custom policies over the real eval set
GET  /api/policy/defaults                         Current (production) policy parameter defaults
GET  /api/ledger?limit=100                       Live session financial ledger (merged decision + execution logs)
GET  /api/feedback                                Which actions perform well/poorly, from real recorded executions
GET  /api/model-health                            Per-action AUC/AP/sample counts/prediction distribution + drift
```

`/predict` now also returns `explanation` (data-driven why-selected /
why-others-rejected) and `counterfactual` (decision advantage + per-action
alternatives) fields.

## New frontend tabs

Recovery Journey, Counterfactuals, Policy Lab, and Model Health were added to
the existing tab bar (Overview, Decision Lab, Evaluation, Guardrails, Audit
Log). The Audit Log tab additionally shows the Revenue Recovery Ledger and
Outcome Feedback panels.

## Design notes / honesty guarantees

- **Counterfactual Simulator**: for live/hypothetical events, alternative-action
  values are exactly what `/predict` already computed (no new numbers invented).
  For historical evaluation events, the oracle comparison uses real ground-truth
  simulated outcomes from `data/raw/recovery_actions.csv` (every action was
  actually simulated for every event in this dataset by design).
- **Adaptive Sequencer**: every step re-runs the real Decision Agent + real
  guardrail engine against an evolving context. Two independent stopping rules
  (`MAX_STEPS=5` hard cap, and per-action exhaustion after 2 failed attempts)
  guarantee termination — verified by `test_sequence_never_exceeds_max_steps_hard_cap`
  and `test_sequencer_rechecks_guardrails_every_step_via_exhaustion_rule`.
- **Risk Engine**: reuses the same leakage-safe `build_features` function and
  trained models as the Decision Agent — it does not read any dataset or
  outcome column directly. See `test_risk_engine_reuses_leakage_safe_feature_builder`.
- **Policy Lab / A/B**: batch-scores the real trained model once over all
  12,347 August held-out events, then applies the candidate policy's
  guardrails on top — it never retrains and never touches the production
  policy globals (`test_policy_what_if_does_not_mutate_production_defaults`).
- **Drift Detection**: real Population Stability Index + two-sample
  Kolmogorov-Smirnov test between the Jan-Jun training window and the August
  evaluation window on 4 real pre-action features.
- **Ledger / Feedback**: built entirely from `data/runtime/recoverai.db`
  and `data/runtime/recoverai.db` — i.e. only real `/predict` and
  `/execute-recovery` (including sequencer) calls that actually happened in
  the running session. Restart the backend / delete those files to reset it.

## Known scope limits (documented, not hidden)

- `retry_cooldown_hours` / `reminder_cooldown_hours` in the Policy Lab only
  affect the Adaptive Sequencer, which has a real timeline. The static
  evaluation dataset has exactly one decision point per event, so these two
  knobs are accepted for API symmetry but have no effect there — the API
  response says so explicitly via `cooldown_note`.
- The Ledger's live "oracle capture / regret" figures are computed at
  dataset scale (`/api/metrics`, shown under `dataset_summary`) rather than
  per-live-decision, since the oracle counterfactual dataset only exists for
  the historical August events.

---

# Version 2 additions: Database, Feature Attribution, UPI Mandate Sequencer

Three further upgrades were added on top of everything above.

## 1. Real database (SQLite)

Every JSONL file has been replaced by a real SQLite database at
`data/runtime/recoverai.db`, via SQLAlchemy (`src/db/`). Decisions,
executions, adaptive-recovery sequences, UPI mandate-retry sequences, and
every Policy Lab experiment (What-If / A-B) are now persisted there.

**This was verified, not just implemented**: a decision was written, the
backend process was killed, a brand-new process was started, and the
decision was still queryable — genuine durability across restarts, which
the old JSONL-append approach also technically had, but with no real query
capability. The ledger/feedback/audit endpoints now run real queries against
`src/db/repository.py` instead of re-parsing text files on every request.

Swapping to Postgres later is a one-line `DATABASE_URL` change since
everything goes through SQLAlchemy.

## 2. Real model feature attribution

Two genuinely model-grounded explanations were added (`src/decision/attribution.py`):

- **Per-decision** (`explain_instance`): for the specific event just
  scored, each feature's contribution is measured by actually re-running
  the trained pipeline with that feature reset to its population-typical
  value and observing how much the predicted probability moves — a
  real single-feature ablation, computed by calling `predict_proba` on the
  real model, not estimated. Surfaced on every `/predict` response as
  `feature_attribution`, and shown as directional bars in the Decision Lab UI.
- **Global** (`global_importance`): real `sklearn.inspection.permutation_importance`
  against real ground-truth labels (`recovery_success` from
  `data/raw/recovery_actions.csv`, joined onto the August evaluation set),
  scored on ROC-AUC. Surfaced in `/api/model-health` and shown in the Model
  Health tab.

Both were manually verified against the live model — e.g. "reached payment
page" correctly shows up as the strongest driver increasing recovery
probability, and "customer success rate" correctly decreases it when weak.

## 3. UPI Mandate Retry Sequencer

A domain-specific adaptive sequencer for e-mandate / UPI Autopay debit
failures (`src/decision/mandate_sequencer.py`), distinct from the generic
ad-hoc payment sequencer because recurring mandate debits are governed by
real RBI rules:

- **AFA threshold**: RBI requires Additional Factor Authentication for
  recurring e-mandate debits above ₹15,000 (raised from ₹5,000 in June
  2022). Above that threshold, a silent `RETRY_LATER` is guardrail-blocked
  until the customer re-authorizes — because retrying a silent debit that
  failed for lack of authentication will just fail again for the same
  reason.
- **24-hour pre-debit notice**: mandate debits run on a batch/notice cycle,
  not on demand — modeled as the minimum gap between mandate retry steps.
- **Retry-cap risk**: repeatedly failing mandate executions are a known
  industry signal that can lead a bank to flag or suspend a mandate. This
  cap (`MAX_MANDATE_RETRIES = 3`) is explicitly documented as a
  representative convention, not an exact cited regulation.

When the retry cap is reached with AFA still unresolved, the sequencer
forces a `MANDATE_REAUTH_REQUIRED` closure (escalation or a direct
re-authorization prompt) instead of a blunt `STOP` — abandoning a
legitimate subscription mandate isn't the right closure; asking for
re-authorization is.

**Verified end to end**: low-value mandates skip AFA entirely and recover
normally; high-value mandates correctly never select `RETRY_LATER` before
AFA is acknowledged; a harsh multi-failure scenario was run and correctly
triggered the forced re-authorization branch after 3 failed attempts. New
endpoints: `POST /api/mandate/run`, `GET /api/mandate/{id}`, `GET /api/mandate-log`.

New frontend: the Recovery Journey tab now has a toggle between "Ad-hoc
Payment Recovery" and "UPI Mandate Retry".

---

# Version 3 additions: B2B Receivables Chaser, Promise-to-Pay Tracker

Two further domain pathways were added on top of everything above.

## 1. B2B Receivables Chaser

A domain-specific adaptive sequencer for **overdue B2B invoices**
(`src/decision/b2b_chaser.py`), distinct from both the consumer ad-hoc
sequencer and the UPI mandate sequencer:

- **No blind retry loop.** `RETRY_LATER` is always guardrail-blocked for
  the `INVOICE_OVERDUE` pathway — there's nothing to "retry" about an
  unpaid invoice the way there is for a declined card.
- **Real dunning-tier staging by days overdue**: FRIENDLY_REMINDER (0-15
  days) → FIRM_NOTICE (16-30) → FORMAL_DUNNING (31-60) →
  COLLECTIONS_ESCALATION (60+), a representative B2B collections
  convention (documented as such, not a cited regulation).
- **Real generated dunning notices**: when `RECOVERY_REMINDER` is chosen,
  an actual notice (subject + tone + body, personalized with the invoice
  number, customer name, amount and days overdue) is generated per tier —
  not a static placeholder string.
- **Escalates to account manager, not a generic queue**: eligibility is
  based on days overdue (≥45) or invoice size (≥₹1,00,000) — the consumer
  guardrail's customer-success-rate gate is explicitly overridden here,
  since it isn't a meaningful signal for a B2B receivables relationship.

**Verified**: a low-value, recently-overdue invoice recovers in one step
via `ALTERNATIVE_PAYMENT`; a moderately overdue invoice shows real dunning
tier progression (FRIENDLY_REMINDER → FIRM_NOTICE → FORMAL_DUNNING) across
steps as days accumulate; a large, badly overdue invoice reliably escalates
to the account manager. New endpoints: `POST /api/b2b/chase`, `GET /api/b2b/chase/{id}`,
`GET /api/b2b/chase-log`. New frontend: a third toggle in the Recovery
Journey tab, "B2B Receivables Chase".

## 2. Promise-to-Pay Tracker

Tracks a customer's commitment to pay by a specific date
(`src/decision/promise_tracker.py`). There is no fake background scheduler
pretending to wait for the date — every read (`GET /api/promise/{id}` or
`GET /api/promises`) lazily re-checks the promised date against real
current time, and if it has passed while the promise is still `PENDING`,
marks it `BROKEN` and **runs a real Decision Agent escalation** (not a
canned message) before persisting the result.

**Verified end to end**: a promise with a future date correctly stays
`PENDING`; a promise created with a date in the past correctly flips to
`BROKEN` on the very next fetch, with a genuine `decision_id`/`execution_id`
attached from a real `HUMAN_ESCALATION` decision run through the actual
trained model. New endpoints: `POST /api/promise/create`,
`GET /api/promise/{id}`, `POST /api/promise/{id}/keep`, `GET /api/promises`.
New frontend: a Promise-to-Pay panel in the Audit Log tab, including a form
to record a promise and a live status list.

## Recovery Budget Optimizer

`POST /api/budget/optimize` solves a budget-constrained intervention allocation
problem over the August held-out population. Each eligible action receives an
expected net value of `P(recovery) × amount − action cost`; hard production
guardrails are applied before allocation. A Lagrangian relaxation plus a
budget-repair pass keeps the optimizer tractable for thousands of events and
returns a shadow price that indicates the marginal value of additional budget.

## Revenue Recovery Digital Twin

`POST /api/digital-twin` stress-tests the same recovery policy under controlled
volume, amount and recovery-odds multipliers, optionally with a budget cap. It
reuses the V3-100k action models and production eligibility rules and clearly
labels results as modelled scenario estimates rather than realized revenue.
