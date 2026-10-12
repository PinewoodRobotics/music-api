"""Resolve Spotify, Apple Music and YouTube links to Spotify tracks. Stdlib only.

Apple songs and albums come from the public iTunes Lookup API; Apple playlists (including personal ones shared
publicly) only from the server-rendered data on music.apple.com. Apple songs are matched to Spotify by
title/artist search, picking the closest duration. YouTube and YouTube Music links (yt.py) are matched the same way.
"""
import difflib
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import yt
from spotify import SpotifyError, item, to_uri

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
APPLE_RX = re.compile(r"music\.apple\.com/(?:(\w{2})/)?(album|song|playlist)/(?:[^/?#]+/)?([\w.-]+)(?:\?[^#]*?\bi=(\d+))?")
CACHE_TTL = 3600
SPOTIFY_PLAYLIST_LIMIT = 100
LOOSE_SLACK_S = 15


class LinkError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


_cache = {}
_cache_lock = threading.Lock()


def _fetch(url, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise LinkError("that link doesn't exist or isn't public" if e.code == 404 else f"{url.split('/')[2]}: HTTP {e.code}",
                        404 if e.code == 404 else 502)
    except urllib.error.URLError as e:
        raise LinkError(f"couldn't reach {url.split('/')[2]}: {e.reason}", 502)
    return json.loads(body) if as_json else body.decode("utf-8", "replace")


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\s*[\(\[](feat|ft|with)\.?[^\)\]]*[\)\]]", "", s)
    s = re.sub(r"\s+-\s+(\d{4} )?(remaster|single|radio|mono|stereo).*$", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _artists(s):
    return [a.strip() for a in re.split(r"\s*(?:,|&| and | x | feat\.? | ft\.? )\s*", s or "", flags=re.I) if a.strip()]


def _apple_art(url, size=600):
    if not url:
        return None
    return re.sub(r"\{w\}x\{h\}(\w*)\.\{f\}", rf"{size}x{size}\1.jpg", re.sub(r"/\d+x\d+(\w*)\.(jpg|png)$", rf"/{size}x{size}\1.jpg", url))


def _score(cand, name, artists, duration_ms, slack=0):
    n = difflib.SequenceMatcher(None, _norm(cand.get("name")), _norm(name)).ratio()
    cand_artists = {_norm(a.get("name")) for a in cand.get("artists", [])}
    a = 1.0 if any(_norm(x) in cand_artists for x in artists) else 0.0
    d = max(abs((cand.get("duration_ms") or 0) - (duration_ms or 0)) / 1000 - slack, 0) if duration_ms else 0
    return n * 2 + a * 2 - min(d, 30) / 10


def match(api, name, artists, duration_ms=None, album=None, loose=False):
    """Best Spotify track for a song from elsewhere, or None. `loose` forgives intros and outros in the duration."""
    slack = LOOSE_SLACK_S if loose else 0
    key = ("match", _norm(name), tuple(_norm(a) for a in artists), duration_ms, slack)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    title = re.sub(r"\s*[\(\[](feat|ft|with)\.?[^\)\]]*[\)\]]", "", name or "", flags=re.I).strip()
    queries = [f'track:"{title}" artist:"{artists[0]}"' if artists else f'track:"{title}"',
               f"{title} {' '.join(artists[:2])}"]
    best = None
    for q in queries:
        found = api.get("/search", q=q, type="track", limit=10).get("tracks", {}).get("items", [])
        scored = sorted(((_score(t, name, artists, duration_ms, slack), t) for t in found if t), key=lambda x: -x[0])
        if scored and scored[0][0] >= 2.6:
            best = item(scored[0][1])
            break
    with _cache_lock:
        _cache[key] = best
    return best


def _song(name, artists, album, duration_ms, artwork, uri=None):
    return {"name": name, "artists": artists, "album": album, "duration_ms": duration_ms, "artwork": artwork, "uri": uri}


def _match_all(api, songs):
    def one(s):
        try:
            m = match(api, s["name"], s["artists"], s["duration_ms"], s["album"], s.get("loose", False))
        except SpotifyError:
            m = None
        return {**{k: v for k, v in s.items() if k != "loose"}, "uri": m["uri"] if m else None, "artwork": s["artwork"] or (m or {}).get("artwork")}
    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(one, songs))


