#!/usr/bin/env python3
"""Music API v2: HTTP API and web remote for Spotify. Stdlib only; runs on Linux (incl. headless Pi) and macOS.

    python3 server.py [--host 127.0.0.1] [--port 8765] [--token SECRET] [--client-id ID]
    python3 server.py auth          # log in to the Spotify Web API from a terminal (SSH-friendly)

Playback goes through a local Spotify Soloist daemon when one is running with --ws (Linux), otherwise
through the Web API against any Spotify Connect device. Search, library and playlists use the Web API.
Visit http://127.0.0.1:8765/ for the web remote, or GET /api for the endpoint list.
"""
import argparse
import html
import json
import os
import queue as queuelib
import re
import secrets
import sys
import threading
import urllib.parse
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import activity as activity_log
import airplay as airplay_mod
import effects as effects_mod
import extras
import quiet_hours
import links
import slack_bot
import system_stats
import updater as updater_mod
from accounts import ADMIN, SESSION_COOKIE_AGE, AccountError, Admins, Credits, PersonalTokens, Google, Playlists, Sessions, Slack
from effects import EffectsError
from extras import ExtrasError
from guard import Guard
from library import Library
from activity import Activity
from player import REPEAT_ALIASES, Player, PlayerError
from soloist import Soloist, SoloistError, default_data_dir as soloist_data_dir
from spotify import Auth, SpotifyError, WebAPI, item, page, to_uri
from tokens import TokenError, Tokens

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH_TYPES = "track,album,artist,playlist,show,episode,audiobook"

auth = api = player = soloist = tokens = slack = google = sessions = app_playlists = bot = personal = library = None
credits = activity = None
guard = airplay = quiet = effects = None
admins = stats = updates = None
DATA_DIR = None
QUIET_DEFAULT = quiet_hours.DEFAULT_WINDOW
_req = threading.local()  # per-request context: the token entry and the user that authenticated it
WEB_DIST = os.path.join(HERE, "web", "dist")
SESSION_COOKIE = "mapi_session"
APP_ERRORS = (SpotifyError, PlayerError, ExtrasError, TokenError, AccountError, links.LinkError, EffectsError,
              system_stats.StatsError, updater_mod.UpdateError)
# Slack users (non-admins) get playback, search and the app's playlists, not the account's private data or admin routes
ADMIN_ONLY = re.compile(r"^/(api$|api/(tokens|spotify|backend/soloist|library|recent|top|me$|devices/transfer|admin)"
                        r"|auth(/login|/paste|/logout|$))")
ADMIN_ONLY_METHODS = {("GET", "/api/playlists"), ("POST", "/api/playlists"), ("POST", "/api/system/outputs"),
                      ("POST", "/api/effects")}
EFFECT_PATH = re.compile(r"^/api/effects/[^/]+$")
DOC_FILES = {"/llms.txt": ("llms.txt", "text/plain"), "/llms-full.txt": ("llms-full.txt", "text/plain"),
             "/LLMS.md": ("llms-full.txt", "text/markdown"), "/API.md": ("API.md", "text/markdown"),
             "/README.md": ("README.md", "text/markdown")}


# ---------- HTTP routing ----------

ROUTES = []


def route(method, pattern):
    rx = re.compile("^" + re.sub(r"{(\w+)}", r"(?P<\1>[^/]+)", pattern) + "$")

    def deco(fn):
        ROUTES.append((method, rx, pattern, fn.__doc__ or "", fn))
        return fn
    return deco


def _uris(q, b):
    raw = b.get("uris") or (b.get("uri") and [b["uri"]]) or (q.get("uris") or "").split(",")
    uris = [to_uri(u.strip()) for u in raw if u and u.strip()]
    if not uris:
        raise ValueError("give uris")
    return uris


def _limit(q, default=20, cap=50):
    return min(int(q.get("limit", default)), cap)


# ---------- activity feed ----------

def _log(action, detail=None):
    """Record a successful action by the current user; returns the entry so callers can enrich it later."""
    return activity.record(_req.user, action, detail, _req.origin)


def _credit_skip():
    if not (airplay and airplay.snapshot()):
        credits.skipped(_req.user)


def _playing_name():
    try:
        return (player.status().get("track") or {}).get("name")
    except (SpotifyError, PlayerError):
        return None


def _log_play_item(b):
    ref = b.get("context") or b.get("uri") or (b.get("uris") or [None])[0]
    uri = to_uri(ref, "track")
    entry = _log("play_item", {"uri": uri, "type": uri.split(":")[1]})
    activity.enrich(entry, lambda: {"name": activity_log.item_name(api, uri)})


def _log_playlist(action, playlist_id, **detail):
    entry = _log(action, {"id": playlist_id, **detail})
    if "name" not in detail:
        activity.enrich(entry, lambda: {"name": activity_log.item_name(api, f"spotify:playlist:{playlist_id}")})
    return entry


# ---------- playback ----------

@route("GET", "/api/status")
def _status(q, b):
    """Playback state, position, volume, shuffle/repeat, current track/episode, context, device, backend"""
    return player.status(fresh=True)


@route("GET", "/api/now-playing")
def _now_playing(q, b):
    """Just the current track/episode (or null)"""
    return player.status()["track"]


@route("GET", "/api/artwork")
def _artwork(q, b):
    """Current cover image: 302 to Spotify's CDN, or ?proxy=1 to get the bytes (for devices without HTTPS).
    During AirPlay: the sender's cover art bytes"""
    if airplay and airplay.snapshot():
        return _airplay_artwork(q, b)
    art = (player.status().get("track") or {}).get("artwork")
    if not art:
        raise PlayerError("nothing playing / no artwork", 404)
    return extras.fetch_image(art) if q.get("proxy") else ("redirect", art)


def _current_track():
    t = player.status(fresh=True).get("track")
    if not t:
        raise PlayerError("nothing playing", 404)
    return t


@route("GET", "/api/airplay")
def _airplay(q, b):
    """AirPlay session: {active, state: playing|paused, sender, track {name, artists, album, artwork, duration_ms},
    position_ms, duration_ms, started_at, resume_spotify} or {active: false}. Also folded into /api/status as
    source "airplay" while a session is on"""
    ap = airplay.snapshot() if airplay else None
    return {**ap, "resume_spotify": guard.resume_after} if ap else {"active": False}


@route("GET", "/api/airplay/artwork")
def _airplay_artwork(q, b):
    """Cover art the AirPlay sender sent for the current song (bytes); 404 if none"""
    art = airplay.artwork() if airplay else None
    if not art:
        raise PlayerError("no AirPlay artwork", 404)
    return art


@route("POST", "/api/airplay/stop")
def _airplay_stop(q, b):
    """End the AirPlay session (restarts the receiver, which disconnects the sender; it can reconnect a few seconds
    later). Spotify then resumes if it was playing when AirPlay took over. 409 airplay_inactive if there's none"""
    sender = (airplay.snapshot() or {}).get("sender") if airplay else None
    res = guard.stop_airplay()
    _log("airplay_stop", {"sender": sender} if sender else {})
    return res


@route("GET", "/api/quiet-hours")
def _quiet_hours(q, b):
    """Quiet hours: {enabled, window: "21:00-08:00", phase: open|grace|locked, locked, idle_since, locks_at,
    until: "08:00", until_ts, starts_at, grace_s}. After the window starts the speakers lock once nothing has played
    for grace_s seconds; while locked, play/resume/skip are refused with 423 {"error": "quiet_hours", "until"}"""
    return quiet.status()


@route("GET", "/api/lyrics")
def _lyrics(q, b):
    """Lyrics for the current song (or ?track=id), synced line-by-line when available (lrclib.net).
    Includes position_ms and the index of the current line"""
    if q.get("track"):
        t = item(api.get(f"/tracks/{to_uri(q['track'], 'track').split(':')[2]}"))
        pos = None
    else:
        st = player.status(fresh=True)
        t, pos = st.get("track"), st.get("position_ms")
        if not t:
            raise PlayerError("nothing playing", 404)
    out = dict(extras.lyrics(t), track={"uri": t["uri"], "name": t["name"]})
    if pos is not None:
        out["position_ms"] = pos
        out["line"] = extras.current_line(out, pos)
    return out


@route("GET", "/api/sleep")
def _sleep(q, b):
    """Sleep timer state"""
    return player.sleep_status()


@route("POST", "/api/sleep")
def _set_sleep(q, b):
    """Body {minutes, fade?: seconds}: pause after N minutes, fading out over the last `fade` seconds (default 30)"""
    return player.set_sleep(b)


@route("DELETE", "/api/sleep")
def _cancel_sleep(q, b):
    """Cancel the sleep timer"""
    return player.cancel_sleep()


@route("GET", "/api/system/volume")
def _sys_volume(q, b):
    """Machine's output volume (PipeWire / PulseAudio / macOS), separate from Spotify's own volume"""
    return extras.system_volume()


@route("POST", "/api/system/volume")
def _set_sys_volume(q, b):
    """Body {volume?: 0-100, delta?: ±n, muted?: bool}"""
    return extras.set_system_volume(b)


