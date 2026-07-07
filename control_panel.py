#!/usr/bin/env python3
"""
Client control panel for FB Autoposter (internet-facing, authenticated).

Run locally:   PANEL_PASSWORD=yourpass python control_panel.py
Deploy:        set PANEL_PASSWORD (and the API secrets) as host env vars;
               the host provides HTTPS and sets $PORT. See DEPLOY.md.

Security model:
  - Refuses to start unless PANEL_PASSWORD is set (no accidental open panel).
  - Password login -> HttpOnly session cookie (random 256-bit token).
  - Every route except the login page requires a valid session.
  - Constant-time password check; simple per-IP throttle on failed logins.
  - Set PANEL_HTTPS=1 in production so the cookie is marked Secure.
Put this behind the host's TLS (Render/Railway/Fly all terminate HTTPS).
"""
import html
import hmac
import os
import secrets
import sys
import time
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import yaml

BASE = Path(__file__).parent
CONFIG = BASE / "config.yaml"
OUT_DIR = BASE / "out"

PASSWORD = os.environ.get("PANEL_PASSWORD", "")
SECURE_COOKIE = os.environ.get("PANEL_HTTPS", "") == "1"
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("PANEL_HOST", "0.0.0.0")

SESSIONS = {}                 # token -> expiry_epoch
SESSION_TTL = 8 * 3600
FAILS = {}                    # ip -> (count, first_ts)

FIELDS = [
    ("topic_criteria", "Topic criteria", "What should posts be about?"),
    ("caption_style", "Caption style", "Tone/length/hashtag rules for the caption."),
    ("image_style", "Image style", "Look of the generated image."),
]
MANUAL = [
    ("topic", "Manual topic (optional)"),
    ("caption", "Manual caption (optional)"),
    ("image_prompt", "Manual image prompt (optional)"),
]


def load_cfg():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def save_cfg(cfg):
    CONFIG.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
                      encoding="utf-8")


def new_session():
    tok = secrets.token_urlsafe(32)
    SESSIONS[tok] = time.time() + SESSION_TTL
    return tok


def valid_session(tok):
    exp = SESSIONS.get(tok)
    if not exp:
        return False
    if exp < time.time():
        SESSIONS.pop(tok, None)
        return False
    return True


def throttled(ip):
    count, first = FAILS.get(ip, (0, time.time()))
    if time.time() - first > 300:          # reset window every 5 min
        FAILS[ip] = (0, time.time())
        return False
    return count >= 5


def record_fail(ip):
    count, first = FAILS.get(ip, (0, time.time()))
    if time.time() - first > 300:
        FAILS[ip] = (1, time.time())
    else:
        FAILS[ip] = (count + 1, first)


def login_page(msg=""):
    m = f'<p style="color:#b91c1c">{html.escape(msg)}</p>' if msg else ""
    return f"""<!doctype html><meta charset=utf-8>
<title>Sign in - FB Autoposter</title>
<style>body{{font:15px system-ui,sans-serif;max-width:340px;margin:80px auto;padding:0 16px}}
input{{width:100%;padding:9px;margin:8px 0;border:1px solid #ccc;border-radius:6px;box-sizing:border-box}}
button{{width:100%;padding:10px;border:0;border-radius:6px;background:#166534;color:#fff;font-size:15px;cursor:pointer}}</style>
<h2>FB Autoposter</h2>{m}
<form method="post" action="/login">
<input type="password" name="password" placeholder="Panel password" autofocus>
<button>Sign in</button></form>"""


