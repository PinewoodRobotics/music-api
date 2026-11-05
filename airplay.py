"""AirPlay now-playing from shairport-sync's metadata pipe, and remote control of the sender over its D-Bus interface.

shairport-sync writes items like
    <item><type>636f7265</type><code>6d696e6d</code><length>5</length>
    <data encoding="base64">
    SGVsbG8=</data></item>
where type and code are four ASCII characters in hex ("core" "minm" = title) and data is base64. Codes used here:
core minm/asar/asal/astm (title, artist, album, length in ms); ssnc pbeg/pend (play session begin/end),
abeg/aend (active state begin/end), paus/pres/prsm/pfls (pause, resume, flush), prgr ("start/current/end" RTP
frames), phbt (heartbeat while frames play; also starts a session we missed the beginning of, e.g. after
a server restart), snam (sender name), PICT (cover art bytes), mdst/mden (bundle markers), copl (AirPlay 2 command
plist: the only source of the song's position, since prgr is classic-only).
"""
import base64
import collections
import datetime
import hashlib
import json
import os
import plistlib
import re
import select
import stat
import subprocess
import sys
import threading
import time
import urllib.parse

DEFAULT_PIPE = "/tmp/shairport-sync-metadata"
RTP_RATE = 44100
RECENT_ART = 8
END_AFTER_PEND = 15
MAX_BUFFER = 16 << 20
ITEM = re.compile(rb"<item><type>([0-9a-fA-F]{8})</type><code>([0-9a-fA-F]{8})</code><length>(\d+)</length>"
                  rb"(?:\s*<data encoding=\"base64\">([A-Za-z0-9+/=\s]*)</data>)?\s*</item>")


BUS_NAME = "org.gnome.ShairportSync"
BUS_PATH = "/org/gnome/ShairportSync"
BUS_INTERFACE = "org.gnome.ShairportSync.RemoteControl"
REMOTE_METHODS = {"play": "Play", "pause": "Pause", "next": "Next", "previous": "Previous"}
SINK_NAME = "AirPlay"
MAX_ART = 16 << 20
NOW_PLAYING = "kMRMediaRemoteNowPlayingInfo"


def log(msg):
    sys.stderr.write(f"airplay: {msg}\n")


class RemoteError(Exception):
    def __init__(self, message, status=502, code="airplay_remote_failed"):
        super().__init__(message)
        self.status, self.code = status, code


def bus_env():
    env = {**os.environ}
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return env


def bus_json(args, run=subprocess.run):
    """busctl --user --json=short <args>, parsed; None if the receiver's bus isn't reachable."""
    try:
        r = run(["busctl", "--user", "--timeout=3", "--json=short"] + list(args), capture_output=True, text=True,
                timeout=6, env=bus_env())
        return json.loads(r.stdout)["data"] if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return None


def _unwrap(v):
    return v["data"] if isinstance(v, dict) and "data" in v else v


def probe_dbus(run=subprocess.run):
    """What shairport-sync's D-Bus interface says about the session, or None if it can't be reached. {"active": bool}
    plus, while active: state, sender, title, artist, album, duration_ms, progress ("start/current/end" RTP frames)
    and art_path."""
    active = bus_json(["get-property", BUS_NAME, BUS_PATH, BUS_NAME, "Active"], run)
    if active is None:
        return None
    if not active:
        return {"active": False}
    out = {"active": True}
    got = bus_json(["call", BUS_NAME, BUS_PATH, "org.freedesktop.DBus.Properties", "GetAll", "s", BUS_INTERFACE], run)
    props = got[0] if isinstance(got, list) and got and isinstance(got[0], dict) else {}
    props = {k: _unwrap(v) for k, v in props.items()}
    meta = {k: _unwrap(v) for k, v in (props.get("Metadata") or {}).items()} if isinstance(props.get("Metadata"), dict) else {}
    artist = meta.get("xesam:artist")
    length = meta.get("mpris:length")
    art = meta.get("mpris:artUrl")
    out.update(state=str(props.get("PlayerState") or "").lower(),
               sender=props.get("ClientName") or None,
               client=props.get("Client") or None,
               title=meta.get("xesam:title") or None,
               artist=(", ".join(artist) if isinstance(artist, list) else artist) or None,
               album=meta.get("xesam:album") or None,
               duration_ms=round(length / 1000) if isinstance(length, int) and length > 0 else None,
               progress=props.get("ProgressString") or None,
               art_path=urllib.parse.unquote(urllib.parse.urlparse(art).path) if isinstance(art, str) and art else None)
    return out


