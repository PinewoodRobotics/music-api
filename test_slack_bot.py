import hashlib
import hmac
import json
import time
import unittest
import urllib.parse
from unittest import mock

import links
import slack_bot as sb
from accounts import Credits

SECRET = "shh"
TRACK = {"uri": "spotify:track:5W3cjX2J3tjhG8zb6u0qHn", "type": "track", "name": "One <More> Time",
         "artists": [{"name": "Daft Punk"}], "album": {"name": "Discovery"}, "duration_ms": 320357,
         "artwork": "https://i.scdn.co/x"}
ADA = {"id": "U1", "name": "Ada", "avatar": "http://a/av.png"}
ADA_Q = {"by": ADA, "how": "queued"}
TRACK2 = dict(TRACK, uri="spotify:track:0DiWol3AO6WpXZgp0goxAV", name="Other")


def signed(body, ts=None, secret=SECRET):
    ts = str(int(time.time()) if ts is None else ts)
    mac = hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=" + mac}


class FakePlayer:
    def __init__(self):
        self.calls, self.state = [], "playing"
        self.subs = []

    def subscribe(self):
        return None

    def status(self, fresh=False):
        return {"state": self.state, "track": TRACK}

    def queue(self, limit=None):
        return {"upcoming": [{"item": TRACK2, "source": "queue"}], "previous": []}

    def next(self): self.calls.append("next")
    def pause(self): self.calls.append("pause")
    def play(self, b): self.calls.append(("play", b))
    def enqueue(self, b): self.calls.append(("enqueue", b))


class FakeSlack:
    bot_token, team_id = "xoxb-1", None


class FakeApi:
    def get(self, path, **q):
        if path == "/search":
            raw = {"tracks": {"items": [{"type": "track", "uri": TRACK["uri"], "name": "T", "artists": [], "album": {}}]},
                   "albums": {"items": [{"type": "album", "uri": "spotify:album:2noRn2Aes5aoNVsU6iWThc", "name": "A"}]},
                   "playlists": {"items": []}}
            return raw
        return {"type": "track", "uri": TRACK["uri"], "name": "T", "artists": [], "album": {}}


def make():
    bot = sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), Credits(), SECRET)
    bot.sent = []
    bot.http = lambda url, payload, token=None: (bot.sent.append((url, payload)) or (200, {"ok": True, "ts": "1.1"}, {}))
    bot.fetch_user = lambda uid: {"display_name": "Ada", "image_72": "http://a/av.png"}
    bot.spawn = lambda fn, *a: fn(*a)
    return bot


class Signature(unittest.TestCase):
    def test_valid(self):
        h = signed(b"x=1")
        self.assertTrue(sb.verify_signature(SECRET, h["X-Slack-Request-Timestamp"], h["X-Slack-Signature"], b"x=1"))

    def test_rejects(self):
        h = signed(b"x=1")
        ts, sig = h["X-Slack-Request-Timestamp"], h["X-Slack-Signature"]
        self.assertFalse(sb.verify_signature(SECRET, ts, sig, b"x=2"))
        self.assertFalse(sb.verify_signature("other", ts, sig, b"x=1"))
        self.assertFalse(sb.verify_signature(SECRET, ts, None, b"x=1"))
        self.assertFalse(sb.verify_signature(SECRET, "abc", sig, b"x=1"))
        old = signed(b"x=1", ts=time.time() - 301)
        self.assertFalse(sb.verify_signature(SECRET, old["X-Slack-Request-Timestamp"], old["X-Slack-Signature"], b"x=1"))
        self.assertFalse(sb.verify_signature(SECRET, ts, "v0=é", b"x=1"))

    def test_handle_requires_signature(self):
        bot = make()
        self.assertEqual(bot.handle("/slack/commands", {}, b"text=help")[0], 401)
        body = urllib.parse.urlencode({"team_id": sb.DEFAULT_TEAM, "text": "help"}).encode()
        status, res = bot.handle("/slack/commands", signed(body), body)
        self.assertEqual(status, 200)
        self.assertIn("Robotics Music", res["text"])

    def test_disabled_without_secret(self):
        bot = sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), Credits(), None)
        self.assertEqual(bot.handle("/slack/events", {}, b"")[0], 503)


class Commands(unittest.TestCase):
    def test_parse(self):
        p = sb.parse_command
        self.assertEqual(p(""), ("help", ""))
        self.assertEqual(p("NOW"), ("now", ""))
        self.assertEqual(p("skip"), ("skip", ""))
        self.assertEqual(p("next"), ("skip", ""))
        self.assertEqual(p("play"), ("play", ""))
        self.assertEqual(p("queue"), ("queue", ""))
        self.assertEqual(p("daft punk"), ("search", "daft punk"))
        self.assertEqual(p("skip the intro"), ("search", "skip the intro"))
        self.assertEqual(p("search now"), ("search", "now"))

    def test_wrong_team(self):
        bot = make()
        self.assertEqual(bot.on_command({"team_id": "T0", "text": "skip"})[0], 403)

    def test_skip_responds_without_channel_note(self):
        bot = make()
        bot.on_command({"team_id": bot.team, "text": "skip", "user_id": "U1", "response_url": "http://r/1"})
        self.assertEqual(bot.player.calls, ["next"])
        self.assertFalse([u for u, _ in bot.sent if u.endswith("chat.postMessage")])
        self.assertTrue(any(u == "http://r/1" for u, _ in bot.sent))

    def test_search_blocks(self):
        bot = make()
        bot.on_command({"team_id": bot.team, "text": "daft", "user_id": "U1", "response_url": "http://r/1"})
        payload = [p for u, p in bot.sent if u == "http://r/1"][0]
        ids = [e["action_id"] for b in payload["blocks"] if b["type"] == "actions" for e in b["elements"]]
        self.assertEqual(ids, ["queue_add", "play_uri"])

    def test_link_goes_straight_to_card(self):
        bot = make()
        bot.run_command("search", "https://open.spotify.com/track/5W3cjX2J3tjhG8zb6u0qHn?si=x", "U1", "ada", "http://r/1")
        payload = bot.sent[-1][1]
        self.assertEqual(payload["blocks"][1]["elements"][0]["value"], TRACK["uri"])


