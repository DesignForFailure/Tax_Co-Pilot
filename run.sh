#!/usr/bin/env bash
# Tax Copilot — Run the application
set -e

cd "$(dirname "$0")"

echo "⚡ Tax Copilot — Starting..."
echo "   URL: http://127.0.0.1:8000"
echo ""

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
