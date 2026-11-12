"""Sound effects: short clips registered by name and played over whatever else is playing. Stdlib only.

Clips are normalized once at registration (ffmpeg -> 48 kHz stereo 16-bit WAV, PipeWire's rate), so a play is just
a `pw-play` process on the file: a separate PipeWire stream that mixes with Spotify and AirPlay and never touches
them. Without ffmpeg only WAV uploads are accepted and stored as they are. Files live in <data-dir>/effects/<name>.wav
and the metadata in <data-dir>/effects/index.json.

Effects follow the music volume slider (Spotify's own volume, not the system volume): a play runs at its requested
volume x slider / 100, so an effect at 100 is as loud as the music. The slider comes from `slider()`, which must only
read local state (Soloist's pushed volume), never the Web API; when that has nothing (connect mode, Soloist logged
out), the last value seen in a status or volume change (note_slider) is used. It is kept in <data-dir>/effects/slider.json so a restart doesn't jump to full volume.
An admin can unhook effects from the slider ("fixed" mode, <data-dir>/effects/volume.json): plays then run at
volume x the fixed level / 100, whatever the music volume is. The same file holds play_during_quiet_hours (default
on): while quiet hours have the speakers locked, plays are still allowed and `on_quiet` is told how long to keep the
outputs open (quiet_hours.open_for_effects), then called with 0 when the last such play ends.
"""
import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from email.parser import BytesParser
from email.policy import HTTP

from accounts import _read_json, _write_json
from player import PlayerError

RATE = 48000
MAX_UPLOAD = 25 << 20
MAX_SECONDS = 120
MAX_PLAYING = 16
DEFAULT_DUCK_LEVEL = 30
DEFAULT_SLIDER = 50
VOLUME_MODES = ("follow", "fixed")
QUIET_MARGIN = 2
NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
RESERVED = {"stop", "playing"}
UA = "music-api-v2 (https://github.com/PinewoodRobotics/music-api)"


class EffectsError(PlayerError):
    pass


def log(msg):
    sys.stderr.write(f"effects: {msg}\n")


def slug(name):
    name = re.sub(r"[\s.]+", "-", str(name or "").strip().lower())
    if not NAME_RX.match(name) or name in RESERVED:
        raise EffectsError("name must be 1-48 characters: lowercase letters, digits, - and _ "
                           f"(and not {' or '.join(sorted(RESERVED))})", 400, "bad_name")
    return name


