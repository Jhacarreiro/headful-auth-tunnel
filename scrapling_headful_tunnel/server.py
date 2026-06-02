#!/usr/bin/env python3
from __future__ import annotations

import base64
import http.server
import json
import os
import secrets
import socketserver
import ssl
import threading
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scrapling.fetchers import StealthySession

ROOT = Path(os.environ.get('OUT_DIR', '.')).expanduser().resolve()
OUT = ROOT / 'out'
PROFILE = os.environ.get('PROFILE_DIR', './profile')
HOST = os.environ.get('BIND_HOST', '127.0.0.1')
PORT = int(os.environ.get('PORT', '19192'))
TOKEN = os.environ.get('TOKEN') or secrets.token_hex(16)
TLS_CERT = os.environ.get('TLS_CERT')
TLS_KEY = os.environ.get('TLS_KEY')
BASE_URL = os.environ.get('BASE_URL', 'https://example.com/')

OUT.mkdir(parents=True, exist_ok=True)
Path(PROFILE).mkdir(parents=True, exist_ok=True)

HTML = r'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="referrer" content="no-referrer">
  <title>Headful Browser Tunnel</title>
  <style>
    body { font-family: sans-serif; background:#111; color:white; margin:0; display:flex; flex-direction:column; align-items:center; }
    #bar { width:100%; box-sizing:border-box; padding:8px; display:flex; flex-wrap:wrap; gap:6px; background:#222; position:sticky; top:0; z-index:2; }
    input, button { padding:10px; font-size:15px; border-radius:5px; border:0; }
    button { background:#D4FF00; color:#000; font-weight:700; }
    button.secondary { background:#666; color:#fff; }
    button.done { background:#ff4444; color:#fff; }
    #urlInput { flex: 1 1 260px; }
    #typeInput { flex: 1 1 260px; min-height: 42px; }
    #wrap { width:96vw; margin:8px; border:2px solid #444; overflow:auto; background:#000; }
    #screen { display:block; width:100%; height:auto; cursor:crosshair; touch-action:none; }
    #status { width:100%; box-sizing:border-box; padding:8px 10px; font-size:12px; color:#D4FF00; }
  </style>
</head>
<body>
  <div id="bar">
    <input id="urlInput" value="BASE_URL_PLACEHOLDER">
    <button onclick="gotoUrl()">GO</button>
    <button class="secondary" onclick="goBack()">BACK</button>
    <button class="secondary" onclick="sendKey('Enter')">ENTER</button>
    <button class="secondary" onclick="sendKey('Tab')">TAB</button>
    <button class="secondary" onclick="sendKey('Backspace')">BACKSPACE</button>
    <button class="secondary" onclick="sendKey('Control+A')">CTRL+A</button>
    <button class="secondary" onclick="clearField()">CLEAR FIELD</button>
    <button class="secondary" onclick="pastePrompt()">PASTE PROMPT</button>
    <textarea id="typeInput" placeholder="write here; then SEND TEXT" autocomplete="off" autocorrect="off" autocapitalize="none" spellcheck="false"></textarea>
    <button class="secondary" onclick="sendTextBox()">SEND TEXT</button>
    <button class="secondary" onclick="clearLocalText()">CLEAR LOCAL</button>
    <button class="done" onclick="done()">DONE</button>
  </div>
  <div id="wrap"><img id="screen" alt="remote browser screenshot"></div>
  <div id="status">starting...</div>
<script>
const statusEl = document.getElementById('status');
const screen = document.getElementById('screen');
const typeInput = document.getElementById('typeInput');
let lastObjectUrl = null;
let busy = false;
let token = new URLSearchParams(location.search).get('token') || localStorage.getItem('cgpt_token') || '';
if (token) localStorage.setItem('cgpt_token', token);
function qs() { return token ? ('?token=' + encodeURIComponent(token)) : ''; }
async function api(path, body) {
  busy = true;
  try {
    const r = await fetch(path + qs(), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {}) });
    if (!r.ok) throw new Error(await r.text());
    return await r.json();
  } finally {
    setTimeout(() => { busy = false; }, 250);
  }
}
async function refresh() {
  if (busy) return;
  try {
    const r = await fetch('/screenshot' + qs() + '&t=' + Date.now(), {cache:'no-store'});
    if (!r.ok) { statusEl.textContent = 'screenshot error: ' + r.status + ' ' + await r.text(); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    screen.onload = () => { if (lastObjectUrl) URL.revokeObjectURL(lastObjectUrl); lastObjectUrl = url; };
    screen.src = url;
    statusEl.textContent = 'stream ' + new Date().toLocaleTimeString();
  } catch (e) { statusEl.textContent = 'stream error: ' + e.message; }
}
function coords(e) {
  e.preventDefault();
  const rect = screen.getBoundingClientRect();
  // Browser mouse expects CSS viewport coordinates, not DPR-scaled screenshot pixels.
  const naturalW = 1440;
  const naturalH = 1100;
  const p = e.touches && e.touches[0] ? e.touches[0] : e;
  const x = Math.round((p.clientX - rect.left) * naturalW / rect.width);
  const y = Math.round((p.clientY - rect.top) * naturalH / rect.height);
  statusEl.textContent = `click ${x}, ${y}`;
  api('/click', {x, y}).catch(err => statusEl.textContent = 'click error: ' + err.message);
}
if (window.PointerEvent) screen.addEventListener('pointerdown', coords); else { screen.addEventListener('touchstart', coords, {passive:false}); screen.addEventListener('click', coords); }
async function sendTextBox() {
  const text = typeInput.value;
  if (!text) { statusEl.textContent = 'local type box is empty'; return; }
  statusEl.textContent = `sending ${text.length} chars from local box...`;
  try {
    const r = await api('/type', {text});
    statusEl.textContent = `sent ${r.chars || text.length} chars exactly as shown in local box`;
  } catch (err) { statusEl.textContent = 'send text error: ' + err.message; }
}
function clearLocalText() { typeInput.value = ''; statusEl.textContent = 'local type box cleared only'; }
window.addEventListener('keydown', e => {
  if (document.activeElement && ['INPUT','TEXTAREA'].includes(document.activeElement.tagName)) return;
  if (e.key.length === 1) api('/type', {text:e.key}); else api('/key', {key:e.key});
});
function sendKey(key) { api('/key', {key}).catch(err => statusEl.textContent = err.message); }
async function clearField() {
  statusEl.textContent = 'clearing remote focused field...';
  try {
    await api('/key', {key:'Control+A'});
    await api('/key', {key:'Backspace'});
    statusEl.textContent = 'remote field cleared';
  } catch (err) { statusEl.textContent = 'clear error: ' + err.message; }
}
function gotoUrl() { api('/goto', {url: document.getElementById('urlInput').value}).catch(err => statusEl.textContent = err.message); }
function goBack() { api('/back', {}).then(r => statusEl.textContent = 'back: ' + (r.url || 'ok')).catch(err => statusEl.textContent = 'back error: ' + err.message); }
function pastePrompt() { const text = prompt('Paste text'); if (text) api('/type', {text}).catch(err => statusEl.textContent = err.message); }
async function done() { if (!confirm('Save session marker?')) return; const j = await api('/done', {}); alert(JSON.stringify(j)); }
setInterval(refresh, 1600); refresh();
</script>
</body>
</html>'''

class BrowserState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.session = None
        self.page = None
        self.started_at = None

    def start(self) -> None:
        with self.lock:
            if self.session is not None and self.page is not None:
                return
            self.session = StealthySession(
                headless=False,
                user_data_dir=PROFILE,
                locale='pt-PT',
                timezone_id='Europe/Lisbon',
                timeout=30000,
                solve_cloudflare=False,
                allow_webgl=True,
                hide_canvas=False,
                block_webrtc=True,
                google_search=False,
                network_idle=False,
                load_dom=True,
            )
            self.session.start()
            self.page = self.session.context.new_page()
            self.page.set_viewport_size({'width': 1440, 'height': 1100})
            self.page.goto(BASE_URL, wait_until='domcontentloaded', timeout=30000)
            self.started_at = time.time()

    def close(self) -> None:
        with self.lock:
            if self.session:
                self.session.close()
            self.session = None
            self.page = None

state = BrowserState()

def authorized(handler: http.server.BaseHTTPRequestHandler) -> bool:
    parsed = urlparse(handler.path)
    qs = parse_qs(parsed.query)
    supplied = (qs.get('token') or [''])[0]
    cookie = handler.headers.get('Cookie') or ''
    cookie_token = ''
    for part in cookie.split(';'):
        part = part.strip()
        if part.startswith('cgpt_auth_token='):
            cookie_token = part.split('=', 1)[1]
    return supplied == TOKEN or cookie_token == TOKEN

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'cgpt-scrapling-auth/1.0'

    def log_message(self, fmt: str, *args) -> None:
        print('%s - %s' % (self.address_string(), fmt % args), flush=True)

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def require_auth(self):
        if authorized(self):
            self.send_header('Set-Cookie', f'cgpt_auth_token={TOKEN}; Path=/; HttpOnly; SameSite=Lax')
            return True
        self.send_response(HTTPStatus.FORBIDDEN)
        self.end_headers()
        self.wfile.write(b'Forbidden')
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            self.send_json({'ok': True, 'engine': 'scrapling-stealthy', 'profile': PROFILE, 'started': state.started_at})
            return
        if parsed.path == '/':
            self.send_response(200 if authorized(self) else 403)
            if authorized(self):
                body = HTML.replace('BASE_URL_PLACEHOLDER', BASE_URL).encode('utf-8')
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Set-Cookie', f'cgpt_auth_token={TOKEN}; Path=/; HttpOnly; SameSite=Lax')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.end_headers(); self.wfile.write(b'Forbidden')
            return
        if parsed.path == '/screenshot':
            if not authorized(self):
                self.send_response(403); self.end_headers(); self.wfile.write(b'Forbidden'); return
            with state.lock:
                state.start()
                data = state.page.screenshot(type='jpeg', quality=58, full_page=False)
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404); self.end_headers(); self.wfile.write(b'Not found')

    def do_POST(self):
        parsed = urlparse(self.path)
        if not authorized(self):
            self.send_response(403); self.end_headers(); self.wfile.write(b'Forbidden'); return
        length = int(self.headers.get('Content-Length') or '0')
        body = self.rfile.read(length) if length else b'{}'
        try:
            payload = json.loads(body.decode('utf-8') or '{}')
        except Exception:
            payload = {}
        with state.lock:
            state.start()
            page = state.page
            if parsed.path == '/click':
                x = max(0, min(1439, int(payload.get('x', 0))))
                y = max(0, min(1099, int(payload.get('y', 0))))
                print(f'CLICK x={x} y={y}', flush=True)
                page.mouse.click(x, y)
                self.send_json({'ok': True, 'x': x, 'y': y})
            elif parsed.path == '/type':
                text = str(payload.get('text', ''))
                print(f'TYPE chars={len(text)}', flush=True)
                page.keyboard.type(text)
                self.send_json({'ok': True, 'chars': len(text)})
            elif parsed.path == '/key':
                key = str(payload.get('key', 'Enter'))
                print(f'KEY key={key}', flush=True)
                page.keyboard.press(key)
                self.send_json({'ok': True, 'key': key})
            elif parsed.path == '/goto':
                url = str(payload.get('url', BASE_URL))
                if not url.startswith('http'):
                    url = 'https://' + url
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                self.send_json({'ok': True, 'url': page.url})
            elif parsed.path == '/back':
                print('BACK', flush=True)
                page.go_back(wait_until='domcontentloaded', timeout=15000)
                self.send_json({'ok': True, 'url': page.url})
            elif parsed.path == '/done':
                cookies = state.session.context.cookies()
                marker = {'savedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'engine': 'scrapling-stealthy', 'profile': PROFILE, 'url': page.url, 'title': page.title(), 'cookieCount': len(cookies)}
                (OUT / 'last-auth.json').write_text(json.dumps(marker, ensure_ascii=False, indent=2))
                self.send_json({'ok': True, 'marker': marker})
            else:
                self.send_response(404); self.end_headers(); self.wfile.write(b'Not found')

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main() -> None:
    print('SCRAPLING HEADFUL TUNNEL READY', flush=True)
    print(f'Access Link: http://<host>:{PORT}/?token={TOKEN}', flush=True)
    print(f'Health: http://<host>:{PORT}/health', flush=True)
    print(f'Profile: {PROFILE}', flush=True)
    try:
        state.start()
    except Exception as e:
        print(f'Initial browser start failed: {e}', flush=True)
    with ReusableTCPServer((HOST, PORT), Handler) as httpd:
        if TLS_CERT and TLS_KEY:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(TLS_CERT, TLS_KEY)
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        try:
            httpd.serve_forever()
        finally:
            state.close()

if __name__ == '__main__':
    main()