class Blocks(unittest.TestCase):
    def test_now_playing(self):
        blocks = sb.now_playing_blocks(TRACK, True, ADA_Q, [{"item": TRACK2}], "https://r/")
        self.assertEqual(blocks[0]["accessory"]["image_url"], TRACK["artwork"])
        self.assertIn("<https://open.spotify.com/track/5W3cjX2J3tjhG8zb6u0qHn|One &lt;More&gt; Time>", blocks[0]["text"]["text"])
        self.assertIn("Daft Punk · Discovery", blocks[0]["text"]["text"])
        flat = json.dumps(blocks)
        self.assertTrue(blocks[0]["text"]["text"].endswith("\nAda"))
        self.assertEqual(blocks[1]["elements"][0]["text"], "*Up next*")
        self.assertEqual(blocks[2]["elements"][0]["type"], "image")
        self.assertIn("Other", blocks[2]["elements"][-1]["text"])
        acts = blocks[-1]["elements"]
        self.assertEqual([a["action_id"] for a in acts], ["playpause", "skip", "open_remote"])
        self.assertEqual(acts[0]["text"]["text"], "Pause")
        self.assertEqual(acts[2]["text"]["text"], "More Controls")
        self.assertEqual(acts[2]["url"], "https://r/")
        self.assertEqual(sb.now_playing_blocks(TRACK, False)[-1]["elements"][0]["text"]["text"], "Play")

    def test_credit_is_name_under_song(self):
        started = {"by": ADA, "how": "started"}
        self.assertTrue(sb.now_playing_blocks(TRACK, True, started)[0]["text"]["text"].endswith("\nAda"))
        self.assertIn(" · Ada", json.dumps(sb.played_blocks(TRACK, ADA_Q), ensure_ascii=False))
        flat = json.dumps(sb.now_playing_blocks(TRACK, True, ADA_Q) + sb.played_blocks(TRACK, started))
        self.assertNotIn("<@", flat)
        self.assertNotIn(" by ", flat)

    def test_played_line_names_the_skipper(self):
        flat = json.dumps(sb.played_blocks(TRACK, {"by": ADA, "how": "started"}, {"name": "Bob"}), ensure_ascii=False)
        self.assertIn(" · Ada · skipped by Bob", flat)
        self.assertNotIn("skipped", json.dumps(sb.played_blocks(TRACK, {"by": ADA, "how": "started"})))

    def test_played_has_no_buttons(self):
        self.assertNotIn("button", json.dumps(sb.played_blocks(TRACK, ADA_Q)))

    def test_duration(self):
        self.assertEqual(sb.duration(320357), "5:20")


class Interactions(unittest.TestCase):
    def payload(self, action, **kw):
        return {"type": "block_actions", "team": {"id": sb.DEFAULT_TEAM}, "user": {"id": "U1", "name": "ada"},
                "response_url": "http://r/2", "container": {"is_ephemeral": True},
                "message": {"blocks": [{"type": "section"}, {"type": "actions", "block_id": "q:" + TRACK["uri"]}]},
                "actions": [dict(action, block_id="q:" + TRACK["uri"])], **kw}

    def test_queue_add_credits_and_updates(self):
        bot = make()
        bot.on_interaction(self.payload({"action_id": "queue_add", "value": TRACK["uri"]}))
        self.assertEqual(bot.player.calls, [("enqueue", {"uri": TRACK["uri"]})])
        self.assertEqual(bot.credits.by_uri[TRACK["uri"]][0][0], ADA)
        sent = bot.sent[-1][1]
        self.assertTrue(sent["replace_original"])
        self.assertIn("Queued by Ada", json.dumps(sent["blocks"]))
        self.assertNotIn("button", json.dumps(sent["blocks"][1]))

    def test_play_uri_credits_start_without_channel_note(self):
        bot = make()
        bot.on_interaction(self.payload({"action_id": "play_uri", "value": "spotify:album:2noRn2Aes5aoNVsU6iWThc"}))
        self.assertEqual(bot.credits.started["uris"], ["spotify:album:2noRn2Aes5aoNVsU6iWThc"])
        self.assertEqual(bot.credits.started["user"], ADA)
        self.assertNotIn("<@", json.dumps(bot.sent))
        self.assertFalse([u for u, _ in bot.sent if u.endswith(("chat.postMessage", "chat.update"))])
        self.assertTrue(any(u == "http://r/2" for u, _ in bot.sent))

    def test_non_ephemeral_never_replaces(self):
        bot = make()
        p = self.payload({"action_id": "queue_add", "value": TRACK["uri"]}, container={"type": "message"})
        bot.on_interaction(p)
        self.assertFalse(bot.sent[-1][1]["replace_original"])

    def test_play_pause_toggle(self):
        bot = make()
        bot.on_interaction(self.payload({"action_id": "playpause"}, container={"type": "message"}))
        self.assertEqual(bot.player.calls, ["pause"])
        bot.player.state = "paused"
        bot.on_interaction(self.payload({"action_id": "playpause"}, container={"type": "message"}))
        self.assertEqual(bot.player.calls[-1], ("play", {}))

    def test_wrong_team_and_ignored(self):
        bot = make()
        self.assertEqual(bot.on_interaction(dict(self.payload({}), team={"id": "T0"}))[0], 403)
        bot.on_interaction(self.payload({"action_id": "open_remote"}))
        self.assertEqual(bot.player.calls, [])


