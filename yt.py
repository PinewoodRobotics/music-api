"""YouTube and YouTube Music links as song rows for links.py. Stdlib only.

Metadata comes from YouTube Music's public InnerTube endpoints (no key, no login); single videos fall back to oEmbed.
Nothing here plays or downloads from YouTube.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import links

CLIENT_VERSION = "1.20261005.01.00"
INNERTUBE = "https://music.youtube.com/youtubei/v1/"
PLAYLIST_LIMIT = 500
VIDEO_RX = re.compile(r"^[\w-]{11}$")
YT_RX = re.compile(r"^<?(?:https?://)?(?:(?:www|m|music)\.)?(?:youtube(?:-nocookie)?\.com|youtu\.be)(?:[/?#>|]|$)", re.I)
PRIVATE_LISTS = ("LL", "FL", "LM", "WL")

NOISE = (r"official|video|audio|lyrics?|visuali[sz]er|re-?master(?:ed)?|\d{4}\s*re-?master(?:ed)?|4k|8k|hd|hq|mv|m/v|"
         r"music|explicit|clean|full song|full album|with lyrics|hd audio|audio only|official audio")
NOISE_RX = re.compile(rf"\s*[\(\[]\s*(?:(?:{NOISE})\b[^\)\]]*)[\)\]]", re.I)
TRAIL_RX = re.compile(r"\s+(?:official\s+(?:music\s+)?(?:video|audio)|lyric video|lyrics)$", re.I)
FEAT_TAIL_RX = re.compile(r"\s+(?:feat|ft|featuring)\.?\s+(.+)$", re.I)
DASH_RX = re.compile(r"\s+[-\u2013\u2014]\s+")


def _find(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            else:
                yield from _find(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from _find(v, key)


def _get(o, *path):
    for p in path:
        try:
            o = o[p]
        except (KeyError, IndexError, TypeError):
            return None
    return o


def _text(node):
    return "".join(r.get("text", "") for r in (node or {}).get("runs") or [] if isinstance(r, dict))


def _innertube(endpoint, body):
    payload = {"context": {"client": {"clientName": "WEB_REMIX", "clientVersion": CLIENT_VERSION, "hl": "en", "gl": "US"}}, **body}
    req = urllib.request.Request(f"{INNERTUBE}{endpoint}?prettyPrint=false", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json", "User-Agent": links.UA,
                                  "Origin": "https://music.youtube.com"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise links.LinkError(f"music.youtube.com: HTTP {e.code}", 502)
    except urllib.error.URLError as e:
        raise links.LinkError(f"couldn't reach music.youtube.com: {e.reason}", 502)
    except ValueError:
        raise links.LinkError("music.youtube.com sent something unreadable", 502)


def parse(url):
    """(kind, id) for a YouTube / YouTube Music link: kind is track, album or playlist."""
    raw = (url or "").strip().lstrip("<").split("|")[0].rstrip(">")
    u = urllib.parse.urlsplit(raw if "//" in raw else "https://" + raw)
    host = (u.hostname or "").lower()
    host = re.sub(r"^(?:www|m|music)\.", "", host)
    parts = [p for p in u.path.split("/") if p]
    q = urllib.parse.parse_qs(u.query)
    vid, lst = (q.get("v") or [""])[0], (q.get("list") or [""])[0]

    def video(v):
        if not VIDEO_RX.match(v or ""):
            raise links.LinkError("that doesn't look like a YouTube video link")
        return "track", v

    def playlist(pl):
        if not pl:
            raise links.LinkError("that doesn't look like a YouTube playlist link")
        if pl.startswith(PRIVATE_LISTS):
            raise links.LinkError("that's a private YouTube list (liked songs, watch later); add the songs to a public playlist and paste that")
        if pl.startswith("RD"):
            raise links.LinkError("YouTube mixes are generated per listener and can't be imported; paste a playlist or album link")
        return ("album" if pl.startswith("OLAK5uy_") else "playlist"), pl

    if host == "youtu.be":
        return video(parts[0] if parts else "")
    if host not in ("youtube.com", "youtube-nocookie.com") or not parts:
        raise links.LinkError("paste a YouTube or YouTube Music link to a song, album or playlist")
    head = parts[0]
    if head == "watch":
        return video(vid) if vid else playlist(lst)
    if head in ("shorts", "live", "v", "embed") and len(parts) > 1:
        return playlist(lst) if parts[1] == "videoseries" else video(parts[1])
    if head == "playlist":
        return playlist(lst)
    if head == "browse" and len(parts) > 1:
        if parts[1].startswith("MPREb_"):
            return "album", parts[1]
        if parts[1].startswith("VL"):
            return playlist(parts[1][2:])
    if head in ("channel", "browse", "c", "user") or head.startswith("@"):
        raise links.LinkError("YouTube channel and artist links aren't supported; paste a song, album or playlist")
    raise links.LinkError("paste a YouTube or YouTube Music link to a song, album or playlist")


def _clean_channel(name):
    name = re.sub(r"\s+-\s+Topic$", "", name or "", flags=re.I)
    name = re.sub(r"\s*VEVO$", "", name, flags=re.I)
    return re.sub(r"\s+Official$|^Official\s+", "", name, flags=re.I).strip()


def clean_title(title, channel=None):
    """(name, artists) from a user-uploaded video title and its channel name."""
    name = NOISE_RX.sub("", title or "")
    name = TRAIL_RX.sub("", re.sub(r"\s*[|\u2502].*$", "", name).strip())
    artists, guests = [], []
    parts = DASH_RX.split(name, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        artists, name = links._artists(parts[0]), parts[1].strip()
    elif channel:
        artists = [_clean_channel(channel)]
    feat = FEAT_TAIL_RX.search(name)
    if feat:
        name, guests = name[:feat.start()].strip(), links._artists(feat.group(1))
    name = NOISE_RX.sub("", name).strip(" -\u2013\u2014")
    return name or (title or "").strip(), [a for a in artists + guests if a]


def _duration(text):
    try:
        secs = 0
        for p in text.strip().split(":"):
            secs = secs * 60 + int(p)
        return secs * 1000
    except (AttributeError, ValueError):
        return None


def _art(thumbs, size=544):
    url = _get(thumbs, -1, "url") if isinstance(thumbs, list) else None
    if not url:
        return None
    return re.sub(r"=w\d+-h\d+", f"=w{size}-h{size}", url) if "googleusercontent" in url else None


def thumbnail(vid):
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


def _runs_artists(runs):
    linked = [r["text"] for r in runs if isinstance(r, dict) and r.get("text") and
              _get(r, "navigationEndpoint", "browseEndpoint", "browseId") and
              not str(_get(r, "navigationEndpoint", "browseEndpoint", "browseId")).startswith("MPRE")]
    if linked:
        return [_clean_channel(a) for a in linked]
    return [_clean_channel(a) for a in links._artists("".join(r.get("text", "") for r in runs if isinstance(r, dict)))]


def _album_run(runs):
    return next((r for r in runs if str(_get(r, "navigationEndpoint", "browseEndpoint", "browseId")).startswith("MPRE")), {})


def _clean_row(title, artists, album, duration_ms, art, vtype):
    if vtype in ("MUSIC_VIDEO_TYPE_ATV", "MUSIC_VIDEO_TYPE_OMV"):
        row = links._song(title, artists, album, duration_ms, art if vtype.endswith("ATV") else None)
    else:
        name, who = clean_title(title, ", ".join(artists))
        row = links._song(name, who, album, duration_ms, None)
        row["loose"] = True
    return row


def _list_row(r):
    cols = [_get(c, "musicResponsiveListItemFlexColumnRenderer", "text") or {} for c in r.get("flexColumns") or []]
    cols += [{}] * (3 - len(cols))
    vtype = next(_find(cols[0], "musicVideoType"), "") or ""
    vid = _get(r, "playlistItemData", "videoId") or next(_find(cols[0], "videoId"), None)
    if not vid or "PODCAST" in vtype:
        return None
    title = _text(cols[0])
    if not title:
        return None
    fixed = _get(r, "fixedColumns", 0, "musicResponsiveListItemFixedColumnRenderer", "text")
    art = _art(next(_find(r.get("thumbnail"), "thumbnails"), None))
    return _clean_row(title, _runs_artists(cols[1].get("runs") or []), _album_run(cols[2].get("runs") or []).get("text"),
                      _duration(_text(fixed)), art, vtype)


def _shelf_items(resp):
    items = next(_find(resp, "continuationItems"), None)
    if items is None:
        items = next((s.get("contents") for k in ("musicPlaylistShelfRenderer", "musicShelfRenderer", "musicPlaylistShelfContinuation",
                                                   "musicShelfContinuation")
                      for s in _find(resp, k) if isinstance(s, dict) and s.get("contents")), None)
    return items if isinstance(items, list) else []


def _rows(items):
    songs, token = [], None
    for it in items:
        if not isinstance(it, dict):
            continue
        if isinstance(it.get("musicResponsiveListItemRenderer"), dict):
            row = _list_row(it["musicResponsiveListItemRenderer"])
            if row:
                songs.append(row)
        elif "continuationItemRenderer" in it:
            token = next(_find(it, "token"), None)
    return songs, token


def _header(resp):
    for key in ("musicResponsiveHeaderRenderer", "musicDetailHeaderRenderer"):
        h = next(_find(resp, key), None)
        if isinstance(h, dict):
            return h
    return {}


def _browse_rows(browse_id, limit):
    resp = _innertube("browse", {"browseId": browse_id})
    items = _shelf_items(resp)
    songs, token = _rows(items)
    while token and len(songs) < limit:
        more, token = _rows(_shelf_items(_innertube("browse", {"continuation": token})))
        if not more:
            break
        songs += more
    return resp, items, songs, bool(token) or len(songs) > limit


def track(vid):
    """The song row for a video id, or a LinkError."""
    try:
        resp = _innertube("next", {"videoId": vid})
        # unknown ids still get HTTP 200, just without any renderers
        panel = next((p for p in _find(resp, "playlistPanelVideoRenderer") if isinstance(p, dict) and p.get("videoId") == vid), None)
        if panel:
            groups, cur = [], []
            for run in _get(panel, "longBylineText", "runs") or []:
                if run.get("text", "").strip() == "\u2022":
                    groups.append(cur)
                    cur = []
                else:
                    cur.append(run)
            groups.append(cur)
            vtype = next(_find(panel, "musicVideoType"), "") or ""
            row = _clean_row(_text(panel.get("title")), _runs_artists(groups[0]), _album_run(sum(groups, [])).get("text"),
                             _duration(_text(panel.get("lengthText"))), _art(_get(panel, "thumbnail", "thumbnails")), vtype)
            if row["name"]:
                return row
    except links.LinkError:
        pass
    return _oembed(vid)


def _oembed(vid):
    target = urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}", safe="")
    try:
        data = links._fetch(f"https://www.youtube.com/oembed?url={target}&format=json")
    except links.LinkError:
        raise links.LinkError("couldn't read that YouTube video (is it public?)", 404)
    name, artists = clean_title(data.get("title"), data.get("author_name"))
    if not name:
        raise links.LinkError("couldn't read that YouTube video (is it public?)", 404)
    row = links._song(name, artists, None, None, None)
    row["loose"] = True
    return row


def _album_header(resp):
    h = _header(resp)
    if not h:
        return None
    strap = _get(h, "straplineTextOne") or _get(h, "subtitle") or {}
    return {"name": _text(h.get("title")), "artist": _text(strap),
            "artwork": _art(next(_find(h.get("thumbnail"), "thumbnails"), None), 600)}


def album(album_id):
    """{name, artist, artwork, songs} for a YouTube Music album (MPREb_ browse id) or its OLAK playlist id."""
    if album_id.startswith("MPREb_"):
        resp = _innertube("browse", {"browseId": album_id})
        meta = _album_header(resp)
        songs, _ = _rows(_shelf_items(resp))
        if not meta or not meta["name"] or not songs:
            raise links.LinkError("couldn't find that YouTube Music album", 404)
        for s in songs:
            s["artists"] = s["artists"] or [meta["artist"]]
            s["album"] = s["album"] or meta["name"]
            s["artwork"] = s["artwork"] or meta["artwork"]
        return {**meta, "songs": songs}
    _, items, songs, _ = _browse_rows("VL" + album_id, PLAYLIST_LIMIT)
    if not songs:
        raise links.LinkError("couldn't find that YouTube Music album", 404)
    mpre = next((_get(_album_run(runs), "navigationEndpoint", "browseEndpoint", "browseId") for runs in _find(items, "runs")
                 if _album_run(runs)), None)
    try:
        meta = album(mpre) if mpre else None
    except links.LinkError:
        meta = None
    if meta:
        for s, m in zip(songs, meta["songs"]):
            s["artwork"] = s["artwork"] or m["artwork"] or meta["artwork"]
        return {**meta, "songs": songs}
    first = songs[0]
    return {"name": first["album"] or "YouTube Music album", "artist": ", ".join(first["artists"]), "artwork": first["artwork"],
            "songs": songs}


def playlist(playlist_id):
    """{name, owner, artwork, songs, truncated} for a public YouTube playlist, capped at PLAYLIST_LIMIT songs."""
    resp, items, songs, more = _browse_rows("VL" + playlist_id, PLAYLIST_LIMIT)
    if not items or not songs:
        raise links.LinkError("couldn't find any songs in that YouTube playlist (is it public?)", 404)
    h = _header(resp)
    name = _text(h.get("title")) or _get(next(_find(resp, "microformatDataRenderer"), {}), "title") or "YouTube playlist"
    return {"name": name, "owner": _text(h.get("straplineTextOne")) or None,
            "artwork": _art(next(_find(h.get("thumbnail"), "thumbnails"), None), 600),
            "songs": songs[:PLAYLIST_LIMIT], "truncated": more}
