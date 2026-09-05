#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
fi

choose_runtime_dir() {
  if [ -n "${RUNTIME_DIR:-}" ]; then
    printf '%s\n' "$RUNTIME_DIR"
    return
  fi
  for candidate in "$ROOT_DIR/runtime" /run/headful-auth-tunnel /var/lib/headful-auth-tunnel; do
    if [ -f "$candidate/tunnel.pid" ] || [ -f "$candidate/xvfb.pid" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '%s\n' "$ROOT_DIR/runtime"
}

RUNTIME_DIR=$(choose_runtime_dir)
PID_FILE=${PID_FILE:-$RUNTIME_DIR/tunnel.pid}
XVFB_PID_FILE=${XVFB_PID_FILE:-$RUNTIME_DIR/xvfb.pid}

process_is_running() {
  pid=$1
  kill -0 "$pid" 2>/dev/null || return 1
  if [ -r "/proc/$pid/stat" ] && grep -F ') Z ' "/proc/$pid/stat" >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

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
  kill "$pid" 2>/dev/null || true
  i=0
  while process_is_running "$pid" && [ "$i" -lt 40 ]; do
    sleep 0.25
    i=$((i + 1))
  done
  if process_is_running "$pid"; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
  echo "Stopped $label (pid $pid)"
}

status=0
stop_owned_process "$PID_FILE" "headful" "Headful Auth Tunnel" || status=1
stop_owned_process "$XVFB_PID_FILE" "Xvfb" "Xvfb" || status=1
exit "$status"
