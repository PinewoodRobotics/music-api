"""API tokens: create / list / revoke at runtime. No scopes; every token can do everything, including
managing other tokens. Only SHA-256 hashes are stored, in <data-dir>/api-tokens.json (mode 600)."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class TokenError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


class Tokens:
    def __init__(self, data_dir, static=None):
        self.path = os.path.join(data_dir, "api-tokens.json")
        self.legacy_path = os.path.join(data_dir, "token")
        self.static_hash = _hash(static) if static else None  # --token / $MUSIC_API_TOKEN: accepted, not listed
        self.lock = threading.Lock()
        self.tokens = []
        self._dirty_at = None
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.tokens = json.load(f).get("tokens", [])

    def _save(self):
        tmp = self.path + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump({"tokens": self.tokens}, f, indent=1)
        os.replace(tmp, self.path)
        self._dirty_at = None

    def _add(self, token, name):
        entry = {"id": secrets.token_hex(4), "name": name or "unnamed", "hash": _hash(token),
                 "prefix": token[:9], "created": int(time.time()), "last_used": None}
        self.tokens.append(entry)
        self._save()
        return entry

    def bootstrap(self, required):
        """Import <data-dir>/token (e.g. the migrated v1 token) once; if auth is required and there are
        no tokens at all, generate one and write it there for the admin to read."""
        with self.lock:
            if self.tokens:
                return None
            if os.path.exists(self.legacy_path):
                with open(self.legacy_path) as f:
                    tok = f.read().strip()
                if tok:
                    self._add(tok, "v1 token")
                    return "imported"
            if required and not self.static_hash:
                tok = "mapi_" + secrets.token_urlsafe(32)
                with open(os.open(self.legacy_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                    f.write(tok)
                self._add(tok, "initial")
                return "generated"
            return None

    @property
    def enabled(self):
        return bool(self.tokens or self.static_hash)

    def check(self, given):
        """Return the matching token entry ({} for the static token), or None."""
        if not given:
            return None
        h = _hash(given)
        match = None
        with self.lock:
            for e in self.tokens:  # compare against every entry so timing doesn't reveal which matched
                if hmac.compare_digest(h, e["hash"]):
                    match = e
            if match is not None:
                now = int(time.time())
                if not match["last_used"] or now - match["last_used"] > 60:
                    match["last_used"] = now
                    self._save()
                return match
        if self.static_hash and hmac.compare_digest(h, self.static_hash):
            return {}
        return None

    def list(self, current=None):
        with self.lock:
            return [{k: e[k] for k in ("id", "name", "prefix", "created", "last_used")}
                    | {"current": bool(current) and e["id"] == current.get("id")} for e in self.tokens]

    def create(self, name=None):
        tok = "mapi_" + secrets.token_urlsafe(32)
        with self.lock:
            e = self._add(tok, name)
        return {"id": e["id"], "name": e["name"], "token": tok, "prefix": e["prefix"], "created": e["created"]}

    def revoke(self, token_id):
        with self.lock:
            e = next((e for e in self.tokens if e["id"] == token_id), None)
            if not e:
                raise TokenError(f"no token with id {token_id!r}", 404)
            if len(self.tokens) == 1 and not self.static_hash:
                raise TokenError("refusing to revoke the last token (create another one first)", 409)
            self.tokens.remove(e)
            self._save()
        return {"revoked": token_id, "name": e["name"]}
