# Architecture

## Overview

Headful Auth Tunnel exposes one persistent, human-operated Chromium browser through a small authenticated HTTP service.

```text
remote browser or API client
        |
        | HTTP(S), session cookie or bearer token
        v
ThreadingHTTPServer
        |
        | bounded command queue
        v
single browser worker thread
        |
        | Scrapling StealthySession / persistent Chromium context
        v
PROFILE_DIR
```

The browser is deliberately headful. Xvfb supplies the display on a headless Linux host, but Chromium still runs in normal headed mode.

## Single browser instance

Each tunnel process owns exactly one `StealthySession`, one persistent browser context and one active-page pointer.

All HTTP requests that touch Playwright are converted into commands and executed on the browser worker thread. This prevents cross-thread Playwright access while still allowing the HTTP server to serve multiple clients concurrently.

Tabs and popups are pages inside the same browser context. Focusing a tab changes the active-page pointer; it does not create a second browser.

## Persistent profile

`PROFILE_DIR` is passed to Chromium as its persistent user-data directory. It contains cookies, local storage, IndexedDB, service-worker state and other browser identity data.

The same directory is reused after a tunnel restart. Chromium prevents two processes from opening the same profile concurrently, so a profile must have a single owner at a time.

Treat the profile directory as credential material. Never commit, copy into a container image or expose it through the HTTP API.

## Authentication flow

The long-lived access token comes from `AUTH_TOKEN` or `TOKEN_FILE`.

For the browser UI:

1. the operator submits the token once to `POST /session`;
2. the server verifies it with a constant-time comparison;
3. the server creates a separate random session identifier;
4. the browser receives that identifier in an `HttpOnly`, `SameSite=Strict` cookie.

The access token is not stored in JavaScript, routine URLs or the session cookie. API clients can use `Authorization: Bearer <token>`.

## Destination policy

Public HTTP and HTTPS destinations are permitted by default. Loopback, private, link-local, reserved and common internal names are blocked.

The policy is applied to:

- explicit top-level navigation;
- redirects;
- page subresources;
- WebSocket connections.

`DENIED_HOSTS` has highest precedence. `ALLOWED_HOSTS` can permit a required internal hostname. `ALLOW_PRIVATE_NETWORK_NAVIGATION=true` disables the private-network restriction globally.

DNS results are cached briefly and explicit navigation forces a fresh lookup. This reduces DNS rebinding exposure while avoiding a lookup for every static asset.

## Screenshots and coordinates

The screenshot endpoint returns the current viewport as PNG. The web UI maps clicks and drags using the PNG element's real `naturalWidth` and `naturalHeight`, not a hard-coded viewport.

Runtime viewport changes update every open page in the browser context. The startup defaults remain `1440×1100`.

## DOM snapshot model

DOM snapshots are an auxiliary structured view; the screenshot remains the authoritative human view.

By default, snapshots omit field values. The authenticated operator can request normal values and, separately, sensitive values such as password, token and OTP inputs. Sensitive disclosure is explicit to avoid accidental copying into logs or agent context.

## Deployment boundaries

The process defaults to `127.0.0.1:19192`. Remote access should use a trusted LAN, VPN, SSH forwarding or a reverse proxy with TLS.

The Docker image binds inside the container to `0.0.0.0:19192`, while the example Compose file publishes it only on host loopback. The systemd example runs under a dedicated user and restricts writable paths to the persistent state directory.