APPLE_TRACK = {"source": "apple", "kind": "track", "name": "Song", "subtitle": "Artist", "artwork": "http://x/a.jpg",
               "url": "https://music.apple.com/us/album/x/1?i=2", "spotify_uri": TRACK["uri"], "tracks": [],
               "total": 1, "matched": 1, "truncated": False}
APPLE_PL = {"source": "apple", "kind": "playlist", "name": "Mix", "subtitle": "by Ada", "artwork": None,
            "url": "https://music.apple.com/us/playlist/mix/pl.1", "spotify_uri": None, "tracks": [],
            "total": 92, "matched": 87, "truncated": False}


def buttons(blocks):
    return [(e["action_id"], e.get("value")) for b in blocks if b["type"] == "actions" for e in b["elements"]]


class Links(unittest.TestCase):
    def test_cards(self):
        b = sb.link_blocks(APPLE_TRACK)
        self.assertIn("Matched from Apple Music", json.dumps(b))
        self.assertEqual(buttons(b), [("queue_add", TRACK["uri"]), ("play_uri", TRACK["uri"])])
        b = sb.link_blocks(APPLE_PL)
        self.assertEqual(b[1]["elements"][0]["text"], "92 songs · 87 on Spotify")
        self.assertEqual(buttons(b), [("import_playlist", APPLE_PL["url"])])
        album = dict(APPLE_PL, kind="album", spotify_uri="spotify:album:2noRn2Aes5aoNVsU6iWThc")
        self.assertEqual([a for a, _ in buttons(sb.link_blocks(album))], ["play_uri", "add_album"])
        self.assertEqual([a for a, _ in buttons(sb.link_blocks(dict(album, spotify_uri=None)))], ["import_playlist"])
        sp = dict(APPLE_PL, source="spotify", spotify_uri="spotify:playlist:2noRn2Aes5aoNVsU6iWThc")
        self.assertEqual([a for a, _ in buttons(sb.link_blocks(sp))], ["import_playlist", "play_uri"])
        self.assertEqual(buttons(sb.link_blocks(dict(APPLE_TRACK, spotify_uri=None))), [])

    def test_command_link_uses_resolver(self):
        bot = make()
        seen = []
        bot.resolve = lambda u: seen.append(u) or APPLE_TRACK
        bot.run_command("search", "https://music.apple.com/us/album/x/1?i=2", "U1", "ada", "http://r/1")
        self.assertEqual(seen, ["https://music.apple.com/us/album/x/1?i=2"])
        last = bot.sent[-1][1]
        self.assertTrue(last["replace_original"])
        self.assertEqual(buttons(last["blocks"])[0][0], "queue_add")

    def test_command_link_error(self):
        bot = make()

        def boom(u):
            raise ValueError("unsupported link")
        bot.resolve = boom
        bot.run_command("search", "https://music.apple.com/us/artist/x/1", "U1", "ada", "http://r/1")
        self.assertIn("unsupported link", bot.sent[-1][1]["text"])

    def test_unfurl_apple(self):
        bot = make()
        bot.resolve = lambda u: APPLE_PL
        bot.on_event({"team_id": bot.team, "event_id": "E9", "event": {
            "type": "link_shared", "unfurl_id": "U.1", "source": "composer",
            "links": [{"url": APPLE_PL["url"]}]}}, {})
        call = bot.sent[-1]
        self.assertTrue(call[0].endswith("chat.unfurl"))
        self.assertEqual((call[1]["unfurl_id"], call[1]["source"]), ("U.1", "composer"))
        self.assertIn(APPLE_PL["url"], call[1]["unfurls"])

    def interaction(self, **kw):
        return {"type": "block_actions", "team": {"id": sb.DEFAULT_TEAM}, "user": {"id": "U1", "name": "ada"},
                "response_url": "http://r/3", "container": {"is_ephemeral": True},
                "message": {"blocks": sb.link_blocks(APPLE_PL)},
                "actions": [{"action_id": "import_playlist", "value": APPLE_PL["url"], "block_id": "link"}], **kw}

    def test_import(self):
        bot = make()
        calls = []

        def importer(url, user):
            calls.append((url, user))
            return {"playlist": {"id": "PL1", "name": "Mix"}, "imported": 87, "total": 92,
                    "unmatched": [{"name": "Gone", "artists": ["Z"]}]}
        bot.importer = importer
        bot.on_interaction(self.interaction())
        self.assertEqual(calls, [(APPLE_PL["url"], {"id": "U1", "name": "Ada", "avatar": "http://a/av.png", "admin": False})])
        final = [p for u, p in bot.sent if u == "http://r/3"][-1]
        flat = json.dumps(final)
        self.assertFalse([u for u, _ in bot.sent if u.endswith("chat.postMessage")])
        self.assertIn("Imported 87 of 92 songs", flat)
        self.assertIn("https://music.pinewoodrobotics.org/playlist/PL1", flat)
        self.assertIn("Gone - Z", flat)
        self.assertTrue(final["replace_original"])
        self.assertNotIn("button", json.dumps(final["blocks"]))

    def test_import_failure_and_missing(self):
        bot = make()
        bot.on_interaction(self.interaction())
        self.assertIn("isn't available", bot.sent[-1][1]["text"])

        def fail(url, user):
            raise RuntimeError("Apple said no")
        bot.importer = fail
        bot.on_interaction(self.interaction())
        self.assertIn("Apple said no", bot.sent[-1][1]["text"])


