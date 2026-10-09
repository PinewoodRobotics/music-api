"""Playback facade over two backends.

- soloist: a local Spotify Soloist daemon, driven over its WebSocket API (push events, no polling).
  Things its API can't do (play with an offset, artist/show contexts, list devices) go through the
  Web API, targeted at the Soloist device.
- connect: any Spotify Connect device (the desktop app on a Mac, librespot on a Pi Zero, a speaker...)
  driven entirely through the Web API's /me/player endpoints. Needs Premium on the listening account.
"""
import queue as queuelib
import threading
import time

from soloist import SoloistError
from spotify import SpotifyError, item, to_uri

WS_PLAYABLE = ("track", "album", "playlist", "episode")
REPEAT_ALIASES = {"one": "track", "all": "context", "none": "off"}
# Web API `actions.disallows` keys -> the action names Soloist uses in `available_actions`
DISALLOW_KEYS = {"resuming": "play", "pausing": "pause", "seeking": "seek", "skipping_next": "skip_next",
                 "skipping_prev": "skip_prev", "toggling_shuffle": "shuffle", "toggling_repeat_context": "set_repeat"}


class PlayerError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def entity(e):
    """Soloist entity -> the same shape spotify.item() gives for Web API tracks/episodes."""
    if not e or not (e.get("uri") or e.get("entity_type")):
        return None
    d = e.get("decorations") or {}

    def name_of(ent):
        return ((ent.get("decorations") or {}).get("identity") or {}).get("name")
    covers = {c.get("size"): c.get("url") for c in (d.get("visual_identity") or {}).get("cover", [])}
    parent = (d.get("parent") or {}).get("entity") or {}
    ratings = (d.get("playback") or {}).get("content_ratings") or []
    uri = e.get("uri") or ""
    t = e.get("entity_type")
    out = {"uri": uri or None, "id": uri.rsplit(":", 1)[-1] if uri else None, "type": t,
           "name": (d.get("identity") or {}).get("name"),
           "duration_ms": (d.get("playback") or {}).get("duration_ms"),
           "explicit": "explicit" in ratings,
           "artwork": next((covers[s] for s in ("xlarge", "large", "default", "small") if covers.get(s)), None)}
    parent_ref = {"uri": parent.get("uri"), "name": name_of(parent)} if parent else None
    if t == "episode":
        out["show"] = parent_ref
    else:
        out["album"] = parent_ref
        out["artists"] = [{"uri": c["entity"].get("uri"), "name": name_of(c["entity"])}
                          for c in d.get("creators", []) if c.get("entity")]
    return out


