#!/usr/bin/env python3
"""Quiet hours: once the window has started (default 21:00-08:00, local time) and nothing has played for 5 minutes,
the speakers lock until the window ends. Until then music that's already going can keep going.

The server is the primary enforcer and owns the lock state (<data-dir>/quiet-hours.json). This file is also the
OS-level fallback, run every minute by a systemd user timer:

    python3 quiet_hours.py sync              # apply the lock: AirPlay receiver stopped, every output muted (or undo it)
    python3 quiet_hours.py receiver-allowed  # exit 1 while locked (ExecCondition of airplay.service)
    python3 quiet_hours.py status

When the server's heartbeat is stale, `sync` does the idle detection itself from PipeWire sink activity.
The window and grace come from <data-dir>/quiet-hours-settings.json when an admin has set them, else $QUIET_HOURS.
"""
import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

DEFAULT_WINDOW = "21:00-08:00"
GRACE = 300
HEARTBEAT_EVERY = 60
HEARTBEAT_STALE = 150
RECEIVER_UNIT = "airplay.service"
STATE_FILE = "quiet-hours.json"
OS_STATE_FILE = "quiet-hours-os.json"
SETTINGS_FILE = "quiet-hours-settings.json"
MAX_GRACE = 3 * 3600


def default_data_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.environ.get("MUSIC_API_DATA_DIR") or os.path.join(base, "music-api")


