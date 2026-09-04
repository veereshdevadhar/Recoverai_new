$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if (-not (Test-Path .venv\Scripts\Activate.ps1)) {
  python -m venv .venv
}
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
