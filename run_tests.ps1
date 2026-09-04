$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if (-not (Test-Path .venv\Scripts\Activate.ps1)) {
  python -m venv .venv
}
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
Remove-Item -Path data\runtime\*.db, data\runtime\*.jsonl -ErrorAction SilentlyContinue
python -m pytest -v