class FakeActivity:
    def __init__(self):
        self.entries = []

    def record(self, user, action, detail=None, origin="web"):
        e = {"id": len(self.entries), "by": user, "action": action, "detail": detail, "origin": origin}
        self.entries.append(e)
        return e

    def enrich(self, entry, fn):
        entry["detail"] = {**entry["detail"], **fn()}


MUSIC = sb.DEFAULT_CHANNEL
ALBUM_URI = "spotify:album:2noRn2Aes5aoNVsU6iWThc"


def song(i, uri=True):
    return {"name": f"S{i}", "artists": ["A"], "album": "Al", "duration_ms": 1000, "artwork": None,
            "uri": f"spotify:track:{i:022d}" if uri else None}


SP_ALBUM = {"source": "spotify", "kind": "album", "name": "Discovery", "subtitle": "Daft Punk", "artwork": "http://x/a.jpg",
            "url": "https://open.spotify.com/album/2noRn2Aes5aoNVsU6iWThc", "spotify_uri": ALBUM_URI,
            "tracks": [song(i) for i in range(60)], "total": 60, "matched": 60, "truncated": False}
AP_ALBUM_NOMATCH = dict(SP_ALBUM, source="apple", url="https://music.apple.com/us/album/x/9", spotify_uri=None,
                        tracks=[song(1, False)], matched=0, total=1)
AP_PL = dict(APPLE_PL, tracks=[song(i, i % 2 == 0) for i in range(300)], total=300, matched=150)
SP_PL = dict(APPLE_PL, source="spotify", url="https://open.spotify.com/playlist/2noRn2Aes5aoNVsU6iWThc",
             spotify_uri="spotify:playlist:2noRn2Aes5aoNVsU6iWThc", tracks=[song(1)], total=1, matched=1)
SP_TRACK = dict(APPLE_TRACK, source="spotify", url="https://open.spotify.com/track/5W3cjX2J3tjhG8zb6u0qHn")
RESOLVED = {r["url"]: r for r in (SP_ALBUM, AP_ALBUM_NOMATCH, AP_PL, SP_PL, SP_TRACK, APPLE_TRACK)}


