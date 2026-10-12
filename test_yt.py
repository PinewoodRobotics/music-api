import unittest
from unittest import mock

import links
import slack_bot as sb
import yt
from spotify import SpotifyError


def runs(*parts):
    out = []
    for p in parts:
        text, browse = (p, None) if isinstance(p, str) else p
        run = {"text": text}
        if browse:
            run["navigationEndpoint"] = {"browseEndpoint": {"browseId": browse}}
        out.append(run)
    return {"runs": out}


def thumbs(url):
    return {"thumbnails": [{"url": "x=w60-h60", "width": 60}, {"url": url, "width": 544}]}


def panel(vid, title, byline, length, vtype, art="https://i.ytimg.com/vi/x/hq720.jpg"):
    return {"playlistPanelVideoRenderer": {
        "title": runs(title), "longBylineText": runs(*byline), "lengthText": runs(length), "videoId": vid,
        "thumbnail": thumbs(art),
        "navigationEndpoint": {"watchEndpoint": {"videoId": vid, "watchEndpointMusicSupportedConfigs": {
            "watchEndpointMusicConfig": {"musicVideoType": vtype}}}}}}


def next_resp(*panels):
    return {"contents": {"singleColumnMusicWatchNextResultsRenderer": {"tabbedRenderer": {"watchNextTabbedResultsRenderer": {
        "tabs": [{"tabRenderer": {"content": {"musicQueueRenderer": {"content": {"playlistPanelRenderer": {
            "contents": list(panels) + [{"automixPreviewVideoRenderer": {}}]}}}}}}]}}}}}


def row(vid, title, artist="", album=None, dur="3:00", vtype="MUSIC_VIDEO_TYPE_ATV", art=None, artist_id="UCartist"):
    cols = [{"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": title, "navigationEndpoint": {
        "watchEndpoint": {"videoId": vid, "watchEndpointMusicSupportedConfigs": {"watchEndpointMusicConfig": {
            "musicVideoType": vtype}}}}}]}}},
            {"musicResponsiveListItemFlexColumnRenderer": {"text": runs((artist, artist_id)) if artist else {}}},
            {"musicResponsiveListItemFlexColumnRenderer": {"text": runs((album[0], album[1])) if album else {}}}]
    return {"musicResponsiveListItemRenderer": {
        "flexColumns": cols, "playlistItemData": {"videoId": vid},
        "fixedColumns": [{"musicResponsiveListItemFixedColumnRenderer": {"text": runs(dur)}}],
        "thumbnail": {"musicThumbnailRenderer": {"thumbnail": thumbs(art or "https://i.ytimg.com/vi/x/hq720.jpg")}}}}


def continuation(token):
    return {"continuationItemRenderer": {"continuationEndpoint": {"continuationCommand": {"token": token}}}}


def browse_resp(items, title=None, strap="", art=None):
    out = {"contents": {"twoColumnBrowseResultsRenderer": {"secondaryContents": {"sectionListRenderer": {"contents": [
        {"musicPlaylistShelfRenderer": {"contents": items}}]}}}}}
    if title:
        out["contents"]["twoColumnBrowseResultsRenderer"]["tabs"] = [{"tabRenderer": {"content": {"sectionListRenderer": {
            "contents": [{"musicResponsiveHeaderRenderer": {
                "title": runs(title), "straplineTextOne": runs(strap) if strap else {},
                "thumbnail": {"musicThumbnailRenderer": {"thumbnail": thumbs(art or "https://yt3.googleusercontent.com/a=w544-h544-l90-rj")}}}}]}}}}]
    return out


def album_resp(title, artist, items):
    out = browse_resp([], title, artist)
    out["contents"]["twoColumnBrowseResultsRenderer"]["secondaryContents"]["sectionListRenderer"]["contents"] = [
        {"musicShelfRenderer": {"contents": items}}]
    return out


