"""Activity feed: who did what in the last 24 hours, for the web app's toasts and Activity log. Stdlib only.

Append-only JSON Lines at <data-dir>/activity.jsonl (mode 600). Coalesced or enriched entries are appended again
with the same id; the last line for an id wins on load. Pruning rewrites the file atomically.
"""
import collections
import json
import os
import sys
import threading
import time

TTL = 86400
PRUNE_EVERY = 3600
VOLUME_WINDOW_MS = 10000
COALESCED = {"volume": None, "playlist_reorder": "id"}
LOOKUP_KINDS = {"track": "tracks", "album": "albums", "playlist": "playlists", "artist": "artists",
                "show": "shows", "episode": "episodes", "audiobook": "audiobooks"}
MAX_LOOKUPS = 5


def origin_for(headers, bearer):
    """Where a request came from: the OS media controls, an API token, or the web app."""
    if (headers.get("X-Client-Origin") or "").startswith("media-session"):
        return "media-session"
    return "api" if bearer else "web"


def item_name(api, uri):
    kind, sid = uri.split(":")[1:3]
    path = LOOKUP_KINDS.get(kind)
    return api.get(f"/{path}/{sid}").get("name") if path else None


def track_names(api, uris, queue=None):
    """Names for track URIs: from the Soloist queue when they're in it, else at most MAX_LOOKUPS single lookups
    (batch /tracks?ids isn't available to dev-mode apps). Order follows `uris`; unknown names are skipped."""
    known = {}
    for e in (queue or {}).get("upcoming", []):
        it = e.get("item") or {}
        if it.get("uri") and it.get("name"):
            known[it["uri"]] = it["name"]
    out, lookups = [], 0
    for u in uris:
        name = known.get(u)
        if name is None and lookups < MAX_LOOKUPS:
            lookups += 1
            try:
                name = item_name(api, u)
            except Exception:  # noqa: BLE001 - a missing name must never break the action
                name = None
        if name:
            out.append(name)
    return out


class Activity:
    def __init__(self, path=None, now=time.time):
        self.path = path
        self.now = now
        self.lock = threading.Lock()
        self.publish = None
        self.entries = collections.deque()
        self.seq = 0
        self.pruned_at = now()
        self._load()

    def _cutoff(self):
        return int((self.now() - TTL) * 1000)

    def _load(self):
        by_id = {}
        if self.path and os.path.exists(self.path):
            with open(self.path) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(e, dict):
                        continue
                    if "seq" in e:
                        self.seq = max(self.seq, int(e["seq"]))
                    elif isinstance(e.get("id"), int) and isinstance(e.get("at"), int):
                        by_id[e["id"]] = e
        self.entries = collections.deque(sorted(by_id.values(), key=lambda e: e["id"]))
        if by_id:
            self.seq = max(self.seq, max(by_id))
        self._prune()

    def _append(self, entry):
        if not self.path:
            return
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            sys.stderr.write(f"activity: can't write {self.path}: {e}\n")

    def _prune(self):
        self.pruned_at = self.now()
        cutoff = self._cutoff()
        dropped = False
        while self.entries and self.entries[0]["at"] < cutoff:
            self.entries.popleft()
            dropped = True
        if not self.path or not dropped:
            return
        tmp = self.path + ".tmp"
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(json.dumps({"seq": self.seq}) + "\n")
            for e in self.entries:
                f.write(json.dumps(e) + "\n")
        os.replace(tmp, self.path)

    @staticmethod
    def _copy(e):
        return {**e, "by": dict(e["by"]), "detail": dict(e["detail"])}

    def _emit(self, entry):
        if self.publish:
            try:
                self.publish(entry)
            except Exception:  # noqa: BLE001 - subscribers must not break the request that caused the entry
                pass

    def record(self, user, action, detail=None, origin="web"):
        at = int(self.now() * 1000)
        detail = dict(detail or {})
        with self.lock:
            if self.now() - self.pruned_at > PRUNE_EVERY:
                self._prune()
            by = {k: user.get(k) for k in ("id", "name", "avatar")}
            same = COALESCED.get(action)
            prev = next((e for e in reversed(self.entries) if e["action"] == action and e["by"]["id"] == by["id"]
                         and (same is None or e["detail"].get(same) == detail.get(same))), None) \
                if action in COALESCED else None
            if prev and at - prev["at"] <= VOLUME_WINDOW_MS:
                prev["at"], prev["detail"], prev["origin"] = at, detail, origin
                entry = prev
            else:
                self.seq += 1
                entry = {"id": self.seq, "at": at, "by": by, "action": action, "detail": detail, "origin": origin}
                self.entries.append(entry)
            self._append(entry)
            out = self._copy(entry)
        self._emit(out)
        return out

    def update(self, entry_id, **detail):
        """Merge more detail into an entry (e.g. names that took a lookup) and publish it again under the same id."""
        with self.lock:
            entry = next((e for e in reversed(self.entries) if e["id"] == entry_id), None)
            if not entry:
                return None
            entry["detail"].update(detail)
            self._append(entry)
            out = self._copy(entry)
        self._emit(out)
        return out

    def enrich(self, entry, fn):
        """Run fn() -> dict of extra detail on a background thread, then update the entry. Never blocks the caller."""
        def run():
            try:
                extra = fn()
            except Exception:  # noqa: BLE001
                return
            extra = {k: v for k, v in (extra or {}).items() if v not in (None, "", [])}
            if extra:
                self.update(entry["id"], **extra)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    @property
    def latest(self):
        return self.seq

    def since(self, after=None, limit=500):
        """Entries newer than id `after` (all of the last 24 h when None), oldest first, at most `limit`.
        Without `after` the newest `limit` are kept."""
        cutoff = self._cutoff()
        with self.lock:
            rows = [e for e in self.entries if e["at"] >= cutoff and (after is None or e["id"] > after)]
            rows = rows[-limit:] if after is None else rows[:limit]
            return [self._copy(e) for e in rows]
