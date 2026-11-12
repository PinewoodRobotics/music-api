import os
import tempfile
import unittest

import activity as act
import library as lib
import server
from accounts import AccountError, Playlists
from library import Library

ADA = {"id": "U1", "name": "Ada", "avatar": None, "admin": False}
BOB = {"id": "U2", "name": "Bob", "avatar": None, "admin": False}
ADMIN = {"id": "admin", "name": "Admin", "avatar": None, "admin": True}


def sid(c):
    return c * 22


def track(c, name, artist, album):
    return {"type": "track", "uri": f"spotify:track:{sid(c)}", "id": sid(c), "name": name, "duration_ms": 1000,
            "artists": [{"uri": "spotify:artist:x", "name": artist}], "album": {"uri": "spotify:album:z", "name": album}}


def album_obj(c, name, artist, tracks):
    return {"type": "album", "id": sid(c), "uri": f"spotify:album:{sid(c)}", "name": name, "release_date": "2020-05-01",
            "total_tracks": len(tracks), "images": [{"url": f"art-{c}"}], "artists": [{"uri": "u", "name": artist}],
            "tracks": {"items": tracks, "next": None}}


class FakeApi:
    def __init__(self):
        self.albums, self.playlists, self.items, self.calls = {}, {}, {}, []

    def get(self, path, **q):
        self.calls.append(path)
        parts = path.strip("/").split("/")
        if path == "/me/playlists":
            return {"items": list(self.playlists.values()), "next": None}
        if parts[0] == "albums":
            a = self.albums[parts[1]]
            if len(parts) == 2:
                return a
            rows = a["tracks"]["items"]
            return {"items": rows[q["offset"]:q["offset"] + 50], "next": q["offset"] + 50 < len(rows)}
        if parts[0] == "playlists":
            if len(parts) == 2:
                return self.playlists[parts[1]]
            rows = self.items[parts[1]]
            return {"items": rows[q["offset"]:q["offset"] + 50], "next": q["offset"] + 50 < len(rows)}
        raise AssertionError(path)

    def req(self, method, path, query=None, body=None):
        if (method, path) == ("POST", "/me/playlists"):
            pid = sid(chr(ord("n") + len(self.playlists)))
            pl = {"id": pid, "uri": f"spotify:playlist:{pid}", "name": body["name"], "images": [], "items": {"total": 0}}
            self.playlists[pid] = pl
            self.items[pid] = []
            return pl
        if method == "POST" and path.endswith("/items"):
            pid = path.split("/")[2]
            self.items[pid] += [{"item": {"type": "track", "uri": u, "name": u}, "added_at": "2026-01-01T00:00:00Z"} for u in body["uris"]]
            return {}
        raise AssertionError((method, path))


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.api = FakeApi()
        self.pl = Playlists(self.dir.name, None)
        self.lib = Library(self.dir.name, self.pl)
        t1, t2 = track("1", "Alpha", "Zed", "Rec"), track("2", "Beta", "Amy", "Rec")
        self.api.albums[sid("A")] = album_obj("A", "Rec", "Zed", [t1, t2])
        self.api.albums[sid("B")] = album_obj("B", "Other", "Bo", [track("3", "Gamma", "Bo", "Other")])
        self.url = f"https://open.spotify.com/album/{sid('A')}?si=x"

    def add_playlist(self, c, name, rows, user=ADA, created=None):
        pid = sid(c)
        self.api.playlists[pid] = {"id": pid, "uri": f"spotify:playlist:{pid}", "name": name, "images": [], "items": {"total": len(rows)}}
        self.api.items[pid] = rows
        self.pl._record(pid, user)
        if created:
            self.pl.meta[pid]["created"] = created
        return pid

    def test_add_remove_and_idempotent(self):
        a = self.lib.add_album(self.api, ADA, self.url)
        self.assertEqual((a["kind"], a["id"], a["name"], a["total"], a["year"], a["duration_ms"]), ("album", sid("A"), "Rec", 2, "2020", 2000))
        self.assertEqual(a["added_by"], {"id": "U1", "name": "Ada", "avatar": None})
        self.assertTrue(a["can_edit"])
        self.assertNotIn("already", a)
        again = self.lib.add_album(self.api, BOB, f"spotify:album:{sid('A')}")
        self.assertTrue(again["already"])
        self.assertEqual(again["added_by"]["id"], "U1")
        self.assertFalse(again["can_edit"])
        self.assertEqual(oct(os.stat(self.lib.path).st_mode & 0o777), "0o600")
        with self.assertRaises(AccountError) as e:
            self.lib.remove_album(BOB, sid("A"))
        self.assertEqual(e.exception.status, 403)
        self.assertEqual(self.lib.remove_album(ADA, sid("A")), {"removed": f"spotify:album:{sid('A')}"})
        with self.assertRaises(AccountError) as e:
            self.lib.remove_album(ADMIN, sid("A"))
        self.assertEqual(e.exception.status, 404)
        self.lib.add_album(self.api, ADA, self.url)
        self.lib.remove_album(ADMIN, sid("A"))

    def test_rejects_non_albums(self):
        for u in (f"spotify:playlist:{sid('p')}", "https://music.apple.com/us/album/x/1?i=2", "nonsense"):
            with self.assertRaises(AccountError):
                self.lib.add_album(self.api, ADA, u)

    def test_apple_album_without_spotify_match_is_422(self):
        orig = lib.links.resolve
        lib.links.resolve = lambda api, url: {"kind": "album", "spotify_uri": None}
        self.addCleanup(setattr, lib.links, "resolve", orig)
        with self.assertRaises(AccountError) as e:
            self.lib.add_album(self.api, ADA, "https://music.apple.com/us/album/x/123")
        self.assertEqual(e.exception.status, 422)
        self.assertIn("Import as playlist", str(e.exception))

    def test_apple_album_with_match(self):
        orig = lib.links.resolve
        lib.links.resolve = lambda api, url: {"kind": "album", "spotify_uri": f"spotify:album:{sid('B')}"}
        self.addCleanup(setattr, lib.links, "resolve", orig)
        a = self.lib.add_album(self.api, ADA, "https://music.apple.com/us/album/x/123")
        self.assertEqual(a["id"], sid("B"))
        self.assertEqual(a["source_url"], "https://music.apple.com/us/album/x/123")

    def test_admin_credit_override_and_persistence(self):
        self.lib.add_album(self.api, ADMIN, self.url, added_by=ADA, added="2025-01-01T00:00:00Z")
        again = Library(self.dir.name, self.pl)
        a = again.get_album(self.api, sid("A"), ADA)
        self.assertEqual((a["added_by"]["id"], a["added"], a["can_edit"]), ("U1", "2025-01-01T00:00:00Z", True))
        self.assertEqual([t["name"] for t in a["tracks"]], ["Alpha", "Beta"])
        self.assertEqual(a["tracks"][0]["album"]["name"], "Rec")

    def test_listing_kind_and_sort(self):
        self.add_playlist("p", "Zebra mix", [], ADA, "2026-01-02T00:00:00Z")
        self.add_playlist("q", "apple mix", [], BOB, "2026-01-04T00:00:00Z")
        self.lib.add_album(self.api, BOB, self.url, added="2026-01-03T00:00:00Z")
        names = lambda **kw: [(i["kind"], i["name"]) for i in self.lib.list(self.api, ADA, **kw)["items"]]
        self.assertEqual(names(), [("playlist", "apple mix"), ("album", "Rec"), ("playlist", "Zebra mix")])
        self.assertEqual(names(kind="albums"), [("album", "Rec")])
        self.assertEqual(names(kind="playlists", sort="name"), [("playlist", "apple mix"), ("playlist", "Zebra mix")])
        self.assertEqual(names(sort="name")[0], ("playlist", "apple mix"))
        self.assertEqual([n for _, n in names(sort="creator")], ["Zebra mix", "apple mix", "Rec"])
        self.assertEqual(self.lib.list(self.api, ADA)["items"][0]["can_edit"], False)
        with self.assertRaises(AccountError):
            self.lib.list(self.api, ADA, kind="x")

    def rows(self, *cs):
        return [{"item": {"type": "track", "uri": f"spotify:track:{sid(c)}", "name": n, "artists": [{"name": "Zed"}],
                          "album": {"name": "PL"}}, "added_at": at} for c, n, at in cs]

    def test_songs_aggregate_dedupe_filter_sort(self):
        self.add_playlist("p", "Mix", self.rows(("1", "Alpha", "2026-03-01T00:00:00Z"), ("9", "Zulu", "2026-02-01T00:00:00Z")))
        self.lib.add_album(self.api, ADA, self.url, added="2026-01-01T00:00:00Z")
        songs = self.lib.songs(self.api, ADA)
        self.assertEqual(len(songs), 3)
        alpha = next(t for t in songs if t["name"] == "Alpha")
        self.assertEqual(sorted((s["kind"], s["name"]) for s in alpha["sources"]), [("album", "Rec"), ("playlist", "Mix")])
        self.assertEqual(alpha["added"], "2026-01-01T00:00:00Z")
        self.assertEqual([t["name"] for t in songs], ["Zulu", "Alpha", "Beta"])
        self.assertEqual([t["name"] for t in self.lib.songs(self.api, ADA, sort="title")], ["Alpha", "Beta", "Zulu"])
        self.assertEqual([t["name"] for t in self.lib.songs(self.api, ADA, sort="artist")], ["Beta", "Alpha", "Zulu"])
        self.assertEqual([t["name"] for t in self.lib.songs(self.api, ADA, q="AMY")], ["Beta"])
        self.assertEqual({t["name"] for t in self.lib.songs(self.api, ADA, q="rec")}, {"Beta"})
        with self.assertRaises(AccountError):
            self.lib.songs(self.api, ADA, sort="x")

    def test_songs_cache_and_invalidation(self):
        pid = self.add_playlist("p", "Mix", self.rows(("9", "Zulu", "2026-02-01T00:00:00Z")))
        self.assertEqual(len(self.lib.songs(self.api, ADA)), 1)
        n = len(self.api.calls)
        self.lib.songs(self.api, ADA)
        self.assertEqual(len(self.api.calls), n)
        self.lib.add_album(self.api, ADA, self.url)
        self.assertEqual(len(self.lib.songs(self.api, ADA)), 3)
        self.api.items[pid] += self.rows(("8", "Yankee", "2026-04-01T00:00:00Z"))
        self.assertEqual(len(self.lib.songs(self.api, ADA)), 3)
        self.lib.invalidate()
        self.assertEqual(len(self.lib.songs(self.api, ADA)), 4)
        self.pl._record(sid("p"), ADA)
        self.assertIsNone(self.lib.songs_cache)
        self.lib.songs(self.api, ADA)
        self.lib.remove_album(ADA, sid("A"))
        self.assertEqual(len(self.lib.songs(self.api, ADA)), 2)

    def test_cache_expires(self):
        self.add_playlist("p", "Mix", [])
        self.lib.songs(self.api, ADA)
        self.lib.songs_cache = (self.lib.songs_cache[0] - lib.SONGS_TTL - 1, self.lib.songs_cache[1])
        n = len(self.api.calls)
        self.lib.songs(self.api, ADA)
        self.assertGreater(len(self.api.calls), n)

    def test_play_queue_starts_at_song_in_order_and_caps(self):
        self.lib.add_album(self.api, ADA, self.url)
        song, uris = self.lib.play_queue(self.api, ADA, f"spotify:track:{sid('2')}", sort="title")
        self.assertEqual((song["name"], uris), ("Beta", [f"spotify:track:{sid('2')}"]))
        _, uris = self.lib.play_queue(self.api, ADA, f"spotify:track:{sid('1')}", sort="title")
        self.assertEqual(len(uris), 2)
        with self.assertRaises(AccountError):
            self.lib.play_queue(self.api, ADA, f"spotify:track:{sid('8')}")
        many = [track(chr(97 + i % 26) + "", f"T{i:03}", "A", "R") for i in range(150)]
        for i, t in enumerate(many):
            t["uri"] = f"spotify:track:{i:022}"
        self.api.albums[sid("C")] = album_obj("C", "Big", "A", many)
        self.lib.add_album(self.api, ADA, f"spotify:album:{sid('C')}")
        _, uris = self.lib.play_queue(self.api, ADA, many[0]["uri"], q="T", sort="title")
        self.assertEqual(len(uris), lib.PLAY_LIMIT)

    def test_import_routes_albums_to_library(self):
        res = self.lib.import_link(self.api, ADA, self.url)
        self.assertEqual((res["kind"], res["album"]["id"]), ("album", sid("A")))
        self.assertEqual(self.api.playlists, {})
        self.assertTrue(self.lib.import_link(self.api, ADA, self.url)["album"]["already"])

    def test_import_routes_playlists_to_playlists(self):
        calls = []
        self.pl.import_link = lambda api, user, url: calls.append(url) or {"playlist": {"id": "x"}}
        self.lib.import_link(self.api, ADA, "https://open.spotify.com/playlist/" + sid("p"))
        self.lib.import_link(self.api, ADA, "https://music.apple.com/us/album/x/1?i=2")
        self.assertEqual(len(calls), 2)

    def test_duplicate_playlist(self):
        pid = self.add_playlist("p", "Mix", self.rows(("1", "Alpha", "2026-03-01T00:00:00Z"), ("9", "Zulu", "2026-02-01T00:00:00Z")))
        copy = self.pl.duplicate(self.api, BOB, pid)
        self.assertEqual((copy["name"], copy["total"], copy["created_by"]["id"], copy["can_edit"]), ("Mix (copy)", 2, "U2", True))
        self.assertEqual([r["item"]["uri"] for r in self.api.items[copy["id"]]],
                         [f"spotify:track:{sid('1')}", f"spotify:track:{sid('9')}"])
        self.assertEqual(self.pl.duplicate(self.api, BOB, pid, " Mine ")["name"], "Mine")


