#!/bin/sh
set -eu
ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
fi
DISPLAY=${DISPLAY:-:99}
SCREEN_WIDTH=${SCREEN_WIDTH:-1440}
SCREEN_HEIGHT=${SCREEN_HEIGHT:-1100}
export DISPLAY SCREEN_WIDTH SCREEN_HEIGHT

RUNTIME_DIR=${RUNTIME_DIR:-$ROOT_DIR/runtime}
PID_FILE=${PID_FILE:-$RUNTIME_DIR/tunnel.pid}
XVFB_PID_FILE=${XVFB_PID_FILE:-$RUNTIME_DIR/xvfb.pid}
mkdir -p "$RUNTIME_DIR"

process_is_running() {
  pid=$1
  kill -0 "$pid" 2>/dev/null || return 1
  if [ -r "/proc/$pid/stat" ] && grep -F ') Z ' "/proc/$pid/stat" >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

terminate_child() {
  pid=$1
  [ -z "$pid" ] && return 0
  kill "$pid" 2>/dev/null || true
  i=0
  while process_is_running "$pid" && [ "$i" -lt 120 ]; do
    sleep 0.25
    i=$((i + 1))
  done
  if process_is_running "$pid"; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

xvfb_pid=""
app_pid=""
cleanup_done=0
cleanup() {
  [ "$cleanup_done" -eq 0 ] || return 0
  cleanup_done=1
  [ -z "$app_pid" ] || terminate_child "$app_pid"
  [ -z "$xvfb_pid" ] || terminate_child "$xvfb_pid"
  rm -f "$PID_FILE" "$XVFB_PID_FILE"
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24" -nolisten tcp -ac &
xvfb_pid=$!
printf '%s\n' "$xvfb_pid" > "$XVFB_PID_FILE"
sleep 1

if [ "$#" -gt 0 ]; then
  "$@" &
elif command -v headful-auth-tunnel >/dev/null 2>&1; then
  headful-auth-tunnel &
else
  python3 -m headful_auth_tunnel.server &
fi
app_pid=$!
printf '%s\n' "$app_pid" > "$PID_FILE"
wait "$app_pid"