@route("GET", "/api/system/outputs")
def _sys_outputs(q, b):
    """Audio outputs (sinks) on this machine, e.g. the USB speakers (Linux)"""
    return extras.system_outputs()


@route("POST", "/api/system/outputs")
def _set_sys_output(q, b):
    """Body {id}: make that output the default (Linux)"""
    return extras.set_system_output(b)


# ---------- sound effects ----------

def _flag(v):
    return v is True or str(v).lower() in ("1", "true", "yes", "on")


def _effect_fields(q, b):
    return {k: b.get(k) if b.get(k) is not None else q.get(k) for k in ("title", "volume")}


@route("GET", "/api/effects")
def _effects(q, b):
    """Registered sound effects: [{name, title, volume, duration_ms, size, source, created, updated, playing}]"""
    return effects.list()


@route("POST", "/api/effects")
def _register_effect(q, b):
    """Register a sound effect (admins only). Send the audio as the raw body (Content-Type audio/* or
    application/octet-stream) with ?name=slug, or multipart/form-data with `name` and a `file` part, or JSON
    {name, url} to fetch it. wav, mp3, ogg or flac, max 25 MB and 120 s; converted once to 48 kHz stereo wav
    (mp3/ogg/flac need ffmpeg on the server). Optional title, volume (0-100, the default play volume) and overwrite.
    409 exists if the name is taken"""
    name = b.get("name") or q.get("name")
    fields = {**_effect_fields(q, b), "overwrite": _flag(b.get("overwrite", q.get("overwrite")))}
    audio = b.get("audio")
    if isinstance(audio, bytes):
        return effects.register(name, audio, **fields)
    if b.get("url") or q.get("url"):
        return effects.register_url(name, b.get("url") or q.get("url"), **fields)
    raise EffectsError("send audio as the request body (or multipart `file`), or JSON {name, url}", 400, "no_audio")


@route("GET", "/api/effects/playing")
def _effects_playing(q, b):
    """Effects playing right now: [{id, name, volume, duck, started_at, elapsed_ms, duration_ms}]"""
    return effects.playing()


@route("POST", "/api/effects/stop")
def _effects_stop(q, b):
    """Stop every playing effect (or only those called `name`). Music is not touched. Returns {stopped: n}"""
    return effects.stop(b.get("name") or q.get("name"))


@route("GET", "/api/effects/{name}")
def _effect(q, b, name):
    """One sound effect's metadata; 404 unknown_effect"""
    return effects.get(name)


@route("PATCH", "/api/effects/{name}")
def _patch_effect(q, b, name):
    """Body {name?, title?, volume?} (admins only): rename or change the default play volume (0-100)"""
    return effects.update(name, b)


@route("DELETE", "/api/effects/{name}")
def _delete_effect(q, b, name):
    """Delete a sound effect (admins only); stops it if it is playing"""
    return effects.delete(name)


@route("POST", "/api/effects/{name}/play")
def _play_effect(q, b, name):
    """Play a sound effect now, over whatever is playing (its own PipeWire stream; music is not paused). Returns at
    once with {id, name, volume, duck, duration_ms, started_at}. Body/query optional: volume (0-100, default the
    effect's own), duck (bool: lower the other streams while it plays, to duck_level % of their volume, default 30).
    Plays may overlap. 423 quiet_hours while the speakers are locked"""
    guard.check("effect")
    opts = {**q, **b}
    return effects.play(name, opts.get("volume"), _flag(opts.get("duck")), opts.get("duck_level"))


@route("POST", "/api/play")
def _play(q, b):
    """Play/resume. Body optional: {uri} (track, album, playlist, artist, episode, show; URI or open.spotify.com link),
    {uris: [...]}, {context, offset: index|uri}, {position: seconds | position_ms}, {shuffle?: bool} (set before playing).
    During AirPlay only the empty body works (resumes the sender); anything else is 409 airplay_active"""
    if b.get("shuffle") is not None:
        player.shuffle({"enabled": bool(b["shuffle"])})
    res = player.play({k: v for k, v in b.items() if k != "shuffle"})
    named = [to_uri(b[k]) for k in ("uri", "context") if b.get(k)] + [to_uri(u, "track") for u in b.get("uris", [])]
    if named:
        credits.start(named, _req.user)
        _log_play_item(b)
    else:
        _log("play")
    return res


@route("POST", "/api/play-url")
def _play_url(q, b):
    """Body {url}: play any open.spotify.com / spotify: link"""
    res = player.play({"uri": b["url"]})
    credits.start([to_uri(b["url"])], _req.user)
    _log_play_item({"uri": b["url"]})
    return res


@route("POST", "/api/pause")
def _pause(q, b):
    """Pause. During AirPlay: pauses the sender"""
    res = player.pause()
    _log("pause")
    return res


@route("POST", "/api/playpause")
def _playpause(q, b):
    """Toggle play/pause (the AirPlay sender's, during AirPlay)"""
    was_playing = player.status().get("state") in ("playing", "buffering")
    res = player.playpause()
    _log("pause" if was_playing else "play")
    return res


@route("POST", "/api/next")
def _next(q, b):
    """Skip to next (the AirPlay sender's, during AirPlay)"""
    _credit_skip()
    name = _playing_name()
    res = player.next()
    _log("next", {"from": name} if name else {})
    return res


@route("POST", "/api/previous")
def _previous(q, b):
    """Previous track (restarts the current one if it's past the first few seconds). During AirPlay: the sender's"""
    _credit_skip()
    name = _playing_name()
    res = player.previous()
    _log("previous", {"from": name} if name else {})
    return res


@route("POST", "/api/back")
def _back(q, b):
    """Alias of /api/previous (v1 compatibility)"""
    return _previous(q, b)


@route("POST", "/api/seek")
def _seek(q, b):
    """Body {position: seconds} | {position_ms} | {delta: ±seconds}"""
    res = player.seek(b)
    ms = int(b["position_ms"]) if "position_ms" in b else int(float(b["position"]) * 1000) if "position" in b \
        else res.get("position_ms")
    _log("seek", {"position_ms": max(0, ms)} if ms is not None else {})
    return res


@route("POST", "/api/volume")
def _volume(q, b):
    """Body {volume: 0-100} | {delta: ±n}"""
    res = player.volume(b)
    vol = max(0, min(100, int(b["volume"]))) if "volume" in b else res.get("volume")
    _log("volume", {"volume": vol})
    return res


@route("POST", "/api/shuffle")
def _shuffle(q, b):
    """Body {enabled?: bool}; omit to toggle"""
    enabled = b.get("enabled")
    if enabled is None:
        enabled = not player.status().get("shuffle")
    res = player.shuffle(b)
    _log("shuffle", {"enabled": bool(enabled)})
    return res


@route("POST", "/api/repeat")
def _repeat(q, b):
    """Body {mode?: off|context|track} (one/all accepted); omit to cycle"""
    mode = b.get("mode")
    if mode is None:
        mode = {"off": "context", "context": "track"}.get(player.status().get("repeat") or "off", "off")
    res = player.repeat(b)
    _log("repeat", {"mode": REPEAT_ALIASES.get(mode, mode)})
    return res


@route("GET", "/api/activity")
def _activity(q, b):
    """What people did in the last 24 h, oldest first: {entries: [{id, at (unix ms), by {id, name, avatar}, action,
    detail, origin: web|slack|api|media-session}], latest}. ?since=<id> returns only newer entries; ?limit= (default and max 500).
    Also pushed live as the `activity` SSE event"""
    since = int(q["since"]) if q.get("since") else None
    return {"entries": activity.since(since, min(int(q.get("limit", 500)), 500)), "latest": activity.latest}


@route("GET", "/api/queue")
def _queue(q, b):
    """Upcoming (and, with Soloist, previous) queue entries, each with added_by {id, name, avatar} when someone
    queued it through this API. ?limit=n (Soloist: up to 80)"""
    return credits.annotate(player.queue(int(q["limit"]) if q.get("limit") else None))


@route("POST", "/api/queue")
def _enqueue(q, b):
    """Body {uri} | {uris: [...]}: add to the end of the queue"""
    res = player.enqueue(b)
    credits.add(res["added"], _req.user)
    uris = res["added"]
    entry = _log("queue_add", {"uris": uris, "count": len(uris)})
    activity.enrich(entry, lambda: {"names": activity_log.track_names(
        api, uris, player.queue(80) if player.backend == "soloist" else None)})
    return res


@route("POST", "/api/queue/remove")
def _queue_remove(q, b):
    """Body {uid} | {uids: [...]} | {index}: remove entries from Up Next (any signed-in user). Soft: they're hidden from
    every queue view and skipped the moment they start. 404 if one isn't in Up Next. Returns the queue"""
    res = player.remove_from_queue(b, _req.user)
    names = [(e.get("item") or {}).get("name") for e in res["removed"]]
    _log("queue_remove", {"names": [n for n in names if n], "count": len(res["removed"])})
    return credits.annotate(res["queue"])


