#!/usr/bin/env bash
# One-step launcher for Mac / Linux: sets itself up the first time, then opens the app.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  echo "First run: installing (about a minute)..."
  python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt || exit 1
else
  . .venv/bin/activate
fi
streamlit run app.py
