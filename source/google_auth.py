# -*- coding: utf-8 -*-
"""
تسجيل دخول جوجل لتطبيق سطح المكتب: PKCE من غير سر، والتوكن في الذاكرة.
GOOGLE_CLIENT_ID فاضي لحد ما يتلزق معرّف عميل إملاء. معرّف بوستورا مش بيتنسخ.
"""
import base64
import hashlib
import http.client
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse

import backup

GOOGLE_CLIENT_ID = ""
SCOPES = "openid email profile https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
# فشل النقل من الديسك أو الشبكة. HTTPError بتاع urllib جوه URLError،
# والرد المقطوع من http.client مش دايمًا بيطلع OSError.
TRANSPORT_ERRORS = (OSError, urllib.error.URLError, http.client.HTTPException)
# MAX_TOTAL سقف المحتوى غير المضغوط. الملف على الديسك أكبر بهيدر كل عضو
# والدليل المركزي، والصوت المضغوط أصلًا ممكن يتمدّد شوية جوّه الـzip.
# القراية بتقف هنا عشان ملف أكبر مايتحملش كله في الذاكرة قبل الرفض.
BACKUP_READ_CAP = backup.MAX_TOTAL + 8 * 1024 * 1024
_memory = {}
_state_lock = threading.Lock()
_sign_out_generation = {}


class GoogleError(backup.BackupError):
    pass


def _pkce():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _claims(token):
    try:
        payload = token.split(".")[1]
        pad = "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload + pad))
    except (IndexError, ValueError, json.JSONDecodeError):
        raise backup.BackupError("reauth")


def _check_claims(claims, client_id, now):
    if not isinstance(claims, dict):
        raise backup.BackupError("reauth")
    if claims.get("aud") != client_id or claims.get("iss") not in ISSUERS:
        raise backup.BackupError("reauth")
    if not claims.get("email") or float(claims.get("exp") or 0) <= now:
        raise backup.BackupError("reauth")


def state_path(base_dir):
    return os.path.join(base_dir, "google.json")


def read_state(base_dir):
    path = state_path(base_dir)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def current_generation(base_dir):
    with _state_lock:
        return _sign_out_generation.get(base_dir, 0)


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        return


def write_state(base_dir, state, generation=None, create=True):
    path = state_path(base_dir)
    tmp = path + "." + os.urandom(4).hex() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    with _state_lock:
        signed_out = generation is not None and _sign_out_generation.get(base_dir, 0) != generation
        # ملف اتمسح يعني الخروج خلّص قبل الكتابة. إنشاء الملف هنا كان هيرجّع التوكن.
        missing = generation is not None and not create and not os.path.exists(path)
        if signed_out or missing:
            _discard(tmp)
            return False
        os.replace(tmp, path)
        if generation is None:
            _sign_out_generation[base_dir] = _sign_out_generation.get(base_dir, 0) + 1
        return True


def read_bounded(path):
    with open(path, "rb") as handle:
        blob = handle.read(BACKUP_READ_CAP + 1)
    if len(blob) > BACKUP_READ_CAP:
        raise backup.BackupError("too_large")
    return blob


def sign_in(client_id, transport, listener, opener, clock, base_dir):
    """client_id فاضي = ولا متعاون بيتنده. الاختبارات بتبعّت معرّف وهمي."""
    if not (client_id or "").strip():
        raise backup.BackupError("unconfigured")
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    redirect_uri, wait = listener()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    })
    opener(url)
    redirect = wait()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)
    if (query.get("state") or [None])[0] != state or not (query.get("code") or [None])[0]:
        raise backup.BackupError("reauth")
    status, _headers, body = transport("POST", TOKEN_URL, {}, urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": query["code"][0],
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }).encode("utf-8"))
    if status != 200:
        raise backup.BackupError("reauth")
    token = json.loads(body.decode("utf-8"))
    claims = _claims(token.get("id_token") or "")
    _check_claims(claims, client_id, clock())
    account = {
        "email": claims["email"],
        "name": claims.get("name") or claims["email"],
        "picture": claims.get("picture") or "",
    }
    previous = read_state(base_dir)
    previous_email = (previous.get("account") or {}).get("email")
    switched = previous_email not in (None, account["email"])
    # حساب تاني بيمسح معرّفات الملفات القديمة عشان البحث يبقى في درايف الحساب ده
    if switched:
        previous.pop("folderId", None)
        previous.pop("fileId", None)
    previous["account"] = account
    refresh = token.get("refresh_token")
    if refresh:
        previous["refreshToken"] = refresh
    elif switched:
        # الرد من غير refresh token ما يفضلش شايل توكن الحساب القديم تحت إيميل الجديد
        previous.pop("refreshToken", None)
    else:
        previous["refreshToken"] = previous.get("refreshToken") or ""
    write_state(base_dir, previous)
    _memory[base_dir] = {
        "access": token.get("access_token"),
        "expires": clock() + int(token.get("expires_in") or 3600),
    }
    return account


def access_token(base_dir, transport, clock, client_id=None):
    client_id = GOOGLE_CLIENT_ID if client_id is None else client_id
    cached = _memory.get(base_dir) or {}
    if cached.get("access") and cached.get("expires", 0) - 60 > clock():
        return cached["access"]
    state = read_state(base_dir)
    refresh = state.get("refreshToken")
    if not refresh:
        raise backup.BackupError("reauth")
    status, _headers, body = transport("POST", TOKEN_URL, {}, urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client_id,
    }).encode("utf-8"))
    if status != 200:
        raise backup.BackupError("reauth")
    token = json.loads(body.decode("utf-8"))
    _memory[base_dir] = {
        "access": token["access_token"],
        "expires": clock() + int(token.get("expires_in") or 3600),
    }
    return token["access_token"]


def sign_out(base_dir, transport=None):
    # النقل بيتتجاهل: الخروج بينسى الحساب على الجهاز ومش بينادي جوجل ولا درايف
    with _state_lock:
        path = state_path(base_dir)
        if os.path.exists(path):
            os.remove(path)
        _memory.pop(base_dir, None)
        _sign_out_generation[base_dir] = _sign_out_generation.get(base_dir, 0) + 1


def listen_once(timeout=300):
    """منفذ على 127.0.0.1 بس. بيتفتح بعد ما المعرّف يتأكد إنه مش فاضي."""
    import http.server
    held = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            held["url"] = "http://127.0.0.1:%s%s" % (server.server_address[1], self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("تم تسجيل الدخول. ارجع لبرنامج إملاء.".encode("utf-8"))

        def log_message(self, fmt, *args):
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = timeout

    def wait():
        try:
            server.handle_request()
        finally:
            server.server_close()
        if "url" not in held:
            raise backup.BackupError("reauth")
        return held["url"]

    return "http://127.0.0.1:%s/" % server.server_address[1], wait


def _read_capped(response):
    return response.read(BACKUP_READ_CAP + 1)


def urllib_transport(method, url, headers, body):
    import urllib.request
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60, context=providers_ssl()) as res:
            return res.status, dict(res.headers), _read_capped(res)
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers or {}), _read_capped(err)


def providers_ssl():
    import providers
    return providers._ssl_context()


def forget_for_tests(base_dir=None):
    if base_dir is None:
        _memory.clear()
        _sign_out_generation.clear()
    else:
        _memory.pop(base_dir, None)
        _sign_out_generation.pop(base_dir, None)