@route("POST", "/api/queue/jump")
def _queue_jump(q, b):
    """Body {uid} (Soloist) or {index}: skip ahead to that Up Next entry, dropping the ones before it"""
    credits.skipped(_req.user)
    target = None
    try:
        up = player.queue(80)["upcoming"]
        e = next((x for x in up if x.get("uid") == b["uid"]), None) if b.get("uid") else \
            up[int(b["index"])] if 0 <= int(b.get("index", -1)) < len(up) else None
        target = ((e or {}).get("item") or {}).get("name")
    except (SpotifyError, PlayerError, KeyError, ValueError):
        pass
    res = player.jump(b)
    _log("jump", {"name": target} if target else {})
    return res


@route("GET", "/api/devices")
def _devices(q, b):
    """Spotify Connect devices on the account (plus the local Soloist device)"""
    return player.devices()


@route("POST", "/api/devices/transfer")
def _transfer(q, b):
    """Body {device: name|id|"soloist", play?: bool}: move playback to a device"""
    return player.transfer(b)


@route("GET", "/api/backend")
def _backend(q, b):
    """Which playback backend is in use and how it's doing"""
    out = {"backend": player.backend, "web_api": auth.status()}
    if soloist:
        out["soloist"] = {"connected": soloist.connected, "endpoint": soloist.endpoint(),
                          "data_dir": soloist.data_dir, "error": soloist.last_error, **soloist.auth}
    return out


@route("POST", "/api/backend/soloist/{verb}")
def _soloist_verb(q, b, verb):
    """activate | deactivate: claim or release active-device status for Soloist"""
    if not soloist or verb not in ("activate", "deactivate"):
        raise PlayerError("unknown verb or no Soloist backend", 404)
    try:
        soloist.command(verb)
    except SoloistError as e:
        raise PlayerError(str(e), e.status)
    return player.status()


# ---------- catalog ----------

@route("GET", "/api/search")
def _search(q, b):
    """?q=&type=track,album,artist,playlist,...&limit=(max 10)&offset=. Returns {type: page}"""
    res = api.get("/search", q=q["q"], type=q.get("type", "track,album,artist,playlist"),
                  limit=_limit(q, 10, 10), offset=q.get("offset"))
    return {k: page(v) for k, v in res.items()}


@route("GET", "/api/tracks/{id}")
def _track(q, b, id):
    """One track; id may be 'current'. Adds saved: bool"""
    if id == "current":
        t = player.status()["track"]
        if not t or not t.get("id"):
            raise PlayerError("nothing playing on Spotify", 404)
        id = t["id"]
    t = item(api.get(f"/tracks/{id}"))
    t["saved"] = api.get("/me/library/contains", uris=t["uri"])[0]
    return t


@route("PATCH", "/api/tracks/{id}")
def _patch_track(q, b, id):
    """Body {saved: bool}: like/unlike (save to / remove from Liked Songs); id may be 'current'"""
    if id == "current":
        id = (player.status()["track"] or {}).get("id") or ""
    uri = to_uri(id, "track")
    api.req("PUT" if b["saved"] else "DELETE", "/me/library", {"uris": uri})
    return {"uri": uri, "saved": bool(b["saved"])}


@route("GET", "/api/albums/{id}")
def _album(q, b, id):
    """Album with its first page of tracks"""
    a = api.get(f"/albums/{id}")
    out = item(a)
    out["label"] = a.get("label")
    out["tracks"] = page(a.get("tracks"))
    for t in out["tracks"]["items"]:
        t.update(album={"uri": out["uri"], "name": out["name"]}, artwork=out["artwork"])
    return out


@route("GET", "/api/albums/{id}/tracks")
def _album_tracks(q, b, id):
    """?limit=&offset="""
    return page(api.get(f"/albums/{id}/tracks", limit=_limit(q), offset=q.get("offset")))


@route("GET", "/api/artists/{id}")
def _artist(q, b, id):
    """One artist"""
    return item(api.get(f"/artists/{id}"))


@route("GET", "/api/artists/{id}/albums")
def _artist_albums(q, b, id):
    """?include_groups=album,single,appears_on,compilation&limit=&offset="""
    return page(api.get(f"/artists/{id}/albums", include_groups=q.get("include_groups"),
                        limit=_limit(q), offset=q.get("offset")))


@route("GET", "/api/episodes/{id}")
def _episode(q, b, id):
    """One podcast episode"""
    e = api.get(f"/episodes/{id}")
    out = item(e)
    out.update(description=e.get("description"), resume_point=e.get("resume_point"))
    return out


@route("GET", "/api/shows/{id}")
def _show(q, b, id):
    """Podcast with its first page of episodes"""
    sh = api.get(f"/shows/{id}")
    out = item(sh)
    out["episodes"] = page(sh.get("episodes"))
    return out


@route("GET", "/api/audiobooks/{id}")
def _audiobook(q, b, id):
    """Audiobook with authors, narrators and its first page of chapters"""
    ab = api.get(f"/audiobooks/{id}")
    out = item(ab)
    out.update(authors=[a.get("name") for a in ab.get("authors", [])],
               narrators=[n.get("name") for n in ab.get("narrators", [])], chapters=page(ab.get("chapters")))
    return out


@route("GET", "/api/audiobooks/{id}/chapters")
def _audiobook_chapters(q, b, id):
    """?limit=&offset="""
    return page(api.get(f"/audiobooks/{id}/chapters", limit=_limit(q), offset=q.get("offset")))


@route("GET", "/api/chapters/{id}")
def _chapter(q, b, id):
    """One audiobook chapter"""
    return item(api.get(f"/chapters/{id}"))


@route("GET", "/api/shows/{id}/episodes")
def _show_episodes(q, b, id):
    """?limit=&offset="""
    return page(api.get(f"/shows/{id}/episodes", limit=_limit(q), offset=q.get("offset")))


# ---------- playlists ----------

@route("GET", "/api/playlists")
def _playlists(q, b):
    """Your playlists. ?limit=&offset="""
    return page(api.get("/me/playlists", limit=_limit(q), offset=q.get("offset")))


@route("POST", "/api/playlists")
def _create_playlist(q, b):
    """Body {name, description?, public?, collaborative?}"""
    body = {k: b[k] for k in ("name", "description", "public", "collaborative") if k in b}
    pl = api.req("POST", "/me/playlists", body=body)
    if "public" in b and pl.get("public") != b["public"]:
        # Spotify ignores `public` on create; try again with an edit and report what it actually stored
        api.req("PUT", f"/playlists/{pl['id']}", body={"public": b["public"]})
        return _playlist(q, {}, pl["id"])
    return item(pl)


@route("GET", "/api/playlists/{id}")
def _playlist(q, b, id):
    """Playlist details (no items; see /items)"""
    return item(api.get(f"/playlists/{id}", fields="uri,id,type,name,description,public,collaborative,owner,images,items(total)"))


@route("PATCH", "/api/playlists/{id}")
def _edit_playlist(q, b, id):
    """Body {name?, description?, public?, collaborative?}"""
    api.req("PUT", f"/playlists/{id}", body={k: b[k] for k in ("name", "description", "public", "collaborative") if k in b})
    return _playlist(q, {}, id)


@route("DELETE", "/api/playlists/{id}")
def _delete_playlist(q, b, id):
    """Remove from your library (Spotify has no hard delete; for your own playlists this is the same thing)"""
    api.req("DELETE", "/me/library", {"uris": f"spotify:playlist:{id}"})
    return {"removed": f"spotify:playlist:{id}"}


@route("GET", "/api/playlists/{id}/items")
def _playlist_items(q, b, id):
    """?limit=&offset=. Spotify only returns items for playlists you own or collaborate on"""
    return page(api.get(f"/playlists/{id}/items", limit=_limit(q, 50, 50), offset=q.get("offset"),
                        additional_types="track,episode"), key="item")


@route("POST", "/api/playlists/{id}/items")
def _playlist_add(q, b, id):
    """Body {uris: [...], position?: n}"""
    body = {"uris": _uris(q, b)}
    if b.get("position") is not None:
        body["position"] = int(b["position"])
    res = api.req("POST", f"/playlists/{id}/items", body=body)
    uris = body["uris"]
    library.invalidate()
    entry = _log_playlist("playlist_add", id, count=len(uris))
    activity.enrich(entry, lambda: {"names": activity_log.track_names(api, uris)})
    return res


@route("DELETE", "/api/playlists/{id}/items")
def _playlist_remove(q, b, id):
    """Body {uris: [...]} (removes every occurrence)"""
    uris = _uris(q, b)
    res = api.req("DELETE", f"/playlists/{id}/items", body={"items": [{"uri": u} for u in uris]})
    library.invalidate()
    _log_playlist("playlist_remove", id, count=len(uris))
    return res