def probe_sink(run=subprocess.run):
    """Fallback when D-Bus is unreachable: is shairport-sync's PipeWire/Pulse stream uncorked (audio flowing)?"""
    try:
        r = run(["pactl", "--format=json", "list", "sink-inputs"], capture_output=True, text=True, timeout=6,
                env=bus_env())
        inputs = json.loads(r.stdout) if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    for i in inputs if isinstance(inputs, list) else []:
        props = i.get("properties") or {}
        if props.get("application.name") == SINK_NAME and not i.get("corked"):
            return {"active": True, "state": "playing"}
    return {"active": False}


def remote(action, run=subprocess.run):
    """Send play/pause/next/previous to the AirPlay sender through shairport-sync's own RemoteControl interface on the
    session bus (dbus_service_bus = "session"). shairport-sync finds the sender's DACP service and holds its
    Active-Remote token, so none of that is reimplemented here. Needs busctl (systemd)."""
    method = REMOTE_METHODS[action]
    base = ["busctl", "--user", "--timeout=3"]
    env = bus_env()

    def busctl(*args):
        try:
            r = run(base + list(args), capture_output=True, text=True, timeout=6, env=env)
        except FileNotFoundError:
            raise RemoteError("busctl isn't installed, so AirPlay can't be controlled from here", 503,
                              "airplay_remote_unavailable")
        except subprocess.TimeoutExpired:
            raise RemoteError("the AirPlay receiver didn't answer", 504)
        if r.returncode != 0:
            raise RemoteError("couldn't reach the AirPlay receiver's D-Bus interface (is it built with D-Bus and "
                              f"dbus_service_bus = \"session\"?): {(r.stderr or '').strip()}", 503,
                              "airplay_remote_unavailable")
        return r.stdout

    if "false" in busctl("get-property", BUS_NAME, BUS_PATH, BUS_INTERFACE, "Available").lower():
        # shairport-sync 5.6 leaves Available false for the whole of an AirPlay 2 session, though commands work.
        try:
            stream = busctl("get-property", BUS_NAME, BUS_PATH, BUS_INTERFACE, "StreamType").lower()
        except RemoteError:
            stream = ""
        if "buffered" not in stream and "realtime" not in stream:
            raise RemoteError("the device playing over AirPlay doesn't accept remote control", 409,
                              "airplay_remote_unavailable")
    busctl("call", BUS_NAME, BUS_PATH, BUS_INTERFACE, method)


class Parser:
    """Incremental parser: feed() raw pipe bytes, get back complete (type, code, payload bytes) items."""

    def __init__(self):
        self.buf = b""

    def feed(self, chunk):
        self.buf += chunk
        out = []
        while True:
            m = ITEM.search(self.buf)
            if not m:
                break
            try:
                kind, code = bytes.fromhex(m.group(1).decode()).decode("latin-1"), \
                    bytes.fromhex(m.group(2).decode()).decode("latin-1")
                data = base64.b64decode(re.sub(rb"\s+", b"", m.group(4))) if m.group(4) else b""
                out.append((kind, code, data))
            except ValueError:
                pass
            self.buf = self.buf[m.end():]
        start = self.buf.rfind(b"<item>")
        if start > 0:
            self.buf = self.buf[start:]
        elif start < 0:
            self.buf = self.buf[-16:]
        if len(self.buf) > MAX_BUFFER:
            self.buf = b""
        return out


