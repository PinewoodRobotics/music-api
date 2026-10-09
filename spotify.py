"""Spotify Web API client with OAuth Authorization Code + PKCE. Stdlib only.

PKCE needs no client secret, so the only thing to configure is a Client ID from
https://developer.spotify.com/dashboard. Tokens live in <data-dir>/spotify-tokens.json (mode 600)
and are refreshed automatically.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ACCOUNTS = "https://accounts.spotify.com"
API = "https://api.spotify.com/v1"
SCOPES = " ".join([
    "user-read-playback-state", "user-modify-playback-state", "user-read-currently-playing",
    "user-library-read", "user-library-modify", "user-follow-read", "user-follow-modify",
    "playlist-read-private", "playlist-read-collaborative", "playlist-modify-private", "playlist-modify-public",
    "user-read-recently-played", "user-top-read", "user-read-private",
])


class SpotifyError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg)
        self.status = status


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _post_form(url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
            msg = err.get("error_description") or err.get("error") or str(e)
        except ValueError:
            msg = str(e)
        raise SpotifyError(f"Spotify accounts: {msg}", 401 if e.code in (400, 401) else 502)


class Auth:
    def __init__(self, data_dir, client_id=None, redirect_uri=None):
        self.path = os.path.join(data_dir, "spotify-tokens.json")
        self.lock = threading.Lock()
        self.pending = {}  # state -> (verifier, redirect_uri, created)
        self.tokens = {}
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.tokens = json.load(f)
        self.client_id = client_id or self.tokens.get("client_id")
        self.redirect_uri = redirect_uri

    def _save(self):
        tmp = self.path + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(self.tokens, f)
        os.replace(tmp, self.path)

    @property
    def logged_in(self):
        return bool(self.tokens.get("refresh_token"))

    def status(self):
        return {"configured": bool(self.client_id), "logged_in": self.logged_in,
                "scope": self.tokens.get("scope"), "redirect_uri": self.redirect_uri,
                "expires_at": self.tokens.get("expires_at")}

    def login_url(self, redirect_uri=None):
        if not self.client_id:
            raise SpotifyError("no Spotify Client ID: start with --client-id or set SPOTIFY_CLIENT_ID", 412)
        redirect_uri = redirect_uri or self.redirect_uri
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(16)
        now = time.time()
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if now - v[2] < 900}
            self.pending[state] = (verifier, redirect_uri, now)
        return ACCOUNTS + "/authorize?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": self.client_id, "scope": SCOPES,
            "redirect_uri": redirect_uri, "state": state, "code_challenge_method": "S256",
            "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        })

    def finish(self, code=None, state=None, url=None):
        """Exchange the auth code. Accepts either code+state or the full redirected URL (pasted by the user)."""
        if url:
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url.strip()).query))
            if q.get("error"):
                raise SpotifyError(f"Spotify login refused: {q['error']}", 400)
            code, state = q.get("code"), q.get("state")
        with self.lock:
            entry = self.pending.pop(state or "", None)
        if not code or not entry:
            raise SpotifyError("unknown or expired login attempt; start again from /auth/login", 400)
        verifier, redirect_uri, _ = entry
        tok = _post_form(ACCOUNTS + "/api/token", {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": self.client_id, "code_verifier": verifier,
        })
        self._store(tok)
        return self.status()

    def _store(self, tok):
        with self.lock:
            self.tokens.update(
                client_id=self.client_id,
                access_token=tok["access_token"],
                expires_at=int(time.time()) + int(tok.get("expires_in", 3600)),
                scope=tok.get("scope", self.tokens.get("scope")),
            )
            if tok.get("refresh_token"):
                self.tokens["refresh_token"] = tok["refresh_token"]
            self._save()

    def logout(self):
        with self.lock:
            self.tokens = {"client_id": self.client_id} if self.client_id else {}
            self._save()

    def access_token(self, force_refresh=False):
        if not self.logged_in:
            raise SpotifyError("not logged in to the Spotify Web API; open /auth/login", 401)
        if force_refresh or self.tokens.get("expires_at", 0) - 60 < time.time():
            tok = _post_form(ACCOUNTS + "/api/token", {
                "grant_type": "refresh_token", "refresh_token": self.tokens["refresh_token"],
                "client_id": self.client_id,
            })
            self._store(tok)
        return self.tokens["access_token"]


class WebAPI:
    def __init__(self, auth):
        self.auth = auth

    def req(self, method, path, query=None, body=None, _retry=True, _refresh=False):
        if not path.startswith("http"):
            path = API + path
        if query:
            query = {k: v for k, v in query.items() if v is not None}
            path += ("&" if "?" in path else "?") + urllib.parse.urlencode(query)
        if isinstance(body, bytes):  # raw upload (playlist cover: base64 JPEG)
            data, ctype = body, "image/jpeg"
        else:
            data = json.dumps(body).encode() if body is not None else (b"" if method in ("PUT", "POST") else None)
            ctype = "application/json"
        req = urllib.request.Request(path, data=data, method=method, headers={
            "Authorization": "Bearer " + self.auth.access_token(force_refresh=_refresh),
            "Content-Type": ctype,
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code == 401 and _retry:
                return self.req(method, path, None, body, _retry=False, _refresh=True)
            if e.code == 429 and _retry:
                wait = int(e.headers.get("Retry-After") or 1)
                if wait <= 5:
                    time.sleep(wait)
                    return self.req(method, path, None, body, _retry=False)
            try:
                err = json.loads(raw).get("error", {})
                msg = err.get("message") if isinstance(err, dict) else str(err)
                if isinstance(err, dict) and err.get("reason"):
                    msg = f"{msg} ({err['reason']})"
            except ValueError:
                msg = raw.decode(errors="replace")[:200] or str(e)
            raise SpotifyError(f"Spotify {e.code}: {msg}", e.code if e.code < 500 else 502)
        except urllib.error.URLError as e:
            raise SpotifyError(f"cannot reach Spotify: {e.reason}", 502)
        return json.loads(raw) if raw.strip() else None

    def get(self, path, **query):
        return self.req("GET", path, query)


# ---------- normalizing ----------

URI_RX = re.compile(r"(?:spotify:|https?://open\.spotify\.com/(?:intl-[\w-]+/)?(?:embed/)?)"
                    r"(track|album|playlist|artist|episode|show|audiobook|chapter)[:/]([A-Za-z0-9]{22})")


def to_uri(s, default_type=None):
    """Spotify URI from a URI, an open.spotify.com link, or (with default_type) a bare ID."""
    m = URI_RX.search(s or "")
    if m:
        return f"spotify:{m.group(1)}:{m.group(2)}"
    if default_type and re.fullmatch(r"[A-Za-z0-9]{22}", s or ""):
        return f"spotify:{default_type}:{s}"
    raise ValueError(f"not a Spotify URI or link: {s!r}")


def _image(images):
    return images[0]["url"] if images else None


def item(o):
    """Compact form of a Web API track / episode / album / artist / playlist / show object."""
    if not o:
        return None
    t = o.get("type")
    out = {"uri": o.get("uri"), "id": o.get("id"), "type": t, "name": o.get("name")}
    if t == "track":
        album = o.get("album") or {}
        out.update(artists=[{"uri": a.get("uri"), "name": a.get("name")} for a in o.get("artists", [])],
                   album={"uri": album.get("uri"), "name": album.get("name")},
                   duration_ms=o.get("duration_ms"), explicit=o.get("explicit"),
                   track_number=o.get("track_number"), artwork=_image(album.get("images")),
                   is_local=o.get("is_local", False))
    elif t == "episode":
        show = o.get("show") or {}
        out.update(show={"uri": show.get("uri"), "name": show.get("name")}, duration_ms=o.get("duration_ms"),
                   explicit=o.get("explicit"), release_date=o.get("release_date"),
                   artwork=_image(o.get("images") or show.get("images")))
    elif t == "album":
        out.update(artists=[{"uri": a.get("uri"), "name": a.get("name")} for a in o.get("artists", [])],
                   album_type=o.get("album_type"), release_date=o.get("release_date"),
                   total_tracks=o.get("total_tracks"), artwork=_image(o.get("images")))
    elif t == "artist":
        out.update(genres=o.get("genres"), artwork=_image(o.get("images")))
    elif t == "playlist":
        items = o.get("items") or o.get("tracks") or {}
        out.update(owner=(o.get("owner") or {}).get("display_name"), description=o.get("description"),
                   public=o.get("public"), collaborative=o.get("collaborative"),
                   total=items.get("total") if isinstance(items, dict) else None,
                   artwork=_image(o.get("images")))
    elif t in ("show", "audiobook"):
        out.update(description=o.get("description"), artwork=_image(o.get("images")))
    return out


def page(p, key=None):
    """Compact a paging object; `key` picks the wrapped object (e.g. 'track' in saved-track rows)."""
    if p is None:
        return None
    rows = []
    for row in p.get("items", []):
        obj = row
        if key and isinstance(row, dict):
            obj = row.get(key) or row.get("track")
        entry = item(obj) if isinstance(obj, dict) else obj
        if entry is not None and key and isinstance(row, dict):
            for k in ("added_at", "played_at"):
                if row.get(k):
                    entry[k] = row[k]
        rows.append(entry)
    return {"items": rows, "total": p.get("total"), "offset": p.get("offset"),
            "limit": p.get("limit"), "next": bool(p.get("next"))}
