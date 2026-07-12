# headful-auth-tunnel

A small, self-hosted remote-control tunnel for **human-operated headful browser sessions** with persistent profiles.

It is useful when automation runs on a headless machine, but a person must occasionally open the real browser, authenticate an account they are authorised to use, and leave the resulting profile available for later permitted automation.

> Use this only on a trusted host, LAN or VPN. Do not expose it directly to the public internet.

## What 0.4.0 provides

- Persistent Scrapling `StealthySession` browser profile.
- Token login that creates a random `HttpOnly`, `SameSite=Strict` session cookie.
- No token in URLs, browser history, JavaScript storage or routine access logs.
- Live PNG screenshots with click/drag coordinates based on the actual image dimensions.
- Editable viewport from `320×240` to `7680×4320`; the `1440×1100` default is preserved.
- Editable locale and timezone; `pt-PT` and `Europe/Lisbon` remain the defaults.
- Navigation, back, forward, reload, typing and key presses.
- Tab/popup discovery, focus and close controls.
- DOM inspection plus selector click, fill, press and select.
- Explicit operator-controlled access to password, token and OTP field values when needed.
- Public-internet navigation by default while private/internal destinations are blocked.
- Destination filtering for navigation, redirects, subresources and WebSockets.
- Optional direct TLS.
- Docker, systemd, lifecycle scripts, tests, CI, Dependabot and tagged-release builds.


## Documentation

