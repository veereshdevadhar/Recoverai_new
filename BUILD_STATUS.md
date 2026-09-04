# RecoverAI Build Status

## Current build

**RecoverAI V4 — Revenue Recovery Autopilot**

The existing V3-100K ML decision pipeline remains intact. The latest build adds a real Revenue Detective / root-cause / affected-customer intelligence layer and opt-in external execution adapters with circuit-breaker protection, while preserving safe local simulation by default.

### Verified

- Python source compiles successfully.
- Revenue intelligence API smoke-tested: health, metrics, anomaly scan, root-cause scan, affected-customer discovery and integration status.
- New Revenue Autopilot tests: 6/6 passed.
- Existing test files were run individually: `test_api.py` 11/11, `test_leakage.py` 1/1, `test_planner.py` 5/5, `test_advanced_features.py` 22/22, `test_advanced_v2.py` 15/15, `test_advanced_v3.py` 12/12.
- Full-suite collection currently contains 72 tests. In the build environment a single combined run exceeded the available execution window despite the individual files passing; this is documented rather than hidden.
- Frontend dependencies are not bundled in the ZIP, so a frontend production build must be run on the user's machine with `npm install && npm run build`.

### Live integrations

No credentials are bundled. Safe simulation is the default. Real Razorpay/SMTP/Twilio/webhook execution is opt-in through environment variables documented in `README.md`.

## Production hardening pass — 2026-08-30

Implemented fixes for the previously misleading/incomplete product flows:

- Added an executable held-out Evaluation runner and UI **Run Evaluation** action.
- Removed misleading static Policy Lab cooldown controls; timing belongs to the real-time sequencer.
- Made Policy Lab `high_value_threshold` an actual candidate-policy guardrail for human escalation.
- Added explicit live-execution confirmation and disabled LIVE mode unless backend live execution is enabled.
- Added action-specific live provider validation and clear provider capability reporting.
- Fixed LIVE `RETRY_LATER` and LIVE `HUMAN_ESCALATION` so they actually use the configured orchestration webhook instead of silently behaving like simulation.
- Added authenticated HMAC recovery verification webhook; provider acceptance is not counted as revenue until verified.
- Clarified that email/phone are optional at decision time but required when the chosen live channel needs customer contact.
- Reframed Budget Optimizer and Digital Twin as explicit planning/scenario tools rather than implying realized business outcomes.
- Added a real **Run Autopilot Cycle** control; autopilot analysis remains separate from customer-facing execution.

Targeted regression/hardening suite: 15 tests passed. Existing API/advanced/autopilot suite: 39 tests passed after the changes.

### Phase 4-8 merchant incident control plane
- Phase 4: merchant-aware Autopilot orchestration completed.
- Phase 5: recovery outcome analytics completed.
- Phase 6: persistent feedback/evaluation loop completed; no automatic retraining.
- Phase 7: deterministic end-to-end demo mode completed.
- Phase 8: production/safety audit endpoint and regression checks completed.
- Validation: 117 tests passed across the complete test suite in individual/batched runs.