@route("PUT", "/api/playlists/{id}/items")
def _playlist_reorder(q, b, id):
    """Body {range_start, insert_before, range_length?} to move items, or {uris: [...]} to replace all"""
    if "uris" in b:
        body = {"uris": _uris(q, b)}
    else:
        body = {k: int(b[k]) for k in ("range_start", "insert_before", "range_length") if k in b}
    res = api.req("PUT", f"/playlists/{id}/items", body=body)
    library.invalidate()
    _log_playlist("playlist_reorder", id)
    return res


@route("GET", "/api/playlists/{id}/image")
def _playlist_image(q, b, id):
    """Cover image URLs"""
    return api.get(f"/playlists/{id}/images")


@route("PUT", "/api/playlists/{id}/image")
def _playlist_set_image(q, b, id):
    """Body {jpeg_base64}: upload a custom cover (JPEG, max 256 KB)"""
    data = b["jpeg_base64"].split(",", 1)[-1].strip().encode()  # accepts a data: URL too
    api.req("PUT", f"/playlists/{id}/images", body=data)
    return {"uploaded": True}


@route("POST", "/api/playlists/{id}/play")
def _playlist_play(q, b, id):
    """Body {offset?: index|uri, shuffle?: bool}"""
    if b.get("shuffle") is not None:
        player.shuffle({"enabled": b["shuffle"]})
    res = player.play({"context": f"spotify:playlist:{id}", "offset": b.get("offset")})
    credits.start([f"spotify:playlist:{id}"], _req.user)
    _log_playlist("playlist_play", id)
    return res


# ---------- web app: accounts and shared playlists ----------

@route("GET", "/api/app/me")
def _app_me(q, b):
    """Who's signed in: {id, name, avatar, admin, kind: slack|token}. API tokens show as Admin"""
    return _req.user


@route("GET", "/api/app/token")
def _app_token(q, b):
    """Your personal API token {token, created, docs}: same permissions as you; created on first request"""
    if _req.user.get("kind") != "slack":
        raise AccountError("you're already using an API token", 400)
    return {**personal.get(_req.user), "docs": (Handler.canonical_url or "").rstrip("/") + "/llms.txt"}


@route("POST", "/api/app/token/regenerate")
def _app_token_regenerate(q, b):
    """Replace your personal API token; the old one stops working immediately"""
    if _req.user.get("kind") != "slack":
        raise AccountError("you're already using an API token", 400)
    return {**personal.get(_req.user, regenerate=True), "docs": (Handler.canonical_url or "").rstrip("/") + "/llms.txt"}


@route("GET", "/api/app/playlists")
def _app_playlists(q, b):
    """Playlists shown in the web app (the account's own are hidden), newest first, with created_by, source_url, can_edit"""
    return app_playlists.list(api, _req.user)


@route("POST", "/api/app/playlists")
def _app_create(q, b):
    """Body {name, description?}: create a playlist credited to you"""
    pl = app_playlists.create(api, _req.user, b.get("name"), b.get("description") or "")
    _log("playlist_create", {"id": pl["id"], "name": pl["name"]})
    return pl


@route("POST", "/api/app/playlists/import")
def _app_import(q, b):
    """Body {url}: copy a Spotify, Apple Music or YouTube playlist/song link into a new playlist
    → {playlist, imported, total, truncated, source, unmatched: [{name, artists}]}.
    Album links are added to the Library as albums instead → {kind: "album", album: {...}}, unless
    {as: "playlist"} (e.g. an Apple Music or YouTube album with no Spotify match) copies its songs into a playlist"""
    if b.get("as") == "playlist":
        res = app_playlists.import_link(api, _req.user, b.get("url"))
        library.invalidate()
    else:
        res = library.import_link(api, _req.user, b.get("url"))
    if res.get("kind") == "album":
        if not res["album"].get("already"):
            _log("album_add", {"id": res["album"]["id"], "name": res["album"]["name"]})
        return res
    pl = res["playlist"]
    _log("playlist_import", {"id": pl["id"], "name": pl["name"], "imported": res["imported"], "source": res["source"]})
    return res


@route("POST", "/api/app/playlists/{id}/duplicate")
def _app_duplicate(q, b, id):
    """Body {name?}: copy a playlist's tracks into a new playlist credited to you → the new playlist"""
    pl = app_playlists.duplicate(api, _req.user, id, b.get("name"))
    _log("playlist_duplicate", {"id": pl["id"], "name": pl["name"], "from": id})
    return pl


@route("POST", "/api/resolve")
def _resolve(q, b):
    """Body {url}: a Spotify, Apple Music or YouTube song/album/playlist link → {source, kind, name, subtitle, artwork, url,
    spotify_uri, tracks: [{name, artists, album, duration_ms, artwork, uri}], total, matched, truncated}"""
    return links.resolve(api, b.get("url"))


@route("GET", "/api/app/playlists/{id}")
def _app_playlist(q, b, id):
    """One app playlist"""
    return app_playlists.get(api, id, _req.user)


@route("PATCH", "/api/app/playlists/{id}")
def _app_edit(q, b, id):
    """Body {name?, description?} (creator or admin)"""
    pl = app_playlists.edit(api, _req.user, id, b)
    if "name" in b:
        _log("playlist_rename", {"id": id, "name": pl["name"]})
    return pl


@route("DELETE", "/api/app/playlists/{id}")
def _app_delete(q, b, id):
    """Delete (creator or admin)"""
    try:
        name = app_playlists.get(api, id, _req.user)["name"]
    except (SpotifyError, AccountError):
        name = None
    res = app_playlists.delete(api, _req.user, id)
    _log("playlist_delete", {"id": id, "name": name})
    return res


# ---------- web app: library (playlists + albums + songs) ----------

@route("GET", "/api/app/library")
def _app_library(q, b):
    """?kind=all|playlists|albums&sort=recent|name|creator (default all, recent). → {items: [...]}: playlists as in
    /api/app/playlists plus kind "playlist", albums as in POST /api/app/library/albums with kind "album" """
    return library.list(api, _req.user, q.get("kind") or "all", q.get("sort") or "recent")


@route("POST", "/api/app/library/albums")
def _app_album_add(q, b):
    """Body {url | uri}: a Spotify album URI/link or an Apple Music or YouTube Music album link with a Spotify match (else 422: use Import as playlist).
    Admins may also pass {added_by: {id, name, avatar}, added: ISO time}. Idempotent (existing → "already": true).
    → {kind: "album", id, uri, name, artists: [{uri, name}], artwork, total, year, duration_ms, added_by, added, source_url, can_edit}"""
    admin = _req.user.get("admin")
    album = library.add_album(api, _req.user, b.get("url") or b.get("uri"),
                              added_by=b.get("added_by") if admin else None, added=b.get("added") if admin else None)
    if not album.get("already"):
        _log("album_add", {"id": album["id"], "name": album["name"]})
    return album


@route("GET", "/api/app/library/albums/{id}")
def _app_album(q, b, id):
    """A library album plus "tracks": every track as a compact item"""
    return library.get_album(api, id, _req.user)


@route("DELETE", "/api/app/library/albums/{id}")
def _app_album_remove(q, b, id):
    """Remove an album from the Library (whoever added it, or an admin) → {removed: "spotify:album:..."}"""
    try:
        name = library.get_album(api, id, _req.user)["name"] if id in library.albums else None
    except (SpotifyError, AccountError):
        name = None
    res = library.remove_album(_req.user, id)
    _log("album_remove", {"id": id, "name": name})
    return res


@route("GET", "/api/app/library/songs")
def _app_songs(q, b):
    """?q=&sort=recent|title|artist|album&offset=&limit= (default 100, max 500). Every distinct track across the Library's
    playlists and albums → {items: [{...track item, sources: [{kind: playlist|album, id, name}], added}], total}"""
    rows = library.songs(api, _req.user, q.get("q"), q.get("sort") or "recent")
    offset, limit = max(0, int(q.get("offset") or 0)), max(1, min(int(q.get("limit") or 100), 500))
    return {"items": rows[offset:offset + limit], "total": len(rows)}


@route("POST", "/api/app/library/songs/play")
def _app_songs_play(q, b):
    """Body {uri, sort?, q?}: play the songs list (same q/sort as GET /api/app/library/songs) as a queue of up to 100
    tracks starting at uri; credited to you"""
    uri = to_uri(b.get("uri"), "track")
    song, uris = library.play_queue(api, _req.user, uri, b.get("q"), b.get("sort") or "recent")
    res = player.play({"uris": uris})
    credits.start(uris, _req.user)
    _log("library_songs_play", {"uri": uri, "name": song.get("name"), "count": len(uris)})
    return res


# ---------- library & listening history ----------

LIBRARY = {"tracks": ("/me/tracks", "track"), "albums": ("/me/albums", "album"),
           "episodes": ("/me/episodes", "episode"), "shows": ("/me/shows", "show"),
           "audiobooks": ("/me/audiobooks", None), "playlists": ("/me/playlists", None)}