def image_type(data):
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "application/octet-stream"


class AirPlay:
    def __init__(self, pipe=DEFAULT_PIPE, clock=time.time, probe=None, sink_probe=None, state_path=None):
        self.pipe = pipe
        self.state_path = state_path
        self.clock = clock
        self.probe = probe or probe_dbus
        self.sink_probe = sink_probe or probe_sink
        self.lock = threading.RLock()
        self.on_start = None
        self.on_end = None
        self.on_change = None
        self.art = None
        self.recent_art = collections.OrderedDict()
        self._ignore_until = 0
        self._clear(forget=False)

    def _clear(self, forget=True):
        if forget:
            self._forget_sender()
        self.active = False
        self.client = None
        self.recovered = False
        self.playing = False
        self.sender = None
        self.title = self.artist = self.album = None
        self.duration_ms = None
        self.art = None
        self.started_at = None
        self._anchor = None   # (position_ms, at)
        self._rtp = None      # (start, end) frames of the current track
        self._pend_at = None

    # ---------- state machine ----------

    def handle(self, kind, code, data):
        events = []
        with self.lock:
            now = self.clock()
            text = data.decode("utf-8", "replace") if data else ""
            if kind == "core":
                if code == "minm":
                    if text != self.title:
                        self.art = None
                        self._anchor = None
                    self.title = text or None
                elif code == "asar":
                    self.artist = text or None
                elif code == "asal":
                    self.album = text or None
                elif code == "astm" and len(data) >= 4:
                    self.duration_ms = int.from_bytes(data[:4], "big") or None
                else:
                    return
            elif kind == "ssnc":
                if code in ("pbeg", "abeg"):
                    self._pend_at = None
                    if not self.active:
                        self.active, self.started_at = True, now
                        events.append("start")
                    if code == "pbeg":
                        self._set_playing(True, now)
                elif code == "pend":
                    self._set_playing(False, now)
                    self._pend_at = now
                elif code == "aend":
                    if self.active:
                        events.append("end")
                    self._clear()
                elif code in ("paus", "pfls"):
                    self._set_playing(False, now)
                elif code in ("pres", "prsm", "phb0", "phbt"):
                    was = self.playing
                    if code in ("pres", "phb0", "phbt") and not self.active and now >= self._ignore_until:
                        self.active, self.started_at = True, now
                        events.append("start")
                    if self.active:
                        self._set_playing(True, now)
                        if code == "phbt":
                            self._heartbeat(text, now)
                    if code in ("pres", "prsm"):
                        self._pend_at = None
                    elif was == self.playing:
                        return
                elif code == "prgr":
                    self._progress(text, now)
                elif code == "copl":
                    if not self._now_playing(data, now):
                        return
                elif code == "snam":
                    self.sender = text or None
                    self._save_sender()
                elif code == "clip":
                    self.client = text or None
                    self._save_sender()
                elif code == "PICT":
                    self.art = (data, image_type(data), hashlib.sha1(data).hexdigest()[:12]) if data else None
                    if self.art:
                        self.recent_art[self.art[2]] = self.art[:2]
                        while len(self.recent_art) > RECENT_ART:
                            self.recent_art.popitem(last=False)
                else:
                    return
            else:
                return
        self._fire(events)

    def _set_playing(self, playing, now):
        if playing == self.playing:
            return
        self._anchor = (self._position(now), now) if self._anchor else None
        self.playing = playing

    def _progress(self, text, now):
        try:
            start, cur, end = (int(x) for x in text.split("/"))
        except ValueError:
            return
        span = (end - start) & 0xFFFFFFFF
        if span:
            self.duration_ms = round(span * 1000 / RTP_RATE)
        self._rtp = (start, end)
        self._anchor = (max(0, round(((cur - start) & 0xFFFFFFFF) * 1000 / RTP_RATE)), now)

    def _now_playing(self, data, now):
        try:
            command = plistlib.loads(data)
            params = command["params"]
            if command["type"] != "updateMRNowPlayingInfo" or params["type"] != "npi-text":
                return False
            info = params["params"]
            title = info.get(NOW_PLAYING + "Title")
            elapsed = info.get(NOW_PLAYING + "ElapsedTime")
            rate = info.get(NOW_PLAYING + "PlaybackRate")
            stamp = info.get(NOW_PLAYING + "Timestamp")
        except Exception:  # noqa: BLE001 - a sender's malformed plist must not stop the pipe reader
            return False
        # shairport-sync writes PICT and minm after this item, so a new title has to be taken now: taken at minm it
        # would clear the art and position that belong to the new song.
        if isinstance(title, str) and title != self.title:
            self.art = None
            self._anchor = None
            self.title = title or None
        if isinstance(elapsed, (int, float)) and elapsed >= 0:
            if isinstance(rate, (int, float)) and rate > 0 and isinstance(stamp, datetime.datetime):
                elapsed += max(0, now - stamp.replace(tzinfo=datetime.timezone.utc).timestamp())
            self._anchor = (round(elapsed * 1000), now)
        return True

    def _heartbeat(self, text, now):
        try:
            frame = int(text.split("/")[0])
        except ValueError:
            return
        if self._rtp:
            start, end = self._rtp
            into = (frame - start) & 0xFFFFFFFF
            if into <= ((end - start) & 0xFFFFFFFF) + RTP_RATE:
                self._anchor = (round(into * 1000 / RTP_RATE), now)

    def _position(self, now):
        if not self._anchor:
            return 0
        pos, at = self._anchor
        if self.playing:
            pos += (now - at) * 1000
        return int(min(pos, self.duration_ms) if self.duration_ms else pos)

    def recover(self, info):
        """Adopt a session that was already running (server restarted mid-song) from a probe result."""
        with self.lock:
            now = self.clock()
            if self.active or now < self._ignore_until:
                return False
            self.active, self.recovered, self.started_at = True, True, now
            self.playing = info.get("state", "playing") != "paused"
            self.client = info.get("client")
            self.sender = info.get("sender") or self._saved_sender()
            self.title, self.artist, self.album = info.get("title"), info.get("artist"), info.get("album")
            self.duration_ms = info.get("duration_ms")
            if info.get("progress"):
                self._progress(info["progress"], now)
            art = self._read_art(info.get("art_path"))
            if art:
                self.art = (art, image_type(art), hashlib.sha1(art).hexdigest()[:12])
                self.recent_art[self.art[2]] = self.art[:2]
        self._fire(["start"])
        return True

    def _save_sender(self):
        if not self.state_path or not (self.sender or self.client):
            return
        try:
            with open(self.state_path, "w") as f:
                json.dump({"sender": self.sender, "client": self.client}, f)
        except OSError as e:
            log(f"couldn't persist the AirPlay sender: {e}")

    def _forget_sender(self):
        if self.state_path:
            try:
                os.remove(self.state_path)
            except FileNotFoundError:
                pass
            except OSError as e:
                log(f"couldn't clear the AirPlay sender: {e}")

    def _saved_sender(self):
        if not self.state_path:
            return None
        try:
            with open(self.state_path) as f:
                saved = json.load(f)
            sender, client = saved.get("sender"), saved.get("client")
        except (OSError, ValueError, AttributeError):
            return None
        if client and self.client and client != self.client:
            return None
        if not self.client:
            self.client = client
        return sender if isinstance(sender, str) and sender else None

    @staticmethod
    def _read_art(path):
        if not path:
            return None
        try:
            with open(path, "rb") as f:
                return f.read(MAX_ART) or None
        except OSError:
            return None

    def poll(self):
        """Notice a session this process didn't see begin (or one that ended unseen). The metadata pipe is the
        primary source; this covers a restart mid-song, when no further session-begin item is coming."""
        with self.lock:
            active, recovered = self.active, self.recovered
        if active and not recovered:
            return
        info = self.probe()
        if info is None and not active:
            info = self.sink_probe()
        if info is None:
            return
        if not active and not info["active"] and not self.sender:
            self._forget_sender()
        if not active and info["active"]:
            self.recover(info)
        elif recovered and not info["active"]:
            with self.lock:
                self._clear()
            self._fire(["end"])

    def watch(self, interval=3):
        while True:
            try:
                self.poll()
            except Exception as e:  # noqa: BLE001 - must keep watching
                log(f"watch: {e!r}")
            time.sleep(interval)

    def tick(self):
        """End a session that sent pend but no aend (older builds, a dropped sender)."""
        with self.lock:
            stale = self.active and self._pend_at and self.clock() - self._pend_at >= END_AFTER_PEND
            if stale:
                self._clear()
        if stale:
            self._fire(["end"])

    def end_session(self):
        """Forget the session now (after the receiver was restarted to kick the sender off)."""
        with self.lock:
            was = self.active
            self._clear()
            # heartbeats still sitting in the pipe from before the restart must not revive the session
            self._ignore_until = self.clock() + 5
        if was:
            self._fire(["end"])
        return was

    def _fire(self, events):
        for ev in events:
            fn = self.on_start if ev == "start" else self.on_end
            if fn:
                try:
                    fn()
                except Exception as e:  # noqa: BLE001 - a callback failing must not stop the pipe reader
                    log(f"{ev} handler: {e!r}")
        if self.on_change:
            try:
                self.on_change()
            except Exception as e:  # noqa: BLE001
                log(f"change handler: {e!r}")

    # ---------- views ----------

    def snapshot(self):
        with self.lock:
            if not self.active:
                return None
            pos = self._position(self.clock())
            art = f"/api/airplay/artwork?v={self.art[2]}" if self.art else None
            track = {"uri": None, "id": None, "type": "airplay", "name": self.title or "AirPlay",
                     "artists": [{"uri": None, "name": self.artist}] if self.artist else [],
                     "album": {"uri": None, "name": self.album} if self.album else None,
                     "duration_ms": self.duration_ms, "explicit": False, "artwork": art}
            return {"active": True, "state": "playing" if self.playing else "paused", "sender": self.sender,
                    "track": track, "position_ms": pos, "duration_ms": self.duration_ms,
                    "started_at": round(self.started_at) if self.started_at else None}

    def artwork(self):
        with self.lock:
            return self.art[:2] if self.art and self.active else None

    def artwork_by_hash(self, key):
        with self.lock:
            return self.recent_art.get(key)

    # ---------- pipe reader ----------

    def loop(self):
        missing_logged = False
        while True:
            try:
                st = os.stat(self.pipe)
                if not stat.S_ISFIFO(st.st_mode):
                    raise FileNotFoundError
                missing_logged = False
                self._read(st.st_ino)
            except FileNotFoundError:
                if not missing_logged:
                    log(f"no metadata pipe at {self.pipe} yet (receiver not installed or not started)")
                    missing_logged = True
            except OSError as e:
                log(f"pipe: {e}")
            self.tick()
            time.sleep(5)

    def _read(self, ino):
        # O_RDWR keeps a writer end open ourselves, so the read side never hits EOF when shairport-sync restarts
        # and the open itself never blocks waiting for a writer.
        fd = os.open(self.pipe, os.O_RDWR | os.O_NONBLOCK)
        parser, checked = Parser(), time.time()
        try:
            while True:
                ready, _, _ = select.select([fd], [], [], 1)
                if ready:
                    try:
                        chunk = os.read(fd, 1 << 16)
                    except BlockingIOError:
                        chunk = b""
                    for item in parser.feed(chunk):
                        self.handle(*item)
                self.tick()
                if time.time() - checked > 30:
                    checked = time.time()
                    if os.stat(self.pipe).st_ino != ino:
                        return
        finally:
            os.close(fd)