def serve(responses):
    calls = []

    def fake(endpoint, body):
        calls.append((endpoint, body))
        key = body.get("videoId") or body.get("browseId") or body.get("continuation")
        resp = responses[key]
        if isinstance(resp, Exception):
            raise resp
        return resp
    return mock.patch.object(yt, "_innertube", fake), calls


ATV = "MUSIC_VIDEO_TYPE_ATV"
OMV = "MUSIC_VIDEO_TYPE_OMV"
UGC = "MUSIC_VIDEO_TYPE_UGC"
VID = "9RfVp-GhKfs"


class Parse(unittest.TestCase):
    def test_table(self):
        cases = {
            "https://www.youtube.com/watch?v=9RfVp-GhKfs": ("track", VID),
            "https://music.youtube.com/watch?v=9RfVp-GhKfs&si=abc&feature=share": ("track", VID),
            "http://m.youtube.com/watch?v=9RfVp-GhKfs&t=30s&pp=x": ("track", VID),
            "youtube.com/watch?v=9RfVp-GhKfs": ("track", VID),
            "https://www.youtube-nocookie.com/embed/9RfVp-GhKfs": ("track", VID),
            "https://youtu.be/9RfVp-GhKfs?si=abc": ("track", VID),
            "https://youtu.be/9RfVp-GhKfs/": ("track", VID),
            "https://www.youtube.com/shorts/9RfVp-GhKfs": ("track", VID),
            "https://www.youtube.com/live/9RfVp-GhKfs?feature=share": ("track", VID),
            "https://www.youtube.com/embed/9RfVp-GhKfs": ("track", VID),
            "https://www.youtube.com/watch?v=9RfVp-GhKfs&list=PLabcdefghijklmnop": ("track", VID),
            "https://www.youtube.com/watch?v=9RfVp-GhKfs&list=RDAMVM9RfVp-GhKfs": ("track", VID),
            "https://www.youtube.com/playlist?list=OLAK5uy_l1_KgYytnFrThUgqIjsEA7-WaQ8M4Y-No":
                ("album", "OLAK5uy_l1_KgYytnFrThUgqIjsEA7-WaQ8M4Y-No"),
            "https://music.youtube.com/playlist?list=OLAK5uy_abc": ("album", "OLAK5uy_abc"),
            "https://www.youtube.com/playlist?list=PLMC9KNkIncKvYin_USF1qoJQnIyMAfRxl": ("playlist", "PLMC9KNkIncKvYin_USF1qoJQnIyMAfRxl"),
            "https://www.youtube.com/playlist?list=UUabcdefghijklmnop": ("playlist", "UUabcdefghijklmnop"),
            "https://www.youtube.com/watch?list=PLabcdefghijklmnop": ("playlist", "PLabcdefghijklmnop"),
            "https://music.youtube.com/browse/MPREb_TgQPwAzodvg": ("album", "MPREb_TgQPwAzodvg"),
            "<https://youtu.be/9RfVp-GhKfs|that song>": ("track", VID),
        }
        for url, want in cases.items():
            self.assertEqual(yt.parse(url), want, url)

    def test_unsupported(self):
        for url, word in [("https://www.youtube.com/playlist?list=LL", "private"),
                          ("https://www.youtube.com/playlist?list=FLabc", "private"),
                          ("https://www.youtube.com/playlist?list=LM", "private"),
                          ("https://www.youtube.com/playlist?list=RDAMVM9RfVp-GhKfs", "mixes"),
                          ("https://www.youtube.com/channel/UCr_iyUANcn9OX_yy9piYoLw", "channel"),
                          ("https://music.youtube.com/browse/UCr_iyUANcn9OX_yy9piYoLw", "channel"),
                          ("https://www.youtube.com/@radiohead", "channel"),
                          ("https://www.youtube.com/watch?v=short", "video"),
                          ("https://www.youtube.com/feed/history", "paste"),
                          ("https://example.com/watch?v=9RfVp-GhKfs", "paste")]:
            with self.assertRaises(links.LinkError, msg=url) as cm:
                yt.parse(url)
            self.assertIn(word, str(cm.exception), url)
            self.assertEqual(cm.exception.status, 400)

    def test_detect(self):
        self.assertTrue(yt.YT_RX.search("https://music.youtube.com/watch?v=x"))
        self.assertTrue(yt.YT_RX.search("youtu.be/x"))
        self.assertFalse(yt.YT_RX.search("https://open.spotify.com/track/x"))
        self.assertFalse(yt.YT_RX.search("https://notyoutube.com/x"))