def _from_spotify_item(t):
    return _song(t.get("name"), [a["name"] for a in t.get("artists", [])], (t.get("album") or {}).get("name"),
                 t.get("duration_ms"), t.get("artwork"), t.get("uri"))


def _spotify(api, uri):
    kind, sid = uri.split(":")[1:]
    if kind == "track":
        t = item(api.get(f"/tracks/{sid}"))
        return {"kind": "track", "name": t["name"], "subtitle": ", ".join(a["name"] for a in t["artists"]),
                "artwork": t.get("artwork"), "spotify_uri": uri, "tracks": [_from_spotify_item(t)]}
    if kind == "album":
        a = api.get(f"/albums/{sid}")
        art = item(a).get("artwork")
        rows, page = [], a.get("tracks") or {}
        while True:
            for t in page.get("items", []):
                if t:
                    rows.append(_song(t.get("name"), [x["name"] for x in t.get("artists", [])], a.get("name"),
                                      t.get("duration_ms"), art, t.get("uri")))
            if not page.get("next") or len(rows) >= 500:
                break
            page = api.req("GET", page["next"])
        return {"kind": "album", "name": a.get("name"), "subtitle": ", ".join(x["name"] for x in a.get("artists", [])),
                "artwork": art, "spotify_uri": uri, "tracks": rows}
    if kind == "playlist":
        html = _fetch(f"https://open.spotify.com/embed/playlist/{sid}", as_json=False)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        try:
            e = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        except (AttributeError, KeyError, TypeError, ValueError):
            raise LinkError("couldn't read that playlist (is it public?)", 422)
        sources = (e.get("coverArt") or {}).get("sources") or [{}]
        rows = [_song(t.get("title"), _artists(t.get("subtitle")), None, t.get("duration"), None, t["uri"])
                for t in e.get("trackList", []) if t.get("uri", "").startswith(("spotify:track:", "spotify:episode:"))]
        return {"kind": "playlist", "name": e.get("name"), "subtitle": e.get("subtitle"), "artwork": sources[0].get("url"),
                "spotify_uri": uri, "tracks": rows, "truncated": len(rows) >= SPOTIFY_PLAYLIST_LIMIT}
    raise LinkError(f"Spotify {kind} links aren't supported; use a song, album or playlist")


def _itunes(country, **params):
    return _fetch("https://itunes.apple.com/lookup?" + urllib.parse.urlencode({"country": country or "us", **params}))["results"]


def _apple_song_row(r):
    return _song(r.get("trackName"), _artists(r.get("artistName")), r.get("collectionName"),
                 r.get("trackTimeMillis"), _apple_art(r.get("artworkUrl100")))


def _apple_playlist(country, pid):
    html = _fetch(f"https://music.apple.com/{country or 'us'}/playlist/x/{pid}", as_json=False)
    m = re.search(r'<script type="application/json" id="serialized-server-data">(.*?)</script>', html, re.S)
    try:
        sections = json.loads(m.group(1))["data"][0]["data"]["sections"]
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        raise LinkError("couldn't read that Apple Music playlist (is it shared publicly?)", 422)
    header, rows = {}, []
    for sec in sections:
        for it in sec.get("items", []):
            kind = (it.get("contentDescriptor") or {}).get("kind")
            if kind == "playlist" and not header:
                header = it
            elif kind == "song":
                rows.append(_song(it.get("title"), _artists(((it.get("subtitleLinks") or [{}])[0]).get("title")),
                                  ((it.get("tertiaryLinks") or [{}])[0]).get("title"), it.get("duration"),
                                  _apple_art(((it.get("artwork") or {}).get("dictionary") or {}).get("url"), 300)))
    if not header and not rows:
        raise LinkError("couldn't find any songs in that Apple Music playlist", 422)
    owner = ((header.get("subtitleLinks") or [{}])[0]).get("title")
    return header.get("title") or "Apple Music playlist", owner, \
        _apple_art(((header.get("artwork") or {}).get("dictionary") or {}).get("url")), rows


