#!/usr/bin/env python3
"""Turn app playlists that are unedited copies of an album into Library albums.

For every app playlist whose source_url is an album link (open.spotify.com/album/... or music.apple.com/.../album/...
without ?i=), compare its track URIs with the album's matched Spotify tracks. Identical means an untouched copy: the
album is added to the Library credited to the playlist's creator and creation time, then the playlist is deleted.
Edited copies are left alone.

Talks to the running server over HTTP (admin token), so its in-memory state stays consistent.
Dry run by default; pass --apply to act.

    python3 deploy/migrate_album_playlists.py [--base URL] [--token TOKEN] [--apply]
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import links  # noqa: E402

TOKEN_FILE = os.path.expanduser("~/.local/share/music-api/token")


class Client:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method, path, body=None, **query):
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json",
                                              "User-Agent": "music-api-migrate/1"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["result"]
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("error")
            except ValueError:
                msg = None
            raise RuntimeError(f"{method} {path}: HTTP {e.code} {msg or ''}".strip())

    def playlist_uris(self, pid):
        uris, offset = [], 0
        while True:
            page = self.call("GET", f"/api/playlists/{pid}/items", limit=50, offset=offset)
            uris += [t["uri"] for t in page["items"] if t and t.get("uri")]
            offset += 50
            if not page.get("next"):
                return uris


def check(client, p):
    """(verdict, reason): verdict is 'migrate' or 'keep'."""
    src = client.call("POST", "/api/resolve", {"url": p["source_url"]})
    if src["kind"] != "album":
        return "keep", "source isn't an album"
    if not (src.get("spotify_uri") or "").startswith("spotify:album:"):
        return "keep", "no Spotify album match"
    album = [t["uri"] for t in src["tracks"] if t["uri"]]
    current = client.playlist_uris(p["id"])
    if current == album:
        return "migrate", f"identical, {len(album)} tracks"
    if sorted(current) == sorted(album):
        return "keep", "edited: tracks reordered"
    added, removed = len(set(current) - set(album)), len(set(album) - set(current))
    return "keep", f"edited: {added} added, {removed} removed" if added or removed else "edited: duplicates changed"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default=os.environ.get("MUSIC_API_URL", "http://127.0.0.1:8765"))
    ap.add_argument("--token", default=os.environ.get("MUSIC_API_TOKEN"))
    ap.add_argument("--apply", action="store_true", help="actually add albums and delete playlists (default: dry run)")
    a = ap.parse_args()
    token = a.token
    if not token:
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
    client = Client(a.base, token)

    rows = []
    for p in client.call("GET", "/api/app/playlists"):
        if links.album_ref(p.get("source_url")):
            try:
                verdict, reason = check(client, p)
            except Exception as e:  # noqa: BLE001 - report and carry on with the other playlists
                verdict, reason = "keep", f"error: {e}"
            if verdict == "migrate" and a.apply:
                try:
                    album = client.call("POST", "/api/app/library/albums",
                                        {"url": p["source_url"], "added_by": p["created_by"], "added": p["created"]})
                    client.call("DELETE", f"/api/app/playlists/{p['id']}")
                    verdict, reason = "migrated", f"album {album['id']}" + (" (already in library)" if album.get("already") else "")
                except Exception as e:  # noqa: BLE001
                    verdict, reason = "failed", str(e)
            rows.append((verdict, p["id"], (p["name"] or "")[:44], (p.get("created_by") or {}).get("name") or "-", reason))

    if not rows:
        print("No playlists were imported from album links.")
        return
    widths = [max(len(r[i]) for r in rows + [("verdict", "playlist", "name", "by", "reason")]) for i in range(5)]
    for r in [("verdict", "playlist", "name", "by", "reason")] + rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    todo = sum(r[0] == "migrate" for r in rows)
    print(f"\n{'Applied' if a.apply else 'Dry run'}: {sum(r[0] == 'migrated' for r in rows) if a.apply else todo} to migrate, "
          f"{sum(r[0] in ('keep', 'failed') for r in rows)} left alone." + ("" if a.apply else "  Re-run with --apply to act."))


if __name__ == "__main__":
    main()