class Player:
    def __init__(self, backend, api, soloist=None, device=None, credit_fn=None):
        self.credit_fn = credit_fn
        self._src = (None, None, [])  # (track uri, its source, Up Next seen while it played)
        self.backend = backend          # "soloist" | "connect"
        self.api = api
        self.soloist = soloist
        self.device = device            # connect mode: device name or id to target (None = active device)
        self.subs = set()
        self.subs_lock = threading.Lock()
        self.last = None
        self._cache = (0, None)
        self._last_track = None
        self._sleep = None  # {"ends_at", "fade", "cancel": Event}

    # ---------- events ----------

    def subscribe(self):
        q = queuelib.Queue(maxsize=100)
        with self.subs_lock:
            self.subs.add(q)
        return q

    def unsubscribe(self, q):
        with self.subs_lock:
            self.subs.discard(q)

    def publish(self, event, data):
        with self.subs_lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except queuelib.Full:
                pass

    def _emit_status(self):
        try:
            st = self.status(fresh=True)
        except (SpotifyError, PlayerError) as e:
            self.publish("error", {"error": str(e)})
            return
        self.last = st
        self.publish("status", st)
        uri = (st.get("track") or {}).get("uri")
        if uri != self._last_track:
            self._last_track = uri
            self.publish("track", st.get("track"))

    def on_soloist_event(self, name, msg):
        if name in ("command_result", "error"):
            return
        if name == "queue_changed":
            self.publish("queue", self._soloist_queue_from(msg))
        self._emit_status()

    def loop(self):
        """Status ticker: 1/s while anyone listens (position updates); polls the Web API in connect mode."""
        while True:
            time.sleep(1 if self.backend == "soloist" else 2)
            if self.subs:
                self._emit_status()

    # ---------- helpers ----------

    def _need_api(self, why):
        if not self.api.auth.logged_in:
            raise PlayerError(f"{why} needs the Spotify Web API; log in at /auth/login", 412)

    def _sol(self, name, **fields):
        try:
            return self.soloist.command(name, **fields)
        except SoloistError as e:
            raise PlayerError(str(e), e.status)

    def _device_id(self):
        """Web API device id to target, or None for the currently active device."""
        want = self.soloist.auth.get("device_name") if self.backend == "soloist" else self.device
        if not want:
            return None
        for d in self.api.get("/me/player/devices").get("devices", []):
            if d.get("id") == want or (d.get("name") or "").lower() == want.lower():
                return d["id"]
        raise PlayerError(f"Spotify Connect device {want!r} not found (is it online?)", 404)

    def _put(self, path, query=None, body=None, method="PUT"):
        query = dict(query or {})
        query.setdefault("device_id", self._device_id())
        return self.api.req(method, path, query, body)

    # ---------- status ----------

    def status(self, fresh=False):
        st = self._status(fresh)
        st = {**st, "source": self._source(st)}
        return {**st, "credit": self.credit_fn(st) if self.credit_fn else None}

    def _source(self, st):
        """Where the current track came from (context, queue or autoplay). Soloist only tags Up Next entries,
        so look the track up in the Up Next we saw while the previous track was playing."""
        if self.backend != "soloist":
            return None
        uri = (st.get("track") or {}).get("uri")
        upcoming = (getattr(self.soloist, "queue", None) or {}).get("upcoming") or []
        cur, source, seen = self._src
        if uri != cur:
            source = next((e.get("source") for e in seen if (e.get("item") or {}).get("uri") == uri), None)
        else:
            seen = upcoming or seen
        self._src = (uri, source, seen)
        return source

    def _status(self, fresh=False):
        if self.backend == "soloist":
            return self._soloist_status()
        now = time.time()
        if not fresh and now - self._cache[0] < 1 and self._cache[1]:
            return self._cache[1]
        st = self._connect_status()
        self._cache = (now, st)
        return st

    def _soloist_status(self):
        s = self.soloist
        pb = s.playback or {}
        opts = pb.get("options") or {}
        track = entity(pb.get("item"))
        pos = s.position_ms() if pb else 0
        return {
            "backend": "soloist", "connected": s.connected, "logged_in": bool(s.auth.get("logged_in")),
            "active": bool(s.auth.get("is_active")),
            "device": {"name": s.auth.get("device_name"), "type": "Soloist", "active": bool(s.auth.get("is_active"))},
            "state": pb.get("status", "idle"), "position_ms": pos, "position": round(pos / 1000, 3),
            "duration_ms": (track or {}).get("duration_ms"), "volume": pb.get("volume"),
            "shuffle": opts.get("shuffle"), "repeat": opts.get("repeat"),
            "track": track, "context": entity(pb.get("context")),
            "actions": sorted((pb.get("available_actions") or {}).keys()),
            "error": None if s.connected else s.last_error,
        }

    def _connect_status(self):
        self._need_api("connect backend")
        p = self.api.get("/me/player", additional_types="episode")
        if not p:
            return {"backend": "connect", "state": "idle", "active": False, "device": None, "track": None,
                    "context": None, "position_ms": 0, "position": 0, "duration_ms": None, "volume": None,
                    "shuffle": None, "repeat": None, "actions": []}
        dev = p.get("device") or {}
        track = item(p.get("item"))
        pos = p.get("progress_ms") or 0
        ctx = p.get("context") or {}
        disallows = (p.get("actions") or {}).get("disallows") or {}
        return {
            "backend": "connect", "state": "playing" if p.get("is_playing") else "paused",
            "active": bool(dev.get("is_active")),
            "device": {"id": dev.get("id"), "name": dev.get("name"), "type": dev.get("type"),
                       "active": dev.get("is_active"), "supports_volume": dev.get("supports_volume")},
            "position_ms": pos, "position": round(pos / 1000, 3), "duration_ms": (track or {}).get("duration_ms"),
            "volume": dev.get("volume_percent"), "shuffle": p.get("shuffle_state"), "repeat": p.get("repeat_state"),
            "track": track, "context": {"uri": ctx.get("uri"), "type": ctx.get("type")} if ctx else None,
            "actions": sorted({a for k, a in DISALLOW_KEYS.items() if not disallows.get(k)} | {"add_to_queue"}),
        }

    # ---------- transport ----------

    def play(self, b):
        """Body (all optional): {uri} track/episode/album/playlist/artist/show URI or link,
        {uris: [...]}, {context, offset: n|uri}, {position_ms | position}."""
        uri = to_uri(b["uri"]) if b.get("uri") else None
        uris = [to_uri(u, "track") for u in b.get("uris", [])]
        context = to_uri(b["context"]) if b.get("context") else None
        offset = b.get("offset")
        if isinstance(offset, str) and offset.isdigit():
            offset = int(offset)
        pos = b.get("position_ms", int(b["position"] * 1000) if b.get("position") is not None else None)

        if self.backend == "soloist":
            simple = not (uris or context or offset is not None or pos)
            if simple and (uri is None or uri.split(":")[1] in WS_PLAYABLE):
                self._sol("play", **({"uri": uri} if uri else {}))
                return self.status()
            self._need_api("play with uris/context/offset/position (or an artist/show URI)")

        body = {}
        if uri and uri.split(":")[1] in ("track", "episode"):
            uris = [uri] + uris
        elif uri:
            context = uri
        if uris:
            body["uris"] = uris
        if context:
            body["context_uri"] = context
        if offset is not None:
            body["offset"] = {"position": offset} if isinstance(offset, int) else {"uri": to_uri(offset, "track")}
        if pos is not None:
            body["position_ms"] = int(pos)
        self._put("/me/player/play", body=body or None)
        return self.status(fresh=True)

    def pause(self):
        if self.backend == "soloist":
            self._sol("pause")
            return self.status()
        self._put("/me/player/pause")
        return self.status(fresh=True)

    def playpause(self):
        return self.pause() if self.status(fresh=True)["state"] in ("playing", "buffering") else self.play({})

    def next(self):
        if self.backend == "soloist":
            self._sol("skip_next")
            return self.status()
        self._put("/me/player/next", method="POST")
        return self.status(fresh=True)

    def jump(self, b):
        """Skip ahead to an Up Next entry (by uid, else index), dropping the ones before it like Spotify does."""
        up = self.queue(80)["upcoming"]
        if b.get("uid"):
            idx = next((i for i, e in enumerate(up) if e.get("uid") == b["uid"]), None)
            if idx is None:
                raise PlayerError("that song isn't in Up Next anymore", 409)
        else:
            idx = int(b["index"])
            if not 0 <= idx < len(up):
                raise PlayerError("no such Up Next entry", 404)
        for _ in range(idx + 1):
            self.next()
        return self.status(fresh=True)

    def previous(self):
        if self.backend == "soloist":
            self._sol("skip_prev")
            return self.status()
        self._put("/me/player/previous", method="POST")
        return self.status(fresh=True)

    def seek(self, b):
        """Body {position: seconds} | {position_ms} | {delta: ±seconds}"""
        if "position_ms" in b:
            ms = int(b["position_ms"])
        elif "position" in b:
            ms = int(float(b["position"]) * 1000)
        else:
            ms = self.status(fresh=True)["position_ms"] + int(float(b["delta"]) * 1000)
        ms = max(0, ms)
        if self.backend == "soloist":
            self._sol("seek", position_ms=ms)
            return self.status()
        self._put("/me/player/seek", {"position_ms": ms})
        return self.status(fresh=True)

    def volume(self, b):
        """Body {volume: 0-100} | {delta: ±n}"""
        v = b["volume"] if "volume" in b else (self.status(fresh=True)["volume"] or 0) + b["delta"]
        v = max(0, min(100, int(v)))
        if self.backend == "soloist":
            self._sol("set_volume", volume=v)
            return self.status()
        self._put("/me/player/volume", {"volume_percent": v})
        return self.status(fresh=True)

    def shuffle(self, b):
        """Body {enabled?: bool}; omit to toggle"""
        en = b.get("enabled")
        if en is None:
            en = not self.status(fresh=True)["shuffle"]
        if self.backend == "soloist":
            self._sol("set_shuffle", enabled=bool(en))
            return self.status()
        self._put("/me/player/shuffle", {"state": "true" if en else "false"})
        return self.status(fresh=True)

    def repeat(self, b):
        """Body {mode?: off|context|track} (also one/all); omit to cycle off → context → track"""
        mode = b.get("mode")
        if mode is None:
            cur = self.status(fresh=True)["repeat"] or "off"
            mode = {"off": "context", "context": "track"}.get(cur, "off")
        mode = REPEAT_ALIASES.get(mode, mode)
        if mode not in ("off", "context", "track"):
            raise PlayerError("mode must be off, context or track")
        if self.backend == "soloist":
            # Soloist sets repeat with two booleans, in this order (see its WebSocket API reference).
            if mode == "track":
                self._sol("set_repeat_context", enabled=False)
                self._sol("set_repeat_track", enabled=True)
            else:
                self._sol("set_repeat_track", enabled=False)
                self._sol("set_repeat_context", enabled=mode == "context")
            return self.status()
        self._put("/me/player/repeat", {"state": mode})
        return self.status(fresh=True)

    # ---------- queue ----------

    def _soloist_queue_from(self, q):
        def rows(entries):
            return [{"uid": e.get("uid"), "source": e.get("source"), "item": entity(e.get("item"))} for e in entries]
        return {"upcoming": rows(q.get("upcoming", [])), "previous": rows(q.get("previous", []))}

    def queue(self, limit=None):
        if self.backend == "soloist":
            msg = self._sol("get_queue", limit=int(limit or 0))
            return self._soloist_queue_from(msg)
        self._need_api("queue")
        q = self.api.get("/me/player/queue")
        upcoming = [{"uid": None, "source": None, "item": item(x)} for x in q.get("queue", [])]
        return {"current": item(q.get("currently_playing")), "upcoming": upcoming[:limit] if limit else upcoming,
                "previous": []}

    def enqueue(self, b):
        """Body {uri} or {uris: [...]}: add tracks/episodes to the end of the user queue"""
        uris = [to_uri(u, "track") for u in ([b["uri"]] if b.get("uri") else b.get("uris", []))]
        if not uris:
            raise PlayerError("give uri or uris")
        for u in uris:
            if self.backend == "soloist" and u.startswith("spotify:track:"):
                self._sol("add_to_queue", uri=u)
            else:
                self._need_api(f"queueing {u.split(':')[1]}s")
                self._put("/me/player/queue", {"uri": u}, method="POST")
        return {"added": uris}

    # ---------- devices ----------

    def devices(self):
        out = []
        if self.api.auth.logged_in:
            for d in self.api.get("/me/player/devices").get("devices", []):
                out.append({"id": d.get("id"), "name": d.get("name"), "type": d.get("type"),
                            "active": d.get("is_active"), "volume": d.get("volume_percent"),
                            "restricted": d.get("is_restricted")})
        if self.backend == "soloist":
            name = self.soloist.auth.get("device_name")
            for d in out:
                d["soloist"] = d["name"] == name
            if not any(d["soloist"] for d in out):
                out.insert(0, {"id": None, "name": name, "type": "Soloist",
                               "active": bool(self.soloist.auth.get("is_active")), "soloist": True})
        return out

    def transfer(self, b):
        """Body {device: name|id|"soloist", play?: bool}: move playback to that device"""
        want = b["device"]
        if self.backend == "soloist" and want in ("soloist", self.soloist.auth.get("device_name")):
            self._sol("activate")
            if b.get("play"):
                self._sol("play")
            return self.status()
        self._need_api("transferring to another device")
        target = next((d for d in self.devices()
                       if want == d["id"] or want.lower() == (d["name"] or "").lower()), None)
        if not target or not target["id"]:
            raise PlayerError(f"device {want!r} not found", 404)
        self.api.req("PUT", "/me/player", body={"device_ids": [target["id"]], "play": bool(b.get("play"))})
        return {"transferred": target}

    # ---------- sleep timer ----------

    def sleep_status(self):
        sl = self._sleep
        if not sl:
            return {"active": False}
        return {"active": True, "ends_at": sl["ends_at"], "remaining": max(0, round(sl["ends_at"] - time.time())),
                "fade": sl["fade"]}

    def set_sleep(self, b):
        """Body {minutes, fade?: seconds (default 30)}: pause after that long, fading the volume out first"""
        self.cancel_sleep()
        secs = float(b["minutes"]) * 60
        fade = max(0, min(int(b.get("fade", 30)), secs))
        sl = {"ends_at": time.time() + secs, "fade": fade, "cancel": threading.Event()}
        self._sleep = sl

        def run():
            try:
                fade_out()
            except Exception as e:  # noqa: BLE001 - report anything, the timer thread must not die silently
                self.publish("error", {"error": f"sleep timer: {e}"})
                if self._sleep is sl:
                    self._sleep = None

        def fade_out():
            if sl["cancel"].wait(secs - fade):
                return
            start = self.status(fresh=True).get("volume") or 0
            steps = int(fade)
            for i in range(1, steps + 1):
                if sl["cancel"].wait(1):
                    self.volume({"volume": start})
                    return
                self.volume({"volume": round(start * (1 - i / steps))})
            try:
                self.pause()
            finally:
                if steps:
                    time.sleep(1)
                    self.volume({"volume": start})  # restore for next time; already paused
                if self._sleep is sl:
                    self._sleep = None
                self.publish("sleep", self.sleep_status())

        threading.Thread(target=run, daemon=True).start()
        self.publish("sleep", self.sleep_status())
        return self.sleep_status()

    def cancel_sleep(self):
        sl, self._sleep = self._sleep, None
        if sl:
            sl["cancel"].set()
            self.publish("sleep", self.sleep_status())
        return self.sleep_status()
