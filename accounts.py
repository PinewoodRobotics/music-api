"""Web app accounts: Sign in with Slack, cookie sessions, and the shared playlists people create or import.
Stdlib only.

Slack's OpenID userInfo has the real name but not the display name, so a bot token with users:read
looks that up. Sessions are random IDs stored hashed in <data-dir>/sessions.json (mode 600).
"""
import hashlib
import html
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import links

SLACK = "https://slack.com"
SESSION_TTL = 30 * 86400
ADMIN = {"id": "admin", "name": "@admin", "avatar": None, "admin": True, "kind": "token"}


class AccountError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _http_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.URLError as e:
        raise AccountError(f"Slack unreachable: {e}", 502)


class Slack:
    def __init__(self, client_id, client_secret, bot_token, redirect_uri, team_id=None, admins=()):
        self.client_id, self.client_secret, self.bot_token = client_id, client_secret, bot_token
        self.redirect_uri, self.team_id = redirect_uri, team_id
        self.admins = {a.strip().lower() for a in admins if a.strip()}  # Slack user IDs or emails
        self.pending = {}  # state -> (next path, created)
        self.lock = threading.Lock()

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and self.bot_token)

    def _call(self, method, token, **params):
        data = urllib.parse.urlencode(params).encode() if params else None
        res = _http_json(f"{SLACK}/api/{method}", data, {"Authorization": "Bearer " + token})
        if not res.get("ok"):
            raise AccountError(f"Slack {method}: {res.get('error', 'failed')}", 502)
        return res

    def team(self):
        if not self.team_id:
            self.team_id = self._call("auth.test", self.bot_token)["team_id"]
        return self.team_id

    def login_url(self, next_path="/"):
        if not self.configured:
            raise AccountError("Sign in with Slack isn't configured on this server", 503)
        state = secrets.token_urlsafe(24)
        now = time.time()
        with self.lock:
            self.pending = {s: v for s, v in self.pending.items() if now - v[1] < 600}
            self.pending[state] = (next_path if next_path.startswith("/") and not next_path.startswith("//") else "/", now)
        return f"{SLACK}/openid/connect/authorize?" + urllib.parse.urlencode({
            "response_type": "code", "scope": "openid profile email", "client_id": self.client_id, "state": state,
            "team": self.team(), "nonce": secrets.token_urlsafe(16), "redirect_uri": self.redirect_uri})

    def finish(self, code, state):
        """Exchange the callback code for the user's identity. Returns (user, next path)."""
        with self.lock:
            pending = self.pending.pop(state or "", None)
        if not pending or not code:
            raise AccountError("Sign-in link expired or invalid; try again", 400)
        tok = _http_json(f"{SLACK}/api/openid.connect.token", urllib.parse.urlencode({
            "client_id": self.client_id, "client_secret": self.client_secret,
            "code": code, "redirect_uri": self.redirect_uri}).encode())
        if not tok.get("ok"):
            raise AccountError(f"Slack sign-in failed: {tok.get('error')}", 400)
        info = self._call("openid.connect.userInfo", tok["access_token"])
        if info.get("https://slack.com/team_id") != self.team():
            raise AccountError("That Slack account isn't in the Pinewood Robotics workspace", 403)
        uid = info["https://slack.com/user_id"]
        profile = self._call("users.info", self.bot_token, user=uid)["user"].get("profile", {})
        name = profile.get("display_name") or profile.get("real_name") or info.get("name") or uid
        avatar = profile.get("image_192") or profile.get("image_72") or info.get("picture")
        email = (info.get("email") or "").lower()
        admin = uid.lower() in self.admins or (email and email in self.admins)
        return {"id": uid, "name": name, "avatar": avatar, "admin": bool(admin), "kind": "slack"}, pending[0]