@route("GET", "/api/library/{kind}")
def _library(q, b, kind):
    """kind = tracks | albums | episodes | shows | audiobooks | playlists | artists (followed). ?limit=&offset= (artists: ?after=)"""
    if kind == "artists":
        res = api.get("/me/following", type="artist", limit=_limit(q), after=q.get("after"))["artists"]
        out = page(res)
        out["after"] = (res.get("cursors") or {}).get("after")
        return out
    if kind == "contains":
        return _library_contains(q, b)
    if kind not in LIBRARY:
        raise PlayerError(f"unknown library kind {kind!r}", 404)
    path, key = LIBRARY[kind]
    return page(api.get(path, limit=_limit(q), offset=q.get("offset")), key=key)


@route("PUT", "/api/library")
def _library_save(q, b):
    """Body {uris: [...]}: save tracks/albums/episodes/shows/playlists, follow artists/users (max 40)"""
    uris = _uris(q, b)
    api.req("PUT", "/me/library", {"uris": ",".join(uris)})
    return {"saved": uris}


@route("DELETE", "/api/library")
def _library_remove(q, b):
    """Body {uris: [...]}: remove / unfollow (max 40)"""
    uris = _uris(q, b)
    api.req("DELETE", "/me/library", {"uris": ",".join(uris)})
    return {"removed": uris}


@route("GET", "/api/library/contains")
def _library_contains(q, b):
    """?uris=a,b,c → {uri: bool}"""
    uris = _uris(q, b)
    return dict(zip(uris, api.get("/me/library/contains", uris=",".join(uris))))


@route("GET", "/api/recent")
def _recent(q, b):
    """Recently played tracks. ?limit=(max 50)&before=&after= (unix ms)"""
    res = api.get("/me/player/recently-played", limit=_limit(q), before=q.get("before"), after=q.get("after"))
    out = page(res, key="track")
    out["context"] = [r.get("context") for r in res.get("items", [])]
    return out


@route("GET", "/api/top/{kind}")
def _top(q, b, kind):
    """kind = tracks | artists. ?time_range=short_term|medium_term|long_term&limit=&offset="""
    if kind not in ("tracks", "artists"):
        raise PlayerError("kind must be tracks or artists", 404)
    return page(api.get(f"/me/top/{kind}", time_range=q.get("time_range"), limit=_limit(q), offset=q.get("offset")))


@route("GET", "/api/me")
def _me(q, b):
    """Spotify profile of the logged-in Web API user"""
    me = api.get("/me")
    return {"id": me.get("id"), "name": me.get("display_name"), "uri": me.get("uri"),
            "artwork": (me.get("images") or [{}])[0].get("url")}


# ---------- API tokens ----------

@route("GET", "/api/tokens")
def _tokens(q, b):
    """All API tokens (no secrets): id, name, prefix, created, last_used, current"""
    return tokens.list(getattr(_req, "token", None))


@route("POST", "/api/tokens")
def _create_token(q, b):
    """Body {name?}: create a token. The response is the only time the token itself is shown"""
    return tokens.create(b.get("name"))


@route("DELETE", "/api/tokens/{id}")
def _revoke_token(q, b, id):
    """Revoke a token immediately (any token may revoke any other, or itself; never the last one)"""
    return tokens.revoke(id)


# ---------- admin ----------

def _by():
    return {"id": _req.user.get("id"), "name": _req.user.get("name")}


@route("GET", "/api/admin/system")
def _admin_system(q, b):
    """System health (admins only): {sampled_at, hostname, model, uptime_s, cpu {percent, cores: [%], count, freq_mhz,
    max_mhz}, load [1, 5, 15 min], temp_c, power {source: vcgencmd|sysfs|hwmon, raw, now {under_voltage, freq_capped,
    throttled, soft_temp_limit}, since_boot {same}, events (under-voltage kernel messages this boot), last_event_at},
    memory {total, available, used, percent, swap_total, swap_used} (bytes), disk {path, total, used, free, percent},
    network {interface, ip, ssid, bssid, signal_dbm, quality 0-100, bitrate_mbps, freq_mhz}, services [{name, unit,
    scope: user|system, state, sub, since, enabled, restartable}], versions {commit, commit_short, subject, built_at,
    python, soloist, shairport_sync, kernel, os}, history [{t, cpu, temp}] (every 5 s, last 10 min)}.
    ?history=0 leaves out the history. Unknown values are null"""
    return stats.snapshot(history=q.get("history") != "0")


@route("POST", "/api/admin/services/{name}/restart")
def _admin_restart(q, b, name):
    """Restart soloist, airplay or music-display (admins only) → {name, state}. Restarting soloist interrupts the
    music for a few seconds; restarting airplay disconnects the AirPlay sender"""
    return stats.restart(name)


@route("GET", "/api/admin/logs/{name}")
def _admin_logs(q, b, name):
    """Recent journal lines of a service from the System list (admins only): ?lines= (default 200, max 1000)
    → {name, unit, lines: [str], error}"""
    return stats.logs(name, q.get("lines") or 200)


def _quiet_admin():
    cfg = quiet_hours.settings(DATA_DIR, QUIET_DEFAULT)
    times = cfg["times"] or quiet_hours.parse_window(quiet_hours.DEFAULT_WINDOW)
    return {"settings": {"enabled": cfg["window"] is not None, "start": quiet_hours.hhmm(times[0]),
                         "end": quiet_hours.hhmm(times[1]), "grace_min": round(cfg["grace"] / 60, 2),
                         "source": cfg["source"], "env_window": cfg["env_window"], "updated_by": cfg["updated_by"],
                         "updated_at": cfg["updated_at"]},
            "status": quiet.status()}


def _apply_quiet():
    cfg = quiet_hours.settings(DATA_DIR, QUIET_DEFAULT)
    quiet.configure(cfg["window"], cfg["grace"])
    guard.quiet_changed()


@route("GET", "/api/admin/quiet-hours")
def _admin_quiet(q, b):
    """Quiet-hours settings and state (admins only): {settings {enabled, start: "21:00", end: "08:00", grace_min,
    source: admin|env, env_window, updated_by, updated_at}, status (as GET /api/quiet-hours, plus override
    {kind: unlocked|locked, until_ts, by})}"""
    return _quiet_admin()


@route("PUT", "/api/admin/quiet-hours")
def _admin_set_quiet(q, b):
    """Body {enabled?, start?: "HH:MM", end?: "HH:MM", grace_min?} (admins only): change the window at runtime, or
    {reset: true} to go back to the server default (QUIET_HOURS). Saved in the data dir and also used by the OS
    watchdog (quiet_hours.py sync, the AirPlay receiver's start check). Applies at once: enabling a window that has
    already started locks the speakers if nothing has played for the grace period"""
    if b.get("reset"):
        quiet_hours.reset_settings(DATA_DIR)
    else:
        cur = quiet_hours.settings(DATA_DIR, QUIET_DEFAULT)
        times = cur["times"]
        start = b.get("start") or quiet_hours.hhmm(times[0])
        end = b.get("end") or quiet_hours.hhmm(times[1])
        window = quiet_hours.parse_window(f"{start}-{end}")
        enabled = b["enabled"] if "enabled" in b else cur["window"] is not None
        grace = round(float(b["grace_min"]) * 60) if b.get("grace_min") is not None else cur["grace"]
        if not 0 <= grace <= quiet_hours.MAX_GRACE:
            raise ValueError(f"grace_min must be 0-{quiet_hours.MAX_GRACE // 60}")
        quiet_hours.save_settings(DATA_DIR, window if enabled else None, grace, _by(), times=window)
    _apply_quiet()
    return _quiet_admin()


@route("POST", "/api/admin/quiet-hours/override")
def _admin_quiet_override(q, b):
    """Body {action: unlock|lock|clear} (admins only). unlock: the speakers stay unlocked until the current (or next)
    window ends. lock: lock now until the window ends (409 outside the window). clear: back to the normal rules"""
    try:
        quiet.set_override(b.get("action"), _by())
    except ValueError as e:
        raise AccountError(str(e), 409)
    guard.quiet_changed()
    return _quiet_admin()


def _known_users():
    known = {}
    for uid, e in personal.by_user.items():
        u = e.get("user") or {}
        if u.get("kind") == "slack":
            known[uid] = (u, None)
    for uid, (u, seen) in sessions.users().items():
        if u.get("kind") == "slack":
            known[uid] = (u, seen)
    return known


def _admins_out():
    known = _known_users()
    by_key = {}
    for u, _ in known.values():
        by_key.update({k: u for k in Admins._keys(u)})
    me = Admins._keys(_req.user)
    out = []
    for e in admins.entries():
        u = by_key.get(e["key"]) or {}
        out.append({"key": e["key"], "id": u.get("id") or e.get("id"), "email": u.get("email") or e.get("email"),
                    "name": u.get("name") or e.get("name"), "avatar": u.get("avatar") or e.get("avatar"),
                    "source": e["source"], "added_by": e.get("added_by"), "added": e.get("added"),
                    "you": e["key"] in me})
    people = [{"id": uid, "name": u.get("name"), "avatar": u.get("avatar"), "email": u.get("email"),
               "admin": admins.resolve(u)["admin"], "last_seen": seen} for uid, (u, seen) in known.items()]
    people.sort(key=lambda p: (-(p["last_seen"] or 0), (p["name"] or "").lower()))
    return {"admins": out, "known": people}