class ThreadCards(unittest.TestCase):
    def setUp(self):
        self.bot = make()
        self.bot.resolve = lambda u: RESOLVED[u]
        self.bot.activity = FakeActivity()
        self.bot.own_user_id = lambda: "UBOT"
        self.albums = []

        def add_album(url, user):
            self.albums.append((url, user))
            return {"id": "2noRn2Aes5aoNVsU6iWThc", "name": "Discovery", "already": len(self.albums) > 1}
        self.bot.add_album = add_album

    def shared(self, urls, channel=MUSIC, eid="E1", user="U9", ts="5.5", **kw):
        return self.bot.on_event({"team_id": self.bot.team, "event_id": eid, "event": {
            "type": "link_shared", "channel": channel, "message_ts": ts, "user": user,
            "links": [{"url": u} for u in urls], **kw}}, {})

    def click(self, blocks, block_id, action_id, value, uid="U1", name="ada", ts="7.7"):
        self.bot.sent.clear()
        self.bot.on_interaction({"type": "block_actions", "team": {"id": self.bot.team}, "user": {"id": uid, "name": name},
                                 "response_url": "http://r/9", "channel": {"id": MUSIC}, "container": {"type": "message"},
                                 "message": {"ts": ts, "text": "t", "blocks": blocks},
                                 "actions": [{"action_id": action_id, "value": value, "block_id": block_id}]})
        return self.bot.sent

    def post(self, urls):
        self.shared(urls)
        call = self.bot.sent[-1]
        self.assertTrue(call[0].endswith("chat.postMessage"))
        return call[1]

    def test_music_channel_posts_one_broadcast_reply(self):
        post = self.post([SP_ALBUM["url"], SP_TRACK["url"], AP_PL["url"], SP_PL["url"]])
        self.assertEqual((post["thread_ts"], post["reply_broadcast"], post["channel"]), ("5.5", True, MUSIC))
        ids = [b.get("block_id") for b in post["blocks"] if b.get("block_id")]
        self.assertEqual(ids, ["info0", "rl0", "info1", "rl1", "info2", "rl2"])
        self.assertEqual(len([u for u, _ in self.bot.sent if u.endswith("chat.postMessage")]), 1)
        info = post["blocks"][1]["elements"][0]["text"]
        self.assertEqual(info, "Album · 60 songs · 60 on Spotify · shared by Ada")
        self.assertNotIn("<@", json.dumps(post["blocks"]))
        self.assertEqual([a for a, _ in buttons(post["blocks"][:3])], ["rl_play", "rl_queue", "rl_library"])

    def test_dedupe_and_other_channel_and_own_posts(self):
        self.shared([SP_TRACK["url"]])
        n = len(self.bot.sent)
        self.shared([SP_TRACK["url"]], eid="E2")
        self.assertEqual(len(self.bot.sent), n)
        self.bot.sent.clear()
        self.shared([SP_TRACK["url"]], eid="E3", ts="6.6", user="UBOT")
        self.assertEqual(self.bot.sent, [])
        self.shared([SP_TRACK["url"]], channel="C999", eid="E4", ts="8.8", unfurl_id="U.1", source="composer")
        self.assertTrue(self.bot.sent[-1][0].endswith("chat.unfurl"))

    def test_unresolvable_links_post_nothing(self):
        self.bot.resolve = lambda u: (_ for _ in ()).throw(ValueError("nope"))
        self.shared(["https://open.spotify.com/artist/x"])
        self.assertEqual(self.bot.sent, [])

    def test_card_variants(self):
        apple = sb.reply_card(APPLE_TRACK, 0, "Ada")
        self.assertIn("Song · Apple Music → matched on Spotify", apple[1]["elements"][0]["text"])
        self.assertEqual([a for a, _ in buttons(apple)], ["rl_play", "rl_queue"])
        self.assertIn("Playlist", sb.reply_card(AP_PL, 0, None)[1]["elements"][0]["text"])
        self.assertEqual([a for a, _ in buttons(sb.reply_card(AP_PL, 0, None))], ["rl_play", "rl_queue", "rl_import"])
        self.assertEqual([a for a, _ in buttons(sb.reply_card(SP_PL, 0, None))], ["rl_play", "rl_queue", "rl_import"])
        nomatch = sb.reply_card(AP_ALBUM_NOMATCH, 0, "Ada")
        self.assertIn("can only be imported as a playlist", json.dumps(nomatch))
        self.assertEqual([a for a, _ in buttons(nomatch)], ["rl_import"])

    def test_play_queue_accumulate_on_same_message(self):
        blocks = sb.reply_card(SP_ALBUM, 0, "Ada")
        sent = self.click(blocks, "rl0", "rl_queue", SP_ALBUM["url"])
        upd = sent[-1]
        self.assertTrue(upd[0].endswith("chat.update"))
        self.assertEqual((upd[1]["ts"], upd[1]["channel"]), ("7.7", MUSIC))
        self.assertEqual(len(self.bot.player.calls[-1][1]["uris"]), sb.QUEUE_CAP)
        out = [b for b in upd[1]["blocks"] if b.get("block_id") == "out0"][0]
        self.assertEqual(out["elements"][0]["text"], "✓ Added 50 songs to queue by Ada")
        self.assertEqual([b.get("block_id") for b in upd[1]["blocks"]][-2:], ["rl0", "out0"])
        self.assertEqual(len(buttons(upd[1]["blocks"])), 3)
        self.assertEqual(self.bot.activity.entries[-1]["origin"], "slack")
        self.assertEqual(self.bot.activity.entries[-1]["action"], "queue_add")
        self.bot.user = lambda uid, fb=None: {"id": uid, "name": "Howard", "avatar": None}
        upd = self.click(blocks, "rl0", "rl_library", SP_ALBUM["url"], uid="U2")[-1]
        out = [b for b in upd[1]["blocks"] if b.get("block_id") == "out0"][0]["elements"][0]["text"]
        self.assertIn("✓ Added 50 songs to queue by Ada · ✓ Added to Library by Howard", out)
        self.assertEqual([a for a, _ in buttons(upd[1]["blocks"])], ["rl_play", "rl_queue"])
        self.assertIn("✓ In Library", upd[1]["blocks"][1]["elements"][0]["text"])
        self.assertEqual(self.albums[0][0], SP_ALBUM["url"])
        self.assertEqual(self.albums[0][1]["admin"], False)
        self.assertEqual(self.bot.activity.entries[-1]["action"], "album_add")

    def test_already_in_library_not_logged(self):
        blocks = sb.reply_card(SP_ALBUM, 0, None)
        self.click(blocks, "rl0", "rl_library", SP_ALBUM["url"])
        n = len(self.bot.activity.entries)
        upd = self.click(blocks, "rl0", "rl_library", SP_ALBUM["url"])[-1]
        self.assertIn("Already in Library", json.dumps(upd[1]["blocks"]))
        self.assertEqual(len(self.bot.activity.entries), n)

    def test_play_variants(self):
        self.click(sb.reply_card(SP_ALBUM, 0, None), "rl0", "rl_play", SP_ALBUM["url"])
        self.assertEqual(self.bot.player.calls[-1], ("play", {"uri": ALBUM_URI}))
        self.click(sb.reply_card(AP_PL, 0, None), "rl0", "rl_play", AP_PL["url"])
        uris = self.bot.player.calls[-1][1]["uris"]
        self.assertEqual(len(uris), 100)
        self.assertEqual(self.bot.credits.started["uris"], uris)
        self.click(sb.reply_card(SP_TRACK, 0, None), "rl0", "rl_queue", SP_TRACK["url"])
        self.assertEqual(self.bot.player.calls[-1], ("enqueue", {"uris": [TRACK["uri"]]}))

    def test_playlist_import_and_unmatched_album(self):
        calls = []
        self.bot.importer = lambda url, user: calls.append(url) or {
            "playlist": {"id": "PL1", "name": "Mix"}, "imported": 150, "total": 300}
        upd = self.click(sb.reply_card(AP_PL, 0, None), "rl0", "rl_import", AP_PL["url"])[-1]
        self.assertIn("✓ Imported 150 of 300 songs to Library by Ada", json.dumps(upd[1]["blocks"], ensure_ascii=False))
        self.assertNotIn("rl_import", json.dumps(upd[1]["blocks"]))
        self.assertEqual(upd[1]["blocks"][-1]["block_id"], "out0")
        self.click(sb.reply_card(AP_ALBUM_NOMATCH, 0, None), "rl0", "rl_import", AP_ALBUM_NOMATCH["url"])
        self.assertEqual(calls[-1], AP_ALBUM_NOMATCH["url"])

    def test_errors_are_ephemeral_to_clicker(self):
        def boom(url, user):
            raise ValueError("no Spotify match")
        self.bot.add_album = boom
        sent = self.click(sb.reply_card(SP_ALBUM, 0, None), "rl0", "rl_library", SP_ALBUM["url"])
        self.assertEqual([u for u, _ in sent], ["http://r/9"])
        self.assertIn("no Spotify match", sent[0][1]["text"])
        self.assertEqual(sent[0][1]["response_type"], "ephemeral")

    def test_add_album_button_in_other_flows(self):
        sent = self.click(sb.link_blocks(SP_ALBUM), "link", "add_album", SP_ALBUM["url"])
        self.assertEqual(self.albums[0][0], SP_ALBUM["url"])
        self.assertIn("to the Library", sent[-1][1]["text"])
        self.bot.importer = lambda u, user: {"kind": "album", "album": {"id": "A1", "name": "Disc"}}
        sent = self.click(sb.link_blocks(AP_ALBUM_NOMATCH), "link", "import_playlist", AP_ALBUM_NOMATCH["url"])
        self.assertIn("Added", sent[-1][1]["text"])

    def test_unmatched_youtube_track_still_gets_a_card(self):
        yt_track = dict(APPLE_TRACK, source="youtube", url="https://youtu.be/KdOD0fZs_XU", name="Mice on Venus", subtitle="C418",
                        spotify_uri=None, matched=0, tracks=[dict(song(1), uri=None)])
        self.bot.resolve = lambda u: yt_track
        post = self.post([yt_track["url"]])
        self.assertIn("YouTube, not found on Spotify", post["blocks"][1]["elements"][0]["text"])
        self.assertEqual(buttons(post["blocks"]), [])

    def test_nothing_resolved_is_logged(self):
        def boom(u):
            raise links.LinkError("nope")
        self.bot.resolve = boom
        with mock.patch.object(sb, "log") as lg:
            self.shared(["https://youtu.be/KdOD0fZs_XU"])
        self.assertEqual(self.bot.sent, [])
        self.assertTrue(any("no card" in c.args[0] for c in lg.call_args_list))

    def test_retried_delivery_is_handled_when_the_first_never_arrived(self):
        self.bot.sent.clear()
        self.bot.on_event({"team_id": self.bot.team, "event_id": "E7", "event": {
            "type": "link_shared", "channel": MUSIC, "message_ts": "8.8", "user": "U9",
            "links": [{"url": SP_TRACK["url"]}]}}, {"X-Slack-Retry-Num": "1"})
        self.assertTrue(self.bot.sent[-1][0].endswith("chat.postMessage"))


