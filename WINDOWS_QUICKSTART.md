# RecoverAI — Windows quickstart (PowerShell)

Two terminals: one for the backend (FastAPI, port 8000), one for the
frontend (Vite, port 5173). Run both from the project root
(`RecoverAI_Final\`).

## 0. One-time prerequisites
- Python 3.11+ on PATH (`python --version`)
- Node.js 18+ on PATH (`node --version`)
- If PowerShell blocks the `.ps1` scripts, run once as your normal user:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

## 1. Backend — Terminal 1
```powershell
cd path\to\RecoverAI_Final
.\run_backend.ps1
```
This creates a `.venv`, installs `requirements.txt`, and starts the API at
`http://127.0.0.1:8000`. First run installs packages, so it takes a minute.
Leave this terminal open.

Confirm it's up (in a third terminal, or your browser):
```powershell
curl http://127.0.0.1:8000/health
```

## 2. Frontend — Terminal 2
```powershell
cd path\to\RecoverAI_Final\frontend
npm install
npm run dev
```
Or use the helper script from the project root instead of the two lines
above:
```powershell
cd path\to\RecoverAI_Final
.\run_frontend.ps1
```
Open **http://localhost:5173** in your browser.

## 3. Run the backend test suite
```powershell
cd path\to\RecoverAI_Final
.\run_tests.ps1
```
Expect `108 passed`. This also clears the local `data\runtime\*.db` /
`*.jsonl` runtime state before running, so it won't pick up leftover data
from manual testing.

## 4. Configure Razorpay TEST mode (optional, for the Payment Link demo)
```powershell
cd path\to\RecoverAI_Final
Copy-Item .env.example .env
notepad .env
```
In `.env`, set:
```
RECOVERAI_EXECUTION_ENV=SANDBOX
RECOVERAI_LIVE_EXECUTION=1
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_test_secret
```
Save, then restart the backend (`Ctrl+C` in Terminal 1, run
`.\run_backend.ps1` again). In the UI, switch the environment badge to
**RAZORPAY TEST**. Do **not** put live (`rzp_live_...`) keys in for a demo —
the code checks the key prefix against the environment and will refuse a
mismatch, but there's no reason to have live keys on a laptop you're demoing
from.

## 5. Where things are in the UI
- **Decision Lab** — single-event decision + execution, including the new
  Hinglish voice-recovery preview (needs a Chromium/Edge/Firefox browser
  with speech-synthesis support — all modern desktop browsers qualify).
- **Merchant Simulator** — the new NovaCart merchant demo. Click
  **"Run scenario: UPI failure → recovery"** for the deterministic,
  reproducible walkthrough, or **Start simulation** for continuous
  synthetic activity. **Inject Failure** chips simulate an incident
  (e.g. UPI provider degradation) and measurably change the simulated
  failure rate — this never touches LIVE execution, by construction.
- **Revenue Autopilot** — Detect → Diagnose → Prioritize pipeline; click
  **Run Autopilot Cycle**.

## 6. Common issues
- **"Backend is not reachable"** in the UI → Terminal 1 isn't running, or
  something else is using port 8000. Check `curl http://127.0.0.1:8000/health`.
- **Blank/white screen with a console error** → hard-refresh
  (`Ctrl+Shift+R`); if it persists, stop the frontend, delete
  `frontend\node_modules`, and re-run `npm install`.
- **PowerShell won't run the `.ps1` files** → see the execution-policy
  command in step 0.
