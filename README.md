# headful-auth-tunnel

A small LAN/VPN-only remote-control tunnel for **human-operated, headful Scrapling browser sessions** with persistent profiles.

Use it when automation runs on a headless server, but a person needs to manually authenticate a persistent browser profile once and reuse that profile later for permitted automation.

## Features

- Headful Scrapling `StealthySession`.
- Persistent browser profile directory.
- Screenshot stream in a simple browser UI.
- Remote click, type, key, paste, clear-field, back and URL navigation controls.
- URL token authentication.
- Optional direct HTTPS with a local/self-signed certificate.
- Intended for LAN/VPN, not public internet exposure.

## Not intended for bypassing protections

This project is for human-operated manual authentication on accounts and systems you are allowed to use. It is not intended to bypass CAPTCHAs, anti-bot protections, access controls, paywalls or rate limits.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install scrapling
```

On headless Linux, install `Xvfb`:

```bash
sudo apt-get update
sudo apt-get install -y xvfb
```

## Quick start

```bash
PROFILE_DIR=$PWD/profiles/example \
BASE_URL=https://example.com \
BIND_HOST=127.0.0.1 \
PORT=19192 \
TOKEN_FILE=$PWD/.token \
./scripts/start.sh
```

Open the printed URL from a browser that can reach the host.

## HTTPS

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -keyout certs/key.pem \
  -out certs/cert.pem
chmod 600 certs/key.pem

PROFILE_DIR=$PWD/profiles/example \
BASE_URL=https://example.com \
BIND_HOST=0.0.0.0 \
PORT=19193 \
TOKEN_FILE=$PWD/.token \
TLS_CERT=$PWD/certs/cert.pem \
TLS_KEY=$PWD/certs/key.pem \
./scripts/start.sh
```

Your browser will warn about a self-signed certificate unless you install/trust it.

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `PROFILE_DIR` | `./profile` | Persistent browser profile directory. |
| `BASE_URL` | `https://example.com/` | URL opened on start. |
| `BIND_HOST` | `127.0.0.1` | Bind address. Use LAN/VPN carefully. |
| `PORT` | `19192` | HTTP(S) port. |
| `TOKEN` | generated | Access token. Prefer `TOKEN_FILE`. |
| `TOKEN_FILE` | unset | File containing/persisting token. |
| `TLS_CERT` | unset | Certificate path. Enables HTTPS with `TLS_KEY`. |
| `TLS_KEY` | unset | Private key path. Enables HTTPS with `TLS_CERT`. |
| `SCREEN_WIDTH` | `1440` | Browser viewport width. |
| `SCREEN_HEIGHT` | `1100` | Browser viewport height. |
| `LOCALE` | `en-US` | Browser locale. |
| `TIMEZONE_ID` | unset | Browser timezone, for example `Europe/Lisbon`. |

## Security notes

- Prefer LAN/VPN only.
- Use HTTPS on untrusted networks.
- Do not expose directly to the public internet.
- Use a dedicated profile per workflow/account.
- Treat profile directories as sensitive: they may contain cookies/session data.
- Keep tokens, profiles and certificates out of git.

## License

MIT.