class Events(unittest.TestCase):
    def test_challenge(self):
        self.assertEqual(make().on_event({"type": "url_verification", "challenge": "abc"}, {}), (200, {"challenge": "abc"}))

    def test_unfurl(self):
        bot = make()
        url = "https://open.spotify.com/track/5W3cjX2J3tjhG8zb6u0qHn"
        ev = {"team_id": bot.team, "event_id": "E1", "event": {"type": "link_shared", "channel": "C1", "message_ts": "9.9",
                                                                  "links": [{"url": url}, {"url": "https://open.spotify.com/artist/4tZwfgrHOc3mvqYlEYSvVi"}]}}
        bot.on_event(ev, {})
        call = bot.sent[-1]
        self.assertTrue(call[0].endswith("chat.unfurl"))
        self.assertEqual(list(call[1]["unfurls"]), [url])
        n = len(bot.sent)
        bot.on_event(ev, {})
        self.assertEqual(len(bot.sent), n)

    def test_wrong_team(self):
        self.assertEqual(make().on_event({"team_id": "T0", "event": {}}, {})[0], 403)


class Feed(unittest.TestCase):
    def run_feed(self, bot, steps):
        t = getattr(bot, "clock", 1000.0)
        for state, track, dt in steps:
            bot.st = {"state": state, "track": track, "credit": getattr(bot, "credit", None)}
            t += dt
            bot.tick(t)
        bot.clock = t
        return t

    def calls(self, bot, method):
        return [p for u, p in bot.sent if u.endswith(method)]

    def test_posts_once_then_rotates_with_played(self):
        bot = make()
        bot.credit = ADA_Q
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4), ("playing", TRACK, 1)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)
        self.assertIn("\\nAda", json.dumps(self.calls(bot, "chat.postMessage")[0]["blocks"]))
        bot.credit = None
        self.run_feed(bot, [("playing", TRACK2, sb.REUSE + 1), ("playing", TRACK2, 4)])
        upd, posts = self.calls(bot, "chat.update"), self.calls(bot, "chat.postMessage")
        self.assertEqual(len(posts), 2)
        self.assertEqual(len(upd), 1)
        self.assertIn(" · Ada", json.dumps(upd[0]["blocks"], ensure_ascii=False))
        self.assertNotIn("button", json.dumps(upd[0]["blocks"]))
        self.assertNotIn("<@", json.dumps(bot.sent))
        self.assertEqual([u.rsplit("/", 1)[1] for u, _ in bot.sent][-2:], ["chat.update", "chat.postMessage"])

    def test_card_posted_once_with_name(self):
        bot = make()
        bot.credit = {"by": ADA, "how": "started"}
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4)])
        self.assertEqual([u.rsplit("/", 1)[1] for u, _ in bot.sent], ["chat.postMessage"])
        self.assertIn("\\nAda", json.dumps(self.calls(bot, "chat.postMessage")[0]["blocks"]))

    def test_admin_credit_stays_plain(self):
        bot = make()
        bot.credit = {"by": {"id": "admin", "name": "Admin", "avatar": None}, "how": "queued"}
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4), ("paused", TRACK, 6)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)
        self.assertNotIn("<@", json.dumps(bot.sent))
        self.assertIn("Admin", json.dumps(self.calls(bot, "chat.update")[-1]["blocks"]))

    def test_old_state_file_without_credit_loads(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "feed.json")
        old = {"uri": TRACK["uri"], "track": TRACK, "playing": True, "upcoming": [], "by": {"name": "Ada", "avatar": None}, "ts": "1.1"}
        def load():
            with open(path, "w") as f:
                json.dump(old, f)
            return sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), Credits(), SECRET, state_path=path)
        self.assertEqual(load().cur["credit"]["how"], "queued")
        del old["by"]
        bot = load()
        self.assertIsNone(bot.cur.get("credit"))
        self.assertTrue(bot.rendered(bot.cur))

    def test_restart_adopts_or_collapses_previous_message(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "feed.json")
        bot = make()
        bot.state_path = path
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)

        again = sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), Credits(), SECRET, state_path=path)
        again.sent = []
        again.http = bot.http = lambda url, payload, token=None: (again.sent.append((url, payload)) or (200, {"ok": True, "ts": "2.2"}, {}))
        self.run_feed(again, [("playing", TRACK, 0), ("playing", TRACK, 4), ("paused", TRACK, 6)])
        self.assertEqual(self.calls(again, "chat.postMessage"), [])
        self.assertTrue(all(p["ts"] == "1.1" for p in self.calls(again, "chat.update")))

        with open(path) as f:
            saved = json.load(f)
        saved.pop("posted")
        with open(path, "w") as f:
            json.dump(saved, f)
        third = sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), Credits(), SECRET, state_path=path)
        third.sent = []
        third.http = lambda url, payload, token=None: (third.sent.append((url, payload)) or (200, {"ok": True, "ts": "3.3"}, {}))
        self.run_feed(third, [("playing", TRACK2, 0), ("playing", TRACK2, 4)])
        upd = self.calls(third, "chat.update")
        self.assertEqual([u["ts"] for u in upd], ["1.1"])
        self.assertNotIn("button", json.dumps(upd[0]["blocks"]))
        self.assertEqual(len(self.calls(third, "chat.postMessage")), 1)
        with open(path) as f:
            self.assertEqual(json.load(f)["ts"], "3.3")

    def test_no_post_when_idle_or_paused(self):
        bot = make()
        self.run_feed(bot, [("idle", None, 0), ("idle", None, 10), ("paused", TRACK, 10), ("paused", TRACK, 10)])
        self.assertEqual(bot.sent, [])

    def test_debounced_pause_update(self):
        bot = make()
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 1)])
        self.run_feed(bot, [("paused", TRACK, 1), ("paused", TRACK, 1)])
        self.assertEqual(len(self.calls(bot, "chat.update")), 0)
        self.run_feed(bot, [("paused", TRACK, 2)])
        self.assertEqual(len(self.calls(bot, "chat.update")), 1)
        self.run_feed(bot, [("paused", TRACK, 60), ("paused", TRACK, 60)])
        self.assertEqual(len(self.calls(bot, "chat.update")), 1)

    def test_card_posted_immediately(self):
        bot = make()
        self.run_feed(bot, [("playing", TRACK, 0)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)

    def test_quick_skip_edits_card_in_place(self):
        bot = make()
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK2, sb.REUSE - 1)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)
        upd = self.calls(bot, "chat.update")
        self.assertEqual([u["ts"] for u in upd], ["1.1"])
        self.assertIn("Other", json.dumps(upd[0]["blocks"]))
        self.assertIn("button", json.dumps(upd[0]["blocks"]))
        self.assertNotIn("Played", upd[0]["text"])

    def test_skip_after_reuse_collapses_and_posts(self):
        bot = make()
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK2, sb.REUSE)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 2)
        upd = self.calls(bot, "chat.update")
        self.assertEqual(len(upd), 1)
        self.assertIn("Played", upd[0]["text"])
        self.assertNotIn("button", json.dumps(upd[0]["blocks"]))

    def test_idle_collapses_to_played_after_settle(self):
        bot = make()
        self.run_feed(bot, [("playing", TRACK, 0), ("idle", None, 1), ("idle", None, sb.SETTLE - 1)])
        self.assertEqual(self.calls(bot, "chat.update"), [])
        self.run_feed(bot, [("idle", None, 1)])
        self.assertIn("Played", self.calls(bot, "chat.update")[0]["text"])

    def test_quick_skip_not_posted(self):
        bot = make()
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4), ("playing", TRACK2, 1), ("playing", TRACK, 1)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)

    def test_failures_logged_once_and_backoff(self):
        bot = make()
        bot.http = lambda url, payload, token=None: (200, {"ok": False, "error": "missing_scope"}, {})
        logged = []
        orig = sb.log
        sb.log = logged.append
        try:
            self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4), ("playing", TRACK, 4)])
            bot.call("chat.postMessage")
        finally:
            sb.log = orig
        self.assertEqual(len(logged), 1)
        self.assertGreater(bot.pause_until, time.time())

    def test_rate_limit_retries(self):
        bot = make()
        bot.sleeps = []
        replies = [(429, {}, {"Retry-After": "2"}), (200, {"ok": True}, {})]
        bot.http = lambda url, payload, token=None: replies.pop(0)
        orig = sb.time.sleep
        sb.time.sleep = bot.sleeps.append
        try:
            self.assertTrue(bot.call("chat.update"))
        finally:
            sb.time.sleep = orig
        self.assertEqual(bot.sleeps, [2.0])



