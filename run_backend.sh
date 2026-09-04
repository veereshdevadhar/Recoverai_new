#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