class ReorderAccessTest(unittest.TestCase):
    def test_slack_users_can_reorder_visible_playlists_only(self):
        server.app_playlists = type("P", (), {"is_hidden": staticmethod(lambda i: i == "hidden")})()
        server._req.user, server._req.bearer = {**ADA, "admin": False}, True
        h = object.__new__(server.Handler)
        self.assertIsNone(h._forbidden("PUT", "/api/playlists/abc/items"))
        self.assertEqual(h._forbidden("PUT", "/api/playlists/hidden/items"), "admins only")
        self.assertEqual(h._forbidden("PATCH", "/api/playlists/abc"), "admins only")


class ReorderActivityTest(unittest.TestCase):
    def test_reorder_coalesces_per_user_and_playlist(self):
        a = act.Activity(None, lambda: 1000.0)
        e1 = a.record(ADA, "playlist_reorder", {"id": "p1"})
        e2 = a.record(ADA, "playlist_reorder", {"id": "p1"})
        e3 = a.record(ADA, "playlist_reorder", {"id": "p2"})
        e4 = a.record(BOB, "playlist_reorder", {"id": "p1"})
        self.assertEqual(e1["id"], e2["id"])
        self.assertEqual(len({e1["id"], e3["id"], e4["id"]}), 3)


if __name__ == "__main__":
    unittest.main()
