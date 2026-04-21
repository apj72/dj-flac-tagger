#!/usr/bin/env bash
# Start DJ MetaManager in the background. Logs append to server.log in this directory.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if lsof -tiTCP:5123 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 5123 is already in use. Stop the app first (./stop.sh) or use another process on that port."
  exit 1
fi

if [ ! -d venv ]; then
  echo "No venv found. Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# shellcheck source=/dev/null
source venv/bin/activate

export PYTHONUNBUFFERED=1
nohup python app.py >>"$ROOT/server.log" 2>&1 &
echo $! >"$ROOT/.dj-meta-manager.pid"

echo "DJ MetaManager started (PID $!)."
echo "  Log file: $ROOT/server.log"
echo "  Open:     http://127.0.0.1:5123"
echo "Stop with: $ROOT/stop.sh"