class PersonalTokens:
    """One API token per Slack user, acting with that user's permissions. Stored in plaintext (mode 600) so the
    web app can show it again; regenerating replaces it."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "personal-tokens.json")
        self.lock = threading.Lock()
        self.by_user = _read_json(self.path, {})
        self.by_hash = {Sessions._key(e["token"]): uid for uid, e in self.by_user.items()}

    def get(self, user, regenerate=False):
        uid = user["id"]
        with self.lock:
            e = self.by_user.get(uid)
            if not e or regenerate:
                if e:
                    self.by_hash.pop(Sessions._key(e["token"]), None)
                e = {"token": "mapu_" + secrets.token_urlsafe(32), "created": int(time.time())}
                self.by_hash[Sessions._key(e["token"])] = uid
            e["user"] = user
            self.by_user[uid] = e
            _write_json(self.path, self.by_user)
            return {"token": e["token"], "created": e["created"]}

    def refresh(self, user):
        with self.lock:
            if user["id"] in self.by_user:
                self.by_user[user["id"]]["user"] = user
                _write_json(self.path, self.by_user)

    def check(self, given):
        if not given:
            return None
        with self.lock:
            uid = self.by_hash.get(Sessions._key(given))
            return self.by_user[uid]["user"] if uid else None


class Sessions:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "sessions.json")
        self.lock = threading.Lock()
        self.sessions = _read_json(self.path, {})

    @staticmethod
    def _key(sid):
        return hashlib.sha256(sid.encode()).hexdigest()

    def create(self, user):
        sid = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.lock:
            self.sessions = {k: s for k, s in self.sessions.items() if now - s["seen"] < SESSION_TTL}
            self.sessions[self._key(sid)] = {"user": user, "created": now, "seen": now}
            _write_json(self.path, self.sessions)
        return sid

    def get(self, sid):
        if not sid:
            return None
        now = int(time.time())
        with self.lock:
            s = self.sessions.get(self._key(sid))
            if not s or now - s["seen"] > SESSION_TTL:
                return None
            if now - s["seen"] > 3600:
                s["seen"] = now
                _write_json(self.path, self.sessions)
            return s["user"]

    def delete(self, sid):
        with self.lock:
            if self.sessions.pop(self._key(sid or ""), None):
                _write_json(self.path, self.sessions)


class Playlists:
    """The playlists the web app shows: every playlist in the Spotify account except the hidden ones,
    tagged with who created or imported them here."""

    def __init__(self, data_dir, hidden_path):
        self.path = os.path.join(data_dir, "app-playlists.json")
        self.hidden_path = hidden_path
        self.lock = threading.Lock()
        self.meta = _read_json(self.path, {})

    def hidden(self):
        entries = _read_json(self.hidden_path, {}).get("playlists", []) if self.hidden_path else []
        return {e["id"] if isinstance(e, dict) else e for e in entries}

    def is_hidden(self, playlist_id):
        return playlist_id in self.hidden()

    def _record(self, playlist_id, user, source_url=None):
        with self.lock:
            self.meta[playlist_id] = {"created_by": {k: user.get(k) for k in ("id", "name", "avatar")},
                                      "source_url": source_url,
                                      "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            _write_json(self.path, self.meta)

    def can_edit(self, playlist_id, user):
        owner = (self.meta.get(playlist_id) or {}).get("created_by") or {}
        return bool(user.get("admin") or (owner.get("id") and owner.get("id") == user.get("id")))

    def check_edit(self, playlist_id, user):
        if self.is_hidden(playlist_id):
            raise AccountError("playlist not found", 404)
        if not self.can_edit(playlist_id, user):
            raise AccountError("only whoever created this playlist can change it", 403)

    def _out(self, p, user):
        meta = self.meta.get(p["id"]) or {}
        images = p.get("images") or []
        return {"id": p["id"], "uri": p.get("uri"), "name": p.get("name"), "description": html.unescape(html.unescape(p.get("description") or "")),
                "artwork": images[0].get("url") if images else None,
                "total": ((p.get("items") or p.get("tracks") or {}).get("total")),
                "created_by": meta.get("created_by"), "source_url": meta.get("source_url"),
                "created": meta.get("created"), "can_edit": self.can_edit(p["id"], user)}

    def list(self, api, user):
        hidden, out, offset = self.hidden(), [], 0
        while True:
            res = api.get("/me/playlists", limit=50, offset=offset)
            out += [self._out(p, user) for p in res.get("items", []) if p and p["id"] not in hidden]
            offset += 50
            if not res.get("next"):
                break
        known = [p for p in out if p["created"]]
        known.sort(key=lambda p: p["created"], reverse=True)
        return known + [p for p in out if not p["created"]]

    def get(self, api, playlist_id, user):
        if self.is_hidden(playlist_id):
            raise AccountError("playlist not found", 404)
        return self._out(api.get(f"/playlists/{playlist_id}"), user)

    def create(self, api, user, name, description=""):
        name = (name or "").strip()
        if not name:
            raise AccountError("give the playlist a name")
        pl = api.req("POST", "/me/playlists", body={"name": name[:100], "description": description[:300], "public": False})
        self._record(pl["id"], user)
        return self._out(pl, user)

    def import_link(self, api, user, url):
        """Copy the songs behind a Spotify or Apple Music playlist/album link into a new playlist credited to `user`."""
        src = links.resolve(api, url)
        if src["kind"] == "track":
            raise AccountError("that's a single song; paste a playlist or album link to import")
        uris = [t["uri"] for t in src["tracks"] if t["uri"]]
        if not uris:
            raise AccountError("none of those songs are on Spotify", 422)
        pl = api.req("POST", "/me/playlists", body={"name": (src["name"] or "Imported playlist")[:100], "public": False})
        for i in range(0, len(uris), 100):
            api.req("POST", f"/playlists/{pl['id']}/items", body={"uris": uris[i:i + 100]})
        self._record(pl["id"], user, src["url"])
        return {"playlist": {**self._out(pl, user), "total": len(uris)}, "imported": len(uris), "total": src["total"],
                "truncated": src["truncated"], "source": src["source"],
                "unmatched": [{"name": t["name"], "artists": t["artists"]} for t in src["tracks"] if not t["uri"]]}

    def edit(self, api, user, playlist_id, b):
        self.check_edit(playlist_id, user)
        body = {k: b[k] for k in ("name", "description") if k in b}
        if body:
            api.req("PUT", f"/playlists/{playlist_id}", body=body)
        return self.get(api, playlist_id, user)

    def delete(self, api, user, playlist_id):
        self.check_edit(playlist_id, user)
        api.req("DELETE", "/me/library", {"uris": f"spotify:playlist:{playlist_id}"})
        with self.lock:
            if self.meta.pop(playlist_id, None):
                _write_json(self.path, self.meta)
        return {"removed": f"spotify:playlist:{playlist_id}"}


class Credits:
    """Remembers who queued or started what through the API, so the status, Up Next and the Slack feed can say so.
    Persisted to `path` (None = in memory)."""

    QUEUE_TTL = 6 * 3600
    START_TTL = 12 * 3600

    def __init__(self, path=None):
        self.path = path
        self.lock = threading.Lock()
        d = _read_json(path, {}) if path else {}
        self.by_uri = {u: [tuple(e) for e in es] for u, es in (d.get("queued") or {}).items()}  # uri -> [(user, time)] oldest first
        self.started = d.get("started")
        self.current = d.get("current")  # {uri, credit}

    @staticmethod
    def _user(user):
        return {k: user.get(k) for k in ("id", "name", "avatar")}

    def _save(self):
        if self.path:
            _write_json(self.path, {"queued": self.by_uri, "started": self.started, "current": self.current})

    def add(self, uris, user):
        now = time.time()
        with self.lock:
            for u in uris:
                self.by_uri.setdefault(u, []).append((self._user(user), now))
            cutoff = now - self.QUEUE_TTL
            self.by_uri = {u: [e for e in es if e[1] > cutoff] for u, es in self.by_uri.items()}
            self.by_uri = {u: es for u, es in self.by_uri.items() if es}
            self._save()

    def start(self, uris, user):
        with self.lock:
            self.started = {"uris": [u for u in uris if u], "user": self._user(user), "time": time.time()}
            self._save()

    def for_status(self, st):
        uri = ((st or {}).get("track") or {}).get("uri")
        if not uri:
            return None
        with self.lock:
            if self.current and self.current["uri"] == uri:
                return self.current["credit"]
            now = time.time()
            credit = None
            es = [e for e in self.by_uri.get(uri, []) if now - e[1] <= self.QUEUE_TTL]
            if es:
                credit = {"by": es.pop(0)[0], "how": "queued"}
            s = self.started
            if not credit and s and now - s["time"] <= self.START_TTL \
                    and (uri in s["uris"] or ((st.get("context") or {}).get("uri") or "\0") in s["uris"]):
                credit = {"by": s["user"], "how": "started"}
            if es:
                self.by_uri[uri] = es
            else:
                self.by_uri.pop(uri, None)
            self.current = {"uri": uri, "credit": credit}
            self._save()
            return credit

    def annotate(self, queue):
        with self.lock:
            for e in queue.get("upcoming", []):
                credits = self.by_uri.get((e.get("item") or {}).get("uri"))
                e["added_by"] = credits[-1][0] if credits and e.get("source") in (None, "queue") else None
        return queue
