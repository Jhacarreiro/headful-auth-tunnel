#!/usr/bin/env sh
set -eu
ROOT=${ROOT:-$(pwd)}
PORT=${PORT:-19192}
TOKEN_FILE=${TOKEN_FILE:-$ROOT/.token}
PROFILE_DIR=${PROFILE_DIR:-$ROOT/profile}
OUT_DIR=${OUT_DIR:-$ROOT}
LOG_FILE=${LOG_FILE:-$ROOT/tunnel.log}
PID_FILE=${PID_FILE:-$ROOT/tunnel.pid}
DISPLAY=${DISPLAY:-:99}
mkdir -p "$PROFILE_DIR" "$OUT_DIR"
if [ ! -f "$TOKEN_FILE" ]; then
  python3 - <<'PY2' > "$TOKEN_FILE"
import secrets
print(secrets.token_hex(16))
PY2
  chmod 600 "$TOKEN_FILE"
fi
if command -v Xvfb >/dev/null 2>&1; then
  if ! pgrep -f "Xvfb $DISPLAY" >/dev/null 2>&1; then
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
    nohup Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH:-1440}x${SCREEN_HEIGHT:-1100}x24" -nolisten tcp > "$OUT_DIR/xvfb.log" 2>&1 &
    echo $! > "$OUT_DIR/xvfb.pid"
    sleep 1
  fi
fi
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "already-running pid=$(cat "$PID_FILE")"
else
  TOKEN=$(cat "$TOKEN_FILE") DISPLAY="$DISPLAY" PROFILE_DIR="$PROFILE_DIR" OUT_DIR="$OUT_DIR" PORT="$PORT" nohup python3 -m headful_auth_tunnel.server > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 3
fi
TOKEN=$(cat "$TOKEN_FILE")
SCHEME=http
if [ -n "${TLS_CERT:-}" ] && [ -n "${TLS_KEY:-}" ]; then SCHEME=https; fi
echo "pid=$(cat "$PID_FILE")"
echo "url=$SCHEME://<host>:$PORT/?token=$TOKEN"
tail -40 "$LOG_FILE"