def page(cfg, run_output=None, image_rel=None, saved=False):
    def val(k): return html.escape(str(cfg.get(k, "") or "").strip())
    mc = cfg.get("manual_content") or {}
    def mval(k): return html.escape(str(mc.get(k, "") or "").strip())

    banner = ""
    if saved:
        banner += '<div class="ok">Saved to config.yaml.</div>'
    if run_output is not None:
        img = f'<img src="/image/{image_rel}" class="prev"/>' if image_rel else \
              '<p><em>No local image (live fal.ai image is hosted remotely).</em></p>'
        banner += ('<div class="runbox"><h3>Run preview</h3>' + img +
                   f'<pre>{html.escape(run_output)}</pre></div>')

    main_fields = "".join(
        f'<label>{lbl}<span>{hint}</span>'
        f'<textarea name="{k}" rows="3">{val(k)}</textarea></label>'
        for k, lbl, hint in FIELDS)
    manual_fields = "".join(
        f'<label>{lbl}<textarea name="mc_{k}" rows="2">{mval(k)}</textarea></label>'
        for k, lbl in MANUAL)
    dry = "checked" if cfg.get("dry_run") else ""
    mock = "checked" if cfg.get("mock_apis") else ""
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>FB Autoposter - Control Panel</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:24px auto;padding:0 16px;color:#1a1a1a}}
 h1{{font-size:22px}} label{{display:block;margin:14px 0;font-weight:600}}
 label span{{display:block;font-weight:400;color:#666;font-size:13px}}
 textarea{{width:100%;font:14px/1.4 ui-monospace,monospace;padding:8px;
   border:1px solid #ccc;border-radius:6px;box-sizing:border-box}}
 .row{{display:flex;gap:24px;align-items:center;margin:14px 0}}
 .row label{{margin:0;font-weight:600}}
 button{{font-size:15px;padding:9px 18px;border:0;border-radius:6px;cursor:pointer;margin-right:10px}}
 .save{{background:#e5e7eb}} .run{{background:#166534;color:#fff}}
 .ok{{background:#dcfce7;padding:10px;border-radius:6px;margin:10px 0}}
 .runbox pre{{background:#0b0b0b;color:#d1fae5;padding:12px;border-radius:6px;overflow:auto;white-space:pre-wrap}}
 .prev{{max-width:280px;border-radius:8px;display:block;margin:8px 0}}
 .note{{color:#666;font-size:13px}} .top{{display:flex;justify-content:space-between;align-items:center}}
 a.out{{font-size:13px;color:#166534}}
</style></head><body>
<div class="top"><h1>FB Autoposter - Control Panel</h1><a class="out" href="/logout">Sign out</a></div>
<p class="note">Edit the prompts, Save, then Run now for a safe preview.
When Dry-run is on, nothing is posted to Facebook.</p>
{banner}
<form method="post" action="/save">
 {main_fields}
 <h3>Manual override</h3>
 <p class="note">Fill these to post exact text (skips the AI writer). Leave blank to auto-generate.</p>
 {manual_fields}
 <div class="row">
   <label><input type="checkbox" name="dry_run" {dry}> Dry-run (safe preview, no posting)</label>
   <label><input type="checkbox" name="mock_apis" {mock}> Mock image (no fal.ai spend)</label>
 </div>
 <button class="save" formaction="/save">Save</button>
 <button class="run" formaction="/run">Save &amp; Run now</button>
</form></body></html>"""


def apply_form(cfg, form):
    def g(k): return form.get(k, [""])[0]
    for k, _, _ in FIELDS:
        cfg[k] = g(k)
    mc = {}
    for k, _ in MANUAL:
        v = g(f"mc_{k}").strip()
        if v:
            mc[k] = v
    if mc:
        cfg["manual_content"] = mc
    else:
        cfg.pop("manual_content", None)
    cfg["dry_run"] = "dry_run" in form
    cfg["mock_apis"] = "mock_apis" in form
    return cfg


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="text/html; charset=utf-8", code=200, cookie=None):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(b)

    def _cookie_token(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            if part.strip().startswith("sid="):
                return part.strip()[4:]
        return ""

    def _authed(self):
        return valid_session(self._cookie_token())

    def _redirect(self, loc, cookie=None):
        self.send_response(303)
        self.send_header("Location", loc)
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def do_GET(self):
        if self.path == "/logout":
            SESSIONS.pop(self._cookie_token(), None)
            return self._redirect("/", cookie="sid=; Max-Age=0; Path=/")
        if not self._authed():
            return self._send(login_page(), code=200)
        if self.path.startswith("/image/"):
            f = OUT_DIR / os.path.basename(self.path.split("/image/", 1)[1])
            if f.exists():
                return self._send(f.read_bytes(), "image/png")
            return self._send(b"", code=404)
        self._send(page(load_cfg()))

    def do_POST(self):
        ip = self.client_address[0]
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))

        if self.path == "/login":
            if throttled(ip):
                return self._send(login_page("Too many attempts. Wait a few minutes."))
            supplied = form.get("password", [""])[0]
            if PASSWORD and hmac.compare_digest(supplied, PASSWORD):
                flags = "; Secure" if SECURE_COOKIE else ""
                cookie = f"sid={new_session()}; HttpOnly; SameSite=Lax; Path=/{flags}"
                return self._redirect("/", cookie=cookie)
            record_fail(ip)
            return self._send(login_page("Wrong password."))

        if not self._authed():
            return self._send(login_page(), code=200)

        cfg = apply_form(load_cfg(), form)
        save_cfg(cfg)
        if self.path == "/run":
            proc = subprocess.run([sys.executable, str(BASE / "autoposter.py")],
                                  capture_output=True, text=True, cwd=str(BASE))
            out = (proc.stdout or "") + (proc.stderr or "")
            newest = None
            if OUT_DIR.exists():
                pngs = sorted(OUT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime)
                newest = pngs[-1].name if pngs else None
            return self._send(page(load_cfg(), run_output=out, image_rel=newest))
        self._send(page(load_cfg(), saved=True))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if not PASSWORD:
        sys.exit("ERROR: set PANEL_PASSWORD before starting "
                 "(refusing to run an unauthenticated panel).")
    print(f"Control panel on {HOST}:{PORT}  (HTTPS should be provided by the host)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