@route("GET", "/api/admin/admins")
def _admin_admins(q, b):
    """Admins (admins only): {admins: [{key, id, email, name, avatar, source: config|admin, added_by, added, you}],
    known: [{id, name, avatar, email, admin, last_seen}] (everyone who has signed in)}. config admins come from
    SLACK_ADMINS and can't be removed here; API tokens are always admin"""
    return _admins_out()


@route("POST", "/api/admin/admins")
def _admin_add(q, b):
    """Body {id} (Slack user ID) or {email} (admins only): make someone an admin, saved in the data dir. 409 if they
    already are. Returns the same as GET"""
    ident = (b.get("id") or "").strip()
    email = (b.get("email") or "").strip() or (ident if "@" in ident else "")
    uid = "" if "@" in ident else ident
    u = (_known_users().get(uid.upper()) or (None,))[0] if uid else None
    if uid and not u and slack and slack.configured:
        try:
            u = slack.session_user(uid.upper())
        except AccountError:
            u = None
    admins.add(_by(), id=uid, email=email, name=(u or {}).get("name"), avatar=(u or {}).get("avatar"))
    return _admins_out()


@route("DELETE", "/api/admin/admins/{key}")
def _admin_remove(q, b, key):
    """Remove an admin added here (admins only); key from GET. 409 for config admins and for removing yourself as
    the last admin. Returns the same as GET"""
    admins.remove(key, _req.user)
    return _admins_out()


@route("GET", "/api/admin/update")
def _admin_update(q, b):
    """Update status (admins only): {configured, setup_hint, deployed {commit, short, subject, date, built_at},
    latest {commit, short, subject, date} (origin/main), build {commit, short, built_at, ready} (the pi-build branch
    GitHub Actions publishes), behind, commits [{commit, short, subject, author, date}] newest first,
    changes {files, restarts, units, notes}, fetched_at, fetch_error, run {id, state: running|succeeded|rolled_back|failed,
    started_at, finished_at, from, to, result, log [{t, msg, level}]}}. Fetches from GitHub if the last fetch is over 10 min old"""
    return updates.status()


@route("POST", "/api/admin/update/check")
def _admin_update_check(q, b):
    """Fetch from GitHub now (admins only); returns the same as GET"""
    return updates.status(fetch=True)


@route("POST", "/api/admin/update")
def _admin_update_start(q, b):
    """Update to the latest build (admins only). Runs in the background: stages the build, swaps it in, restarts
    music-api (and music-display if its files changed; Soloist and AirPlay keep playing), health-checks /api/status
    and rolls back if that fails. Poll GET for run.state and run.log; expect the API to drop for a few seconds.
    409 if already up to date or an update is running"""
    run = updates.start(_by())
    return {**updates.status(fetch=False), "run": run}


# ---------- Web API login (OAuth Authorization Code + PKCE) ----------