class CleanTitle(unittest.TestCase):
    def test_cases(self):
        for title, channel, want in [
            ("Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)", "Rick Astley",
             ("Never Gonna Give You Up", ["Rick Astley"])),
            ("Billie Eilish - bad guy [Official Music Video] | HD", "Billie Eilish", ("bad guy", ["Billie Eilish"])),
            ("Daft Punk - Get Lucky (Official Audio) ft. Pharrell Williams, Nile Rodgers", "Daft Punk",
             ("Get Lucky", ["Daft Punk", "Pharrell Williams", "Nile Rodgers"])),
            ("Never Gonna Give You Up", "RickAstleyVEVO", ("Never Gonna Give You Up", ["RickAstley"])),
            ("Creep", "Radiohead - Topic", ("Creep", ["Radiohead"])),
            ("Me at the zoo", "jawed", ("Me at the zoo", ["jawed"])),
            ("Adele - Hello (Lyrics)", "Lyrics Channel", ("Hello", ["Adele"])),
            ("Coldplay - Yellow - Live at Glastonbury", "x", ("Yellow - Live at Glastonbury", ["Coldplay"])),
            ("Song (feat. Someone) [Visualizer]", "Artist Official", ("Song (feat. Someone)", ["Artist"])),
            ("Artist – Track Official Video", None, ("Track", ["Artist"])),
            ("Simon & Garfunkel - The Sound of Silence", "c", ("The Sound of Silence", ["Simon", "Garfunkel"])),
            ("Song (Live)", "Band", ("Song (Live)", ["Band"])),
        ]:
            self.assertEqual(yt.clean_title(title, channel), want, title)

    def test_empty(self):
        self.assertEqual(yt.clean_title("", None), ("", []))
        self.assertEqual(yt.clean_title("(Official Video)", "X"), ("(Official Video)", ["X"]))


