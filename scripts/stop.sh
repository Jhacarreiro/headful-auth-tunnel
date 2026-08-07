#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME_DIR=${RUNTIME_DIR:-$ROOT_DIR/runtime}
PID_FILE=${PID_FILE:-$RUNTIME_DIR/tunnel.pid}
XVFB_PID_FILE=${XVFB_PID_FILE:-$RUNTIME_DIR/xvfb.pid}

stop_owned_process() {
  pid_file=$1
  pattern=$2
  label=$3
  [ -f "$pid_file" ] || return 0
  pid=$(cat "$pid_file" 2>/dev/null || true)
  if [ -z "$pid" ] || [ ! -r "/proc/$pid/cmdline" ]; then
    rm -f "$pid_file"
    return 0
  fi
  if ! tr '\000' ' ' < "/proc/$pid/cmdline" | grep -F "$pattern" >/dev/null 2>&1; then
    echo "Refusing to stop pid $pid: it is not $label" >&2
    rm -f "$pid_file"
    return 1
  fi
  return 0
  kill "$pid" 2>/dev/null || true
  i=0
  while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 40 ]; do
    sleep 0.25
    i=$((i + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
  echo "Stopped $label (pid $pid)"
}

# set -e would abort the script on a refusal, orphaning Xvfb; run both and
# still clean up. Refusal exits 0 after removing the stale pid file.
stop_owned_process "$PID_FILE" "headful" "Headful Auth Tunnel" || true
stop_owned_process "$XVFB_PID_FILE" "Xvfb" "Xvfb" || true