def _album_result(api, name, artist, art, songs):
    q = f'album:"{re.sub(r" - (EP|Single)$", "", name)}" artist:"{(_artists(artist) or [""])[0]}"'
    for a in api.get("/search", q=q, type="album", limit=5).get("albums", {}).get("items", []):
        if a and _norm(a.get("name")) == _norm(name) and a.get("total_tracks", 0) >= len(songs):
            found = _spotify(api, a["uri"])
            return {**found, "name": name, "artwork": art or found["artwork"]}
    return {"kind": "album", "name": name, "subtitle": artist, "artwork": art, "spotify_uri": None,
            "tracks": _match_all(api, songs)}


def _apple(api, country, kind, aid, song_id):
    if kind == "song" or song_id:
        res = [r for r in _itunes(country, id=song_id or aid) if r.get("wrapperType") == "track"]
        if not res:
            raise LinkError("Apple Music doesn't have that song", 404)
        row = _match_all(api, [_apple_song_row(res[0])])[0]
        return {"kind": "track", "name": row["name"], "subtitle": ", ".join(row["artists"]), "artwork": row["artwork"],
                "spotify_uri": row["uri"], "tracks": [row]}
    if kind == "album":
        res = _itunes(country, id=aid, entity="song", limit=200)
        album = next((r for r in res if r.get("wrapperType") == "collection"), None)
        if not album:
            raise LinkError("Apple Music doesn't have that album", 404)
        art = _apple_art(album.get("artworkUrl100"))
        return _album_result(api, album.get("collectionName"), album.get("artistName"), art,
                             [{**_apple_song_row(r), "artwork": art} for r in res if r.get("wrapperType") == "track"])
    name, owner, art, songs = _apple_playlist(country, aid)
    return {"kind": "playlist", "name": name, "subtitle": owner, "artwork": art, "spotify_uri": None,
            "tracks": _match_all(api, songs[:500])}


def _youtube(api, kind, yid):
    if kind == "track":
        row = _match_all(api, [yt.track(yid)])[0]
        return {"kind": "track", "name": row["name"], "subtitle": ", ".join(row["artists"]),
                "artwork": row["artwork"] or yt.thumbnail(yid), "spotify_uri": row["uri"], "tracks": [row]}
    if kind == "album":
        a = yt.album(yid)
        return _album_result(api, a["name"], a["artist"], a["artwork"], a["songs"])
    p = yt.playlist(yid)
    return {"kind": "playlist", "name": p["name"], "subtitle": p["owner"], "artwork": p["artwork"], "spotify_uri": None,
            "tracks": _match_all(api, p["songs"]), "truncated": p["truncated"]}


def album_ref(url):
    """('spotify', album_uri) for a Spotify album link/URI, ('apple', None) or ('youtube', None) for an Apple Music or
    YouTube Music album link, else None."""
    url = (url or "").strip()
    if yt.YT_RX.search(url):
        try:
            return ("youtube", None) if yt.parse(url)[0] == "album" else None
        except LinkError:
            return None
    apple = APPLE_RX.search(url)
    if apple:
        return ("apple", None) if apple.group(2) == "album" and not apple.group(4) else None
    if "spotify" in url:
        try:
            uri = to_uri(url)
        except ValueError:
            return None
        return ("spotify", uri) if uri.startswith("spotify:album:") else None
    return None


def resolve(api, url):
    """A Spotify, Apple Music or YouTube song/album/playlist link → {source, kind, name, subtitle, artwork, url,
    spotify_uri, tracks: [{name, artists, album, duration_ms, artwork, uri}], total, matched, truncated}."""
    url = (url or "").strip()
    with _cache_lock:
        hit = _cache.get(("url", url))
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    apple = APPLE_RX.search(url)
    if apple:
        country, kind, aid, song_id = apple.groups()
        out = {"source": "apple", **_apple(api, country, kind, aid, song_id)}
    elif yt.YT_RX.search(url):
        kind, yid = yt.parse(url)
        out = {"source": "youtube", **_youtube(api, kind, yid)}
    else:
        uri = to_uri(url) if "spotify" in url else None
        if not uri:
            raise LinkError("paste a Spotify, Apple Music or YouTube link to a song, album or playlist")
        out = {"source": "spotify", **_spotify(api, uri)}
    out.update(url=url, total=len(out["tracks"]), matched=sum(1 for t in out["tracks"] if t["uri"]),
               truncated=out.get("truncated", False))
    with _cache_lock:
        _cache[("url", url)] = (time.time(), out)
    return out
