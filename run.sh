#!/usr/bin/env bash
# Uruchamia backend i otwiera przeglądarkę.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev]"
fi
.venv/bin/python -m backend.app
