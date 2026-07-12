#!/bin/sh
set -eu
ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
fi
TOKEN_FILE=${TOKEN_FILE:-$ROOT_DIR/runtime/token}
[ -f "$TOKEN_FILE" ] || { echo "Token file not found: $TOKEN_FILE" >&2; exit 1; }
cat "$TOKEN_FILE"
