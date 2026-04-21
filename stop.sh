#!/usr/bin/env bash
# Stop DJ MetaManager: PID from start.sh, then anything still listening on port 5123.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ -f .dj-meta-manager.pid ]; then
  PID="$(cat .dj-meta-manager.pid)"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    sleep 0.5
  fi
  rm -f .dj-meta-manager.pid
elif [ -f .dj-metamanager.pid ]; then
  PID="$(cat .dj-metamanager.pid)"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    sleep 0.5
  fi
  rm -f .dj-metamanager.pid
elif [ -f .dj-flac-tagger.pid ]; then
  PID="$(cat .dj-flac-tagger.pid)"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    sleep 0.5
  fi
  rm -f .dj-flac-tagger.pid
fi

# Flask debug mode may leave a child or a stale listener; clear port 5123.
for p in $(lsof -tiTCP:5123 -sTCP:LISTEN 2>/dev/null || true); do
  kill "$p" 2>/dev/null || true
done

sleep 0.3
if lsof -tiTCP:5123 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 5123 still in use; trying kill -9 on listener PIDs."
  for p in $(lsof -tiTCP:5123 -sTCP:LISTEN 2>/dev/null || true); do
    kill -9 "$p" 2>/dev/null || true
  done
fi

echo "DJ MetaManager stopped (port 5123 should be free)."