LOGIN_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Spotify login</title>
<style>body{{font:16px system-ui;max-width:34rem;margin:2rem auto;padding:0 1rem;background:#fff;color:#111}}
@media(prefers-color-scheme:dark){{body{{background:#121212;color:#eee}}}}
a.btn,button{{display:inline-block;background:#1db954;color:#000;border:0;border-radius:2rem;padding:.7rem 1.4rem;
font:inherit;font-weight:600;text-decoration:none;cursor:pointer}}input{{width:100%;padding:.6rem;font:inherit;box-sizing:border-box}}
code{{word-break:break-all}}</style>
<h1>Connect Spotify</h1>
<p><a class=btn href="{url}">Log in with Spotify</a></p>
<p>Spotify will send you back to <code>{redirect}</code>.
If that address belongs to another machine (e.g. this server is a headless Pi), the page won't load.
That's expected: copy the whole URL from the address bar and paste it here.</p>
<form method=post action="/auth/paste{tq}"><input name=url placeholder="http://127.0.0.1:8765/auth/callback?code=..." required>
<p><button>Finish login</button></p></form>"""


def _login_page(q):
    url = auth.login_url()
    tq = "?token=" + urllib.parse.quote(q["token"]) if q.get("token") else ""
    return ("html", LOGIN_PAGE.format(url=html.escape(url), redirect=html.escape(auth.redirect_uri), tq=html.escape(tq)))


def _error_page(msg):
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Sign-in failed</title><body style='font:16px system-ui;margin:2rem;background:#121212;color:#eee'>"
            f"<h1>Couldn't sign you in</h1><p>{html.escape(msg)}</p><p><a style='color:#1db954' href='/'>Back</a></p>")


def _done_page(st):
    return ("html", "<!doctype html><meta charset=utf-8><title>Spotify login</title>"
                    "<body style='font:16px system-ui;margin:2rem'><h1>Logged in ✓</h1><p>"
                    + html.escape(st.get("scope") or "") + "</p><p><a href='/'>Open the remote</a></p>")


# ---------- server ----------

PASSTHROUGH_ACTIONS = {"/me/player/play": "play", "/me/player/next": "next", "/me/player/previous": "previous",
                       "/me/player/seek": "seek", "/me/player/pause": "pause"}


def _guard_passthrough(method, path, body):
    if method == "GET" or not path.startswith("/me/player"):
        return
    action = PASSTHROUGH_ACTIONS.get(path.rstrip("/"))
    if path.rstrip("/") == "/me/player" and method == "PUT":
        action = "transfer_play" if isinstance(body, dict) and body.get("play") else "transfer"
    if action:
        guard.check(action)


def _error_body(e):
    return e.body() if isinstance(e, PlayerError) else {"error": str(e)}


class Handler(BaseHTTPRequestHandler):
    server_version = "MusicAPI/2.0"
    require_token = False  # --public or listening beyond localhost
    canonical_url = None  # tunnelled requests for any other hostname are redirected here

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/events"):
            msg = fmt % args
            sys.stderr.write("%s - %s\n" % (self.address_string(), re.sub(r"(token|code)=[^&\s]+", r"\1=…", msg)))

    def _send(self, code, body, ctype="application/json", headers=()):
        if not isinstance(body, bytes):
            body = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Link", '</llms.txt>; rel="describedby"; type="text/plain"')
        for k, v in [*headers, *getattr(_req, "cookies", ())]:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _session_id(self):
        # Not http.cookies: SimpleCookie drops every cookie after one it can't parse (JSON or spaces in values,
        # set by other *.pinewoodrobotics.org apps), which silently signed people out.
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE and value:
                return value.strip('"')
        return None

    def _authorized(self, query):
        given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip() or query.get("token", "")
        _req.token = tokens.check(given)
        _req.bearer = bool(given)
        _req.cookies = ()
        _req.user = ADMIN if _req.token is not None else personal.check(given)
        if not _req.user:
            sid = self._session_id()
            _req.user, renew = sessions.get(sid)
            if renew:
                _req.cookies = (self._set_cookie(sid, SESSION_COOKIE_AGE),)
        if _req.user and admins:
            _req.user = admins.resolve(_req.user)
        _req.origin = activity_log.origin_for(self.headers, _req.bearer)
        if _req.user:
            return True
        if not (tokens.enabled or self.require_token):
            _req.user = ADMIN
            return True
        return False

    def _forbidden(self, method, path):
        if _req.user.get("admin"):
            return None
        if not _req.bearer and method not in ("GET", "HEAD"):
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
                return "cross-site request refused"
        if ADMIN_ONLY.match(path) or (method, path) in ADMIN_ONLY_METHODS:
            return "admins only"
        if EFFECT_PATH.match(path) and method in ("PATCH", "DELETE"):
            return "admins only"
        m = re.match(r"^/api/playlists/([^/]+)(/.*)?$", path)
        if m and (app_playlists.is_hidden(m.group(1)) or (m.group(2) is None and method != "GET")
                  or m.group(2) == "/image" and method != "GET"):
            return "admins only"
        return None

    def _set_cookie(self, sid, max_age):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "") == "https" or self.headers.get("Cf-Visitor") else ""
        return ("Set-Cookie", f"{SESSION_COOKIE}={sid}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}")

    def _static(self, path):
        """The web app: built assets from web/dist, index.html for every other page (client-side routing)."""
        if path.startswith("/assets/"):
            full = os.path.realpath(os.path.join(WEB_DIST, path.lstrip("/")))
            if not full.startswith(os.path.join(WEB_DIST, "assets") + os.sep) or not os.path.isfile(full):
                return self._send(404, {"error": "not found"})
            with open(full, "rb") as f:
                return self._send(200, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream",
                                  [("Cache-Control", "public, max-age=31536000, immutable")])
        index = os.path.join(WEB_DIST, "index.html")
        if path == "/legacy" or not os.path.exists(index):
            index = os.path.join(HERE, "index.html")
        with open(index, "rb") as f:
            return self._send(200, f.read(), "text/html; charset=utf-8", [("Cache-Control", "no-cache")])

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith(("audio/", "video/ogg", "application/ogg", "application/octet-stream", "multipart/form-data")):
            if length > effects_mod.MAX_UPLOAD + (1 << 20):
                raise EffectsError(f"upload is larger than {effects_mod.MAX_UPLOAD >> 20} MB", 413, "too_large")
            raw = self.rfile.read(length)
            return effects_mod.parse_multipart(ctype, raw) if ctype.startswith("multipart/") else {"audio": raw}
        raw = self.rfile.read(length)
        if ctype.startswith("application/x-www-form-urlencoded"):
            return dict(urllib.parse.parse_qsl(raw.decode()))
        return json.loads(raw or b"{}")

    def _slack(self, path):
        raw = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1 << 20))
        status, res = bot.handle(path, self.headers, raw)
        self._send(status, json.dumps(res) if res is not None else b"")

    def _dispatch(self, method):
        _req.cookies = ()
        url = urllib.parse.urlparse(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        path = url.path.rstrip("/") or "/"
        canonical = urllib.parse.urlparse(self.canonical_url).netloc if self.canonical_url else None
        host = self.headers.get("Host", "")
        # Slack doesn't follow redirects, so its callbacks keep working on old hostnames
        if canonical and host != canonical and self.headers.get("Cf-Visitor") and not path.startswith("/slack/"):
            return self._send(308, b"", "text/plain", [("Location", self.canonical_url.rstrip("/") + self.path)])

        m = re.fullmatch(r"/airplay-art/([0-9a-f]{12})", path)
        if m and method == "GET":
            art = airplay.artwork_by_hash(m.group(1)) if airplay else None
            if not art:
                return self._send(404, {"error": "not found"})
            return self._send(200, art[0], art[1], [("Cache-Control", "public, max-age=31536000, immutable")])
        if method == "GET" and not path.startswith(("/api", "/auth")) and path not in DOC_FILES:
            return self._static(path)
        if path in DOC_FILES and method == "GET":
            name, ctype = DOC_FILES[path]
            try:
                with open(os.path.join(HERE, name), "rb") as f:
                    return self._send(200, f.read(), ctype + "; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, {"error": "not found"})
        try:
            if path == "/auth/callback" and method == "GET":  # protected by the PKCE state instead of the token
                return self._result(_done_page(auth.finish(query.get("code"), query.get("state"),
                                                           url=None if query.get("code") else self.path)))
            if path == "/auth/slack/login" and method == "GET":
                return self._result(("redirect", slack.login_url(query.get("next") or "/")))
            if path == "/auth/slack/callback" and method == "GET":
                if query.get("error"):
                    return self._result(("redirect", "/"))
                user, next_path = slack.finish(query.get("code"), query.get("state"))
                personal.refresh(user)
                return self._send(302, b"", "text/plain", [("Location", next_path),
                                                           self._set_cookie(sessions.create(user), SESSION_COOKIE_AGE)])
            if path == "/auth/google/login" and method == "GET":
                return self._result(("redirect", google.login_url(query.get("next") or "/")))
            if path == "/auth/google/callback" and method == "GET":
                if query.get("error"):
                    return self._result(("redirect", "/"))
                user, next_path = google.finish(query.get("code"), query.get("state"))
                personal.refresh(user)
                return self._send(302, b"", "text/plain", [("Location", next_path),
                                                           self._set_cookie(sessions.create(user), SESSION_COOKIE_AGE)])
            if path == "/auth/methods" and method == "GET":
                return self._send(200, {"slack": slack.configured, "google": google.configured})
            if path == "/auth/slack/logout" and method == "POST":
                sessions.delete(self._session_id())
                return self._send(200, {"result": {"signed_out": True}}, headers=[self._set_cookie("", 0)])
            if path.startswith("/slack/") and method == "POST":  # signed by Slack instead of token/session auth
                return self._slack(path)
            if not self._authorized(query):
                return self._send(401, {"error": "unauthorized"})
            why = self._forbidden(method, path)
            if why:
                return self._send(403, {"error": why})
            if method != "GET":
                origin = self.headers.get("X-Client-Origin")
                sys.stderr.write(f"{method} {path} by {_req.user.get('name')} via "
                                 f"{'token' if _req.bearer else 'session'}{f' from {origin[:40]}' if origin else ''} "
                                 f"[{self.headers.get('User-Agent', '')[:80]}]\n")
            body = self._body()
        except AccountError as e:
            if path.startswith(("/auth/slack/", "/auth/google/")) and method == "GET":
                return self._result(("html", _error_page(str(e))))
            return self._send(e.status, {"error": str(e)})
        except SpotifyError as e:
            return self._send(e.status, {"error": str(e)})
        except EffectsError as e:
            return self._send(e.status, _error_body(e))
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid JSON body"})

        if path == "/api" and method == "GET":
            return self._send(200, [{"method": m, "path": p, "doc": d} for m, _, p, d, _ in ROUTES] + [
                {"method": "GET", "path": "/api/events", "doc": "Server-sent events: status (1/s with Soloist, every 2 s with connect; includes quiet_hours and airplay), track, queue, sleep, activity, error"},
                {"method": "ANY", "path": "/api/spotify/{path}", "doc": "Raw Spotify Web API passthrough, e.g. GET /api/spotify/me/player"},
                {"method": "GET", "path": "/auth/login", "doc": "Web API login page (?redirect=1 to go straight to Spotify)"},
                {"method": "GET", "path": "/auth", "doc": "Web API login status"},
                {"method": "POST", "path": "/auth/paste", "doc": "Body {url}: finish login with the redirected URL"},
                {"method": "POST", "path": "/auth/logout", "doc": "Forget the Web API tokens"},
                {"method": "GET", "path": "/auth/slack/login", "doc": "Sign in with Slack (?next=/path); sets a session cookie"},
                {"method": "GET", "path": "/auth/google/login", "doc": "Sign in with Google (?next=/path); @pinewood.edu accounts that are in the Slack workspace; sets a session cookie"},
                {"method": "GET", "path": "/auth/google/callback", "doc": "Google redirects here after sign-in"},
                {"method": "GET", "path": "/auth/methods", "doc": "Which sign-in methods are configured: {slack, google}"},
                {"method": "POST", "path": "/auth/slack/logout", "doc": "End the Slack session"},
                {"method": "POST", "path": "/slack/commands", "doc": "Slack /music command (Slack signing secret instead of a token)"},
                {"method": "POST", "path": "/slack/interactions", "doc": "Slack button clicks (signing secret)"},
                {"method": "POST", "path": "/slack/events", "doc": "Slack Events API: url_verification, link_shared (signing secret)"},
            ])
        if path == "/api/events" and method == "GET":
            return self._sse()

        try:
            if path == "/auth" and method == "GET":
                return self._send(200, {"result": auth.status()})
            if path == "/auth/login" and method == "GET":
                if query.get("redirect"):
                    return self._result(("redirect", auth.login_url()))
                return self._result(_login_page(query))
            if path == "/auth/paste" and method == "POST":
                st = auth.finish(url=body["url"])
                form = self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded")
                return self._result(_done_page(st) if form else st)
            if path == "/auth/logout" and method == "POST":
                auth.logout()
                return self._send(200, {"result": auth.status()})
            if path.startswith("/api/spotify/"):
                _guard_passthrough(method, path[len("/api/spotify"):], body)
                q = {k: v for k, v in query.items() if k != "token"}
                return self._send(200, {"result": api.req(method, "/" + path[len("/api/spotify/"):], q,
                                                          body if self.headers.get("Content-Length") else None)})
        except APP_ERRORS as e:
            return self._send(e.status, _error_body(e))
        except (KeyError, ValueError, TypeError) as e:
            return self._send(400, {"error": f"bad request: {e}"})

        matched_path = False
        for m, rx, _, _, fn in ROUTES:
            mt = rx.match(path)
            if not mt:
                continue
            matched_path = True
            if m != method:
                continue
            try:
                params = {k: urllib.parse.unquote(v) for k, v in mt.groupdict().items()}
                return self._result(fn(query, body, **params))
            except APP_ERRORS as e:
                return self._send(e.status, _error_body(e))
            except (KeyError, ValueError, TypeError) as e:
                return self._send(400, {"error": f"bad request: {e}"})
        self._send(405 if matched_path else 404, {"error": "method not allowed" if matched_path else "not found"})

    def _result(self, result):
        if isinstance(result, tuple) and isinstance(result[0], bytes):
            return self._send(200, result[0], result[1], [("Cache-Control", "max-age=3600")])
        if isinstance(result, tuple) and result[0] == "redirect":
            return self._send(302, b"", "text/plain", [("Location", result[1])])
        if isinstance(result, tuple) and result[0] == "html":
            return self._send(200, result[1], "text/html; charset=utf-8")
        return self._send(200, {"result": result})

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = player.subscribe()
        try:
            if player.last:
                q.put(("status", player.last))
            while True:
                try:
                    event, data = q.get(timeout=15)
                    self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                except queuelib.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            player.unsubscribe(q)

    def do_GET(self): self._dispatch("GET")

    def do_HEAD(self):
        """For link checkers and agents probing the docs; API routes don't support HEAD."""
        path = urllib.parse.urlparse(self.path).path
        if path in DOC_FILES or not path.startswith(("/api", "/auth")):
            return self._dispatch("GET")
        self._send(405, {"error": "method not allowed"})
    def do_POST(self): self._dispatch("POST")
    def do_PUT(self): self._dispatch("PUT")
    def do_PATCH(self): self._dispatch("PATCH")
    def do_DELETE(self): self._dispatch("DELETE")


def default_data_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "music-api")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["serve", "auth"], default="serve")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other devices on your network")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default=os.environ.get("MUSIC_API_TOKEN"), help="require Bearer token / ?token=")
    ap.add_argument("--public", action="store_true",
                    help="require a token even on localhost (for tunnels). Tokens live in <data-dir>/api-tokens.json; "
                         "if there are none, <data-dir>/token is imported, or a new token is written there")
    ap.add_argument("--data-dir", default=os.environ.get("MUSIC_API_DATA_DIR") or default_data_dir())
    ap.add_argument("--client-id", default=os.environ.get("SPOTIFY_CLIENT_ID"),
                    help="Spotify app Client ID (developer.spotify.com/dashboard); remembered after first login")
    ap.add_argument("--redirect-uri", default=os.environ.get("SPOTIFY_REDIRECT_URI"),
                    help="must match the app's settings; default http://127.0.0.1:<port>/auth/callback")
    ap.add_argument("--backend", choices=["auto", "soloist", "connect"], default=os.environ.get("MUSIC_API_BACKEND", "auto"),
                    help="auto = soloist when its WebSocket is found, else connect")
    ap.add_argument("--soloist-ws", default=os.environ.get("SOLOIST_WS"), help="ADDR:PORT (default: discover from data dir)")
    ap.add_argument("--soloist-data-dir", default=os.environ.get("SOLOIST_DATA_DIR") or soloist_data_dir())
    ap.add_argument("--slack-redirect-uri", default=os.environ.get("SLACK_REDIRECT_URI"),
                    help="Sign in with Slack callback; default http://127.0.0.1:<port>/auth/slack/callback")
    ap.add_argument("--google-redirect-uri", default=os.environ.get("GOOGLE_REDIRECT_URI"),
                    help="Sign in with Google callback; default <MUSIC_API_URL>/auth/google/callback, else http://127.0.0.1:<port>/auth/google/callback")
    ap.add_argument("--hidden-playlists", default=os.environ.get("MUSIC_API_HIDDEN_PLAYLISTS")
                    or os.path.expanduser("~/.config/music-api/hidden-playlists.json"),
                    help='JSON {"playlists": [id or {id, name}, ...]}: account playlists the web app never shows')
    ap.add_argument("--canonical-url", default=os.environ.get("MUSIC_API_URL"),
                    help="public base URL, e.g. https://music.pinewoodrobotics.org; other tunnelled hostnames redirect to it")
    ap.add_argument("--device", default=os.environ.get("MUSIC_API_DEVICE"),
                    help="connect backend: Connect device name or id to control (default: whichever is active)")
    ap.add_argument("--quiet-hours", default=os.environ.get("QUIET_HOURS", quiet_hours.DEFAULT_WINDOW),
                    help="HH:MM-HH:MM local time (may wrap midnight) or off. After it starts the speakers lock once "
                         "nothing has played for 5 minutes, until it ends (default %(default)s)")
    ap.add_argument("--airplay-pipe", default=os.environ.get("AIRPLAY_METADATA_PIPE", airplay_mod.DEFAULT_PIPE),
                    help="shairport-sync metadata pipe (default %(default)s); fine if it doesn't exist")
    a = ap.parse_args()
    try:
        quiet_hours.parse_window(a.quiet_hours)
    except ValueError as e:
        ap.error(str(e))

    global auth, api, player, soloist, tokens, slack, google, sessions, app_playlists, bot, personal, credits, activity, library
    global guard, airplay, quiet, effects, admins, stats, updates, DATA_DIR, QUIET_DEFAULT
    os.makedirs(a.data_dir, mode=0o700, exist_ok=True)
    auth = Auth(a.data_dir, a.client_id, a.redirect_uri or f"http://127.0.0.1:{a.port}/auth/callback")
    api = WebAPI(auth)

    if a.command == "auth":
        print("Open this URL in any browser and log in:\n\n  " + auth.login_url() + "\n")
        print(f"You'll land on {auth.redirect_uri}?code=... (it may fail to load; that's fine).")
        st = auth.finish(url=input("Paste that full URL here: "))
        print("Logged in. Scopes:", st["scope"])
        return

    tokens = Tokens(a.data_dir, a.token)
    DATA_DIR, QUIET_DEFAULT = a.data_dir, a.quiet_hours
    admins = Admins(a.data_dir, os.environ.get("SLACK_ADMINS", "").split(","))
    stats = system_stats.Stats()
    threading.Thread(target=stats.loop, daemon=True).start()
    updates = updater_mod.Updater(data_dir=a.data_dir, port=a.port)
    sessions = Sessions(a.data_dir)
    personal = PersonalTokens(a.data_dir)
    app_playlists = Playlists(a.data_dir, a.hidden_playlists)
    library = Library(a.data_dir, app_playlists)
    slack = Slack(os.environ.get("SLACK_CLIENT_ID"), os.environ.get("SLACK_CLIENT_SECRET"), os.environ.get("SLACK_BOT_TOKEN"),
                  a.slack_redirect_uri or f"http://127.0.0.1:{a.port}/auth/slack/callback",
                  os.environ.get("SLACK_TEAM_ID"), filter(None, os.environ.get("SLACK_ADMINS", "").split(",")))
    google_redirect = a.google_redirect_uri or (
        a.canonical_url.rstrip("/") + "/auth/google/callback" if a.canonical_url else f"http://127.0.0.1:{a.port}/auth/google/callback")
    google = Google(os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET"), google_redirect, slack,
                    os.environ.get("GOOGLE_ALLOWED_DOMAIN") or "pinewood.edu")
    require = a.public or a.host not in ("127.0.0.1", "localhost", "::1")
    boot = tokens.bootstrap(require)
    if boot == "imported":
        print(f"Imported {tokens.legacy_path} as an API token", flush=True)
    elif boot == "generated":
        print(f"Generated an API token in {tokens.legacy_path}", flush=True)

    backend = a.backend
    if backend != "connect":
        soloist = Soloist(a.soloist_ws, a.soloist_data_dir)
        # auto: use Soloist if it's running or has ever run here (it may still be starting up)
        if backend == "auto" and not (soloist.available() or os.path.isdir(soloist.data_dir)):
            soloist, backend = None, "connect"
        else:
            backend = "soloist"
    credits = Credits(os.path.join(a.data_dir, "credits.json"))
    player = Player(backend, api, soloist, a.device, credits.for_status)
    player.skip_fn = credits.recent_skip
    player.uncredit_fn = credits.unqueue
    activity = Activity(os.path.join(a.data_dir, "activity.jsonl"))
    activity.publish = lambda entry: player.publish("activity", entry)
    if soloist:
        soloist.on_event = player.on_soloist_event
        threading.Thread(target=soloist.loop, daemon=True).start()
    qcfg = quiet_hours.settings(a.data_dir, a.quiet_hours)
    quiet = quiet_hours.QuietHours(qcfg["window"], os.path.join(a.data_dir, quiet_hours.STATE_FILE), grace=qcfg["grace"])
    airplay = airplay_mod.AirPlay(a.airplay_pipe, state_path=os.path.join(a.data_dir, "airplay-sender.json"))
    guard = Guard(player, quiet, airplay, enforce=lambda locked: quiet_hours.enforce(locked, a.data_dir),
                  receiver=quiet_hours.receiver, remote=airplay_mod.remote,
                  resume_path=os.path.join(a.data_dir, "airplay-resume"))
    effects = effects_mod.Effects(a.data_dir)
    threading.Thread(target=airplay.loop, daemon=True).start()
    threading.Thread(target=airplay.watch, daemon=True).start()
    threading.Thread(target=guard.loop, args=(5 if backend == "soloist" else 15,), daemon=True).start()
    threading.Thread(target=player.loop, daemon=True).start()
    bot = slack_bot.from_env(slack, player, api, credits, resolve=lambda url: links.resolve(api, url),
                             importer=lambda url, user: app_playlists.import_link(api, user, url),
                             add_album=lambda url, user: library.add_album(api, user, url),
                             state_path=os.path.join(a.data_dir, "slack-feed.json"), activity=activity)
    bot.start()

    Handler.require_token = require
    Handler.canonical_url = a.canonical_url
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print(f"Music API v2 on http://{a.host}:{a.port}/  backend={backend}  web-api={'logged in' if auth.logged_in else 'not logged in (open /auth/login)'}",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
