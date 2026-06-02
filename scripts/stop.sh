#!/usr/bin/env sh
set -eu
ROOT=${ROOT:-$(pwd)}
PID_FILE=${PID_FILE:-$ROOT/tunnel.pid}
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  kill "$(cat "$PID_FILE")" || true
  sleep 2
  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then kill -9 "$(cat "$PID_FILE")" || true; fi
  echo "stopped pid=$(cat "$PID_FILE")"
else
  echo "not-running"
fi
rm -f "$PID_FILE"
