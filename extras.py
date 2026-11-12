"""Things Spotify's APIs don't provide: lyrics (LRCLIB), system audio (PipeWire / macOS), artwork proxy."""
import json
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

UA = "music-api-v2 (https://github.com/PinewoodRobotics/music-api)"


class ExtrasError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg)
        self.status = status


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "application/octet-stream")


# ---------- lyrics ----------

_lyrics_cache = {}
LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


def parse_lrc(text):
    lines = []
    for raw in (text or "").splitlines():
        m = LRC_LINE.match(raw.strip())
        if m:
            lines.append({"time_ms": int((int(m.group(1)) * 60 + float(m.group(2))) * 1000), "text": m.group(3).strip()})
    return lines


def lyrics(track):
    """Look up lyrics for a track dict (name, artists, album, duration_ms) on lrclib.net."""
    if not track or track.get("type") not in ("track", None):
        raise ExtrasError("lyrics are only available for songs", 404)
    key = track.get("uri") or track.get("name")
    if key in _lyrics_cache:
        return _lyrics_cache[key]
    q = {"track_name": track["name"], "artist_name": ", ".join(a["name"] for a in track.get("artists") or [] if a.get("name"))}
    if (track.get("album") or {}).get("name"):
        q["album_name"] = track["album"]["name"]
    if track.get("duration_ms"):
        q["duration"] = round(track["duration_ms"] / 1000)
    try:
        body, _ = _get("https://lrclib.net/api/get?" + urllib.parse.urlencode(q))
        res = json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise ExtrasError(f"lrclib: HTTP {e.code}")
        # exact match failed; fall back to search on title + first artist
        s = {"track_name": track["name"], "artist_name": (track.get("artists") or [{}])[0].get("name", "")}
        try:
            body, _ = _get("https://lrclib.net/api/search?" + urllib.parse.urlencode(s))
            hits = json.loads(body)
        except (urllib.error.URLError, ValueError) as e2:
            raise ExtrasError(f"lrclib: {e2}")
        if not hits:
            raise ExtrasError("no lyrics found", 404)
        res = hits[0]
    except (urllib.error.URLError, ValueError) as e:
        raise ExtrasError(f"lrclib: {e}")
    out = {"source": "lrclib.net", "instrumental": bool(res.get("instrumental")),
           "synced": parse_lrc(res.get("syncedLyrics")), "plain": res.get("plainLyrics"),
           "match": {"track": res.get("trackName"), "artist": res.get("artistName"), "album": res.get("albumName")}}
    _lyrics_cache[key] = out
    return out


def current_line(lyr, position_ms):
    idx = -1
    for i, line in enumerate(lyr.get("synced") or []):
        if line["time_ms"] <= position_ms:
            idx = i
        else:
            break
    return idx


# ---------- artwork proxy ----------

_art_cache = {}
_art_lock = threading.Lock()


def fetch_image(url):
    if not re.match(r"https://([a-z0-9-]+\.)*(scdn\.co|spotifycdn\.com)/", url or ""):
        raise ExtrasError("refusing to proxy a non-Spotify image URL", 400)
    with _art_lock:
        if url in _art_cache:
            return _art_cache[url]
    try:
        out = _get(url)
    except urllib.error.URLError as e:
        raise ExtrasError(f"artwork fetch failed: {e}")
    with _art_lock:
        if len(_art_cache) > 50:
            _art_cache.clear()
        _art_cache[url] = out
    return out


# ---------- system audio ----------

def _run(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise ExtrasError(f"{cmd[0]}: {r.stderr.strip() or 'failed'}", 500)
    return r.stdout


def system_backend():
    if sys.platform == "darwin":
        return "macos"
    if shutil.which("wpctl"):
        return "pipewire"
    if shutil.which("pactl"):
        return "pulseaudio"
    return None


def system_volume():
    b = system_backend()
    if b == "macos":
        s = json.loads(_run("osascript", "-l", "JavaScript", "-e",
                            "JSON.stringify((()=>{const a=Application.currentApplication();a.includeStandardAdditions=true;"
                            "const v=a.getVolumeSettings();return {volume:v.outputVolume,muted:v.outputMuted}})())"))
        return {"backend": b, **s}
    if b == "pipewire":
        out = _run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")  # "Volume: 0.40 [MUTED]"
        m = re.search(r"([\d.]+)", out)
        return {"backend": b, "volume": round(float(m.group(1)) * 100) if m else None, "muted": "MUTED" in out}
    if b == "pulseaudio":
        vol = re.search(r"(\d+)%", _run("pactl", "get-sink-volume", "@DEFAULT_SINK@"))
        mute = "yes" in _run("pactl", "get-sink-mute", "@DEFAULT_SINK@")
        return {"backend": b, "volume": int(vol.group(1)) if vol else None, "muted": mute}
    raise ExtrasError("no supported system mixer (needs PipeWire, PulseAudio or macOS)", 501)


def set_system_volume(b):
    """Body {volume?: 0-100, delta?: ±n, muted?: bool}"""
    cur = system_volume()
    vol = b.get("volume")
    if vol is None and "delta" in b:
        vol = (cur["volume"] or 0) + int(b["delta"])
    be = cur["backend"]
    if vol is not None:
        vol = max(0, min(100, int(vol)))
        if be == "macos":
            _run("osascript", "-e", f"set volume output volume {vol}")
        elif be == "pipewire":
            _run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{vol / 100:.2f}")
        else:
            _run("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%")
    if b.get("muted") is not None:
        m = bool(b["muted"])
        if be == "macos":
            _run("osascript", "-e", f"set volume output muted {'true' if m else 'false'}")
        elif be == "pipewire":
            _run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if m else "0")
        else:
            _run("pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if m else "0")
    return system_volume()


def system_outputs():
    """Audio sinks (PipeWire / PulseAudio). On macOS only the volume is controllable."""
    b = system_backend()
    if b in ("pipewire", "pulseaudio") and shutil.which("pactl"):
        default = _run("pactl", "get-default-sink").strip()
        sinks = json.loads(_run("pactl", "--format=json", "list", "sinks"))
        return [{"id": s.get("name"), "name": s.get("description"), "default": s.get("name") == default,
                 "state": s.get("state"), "driver": s.get("driver")} for s in sinks]
    if b == "pipewire":  # wpctl only: parse the Sinks section of `wpctl status`
        out, sinks, in_sinks = _run("wpctl", "status"), [], False
        for line in out.splitlines():
            if "Sinks:" in line:
                in_sinks = True
                continue
            if in_sinks:
                m = re.match(r"[\s│├└─]*(\*)?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:.*)?$", line)
                if not m:
                    break
                sinks.append({"id": m.group(2), "name": m.group(3).strip(), "default": bool(m.group(1))})
        return sinks
    raise ExtrasError("output listing needs PipeWire or PulseAudio", 501)


def set_system_output(b):
    """Body {id}: make that sink the default output"""
    be = system_backend()
    if be == "pipewire" and str(b["id"]).isdigit():
        _run("wpctl", "set-default", str(b["id"]))
    elif be in ("pipewire", "pulseaudio"):
        _run("pactl", "set-default-sink", str(b["id"]))
    else:
        raise ExtrasError("output switching needs PipeWire or PulseAudio", 501)
    return system_outputs()
