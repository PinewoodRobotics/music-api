"""The web app's Library: playlists plus albums saved as references to the real Spotify album, and the
aggregated list of every song in them. Stdlib only.
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import links
from accounts import AccountError, _read_json, _write_json
from spotify import SpotifyError, item, page, to_uri

ALBUM_TTL = 3600
SONGS_TTL = 120
PLAY_LIMIT = 100
SONG_SORTS = ("recent", "title", "artist", "album")
LIBRARY_SORTS = ("recent", "name", "creator")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _who(user):
    return {k: user.get(k) for k in ("id", "name", "avatar")}


def _paged(api, path, **params):
    offset = 0
    while True:
        res = api.get(path, limit=50, offset=offset, **params)
        yield from res.get("items", [])
        offset += 50
        if not res.get("next"):
            return


class Library:
    def __init__(self, data_dir, playlists):
        self.path = os.path.join(data_dir, "library-albums.json")
        self.playlists = playlists
        self.lock = threading.Lock()
        self.albums = _read_json(self.path, {})
        self.meta = {}
        self.tracks = {}
        self.songs_cache = None
        self.generation = 0
        self.songs_lock = threading.Lock()
        playlists.on_change = self.invalidate

    def invalidate(self):
        self.generation += 1
        self.songs_cache = None

    def can_edit(self, album_id, user):
        owner = (self.albums.get(album_id) or {}).get("added_by") or {}
        return bool(user.get("admin") or (owner.get("id") and owner.get("id") == user.get("id")))

    @staticmethod
    def _cached(store, key, build):
        hit = store.get(key)
        if hit and time.time() - hit[0] < ALBUM_TTL:
            return hit[1]
        try:
            value = build()
        except SpotifyError:
            if hit:
                return hit[1]
            raise
        store[key] = (time.time(), value)
        return value

    def _meta(self, api, album_id):
        def build():
            a = api.get(f"/albums/{album_id}")
            first = a.get("tracks") or {}
            complete = first.get("items") and not first.get("next")
            out = item(a)
            return {"kind": "album", "id": album_id, "uri": f"spotify:album:{album_id}", "name": out["name"],
                    "artists": out["artists"], "artwork": out["artwork"], "total": out["total_tracks"],
                    "year": (out.get("release_date") or "")[:4] or None,
                    "duration_ms": sum((t or {}).get("duration_ms") or 0 for t in first["items"]) if complete else None}
        return self._cached(self.meta, album_id, build)

    def _album_out(self, api, album_id, user):
        rec = self.albums[album_id]
        try:
            base = self._meta(api, album_id)
        except SpotifyError:
            base = {"kind": "album", "id": album_id, "uri": f"spotify:album:{album_id}", "name": "Unavailable album",
                    "artists": [], "artwork": None, "total": None, "year": None, "duration_ms": None}
        return {**base, "added_by": rec.get("added_by"), "added": rec.get("added"), "source_url": rec.get("source_url"),
                "can_edit": self.can_edit(album_id, user)}

    def album_tracks(self, api, album_id):
        def build():
            meta = self._meta(api, album_id)
            album = {"uri": meta["uri"], "name": meta["name"]}
            rows = []
            for t in _paged(api, f"/albums/{album_id}/tracks"):
                if t and t.get("uri"):
                    row = item(t)
                    row.update(album=album, artwork=meta["artwork"])
                    rows.append(row)
            return rows
        return self._cached(self.tracks, album_id, build)

    def get_album(self, api, album_id, user):
        if album_id not in self.albums:
            raise AccountError("album not in the library", 404)
        return {**self._album_out(api, album_id, user), "tracks": self.album_tracks(api, album_id)}

    def add_album(self, api, user, url, added_by=None, added=None):
        """Add a Spotify album (link or URI) or an Apple Music album that has a Spotify match. Idempotent."""
        ref = links.album_ref(url)
        if not ref:
            raise AccountError("paste a Spotify or Apple Music album link (use Import as playlist for playlists and songs)")
        uri = ref[1]
        if not uri:
            uri = links.resolve(api, url).get("spotify_uri")
            if not uri or not uri.startswith("spotify:album:"):
                raise AccountError("that album isn't on Spotify as a whole album; use Import as playlist to copy its songs", 422)
        album_id = uri.split(":")[2]
        if album_id in self.albums:
            return {**self._album_out(api, album_id, user), "already": True}
        self._meta(api, album_id)
        with self.lock:
            self.albums.setdefault(album_id, {"added_by": added_by or _who(user), "added": added or _now(),
                                              "source_url": (url or "").strip()})
            _write_json(self.path, self.albums)
        self.invalidate()
        return self._album_out(api, album_id, user)

    def remove_album(self, user, album_id):
        if album_id not in self.albums:
            raise AccountError("album not in the library", 404)
        if not self.can_edit(album_id, user):
            raise AccountError("only whoever added this album can remove it", 403)
        with self.lock:
            self.albums.pop(album_id, None)
            _write_json(self.path, self.albums)
        self.invalidate()
        return {"removed": f"spotify:album:{album_id}"}

    def import_link(self, api, user, url):
        """Album links become library albums; playlist and song links copy into a new playlist as before."""
        if links.album_ref(url):
            return {"kind": "album", "album": self.add_album(api, user, url)}
        return self.playlists.import_link(api, user, url)

    def list(self, api, user, kind="all", sort="recent"):
        if kind not in ("all", "playlists", "albums"):
            raise AccountError("kind must be all, playlists or albums")
        if sort not in LIBRARY_SORTS:
            raise AccountError("sort must be recent, name or creator")
        items = []
        if kind in ("all", "playlists"):
            items += [{**p, "kind": "playlist"} for p in self.playlists.list(api, user)]
        if kind in ("all", "albums") and self.albums:
            with ThreadPoolExecutor(4) as ex:
                items += list(ex.map(lambda i: self._album_out(api, i, user), list(self.albums)))

        def when(x):
            return x.get("added") or x.get("created") or ""

        def name(x):
            return (x.get("name") or "").casefold()

        def creator(x):
            return ((x.get("added_by") or x.get("created_by") or {}).get("name") or "").casefold()
        if sort == "recent":
            items.sort(key=lambda x: (bool(when(x)), when(x)), reverse=True)
        elif sort == "name":
            items.sort(key=name)
        else:
            items.sort(key=lambda x: (not creator(x), creator(x), name(x)))
        return {"items": items}

    def _build_songs(self, api, user):
        by_uri = {}

        def add(track, source, added):
            if not track or not track.get("uri") or track.get("is_local") or track.get("type") != "track":
                return
            row = by_uri.get(track["uri"])
            if not row:
                row = by_uri[track["uri"]] = {**track, "sources": [], "added": added}
                row.pop("added_at", None)
            if not any(s["kind"] == source["kind"] and s["id"] == source["id"] for s in row["sources"]):
                row["sources"].append(source)
            if added and (not row["added"] or added < row["added"]):
                row["added"] = added

        def playlist_rows(p):
            try:
                return p, page({"items": list(_paged(api, f"/playlists/{p['id']}/items", additional_types="track"))}, key="item")["items"]
            except SpotifyError:
                return p, []

        def album_rows(album_id):
            try:
                return album_id, self.album_tracks(api, album_id)
            except SpotifyError:
                return album_id, []
        with ThreadPoolExecutor(4) as ex:
            plays = list(ex.map(playlist_rows, self.playlists.list(api, user)))
            albums = list(ex.map(album_rows, list(self.albums)))
        for p, rows in plays:
            for t in rows:
                add(t, {"kind": "playlist", "id": p["id"], "name": p["name"]}, (t or {}).get("added_at"))
        for album_id, rows in albums:
            name = self._meta(api, album_id)["name"] if rows else None
            for t in rows:
                add(t, {"kind": "album", "id": album_id, "name": name}, self.albums[album_id].get("added"))
        return list(by_uri.values())

    def all_songs(self, api, user):
        with self.songs_lock:
            hit = self.songs_cache
            if hit and time.time() - hit[0] < SONGS_TTL:
                return hit[1]
            generation = self.generation
            songs = self._build_songs(api, user)
            if generation == self.generation:
                self.songs_cache = (time.time(), songs)
            return songs

    def songs(self, api, user, q="", sort="recent"):
        if sort not in SONG_SORTS:
            raise AccountError("sort must be recent, title, artist or album")
        rows = self.all_songs(api, user)
        q = (q or "").strip().casefold()
        if q:
            rows = [t for t in rows if q in (t.get("name") or "").casefold()
                    or q in ((t.get("album") or {}).get("name") or "").casefold()
                    or any(q in (a.get("name") or "").casefold() for a in t.get("artists") or [])]
        if sort == "recent":
            return sorted(rows, key=lambda t: t.get("added") or "", reverse=True)
        key = {"title": lambda t: (t.get("name") or "").casefold(),
               "artist": lambda t: ((t.get("artists") or [{}])[0].get("name") or "").casefold(),
               "album": lambda t: ((t.get("album") or {}).get("name") or "").casefold()}[sort]
        return sorted(rows, key=lambda t: (key(t), (t.get("name") or "").casefold()))

    def play_queue(self, api, user, uri, q="", sort="recent"):
        rows = self.songs(api, user, q, sort)
        uris = [t["uri"] for t in rows]
        if uri not in uris:
            raise AccountError("that song isn't in the library list", 404)
        i = uris.index(uri)
        return rows[i], uris[i:i + PLAY_LIMIT]