- [Architecture](docs/architecture.md)
- [HTTP API reference](docs/api.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## Non-goals

This project does not solve or bypass CAPTCHAs, anti-bot protections, access controls, paywalls or rate limits. It is a human-control bridge for accounts and systems you are allowed to use.

## Quick start

### Install

Python 3.10 or newer is required.

```bash
git clone https://github.com/Jhacarreiro/headful-auth-tunnel.git
cd headful-auth-tunnel

python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m patchright install chromium
```

On Debian/Ubuntu headless systems:

```bash
sudo apt-get update
sudo apt-get install -y xvfb
python -m patchright install --with-deps chromium
```

### Configure and start

```bash
cp .env.example .env
./scripts/start.sh
./scripts/show-token.sh
```

Open `http://127.0.0.1:19192/`, paste the token into the login form, and operate the browser through the screenshot UI.

The published defaults remain local and compatible:

```dotenv
BIND_HOST=127.0.0.1
PORT=19192
SCREEN_WIDTH=1440
SCREEN_HEIGHT=1100
LOCALE=pt-PT
TIMEZONE_ID=Europe/Lisbon
ALLOW_PRIVATE_NETWORK_NAVIGATION=false
```

The token is generated automatically when missing and stored with mode `0600`. `start.sh` prints its path, not the secret itself.

Stop with:

```bash
./scripts/stop.sh
```

## Resolution and scaling

`SCREEN_WIDTH` and `SCREEN_HEIGHT` set the startup viewport. Both can also be changed at runtime in the web UI.

The screenshot UI no longer assumes a fixed `1440×1100` canvas. Clicks and drags use the PNG's real `naturalWidth` and `naturalHeight`, so larger viewports remain aligned. The end-to-end path has been validated at `3840×2160`.

Examples:

```dotenv
SCREEN_WIDTH=1920
SCREEN_HEIGHT=1200
```

```dotenv
SCREEN_WIDTH=3840
SCREEN_HEIGHT=2160
```

## Destination security policy

The default policy allows normal public `http` and `https` sites and blocks:

- IPv4 and IPv6 loopback;
- private, link-local, multicast, unspecified and reserved addresses;
- single-label hostnames;
- `localhost`, `.localhost`, `.local`, `.internal`, `.lan`, `.home` and `.home.arpa`;
- public-looking hostnames that resolve to a blocked address;
- credentials embedded in URLs;
- `file:` and unsupported schemes.

DNS decisions are revalidated periodically and explicit top-level navigation forces a fresh lookup.

Policy precedence is:

1. `DENIED_HOSTS` always blocks.
2. `ALLOWED_HOSTS` explicitly permits matching hosts, including a required internal callback.
3. `ALLOW_PRIVATE_NETWORK_NAVIGATION=true` permits private/internal destinations globally.
4. Otherwise only public destinations are allowed.

Host lists are comma-separated shell-style patterns:

```dotenv
ALLOWED_HOSTS=auth.internal.example,*.trusted.lan
DENIED_HOSTS=ads.example.com,*.tracking.example
```

A specific allowlist entry is preferable to enabling every private destination.

## Authentication

### Browser UI

The browser submits the access token once to `POST /session`. The server creates an independent random session ID and returns it as an `HttpOnly`, `SameSite=Strict` cookie. The access token itself is not placed in the cookie.

Legacy query-string bootstrap can be enabled temporarily:

```dotenv
ALLOW_QUERY_TOKEN=true
```

It is disabled by default because query strings commonly leak into browser history and logs.

### API clients

API clients may use the configured access token as a bearer token:

```bash
TOKEN=$(./scripts/show-token.sh)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:19192/meta
```

## Browser and DOM controls

The web UI is a live view of the complete headful browser. Login pages, password fields, OTP prompts, consent dialogs and popups remain visible and controllable exactly as the site renders them.

There is one live Chromium instance per running tunnel process. Every HTTP/UI action is queued into that same browser context. `PROFILE_DIR` is reused after restarts, preserving cookies, local storage, IndexedDB and authenticated sessions. Chromium also prevents two processes from opening the same profile concurrently.

The UI supports direct click/drag, navigation, typing, key presses, viewport changes, tab selection and selector-based editing.

Authenticated API operations include:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/meta` | Current URL, title, viewport and settings. |
| `GET` | `/screenshot` | Current viewport as PNG. |
| `GET` | `/tabs` | List open pages and popups. |
| `GET` | `/page` | DOM snapshot without field values. |
| `POST` | `/page` | Add `include_values` and optionally `include_sensitive_values`. |
| `POST` | `/navigate` | Navigate to a policy-approved URL. |
| `POST` | `/viewport` | Change viewport width and height. |
| `POST` | `/click`, `/drag` | Pointer control. |
| `POST` | `/type`, `/key` | Keyboard control. |
| `POST` | `/tabs/focus`, `/tabs/close` | Tab control. |
| `POST` | `/dom/fill`, `/dom/click` | Selector editing. |
| `POST` | `/dom/press`, `/dom/select` | Key/select operations on a selector. |

The DOM snapshot is an auxiliary structured view; it does not replace the visible browser. The UI includes **Include field values** and **Reveal password, token and OTP values** controls. API clients can request the same explicitly:

```json
{
  "include_values": true,
  "include_sensitive_values": true
}
```

Sensitive values are omitted unless `include_sensitive_values` is explicitly enabled. This avoids accidental disclosure in routine snapshots while keeping login, OTP and token workflows fully usable.

## Configuration reference

| Variable | Default | Description |
|---|---:|---|
| `BIND_HOST` | `127.0.0.1` | HTTP bind address. Prefer a specific LAN/VPN IP for remote access. |
| `PORT` | `19192` | HTTP(S) port. |
| `BASE_URL` | `https://example.com` | Initial page. Must pass the destination policy. |
| `PROFILE_DIR` | `~/.headful-auth-tunnel/profile` | Persistent profile for the Python entry point; helper script uses `./profile`. |
| `TOKEN_FILE` | XDG state directory | Generated token path; helper script uses `./runtime/token`. |
| `AUTH_TOKEN` | unset | Inline token override, minimum 24 characters. Prefer `TOKEN_FILE`. |
| `SCREEN_WIDTH` | `1440` | Startup viewport width, 320–7680. |
| `SCREEN_HEIGHT` | `1100` | Startup viewport height, 240–4320. |
| `LOCALE` | `pt-PT` | Browser locale. |
| `TIMEZONE_ID` | `Europe/Lisbon` | Browser timezone ID. |
| `SCREENSHOT_INTERVAL_MS` | `2000` | UI refresh interval, 250–60000 ms. |
| `NAVIGATION_TIMEOUT_MS` | `30000` | Browser navigation timeout. |
| `ALLOW_PRIVATE_NETWORK_NAVIGATION` | `false` | Permit every private/internal destination. |
| `ALLOWED_HOSTS` | empty | Comma-separated explicit allow patterns. |
| `DENIED_HOSTS` | empty | Comma-separated explicit deny patterns. |
| `ALLOW_QUERY_TOKEN` | `false` | Enable legacy `?token=` bootstrap. |
| `SESSION_COOKIE_NAME` | `headful_auth_session` | Session cookie name. |
| `MAX_REQUEST_BYTES` | `1048576` | Maximum request body. |
| `SOCKET_TIMEOUT_SECONDS` | `15` | Per-client socket timeout. |
| `EXPOSE_HEALTH_DETAILS` | `false` | Include browser/tab counts in `/health`. |
| `MAX_DOM_TEXT_CHARS` | `20000` | Maximum page text returned by DOM snapshot. |
| `MAX_DOM_ELEMENTS` | `250` | Maximum controls/links returned by DOM snapshot. |
| `TLS_CERT`, `TLS_KEY` | unset | Enable TLS when both paths are configured. |

## TLS

Configure both files or neither:

```dotenv
TLS_CERT=/absolute/path/tunnel.crt
TLS_KEY=/absolute/path/tunnel.key
```

The server refuses partial TLS configuration. With TLS enabled, session cookies receive the `Secure` flag and responses include HSTS.

For any network beyond a trusted host, use a trusted reverse proxy or a certificate trusted by the client.

## Docker

```bash
cp docker-compose.example.yml docker-compose.yml
docker-compose up -d --build
docker-compose exec headful-auth-tunnel cat /data/state/token
```

Inside the container the service binds `0.0.0.0:19192`; the example publishes it only as `127.0.0.1:19192` on the host and persists profile/token data in named volumes. Replace the host-side `127.0.0.1` with a specific LAN/VPN address only when remote access is required.

## systemd

Reference files are under `deploy/systemd/`. The expected layout is:

```text
/opt/headful-auth-tunnel
/etc/headful-auth-tunnel.env
/var/lib/headful-auth-tunnel
```

Create a dedicated `headful-auth-tunnel` user, install the virtual environment under `/opt/headful-auth-tunnel/.venv`, copy the unit to `/etc/systemd/system/`, then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now headful-auth-tunnel
```

## Upgrading from 0.2.x

- The default address remains `127.0.0.1:19192`.
- The default viewport remains `1440×1100`.
- Open `/` and paste the token; query-string tokens are disabled by default.
- `TOKEN` is replaced by `AUTH_TOKEN`; `TOKEN_FILE` remains preferred.
- Private/internal destinations are blocked unless explicitly allowed.
- Screenshots are PNG rather than compressed JPEG.


## Troubleshooting

### The browser does not start

Run `python -m patchright install --with-deps chromium` and confirm Xvfb is installed. With the helper scripts, inspect `runtime/tunnel.log` and `runtime/xvfb.log`.

### The service works locally but not through Docker

The process inside the container must bind `0.0.0.0:19192`. The supplied image and Compose example already set this. Keep the host-side publish address at `127.0.0.1` unless a LAN/VPN client must connect.

### Chromium reports that the profile is in use

Only one browser process may own a profile directory. Stop the previous tunnel and verify its Chromium/Xvfb processes are gone before starting another process with the same `PROFILE_DIR`.

### An internal callback or login host is blocked

Add the exact hostname to `ALLOWED_HOSTS`. Prefer a narrow allowlist entry over `ALLOW_PRIVATE_NETWORK_NAVIGATION=true`.

### The login session disappears after restart

Confirm that every start uses the same `PROFILE_DIR` and that the directory is writable by the service user. In Docker, mount `/data/profile` as a persistent volume.

### The token is rejected

Use `./scripts/show-token.sh` to read the configured token file. When running the Python entry point directly, confirm that `TOKEN_FILE` or `AUTH_TOKEN` points to the same value used by the client.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest --cov=headful_auth_tunnel --cov-report=term-missing
python -m build
shellcheck scripts/*.sh
```

CI tests Python 3.10, 3.12 and 3.14. Tags matching `v*` build wheel/sdist artefacts and create a GitHub release.

## Security notes

- Use a dedicated profile per workflow/account.
- Treat the persistent profile as a credential store: it contains cookies, storage and active sessions.
- Keep token, profile, TLS key and screenshots containing secrets out of git.
- Prefer a VPN or SSH port forwarding over opening a LAN service broadly.
- Rotate the token by stopping the service, replacing the token file and restarting.
- Review `SECURITY.md` before reporting a vulnerability.

## License

MIT.
