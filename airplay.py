"""AirPlay now-playing from shairport-sync's metadata pipe.

shairport-sync writes items like
    <item><type>636f7265</type><code>6d696e6d</code><length>5</length>
    <data encoding="base64">
    SGVsbG8=</data></item>
where type and code are four ASCII characters in hex ("core" "minm" = title) and data is base64. Codes used here:
core minm/asar/asal/astm (title, artist, album, length in ms); ssnc pbeg/pend (play session begin/end),
abeg/aend (active state begin/end), paus/pres/prsm/pfls (pause, resume, flush), prgr ("start/current/end" RTP
frames), phbt (heartbeat while frames play), snam (sender name), PICT (cover art bytes), mdst/mden (bundle markers).
"""
import base64
import hashlib
import os
import re
import select
import stat
import sys
import threading
import time

DEFAULT_PIPE = "/tmp/shairport-sync-metadata"
RTP_RATE = 44100  # shairport-sync 4.x reports AirPlay 2 progress in 44.1 kHz RTP frames
END_AFTER_PEND = 15
MAX_BUFFER = 16 << 20
ITEM = re.compile(rb"<item><type>([0-9a-fA-F]{8})</type><code>([0-9a-fA-F]{8})</code><length>(\d+)</length>"
                  rb"(?:\s*<data encoding=\"base64\">([A-Za-z0-9+/=\s]*)</data>)?\s*</item>")


def log(msg):
    sys.stderr.write(f"airplay: {msg}\n")


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
    def __init__(self, pipe=DEFAULT_PIPE, clock=time.time):
        self.pipe = pipe
        self.clock = clock
        self.lock = threading.RLock()
        self.on_start = None   # called (outside the lock) when a session starts
        self.on_end = None     # ...and when it ends
        self.on_change = None  # any visible change
        self.art = None
        self._clear()

    def _clear(self):
        self.active = False
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
                elif code == "snam":
                    self.sender = text or None
                elif code == "PICT":
                    self.art = (data, image_type(data), hashlib.sha1(data).hexdigest()[:12]) if data else None
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