def parse_window(spec):
    """'21:00-08:00' -> (start minute, end minute); 'off' -> None."""
    spec = (spec or "").strip().lower()
    if spec in ("", "off", "none", "no", "false", "0"):
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", spec)
    if not m:
        raise ValueError(f"quiet hours must look like 21:00-08:00 or off, not {spec!r}")
    h1, m1, h2, m2 = map(int, m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise ValueError(f"invalid quiet hours {spec!r}")
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if start == end:
        raise ValueError("quiet hours start and end can't be the same")
    return start, end


def hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def clock12(minutes):
    h, m = divmod(minutes, 60)
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def in_window(window, minute):
    start, end = window
    return start <= minute < end if start < end else minute >= start or minute < end


def _at(day, minutes):
    return datetime.datetime.combine(day, datetime.time(minutes // 60, minutes % 60)).timestamp()


def bounds(window, now):
    """(start, end) epochs of the window containing `now`, or of the next one if `now` is outside it."""
    dt = datetime.datetime.fromtimestamp(now)
    today, minute = dt.date(), dt.hour * 60 + dt.minute
    day = datetime.timedelta(days=1)
    start, end = window
    if start < end:
        first = today if minute < end else today + day
        return _at(first, start), _at(first, end)
    if minute >= start:
        return _at(today, start), _at(today + day, end)
    if minute < end:
        return _at(today - day, start), _at(today, end)
    return _at(today, start), _at(today + day, end)


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(path, data):
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def settings(data_dir, default_spec=None):
    """The effective {window, grace, source, ...}: the admin's saved settings, else `default_spec` ($QUIET_HOURS)."""
    default_spec = os.environ.get("QUIET_HOURS", DEFAULT_WINDOW) if default_spec is None else default_spec
    try:
        default = parse_window(default_spec)
    except ValueError as e:
        sys.stderr.write(f"{e}; using {DEFAULT_WINDOW}\n")
        default_spec, default = DEFAULT_WINDOW, parse_window(DEFAULT_WINDOW)
    out = {"window": default, "times": default, "grace": GRACE, "source": "env", "env_window": default_spec,
           "updated_by": None, "updated_at": None}
    saved = _load(os.path.join(data_dir, SETTINGS_FILE)) if data_dir else {}
    if not saved:
        return out
    try:
        window = parse_window(saved.get("window"))
        grace = max(0, min(int(saved.get("grace_s", GRACE)), MAX_GRACE))
    except (ValueError, TypeError) as e:
        sys.stderr.write(f"quiet hours: ignoring {SETTINGS_FILE}: {e}\n")
        return out
    try:
        times = parse_window(saved.get("times")) or window
    except ValueError:
        times = window
    out.update(window=window, times=times or default, grace=grace, source="admin", updated_by=saved.get("updated_by"),
               updated_at=saved.get("updated_at"))
    return out


def _spec(window):
    return f"{hhmm(window[0])}-{hhmm(window[1])}" if window else "off"


def save_settings(data_dir, window, grace, by=None, now=None, times=None):
    """Persist an admin's window (None = off; `times` keeps the hours to show while it's off) and grace seconds.
    Read by the server and by the OS watchdog on every run."""
    _save(os.path.join(data_dir, SETTINGS_FILE), {
        "window": _spec(window), "times": _spec(window or times), "grace_s": int(grace),
        "updated_by": by, "updated_at": round(time.time() if now is None else now)})


def reset_settings(data_dir):
    try:
        os.remove(os.path.join(data_dir, SETTINGS_FILE))
    except FileNotFoundError:
        pass


class QuietHours:
    def __init__(self, window, path=None, grace=GRACE, clock=time.time):
        self.window = window
        self.path = path
        self.grace = grace
        self.clock = clock
        self.lock = threading.Lock()
        st = _load(path) if path else {}
        self.locked_until = st.get("locked_until")
        self.idle_since = st.get("idle_since")
        self.heartbeat = st.get("heartbeat")
        self.override = st.get("override")
        self._saved_at = 0

    def configure(self, window, grace):
        with self.lock:
            self.window, self.grace = window, grace
            self._persist(self.clock())

    def _unlocked_override(self, now):
        o = self.override
        return bool(o and o.get("kind") == "unlocked" and now < o.get("until", 0))

    def set_override(self, action, by=None, now=None):
        """unlock: no lock until the current (or next) window ends. lock: lock now until the window ends (only inside
        the window). clear: drop either, back to the normal rules with a fresh idle clock."""
        now = self.clock() if now is None else now
        with self.lock:
            if action == "clear":
                self.override = None
                if self.locked_until:
                    self.locked_until = None
                    self.idle_since = now if self.idle_since is not None else None
            elif not self.window:
                raise ValueError("quiet hours are off")
            elif action == "unlock":
                end = bounds(self.window, now)[1]
                self.locked_until, self.override = None, {"kind": "unlocked", "until": end, "by": by}
            elif action == "lock":
                if not self.active(now):
                    raise ValueError("quiet hours haven't started; the speakers can only be locked during the window")
                end = bounds(self.window, now)[1]
                self.locked_until, self.override = end, {"kind": "locked", "until": end, "by": by}
            else:
                raise ValueError("action must be unlock, lock or clear")
            self._persist(now)

    def active(self, now=None):
        if not self.window:
            return False
        dt = datetime.datetime.fromtimestamp(self.clock() if now is None else now)
        return in_window(self.window, dt.hour * 60 + dt.minute)

    def locked(self, now=None):
        now = self.clock() if now is None else now
        return bool(self.locked_until and now < self.locked_until and self.active(now))

    def observe(self, playing, now=None, heartbeat=True):
        """Feed the current playback state; returns "locked" or "unlocked" when that changes, else None."""
        now = self.clock() if now is None else now
        changed = None
        with self.lock:
            dirty = False
            if self.override and now >= self.override.get("until", 0):
                self.override, dirty = None, True
            if self.locked_until and not self.locked(now):
                self.locked_until, changed, dirty = None, "unlocked", True
                if self.override and self.override.get("kind") == "locked":
                    self.override = None
            if playing and self.idle_since is not None:
                self.idle_since, dirty = None, True
            elif not playing and self.idle_since is None:
                self.idle_since, dirty = now, True
            if not self.locked_until and not playing and self.active(now) and not self._unlocked_override(now):
                start, end = bounds(self.window, now)
                if now - max(self.idle_since, start) >= self.grace:
                    self.locked_until, changed, dirty = end, "locked", True
            if heartbeat:
                self.heartbeat = now
                dirty = dirty or now - self._saved_at >= HEARTBEAT_EVERY
            if dirty:
                self._persist(now)
        return changed

    def _persist(self, now):
        self._saved_at = now
        if self.path:
            try:
                _save(self.path, {"locked_until": self.locked_until, "idle_since": self.idle_since,
                                  "heartbeat": self.heartbeat, "override": self.override})
            except OSError as e:
                sys.stderr.write(f"quiet hours: couldn't save {self.path}: {e}\n")

    def until_text(self):
        return clock12(self.window[1]) if self.window else None

    def status(self, now=None):
        now = self.clock() if now is None else now
        if not self.window:
            return {"enabled": False, "window": None, "phase": "open", "locked": False}
        start, end = bounds(self.window, now)
        locked = self.locked(now)
        unlocked = self._unlocked_override(now)
        phase = "locked" if locked else "grace" if self.active(now) and not unlocked else "open"
        idle = self.idle_since
        locks_at = max(idle, start) + self.grace if phase == "grace" and idle is not None else None
        o = self.override if self.override and now < self.override.get("until", 0) else None
        if o and o["kind"] == "locked" and not locked:
            o = None
        return {"enabled": True, "window": f"{hhmm(self.window[0])}-{hhmm(self.window[1])}",
                "start": hhmm(self.window[0]), "end": hhmm(self.window[1]), "phase": phase, "locked": locked,
                "grace_s": self.grace, "idle_since": round(idle) if idle is not None else None,
                "locks_at": round(locks_at) if locks_at else None,
                "starts_at": round(start), "until": hhmm(self.window[1]), "until_ts": round(end),
                "override": {"kind": o["kind"], "until_ts": round(o["until"]), "by": o.get("by")} if o else None}


# ---------- OS-level enforcement (Linux: PipeWire/PulseAudio via pactl, systemd user units) ----------

def _run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.stderr.write(f"quiet hours: {cmd[0]}: {e}\n")
        return None


def _sinks():
    r = _run("pactl", "list", "short", "sinks") if shutil.which("pactl") else None
    if not r or r.returncode != 0:
        return []
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def audio_flowing():
    """Any output sink RUNNING (a stream is actually feeding it)."""
    return any(len(s) > 4 and s[4].strip() == "RUNNING" for s in _sinks())


def _muted(name):
    r = _run("pactl", "get-sink-mute", name)
    return bool(r and r.returncode == 0 and "yes" in r.stdout)


def receiver(action):
    """start | stop | restart the AirPlay receiver unit, if it's installed and enabled. Returns True if it ran."""
    if not shutil.which("systemctl"):
        return False
    r = _run("systemctl", "--user", "is-enabled", RECEIVER_UNIT)
    if not r or r.stdout.strip() not in ("enabled", "enabled-runtime"):
        return False
    if action == "start":
        active = _run("systemctl", "--user", "is-active", RECEIVER_UNIT)
        if active and active.stdout.strip() in ("active", "activating"):
            return True
    r = _run("systemctl", "--user", action, RECEIVER_UNIT)
    return bool(r and r.returncode == 0)


def enforce(locked, data_dir=None):
    """Locked: stop the receiver and mute every sink, remembering the previous mute state. Unlocked: undo that
    (once) and make sure the receiver is running. Safe to call repeatedly and from several processes."""
    if sys.platform != "linux":
        return
    data_dir = data_dir or default_data_dir()
    path = os.path.join(data_dir, OS_STATE_FILE)
    with open(path + ".lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        st = _load(path)
        if locked:
            sinks = [s[1] for s in _sinks() if len(s) > 1]
            if not st.get("enforced"):
                st = {"enforced": True, "mutes": {name: _muted(name) for name in sinks}}
                _save(path, st)
            for name in sinks:
                _run("pactl", "set-sink-mute", name, "1")
            receiver("stop")
        else:
            if st.get("enforced"):
                saved = st.get("mutes") or {}
                for s in _sinks():
                    if len(s) > 1:
                        _run("pactl", "set-sink-mute", s[1], "1" if saved.get(s[1]) else "0")
                _save(path, {"enforced": False})
            receiver("start")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    data_dir = default_data_dir()
    os.makedirs(data_dir, mode=0o700, exist_ok=True)
    cfg = settings(data_dir)
    qh = QuietHours(cfg["window"], os.path.join(data_dir, STATE_FILE), grace=cfg["grace"])
    now = time.time()
    if cmd == "receiver-allowed":
        return 1 if qh.locked(now) else 0
    if cmd == "status":
        print(json.dumps(qh.status(now)))
        return 0
    if cmd == "sync":
        if not qh.heartbeat or now - qh.heartbeat > HEARTBEAT_STALE:
            change = qh.observe(audio_flowing(), now, heartbeat=False)
            if change:
                sys.stderr.write(f"quiet hours: {change} (server not running; judged by sink activity)\n")
        enforce(qh.locked(now), data_dir)
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