class Extract(unittest.TestCase):
    def track(self, resp, vid=VID):
        ctx, _ = serve({vid: resp})
        with ctx:
            return yt.track(vid)

    def test_atv(self):
        resp = next_resp(panel(VID, "Creep", ["Radiohead", ("Radiohead", "UCr"), " • ", ("Creep", "MPREb_TgQPwAzodvg"), " • ", "1992"], "3:59",
                               ATV, "https://yt3.googleusercontent.com/h=w544-h544-l90-rj"))
        resp["contents"]["singleColumnMusicWatchNextResultsRenderer"]["tabbedRenderer"]["watchNextTabbedResultsRenderer"]["tabs"][0][
            "tabRenderer"]["content"]["musicQueueRenderer"]["content"]["playlistPanelRenderer"]["contents"][0][
            "playlistPanelVideoRenderer"]["longBylineText"] = runs(("Radiohead", "UCr"), " • ", ("Creep", "MPREb_TgQPwAzodvg"), " • ", "1992")
        self.assertEqual(self.track(resp), {
            "name": "Creep", "artists": ["Radiohead"], "album": "Creep", "duration_ms": 239000,
            "artwork": "https://yt3.googleusercontent.com/h=w544-h544-l90-rj", "uri": None})

    def test_omv_has_no_album_or_square_art(self):
        resp = next_resp(panel("dQw4w9WgXcQ", "Never Gonna Give You Up", [("Rick Astley", "UCw"), " • ", "1.8B views"], "3:34", OMV))
        self.assertEqual(self.track(resp, "dQw4w9WgXcQ"), {
            "name": "Never Gonna Give You Up", "artists": ["Rick Astley"], "album": None, "duration_ms": 214000,
            "artwork": None, "uri": None})

    def test_ugc_is_cleaned_and_loose(self):
        resp = next_resp(panel("abcdefghijk", "Billie Eilish - bad guy (Official Video)", [("Some Channel VEVO", "UCx")], "3:15", UGC))
        row = self.track(resp, "abcdefghijk")
        self.assertEqual((row["name"], row["artists"], row["duration_ms"], row["loose"]), ("bad guy", ["Billie Eilish"], 195000, True))

    def test_panel_for_another_video_is_ignored(self):
        resp = next_resp(panel("zzzzzzzzzzz", "Other", [("A", "UC")], "1:00", ATV))
        with mock.patch.object(yt.links, "_fetch", side_effect=links.LinkError("nope", 404)):
            with self.assertRaises(links.LinkError) as cm:
                self.track(resp)
        self.assertEqual(cm.exception.status, 404)

    def test_invalid_id_falls_through_to_oembed_then_errors(self):
        for resp in ({}, {"contents": None}, {"contents": {"x": [1, "a", None]}}):
            with mock.patch.object(yt.links, "_fetch", side_effect=links.LinkError("gone", 404)):
                with self.assertRaises(links.LinkError) as cm:
                    self.track(resp)
            self.assertIn("couldn't read", str(cm.exception))

    def test_innertube_failure_uses_oembed(self):
        ctx, _ = serve({VID: links.LinkError("HTTP 500", 502)})
        oembed = {"title": "Creep", "author_name": "Radiohead - Topic", "thumbnail_url": "x"}
        with ctx, mock.patch.object(yt.links, "_fetch", return_value=oembed) as f:
            row = yt.track(VID)
        self.assertIn("oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D" + VID, f.call_args[0][0])
        self.assertEqual((row["name"], row["artists"], row["duration_ms"], row["album"]), ("Creep", ["Radiohead"], None, None))

    def test_album_page(self):
        items = [row("v1", "Creep", "", None, "3:59", OMV), row("v2", "Inside My Head", "", None, "3:12"),
                 row("v3", "Gone", "", None, "1:00:05"), {"musicResponsiveListItemRenderer": {"flexColumns": []}}]
        ctx, _ = serve({"MPREb_x": album_resp("Creep", "Radiohead", items)})
        with ctx:
            a = yt.album("MPREb_x")
        self.assertEqual((a["name"], a["artist"], len(a["songs"])), ("Creep", "Radiohead", 3))
        self.assertEqual(a["songs"][0]["artists"], ["Radiohead"])
        self.assertEqual(a["songs"][1]["album"], "Creep")
        self.assertEqual([s["duration_ms"] for s in a["songs"]], [239000, 192000, 3605000])
        self.assertTrue(a["artwork"].endswith("w600-h600-l90-rj"))

    def test_olak_album_uses_mpre_header(self):
        mpre = ("Creep", "MPREb_x")
        ctx, calls = serve({
            "VLOLAK5uy_abc": browse_resp([row("v1", "Creep", "Radiohead", mpre), row("v2", "Yes I Am", "Radiohead", mpre)]),
            "MPREb_x": album_resp("Creep", "Radiohead", [row("v1", "Creep"), row("v2", "Yes I Am")])})
        with ctx:
            a = yt.album("OLAK5uy_abc")
        self.assertEqual((a["name"], a["artist"], [s["name"] for s in a["songs"]]), ("Creep", "Radiohead", ["Creep", "Yes I Am"]))
        self.assertEqual([c[1].get("browseId") for c in calls], ["VLOLAK5uy_abc", "MPREb_x"])

    def test_olak_without_album_page(self):
        ctx, _ = serve({"VLOLAK5uy_abc": browse_resp([row("v1", "Creep", "Radiohead", ("Creep", "MPREb_x"))]),
                        "MPREb_x": links.LinkError("down", 502)})
        with ctx:
            a = yt.album("OLAK5uy_abc")
        self.assertEqual((a["name"], a["artist"]), ("Creep", "Radiohead"))

    def test_empty_album(self):
        ctx, _ = serve({"MPREb_x": {"responseContext": {}}, "VLOLAK5uy_x": {"responseContext": {}}})
        with ctx:
            for aid in ("MPREb_x", "OLAK5uy_x"):
                with self.assertRaises(links.LinkError) as cm:
                    yt.album(aid)
                self.assertEqual(cm.exception.status, 404)

    def test_playlist_follows_continuations(self):
        page1 = browse_resp([row("a1", "One", "A"), row("a2", "Two", "B", vtype=OMV), continuation("t1")], "My List", "Ada")
        more = {"onResponseReceivedActions": [{"appendContinuationItemsAction": {"continuationItems": [
            row("a3", "Three", "C"), row("pod", "Episode", "Show", vtype="MUSIC_VIDEO_TYPE_PODCAST_EPISODE"),
            row("a4", "Four (Lyrics)", "Chan", vtype=UGC)]}}]}
        ctx, calls = serve({"VLPLx": page1, "t1": more})
        with ctx:
            p = yt.playlist("PLx")
        self.assertEqual((p["name"], p["owner"], p["truncated"]), ("My List", "Ada", False))
        self.assertEqual([s["name"] for s in p["songs"]], ["One", "Two", "Three", "Four"])
        self.assertEqual(calls[1], ("browse", {"continuation": "t1"}))

    def test_playlist_cap(self):
        n = yt.PLAYLIST_LIMIT
        page = lambda start, tok: browse_resp([row(f"v{i}", f"S{i}", "A") for i in range(start, start + 300)] + [continuation(tok)], "Big")
        more = lambda start, tok: {"onResponseReceivedActions": [{"appendContinuationItemsAction": {"continuationItems": [
            row(f"v{i}", f"S{i}", "A") for i in range(start, start + 300)] + [continuation(tok)]}}]}
        ctx, calls = serve({"VLPLbig": page(0, "t1"), "t1": more(300, "t2"), "t2": more(600, "t3")})
        with ctx:
            p = yt.playlist("PLbig")
        self.assertEqual((len(p["songs"]), p["truncated"], len(calls)), (n, True, 2))

    def test_empty_playlist(self):
        ctx, _ = serve({"VLPLx": {"microformat": {"microformatDataRenderer": {"noindex": True}}}})
        with ctx, self.assertRaises(links.LinkError) as cm:
            yt.playlist("PLx")
        self.assertEqual(cm.exception.status, 404)

    def test_playlist_title_falls_back_to_microformat(self):
        page = browse_resp([row("a1", "One", "A")])
        page["microformat"] = {"microformatDataRenderer": {"title": "From meta"}}
        ctx, _ = serve({"VLPLx": page})
        with ctx:
            self.assertEqual(yt.playlist("PLx")["name"], "From meta")

    def test_garbage_shapes_do_not_crash(self):
        for junk in ([], "x", None, {"contents": [None, 1, {"musicPlaylistShelfRenderer": {"contents": [None, "a", {}, {"musicResponsiveListItemRenderer": None}]}}]}):
            ctx, _ = serve({"VLPLx": junk})
            with ctx, self.assertRaises(links.LinkError):
                yt.playlist("PLx")