AIR = {"uri": None, "type": "airplay", "name": "Clair de Lune", "artists": [{"uri": None, "name": "Debussy"}],
       "album": None, "artwork": "/api/airplay/artwork?v=1"}
AIR_ART = dict(AIR, artwork="/api/airplay/artwork?v=abcabcabcabc")


class AirPlayTest(unittest.TestCase):
    def test_now_card_names_the_sender(self):
        bot = make()
        bot.player.status = lambda fresh=False: {"state": "playing", "source": "airplay", "track": AIR,
                                                 "airplay": {"sender": "Adam's iPhone"}}
        blocks, text = bot.now_card()
        self.assertEqual(text, "AirPlay from Adam's iPhone: Clair de Lune by Debussy")
        self.assertNotIn("image", str(blocks))

    def feed(self, bot, track, state="playing", sender="John's iPhone", dt=0):
        bot.clock = getattr(bot, "clock", 1000.0) + dt
        bot.st = {"state": state, "source": "airplay", "track": track, "airplay": {"sender": sender}}
        bot.tick(bot.clock)

    def calls(self, bot, method):
        return [p for u, p in bot.sent if u.endswith(method)]

    def test_posts_only_with_title_artist_and_art(self):
        bot = make()
        for track in (dict(AIR, artwork=None), dict(AIR, artists=[]), dict(AIR, name="AirPlay", artists=[])):
            self.feed(bot, track, dt=sb.SETTLE + 1)
            self.feed(bot, track, dt=sb.SETTLE + 1)
        self.assertEqual(bot.sent, [])
        self.feed(bot, AIR_ART, dt=1)
        self.assertEqual(bot.sent, [])
        self.feed(bot, AIR_ART, dt=sb.SETTLE)
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)

    def test_card_credits_sender_without_up_next_or_spotify_links(self):
        bot = make()
        self.feed(bot, AIR_ART)
        self.feed(bot, AIR_ART, dt=sb.SETTLE)
        blocks = self.calls(bot, "chat.postMessage")[0]["blocks"]
        text = json.dumps(blocks)
        self.assertIn("\\nJohn's iPhone", text)
        self.assertNotIn("Up next", text)
        self.assertNotIn("spotify.com", text)
        self.assertIn("https://music.pinewoodrobotics.org/airplay-art/abcabcabcabc", text)

    def test_song_change_rotates_and_finishes_previous(self):
        bot = make()
        self.feed(bot, AIR_ART)
        self.feed(bot, AIR_ART, dt=sb.SETTLE)
        nxt = dict(AIR_ART, name="Arabesque")
        self.feed(bot, nxt, dt=sb.REUSE + 1)
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)
        self.feed(bot, nxt, dt=sb.SETTLE)
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 2)
        played = self.calls(bot, "chat.update")
        self.assertEqual(played[-1]["text"], "Played: Clair de Lune")
        self.assertIn(" · John's iPhone", json.dumps(played[-1]["blocks"], ensure_ascii=False))

    def test_late_art_posts_then_changed_art_updates(self):
        bot = make()
        self.feed(bot, dict(AIR, artwork=None))
        self.feed(bot, dict(AIR, artwork=None), dt=sb.SETTLE + 1)
        self.assertEqual(bot.sent, [])
        self.feed(bot, AIR_ART, dt=1)
        self.feed(bot, AIR_ART, dt=sb.SETTLE)
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)
        self.feed(bot, dict(AIR_ART, artwork="/api/airplay/artwork?v=defdefdefdef"), dt=sb.UPDATE_EVERY + 1)
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)
        self.assertIn("defdefdefdef", json.dumps(self.calls(bot, "chat.update")[-1]["blocks"]))

    def test_metadata_refresh_of_same_song_does_not_repost(self):
        bot = make()
        self.feed(bot, AIR_ART)
        self.feed(bot, AIR_ART, dt=sb.SETTLE)
        self.feed(bot, dict(AIR_ART, duration_ms=1), state="paused", dt=sb.UPDATE_EVERY + 1)
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)
        self.assertIn("Play", json.dumps(self.calls(bot, "chat.update")[-1]["blocks"]))

    def test_handoff_to_spotify_continues_the_feed(self):
        bot = make()
        self.feed(bot, AIR_ART)
        self.feed(bot, AIR_ART, dt=sb.SETTLE)
        bot.clock += sb.REUSE + 1
        bot.st = {"state": "playing", "track": TRACK, "credit": None}
        bot.tick(bot.clock)
        self.assertEqual(self.calls(bot, "chat.update")[-1]["text"], "Played: Clair de Lune")
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 2)
        self.assertIn("One &lt;More&gt; Time", json.dumps(self.calls(bot, "chat.postMessage")[-1]["blocks"]))


if __name__ == "__main__":
    unittest.main()