def sniff(data):
    """Container format by magic bytes, or None."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def parse_multipart(content_type, raw):
    """multipart/form-data -> {field: str, file field: bytes}; the first file part is also stored as "audio"."""
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + raw)
    out = {}
    for part in msg.iter_parts():
        field = part.get_param("name", header="content-disposition")
        if not field:
            continue
        payload = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            out[field] = payload
            out.setdefault("audio", payload)
            out.setdefault("filename", part.get_filename())
        else:
            out[field] = payload.decode("utf-8", "replace")
    return out


def _public_host(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        raise EffectsError(f"can't resolve {host}: {e}", 400, "bad_url")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise EffectsError("refusing to fetch from a private or local address", 400, "bad_url")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise EffectsError("url must be http(s)", 400, "bad_url")
    _public_host(u.hostname)


def download(url, limit=MAX_UPLOAD):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.build_opener(_SafeRedirect).open(req, timeout=20) as r:
            data = r.read(limit + 1)
    except (urllib.error.URLError, OSError) as e:
        raise EffectsError(f"couldn't fetch {url}: {e}", 502, "fetch_failed")
    if len(data) > limit:
        raise EffectsError(f"audio is larger than {limit >> 20} MB", 413, "too_large")
    return data


def player_command(binary=None):
    """(argv builder, name) for the first playback tool installed: pw-play, paplay or afplay (macOS)."""
    for tool in ([binary] if binary else ["pw-play", "paplay", "afplay"]):
        if shutil.which(tool):
            if tool == "pw-play":
                return lambda path, vol: [tool, "--media-role", "Notification", "--volume", f"{vol:.3f}", path], tool
            if tool == "paplay":
                return lambda path, vol: [tool, f"--volume={round(vol * 65536)}", path], tool
            return lambda path, vol: [tool, "-v", f"{vol:.3f}", path], tool
    return None, None


def pactl_json(*args):
    r = subprocess.run(("pactl", "--format=json") + args, capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or "pactl failed")
    return json.loads(r.stdout)


def pactl_set_volume(index, values):
    subprocess.run(["pactl", "set-sink-input-volume", str(index)] + [str(v) for v in values],
                   capture_output=True, timeout=5)


class Effects:
    def __init__(self, data_dir, popen=subprocess.Popen, ffmpeg=None, build_cmd=None, sink_inputs=None,
                 set_volume=None, clock=time.time, slider=None, on_quiet=None):
        self.dir = os.path.join(data_dir, "effects")
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        self.index_path = os.path.join(self.dir, "index.json")
        self.duck_path = os.path.join(self.dir, "duck-restore.json")
        self.slider_path = os.path.join(self.dir, "slider.json")
        self.volume_path = os.path.join(self.dir, "volume.json")
        self.popen = popen
        self.ffmpeg = shutil.which("ffmpeg") if ffmpeg is None else (ffmpeg or None)
        self.build_cmd, self.tool = (build_cmd, "custom") if build_cmd else player_command()
        self.sink_inputs = sink_inputs or (lambda: pactl_json("list", "sink-inputs"))
        self.set_volume = set_volume or pactl_set_volume
        self.clock = clock
        self.slider = slider or (lambda: None)
        self.on_quiet = on_quiet or (lambda until: None)
        self.lock = threading.Lock()
        self.slider_lock = threading.Lock()
        self.quiet_lock = threading.Lock()
        self.quiet_plays = 0
        self.quiet_until = 0
        self.slider_volume = self._clamp(_read_json(self.slider_path, {}).get("volume"), DEFAULT_SLIDER)
        self.volume_cfg = self._load_volume_cfg()
        self.index = _read_json(self.index_path, {})
        self.active = {}
        self.ducks = 0
        self.restore_ducked()

    # ---------- registry ----------

    def _path(self, name):
        return os.path.join(self.dir, name + ".wav")

    def _entry(self, name):
        e = self.index.get(name)
        if not e:
            raise EffectsError(f"no sound effect named '{name}'", 404, "unknown_effect")
        return e

    def _public(self, name, e):
        return {"name": name, **e, "playing": sum(1 for p in self.active.values() if p["name"] == name)}

    def list(self):
        with self.lock:
            return [self._public(n, e) for n, e in sorted(self.index.items())]

    def get(self, name):
        with self.lock:
            return self._public(name, self._entry(name))

    def normalize(self, data):
        """Validate `data` and return WAV bytes ready to play. Raises EffectsError."""
        if len(data) > MAX_UPLOAD:
            raise EffectsError(f"audio is larger than {MAX_UPLOAD >> 20} MB", 413, "too_large")
        fmt = sniff(data)
        if not fmt:
            raise EffectsError("not a wav, mp3, ogg or flac file", 415, "unsupported_format")
        if not self.ffmpeg:
            if fmt != "wav":
                raise EffectsError(f"{fmt} needs ffmpeg on the server; upload a PCM wav instead", 501, "ffmpeg_missing")
            return data
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "in"), os.path.join(tmp, "out.wav")
            with open(src, "wb") as f:
                f.write(data)
            try:
                r = subprocess.run([self.ffmpeg, "-nostdin", "-loglevel", "error", "-i", src, "-vn", "-ac", "2",
                                    "-ar", str(RATE), "-c:a", "pcm_s16le", "-t", str(MAX_SECONDS + 1), dst],
                                   capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                raise EffectsError("converting the audio took too long", 413, "too_long")
            if r.returncode != 0 or not os.path.exists(dst):
                raise EffectsError(f"couldn't decode that audio: {r.stderr.strip()[-200:] or 'unknown error'}",
                                   415, "undecodable")
            with open(dst, "rb") as f:
                return f.read()

    @staticmethod
    def info(wav):
        try:
            with wave.open(io.BytesIO(wav)) as w:
                frames, rate = w.getnframes(), w.getframerate()
                return {"duration_ms": round(frames * 1000 / rate) if rate else 0, "rate": rate,
                        "channels": w.getnchannels()}
        except (wave.Error, EOFError, ZeroDivisionError) as e:
            raise EffectsError(f"couldn't read that wav (try 16-bit PCM): {e}", 415, "undecodable")

    def register(self, name, data, title=None, volume=None, source=None, overwrite=False):
        name = slug(name)
        vol = self._volume(volume, 100)
        wav = self.normalize(data)
        meta = self.info(wav)
        if meta["duration_ms"] > MAX_SECONDS * 1000:
            raise EffectsError(f"effects are limited to {MAX_SECONDS} seconds", 413, "too_long")
        if meta["duration_ms"] <= 0:
            raise EffectsError("that audio is empty", 415, "undecodable")
        with self.lock:
            if name in self.index and not overwrite:
                raise EffectsError(f"'{name}' already exists (pass overwrite=true to replace it)", 409, "exists")
            tmp = self._path(name) + ".tmp"
            with open(tmp, "wb") as f:
                f.write(wav)
            os.replace(tmp, self._path(name))
            created = self.index.get(name, {}).get("created") or int(self.clock())
            self.index[name] = {"title": (str(title)[:100] if title else None), "volume": vol, "created": created,
                                "updated": int(self.clock()), "size": len(wav), "source": source, **meta}
            self._save()
            return self._public(name, self.index[name])

    def register_url(self, name, url, **kw):
        return self.register(name, download(url), source=url, **kw)

    def update(self, name, changes):
        with self.lock:
            e = self._entry(name)
            new = slug(changes["name"]) if changes.get("name") not in (None, "") else name
            if "title" in changes:
                e["title"] = str(changes["title"])[:100] if changes["title"] else None
            if "volume" in changes:
                e["volume"] = self._volume(changes["volume"], 100)
            if new != name:
                if new in self.index:
                    raise EffectsError(f"'{new}' already exists", 409, "exists")
                os.replace(self._path(name), self._path(new))
                self.index[new] = self.index.pop(name)
            e["updated"] = int(self.clock())
            self._save()
            return self._public(new, self.index[new])

    def delete(self, name):
        with self.lock:
            self._entry(name)
            ids = [i for i, p in self.active.items() if p["name"] == name]
        for i in ids:
            self._kill(i)
        with self.lock:
            del self.index[name]
            try:
                os.remove(self._path(name))
            except FileNotFoundError:
                pass
            self._save()
        return {"deleted": name}

    def _save(self):
        _write_json(self.index_path, self.index)

    @staticmethod
    def _volume(value, default):
        if value is None or value == "":
            return default
        v = float(value)
        if not 0 <= v <= 100:
            raise ValueError("volume must be 0-100")
        return round(v)

    # ---------- music volume slider ----------

    @staticmethod
    def _clamp(value, default):
        try:
            return max(0, min(100, round(float(value))))
        except (TypeError, ValueError):
            return default

    def note_slider(self, volume):
        """Remember the music slider position (0-100); None is ignored. Cheap when it hasn't changed."""
        if volume is None:
            return
        v = self._clamp(volume, None)
        if v is None or v == self.slider_volume:
            return
        with self.slider_lock:
            self.slider_volume = v
            try:
                _write_json(self.slider_path, {"volume": v})
            except OSError as e:
                log(f"couldn't persist the slider volume: {e}")

    def current_slider(self):
        try:
            self.note_slider(self.slider())
        except Exception as e:  # noqa: BLE001 - a broken volume source must not stop the effect
            log(f"can't read the music volume: {e}")
        return self.slider_volume

    # ---------- effects volume: follow the slider or a fixed level ----------

    def _load_volume_cfg(self):
        saved = _read_json(self.volume_path, {})
        return {"mode": saved.get("mode") if saved.get("mode") in VOLUME_MODES else "follow",
                "level": self._clamp(saved.get("level"), None),
                "play_during_quiet_hours": saved.get("play_during_quiet_hours") is not False,
                "updated_by": saved.get("updated_by"), "updated_at": saved.get("updated_at")}

    def volume_settings(self):
        cfg = dict(self.volume_cfg)
        media = self.current_slider()
        return {**cfg, "level": media if cfg["level"] is None else cfg["level"], "media_volume": media}

    def set_volume_settings(self, mode=None, level=None, by=None, play_during_quiet_hours=None):
        cfg = dict(self.volume_cfg)
        if play_during_quiet_hours is not None:
            cfg["play_during_quiet_hours"] = self._bool(play_during_quiet_hours, "play_during_quiet_hours")
        if mode is not None:
            if mode not in VOLUME_MODES:
                raise ValueError("mode must be follow or fixed")
            cfg["mode"] = mode
        if level is not None and level != "":
            cfg["level"] = self._volume(level, None)
        if cfg["mode"] == "fixed" and cfg["level"] is None:
            cfg["level"] = self.current_slider()
        cfg.update(updated_by=by, updated_at=round(self.clock()))
        _write_json(self.volume_path, cfg)
        self.volume_cfg = cfg
        return self.volume_settings()

    @staticmethod
    def _bool(value, field):
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("1", "true", "yes", "on"):
            return True
        if str(value).lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{field} must be true or false")

    def plays_during_quiet_hours(self):
        return self.volume_cfg["play_during_quiet_hours"]

    def _level(self):
        cfg = self.volume_cfg
        if cfg["mode"] == "fixed" and cfg["level"] is not None:
            return cfg["level"], "fixed"
        return self.current_slider(), "media"

    # ---------- playback ----------

    def _notify_quiet(self, until):
        try:
            self.on_quiet(until)
        except Exception as e:  # noqa: BLE001 - the effect still plays if the outputs can't be opened
            log(f"can't open the outputs for quiet hours: {e}")

    def _open_quiet(self, duration_ms):
        with self.quiet_lock:
            self.quiet_plays += 1
            self.quiet_until = max(self.quiet_until, self.clock() + duration_ms / 1000 + QUIET_MARGIN)
            self._notify_quiet(self.quiet_until)

    def _close_quiet(self):
        with self.quiet_lock:
            self.quiet_plays -= 1
            if self.quiet_plays <= 0:
                self.quiet_plays, self.quiet_until = 0, 0
                self._notify_quiet(0)

    def play(self, name, volume=None, duck=False, duck_level=None, quiet=False):
        """quiet: quiet hours have the speakers locked and this play was allowed through; the outputs are opened
        for it and closed again when the last such play ends."""
        if not self.build_cmd:
            raise EffectsError("no audio player found (needs pw-play, paplay or afplay)", 501, "no_player")
        level = self._volume(duck_level, DEFAULT_DUCK_LEVEL)
        slider, source = self._level()
        if quiet:
            self._open_quiet(self.get(name)["duration_ms"])
        try:
            return self._start(name, volume, duck, level, slider, source, quiet)
        except BaseException:
            if quiet:
                self._close_quiet()
            raise

    def _start(self, name, volume, duck, level, slider, source, quiet):
        with self.lock:
            e = self._entry(name)
            if len(self.active) >= MAX_PLAYING:
                raise EffectsError(f"already playing {MAX_PLAYING} effects", 429, "too_many")
            vol = self._volume(volume, e["volume"])
            effective = round(vol * slider / 100, 1)
            try:
                proc = self.popen(self.build_cmd(self._path(name), effective / 100), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except OSError as e2:
                raise EffectsError(f"couldn't start {self.tool}: {e2}", 500, "play_failed")
            pid = secrets.token_hex(4)
            rec = {"id": pid, "name": name, "volume": vol, "slider_volume": slider, "volume_source": source,
                   "effective_volume": effective, "duck": bool(duck), "started_at": self.clock(),
                   "duration_ms": e["duration_ms"], "quiet_hours": bool(quiet), "proc": proc}
            self.active[pid] = rec
            if duck:
                self._duck(level)
        threading.Thread(target=self._watch, args=(pid,), daemon=True).start()
        return {k: v for k, v in rec.items() if k != "proc"}

    def _watch(self, pid):
        proc = self.active[pid]["proc"]
        err = b""
        try:
            _, err = proc.communicate()
        except (OSError, ValueError):
            pass
        with self.lock:
            p = self.active.pop(pid, None)
            if p and p["duck"]:
                self._unduck()
        if p and p["quiet_hours"]:
            self._close_quiet()
        if p and proc.returncode and proc.returncode > 0:
            log(f"{p['name']}: {self.tool} exited {proc.returncode}: {(err or b'').decode('utf-8', 'replace').strip()[-200:]}")

    def playing(self):
        now = self.clock()
        with self.lock:
            return [{"id": p["id"], "name": p["name"], "volume": p["volume"], "slider_volume": p["slider_volume"],
                     "volume_source": p["volume_source"], "effective_volume": p["effective_volume"], "duck": p["duck"],
                     "started_at": p["started_at"], "elapsed_ms": round((now - p["started_at"]) * 1000),
                     "duration_ms": p["duration_ms"]} for p in self.active.values()]

    def _kill(self, pid):
        with self.lock:
            p = self.active.get(pid)
        if p and p["proc"].poll() is None:
            try:
                p["proc"].terminate()
            except OSError:
                pass

    def stop(self, name=None):
        with self.lock:
            ids = [i for i, p in self.active.items() if name is None or p["name"] == name]
        for i in ids:
            self._kill(i)
        return {"stopped": len(ids)}

    # ---------- ducking: lower the other PipeWire streams while an effect plays, then put them back ----------

    def _own(self, props):
        pids = {str(p["proc"].pid) for p in self.active.values()}
        return str(props.get("application.process.id")) in pids or props.get("application.name") in ("pw-play", "paplay")

    def _duck(self, level):
        self.ducks += 1
        if self.ducks > 1:
            return
        try:
            inputs = self.sink_inputs()
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            log(f"can't duck: {e}")
            return
        saved = {}
        for si in inputs:
            vols = [v["value"] for v in (si.get("volume") or {}).values()]
            if not vols or self._own(si.get("properties") or {}):
                continue
            saved[str(si["index"])] = vols
            self.set_volume(si["index"], [round(v * level / 100) for v in vols])
        self._save_duck(saved)

    def _unduck(self):
        self.ducks = max(0, self.ducks - 1)
        if self.ducks == 0:
            self.restore_ducked()

    def restore_ducked(self):
        """Put every stream we lowered back where it was. Also run at startup, after a crash mid-duck."""
        saved = _read_json(self.duck_path, {})
        if not saved:
            return
        try:
            live = {str(si["index"]) for si in self.sink_inputs()}
        except (OSError, ValueError, subprocess.SubprocessError):
            live = set()
        for index, vols in saved.items():
            if index in live:
                self.set_volume(index, vols)
        self._save_duck({})

    def _save_duck(self, saved):
        try:
            if saved:
                _write_json(self.duck_path, saved)
            elif os.path.exists(self.duck_path):
                os.remove(self.duck_path)
        except OSError as e:
            log(f"couldn't persist the duck state: {e}")