class FakeApi:
    def __init__(self, tracks=None, albums=None, fail=False):
        self.tracks, self.albums, self.fail, self.queries = tracks or [], albums or [], fail, []

    def get(self, path, **q):
        self.queries.append((path, q))
        if self.fail:
            raise SpotifyError("boom", 500)
        if path == "/search":
            return {"tracks": {"items": self.tracks}, "albums": {"items": self.albums}}
        raise AssertionError(path)


def sp_track(name, artist, ms, uri="spotify:track:" + "a" * 22):
    return {"type": "track", "uri": uri, "id": uri.split(":")[2], "name": name, "duration_ms": ms,
            "artists": [{"uri": "u", "name": artist}], "album": {"uri": "a", "name": "A", "images": [{"url": "http://art"}]}}


class Resolve(unittest.TestCase):
    def setUp(self):
        links._cache.clear()

    def test_track_matched(self):
        resp = next_resp(panel(VID, "Creep", [("Radiohead", "UCr"), " • ", ("Creep", "MPREb_x")], "3:59", ATV,
                               "https://yt3.googleusercontent.com/h=w544-h544"))
        ctx, _ = serve({VID: resp})
        api = FakeApi(tracks=[sp_track("Creep", "Radiohead", 238000)])
        with ctx:
            r = links.resolve(api, f"https://music.youtube.com/watch?v={VID}")
        self.assertEqual((r["source"], r["kind"], r["name"], r["subtitle"], r["matched"], r["total"]),
                         ("youtube", "track", "Creep", "Radiohead", 1, 1))
        self.assertEqual(r["spotify_uri"], "spotify:track:" + "a" * 22)
        self.assertEqual(set(r["tracks"][0]), {"name", "artists", "album", "duration_ms", "artwork", "uri"})

    def test_ugc_duration_tolerance_is_wider(self):
        title = "Radiohead - Creep (Official Video)"
        cand = sp_track("Creep", "Radiohead", 239000 + 20000)
        ugc = next_resp(panel(VID, title, [("Chan", "UC")], "3:59", UGC))
        omv = next_resp(panel(VID, "Creep", [("Radiohead", "UC")], "3:59", OMV))
        for resp, matched in ((ugc, 1), (omv, 0)):
            links._cache.clear()
            ctx, _ = serve({VID: resp})
            with ctx:
                self.assertEqual(links.resolve(FakeApi(tracks=[cand]), f"https://youtu.be/{VID}")["matched"], matched)

    def test_unmatched_track_keeps_thumbnail(self):
        ctx, _ = serve({VID: next_resp(panel(VID, "Obscure", [("Nobody", "UC")], "1:00", OMV))})
        with ctx:
            r = links.resolve(FakeApi(), f"https://youtu.be/{VID}")
        self.assertEqual((r["spotify_uri"], r["matched"], r["artwork"]), (None, 0, f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg"))

    def test_spotify_errors_leave_rows_unmatched(self):
        ctx, _ = serve({VID: next_resp(panel(VID, "Creep", [("Radiohead", "UC")], "3:59", OMV))})
        with ctx:
            self.assertEqual(links.resolve(FakeApi(fail=True), f"https://youtu.be/{VID}")["matched"], 0)

    def test_playlist(self):
        page = browse_resp([row("a1", "One", "A", dur="3:00"), row("a2", "Two", "B", dur="3:00"), continuation("t")], "List", "Ada")
        more = {"onResponseReceivedActions": [{"appendContinuationItemsAction": {"continuationItems": [row("a3", "Three", "C")]}}]}
        ctx, _ = serve({"VLPLx": page, "t": more})
        api = FakeApi(tracks=[sp_track("One", "A", 180000)])
        with ctx:
            r = links.resolve(api, "https://www.youtube.com/playlist?list=PLx")
        self.assertEqual((r["source"], r["kind"], r["name"], r["subtitle"], r["total"], r["truncated"], r["spotify_uri"]),
                         ("youtube", "playlist", "List", "Ada", 3, False, None))
        self.assertEqual(r["matched"], 1)

    def test_album_matches_whole_spotify_album(self):
        items = [row("v1", "Creep", "", None, "3:59"), row("v2", "Yes I Am", "", None, "4:26")]
        ctx, _ = serve({"MPREb_x": album_resp("Creep", "Radiohead", items)})
        sp_album = {"uri": "spotify:album:" + "b" * 22, "id": "b" * 22, "name": "Creep", "total_tracks": 2,
                    "artists": [{"name": "Radiohead"}], "images": [{"url": "http://sp"}],
                    "tracks": {"items": [{"uri": "spotify:track:" + "c" * 22, "name": "Creep", "duration_ms": 1,
                                          "artists": [{"name": "Radiohead"}]}], "next": None}}

        class Api(FakeApi):
            def get(self, path, **q):
                return sp_album if path.startswith("/albums/") else super().get(path, **q)
        with ctx:
            r = links.resolve(Api(albums=[{"uri": sp_album["uri"], "name": "Creep", "total_tracks": 2}]),
                              "https://music.youtube.com/browse/MPREb_x")
        self.assertEqual((r["source"], r["kind"], r["name"], r["spotify_uri"]), ("youtube", "album", "Creep", sp_album["uri"]))

    def test_album_without_spotify_match_matches_tracks(self):
        items = [row("v1", "Creep", "", None, "3:59"), row("v2", "Yes I Am", "", None, "4:26")]
        ctx, _ = serve({"MPREb_x": album_resp("Creep", "Radiohead", items)})
        api = FakeApi(tracks=[sp_track("Creep", "Radiohead", 239000)])
        with ctx:
            r = links.resolve(api, "https://music.youtube.com/browse/MPREb_x")
        self.assertEqual((r["kind"], r["spotify_uri"], r["total"]), ("album", None, 2))
        self.assertGreaterEqual(r["matched"], 1)

    def test_errors_propagate(self):
        for url in ("https://www.youtube.com/playlist?list=RDabc", "https://www.youtube.com/@x"):
            with self.assertRaises(links.LinkError):
                links.resolve(FakeApi(), url)

    def test_album_ref(self):
        self.assertEqual(links.album_ref("https://music.youtube.com/browse/MPREb_x"), ("youtube", None))
        self.assertEqual(links.album_ref("https://www.youtube.com/playlist?list=OLAK5uy_x"), ("youtube", None))
        self.assertIsNone(links.album_ref("https://www.youtube.com/playlist?list=PLx"))
        self.assertIsNone(links.album_ref(f"https://youtu.be/{VID}"))
        self.assertIsNone(links.album_ref("https://www.youtube.com/@x"))


class SlackDetection(unittest.TestCase):
    def test_link_rx(self):
        for text in ("https://music.youtube.com/watch?v=9RfVp-GhKfs", "see https://www.youtube.com/playlist?list=PLx ok",
                     "http://m.youtube.com/watch?v=x", "https://youtu.be/9RfVp-GhKfs?si=a", "https://www.youtube-nocookie.com/embed/x",
                     "https://youtube.com/shorts/x"):
            self.assertTrue(sb.LINK_RX.search(text), text)
        self.assertEqual(sb.LINK_RX.search("go https://youtu.be/abc now").group(0), "https://youtu.be/abc")
        for text in ("https://example.com/watch?v=x", "https://notyoutube.com/x", "youtube is great"):
            self.assertFalse(sb.LINK_RX.search(text), text)

    def test_cards_name_the_source(self):
        track = {"source": "youtube", "kind": "track", "name": "Creep", "subtitle": "Radiohead", "artwork": None, "total": 1,
                 "url": "https://music.youtube.com/watch?v=x", "spotify_uri": "spotify:track:" + "a" * 22, "tracks": [], "matched": 1}
        texts = lambda blocks: " ".join(str(e.get("text", "")) for b in blocks for e in b.get("elements", []) if b["type"] == "context")
        self.assertIn("Matched from YouTube Music", texts(sb.link_blocks(track)))
        self.assertIn("Matched from YouTube", texts(sb.link_blocks(dict(track, url="https://youtu.be/x"))))
        self.assertNotIn("Music", texts(sb.link_blocks(dict(track, url="https://youtu.be/x"))))
        self.assertIn("Matched from Apple Music", texts(sb.link_blocks(dict(track, source="apple"))))
        self.assertIn("YouTube Music, not found on Spotify", texts(sb.reply_card(dict(track, spotify_uri=None), 0, "ada")))


if __name__ == "__main__":
    unittest.main()
