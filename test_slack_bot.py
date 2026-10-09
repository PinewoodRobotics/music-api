import hashlib
import hmac
import json
import time
import unittest
import urllib.parse

import slack_bot as sb
from accounts import QueueCredits

SECRET = "shh"
TRACK = {"uri": "spotify:track:5W3cjX2J3tjhG8zb6u0qHn", "type": "track", "name": "One <More> Time",
         "artists": [{"name": "Daft Punk"}], "album": {"name": "Discovery"}, "duration_ms": 320357,
         "artwork": "https://i.scdn.co/x"}
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
    bot = sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), QueueCredits(), SECRET)
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
        bot = sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), QueueCredits(), None)
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

    def test_skip_notes_channel_and_responds(self):
        bot = make()
        bot.on_command({"team_id": bot.team, "text": "skip", "user_id": "U1", "response_url": "http://r/1"})
        self.assertEqual(bot.player.calls, ["next"])
        post = [p for u, p in bot.sent if u.endswith("chat.postMessage")][0]
        self.assertEqual(post["channel"], sb.DEFAULT_CHANNEL)
        self.assertIn("<@U1> skipped", post["text"])
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
        blocks = sb.now_playing_blocks(TRACK, True, {"name": "Ada", "avatar": "http://a"}, [{"item": TRACK2}], "https://r/")
        self.assertEqual(blocks[0]["accessory"]["image_url"], TRACK["artwork"])
        self.assertIn("<https://open.spotify.com/track/5W3cjX2J3tjhG8zb6u0qHn|One &lt;More&gt; Time>", blocks[0]["text"]["text"])
        self.assertIn("Daft Punk · Discovery", blocks[0]["text"]["text"])
        flat = json.dumps(blocks)
        self.assertIn("Queued by Ada", flat)
        self.assertIn("Up next: Other", flat)
        acts = blocks[-1]["elements"]
        self.assertEqual([a["action_id"] for a in acts], ["playpause", "skip", "listen_along", "open_remote"])
        self.assertEqual(acts[0]["text"]["text"], "Pause")
        self.assertEqual(acts[3]["url"], "https://r/")
        self.assertEqual(sb.now_playing_blocks(TRACK, False)[-1]["elements"][0]["text"]["text"], "Play")

    def test_played_has_no_buttons(self):
        self.assertNotIn("button", json.dumps(sb.played_blocks(TRACK, {"name": "Ada"})))

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
        self.assertEqual(bot.credits.lookup(TRACK["uri"]), {"name": "Ada", "avatar": "http://a/av.png"})
        sent = bot.sent[-1][1]
        self.assertTrue(sent["replace_original"])
        self.assertIn("Queued by Ada", json.dumps(sent["blocks"]))
        self.assertNotIn("button", json.dumps(sent["blocks"][1]))

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
        self.assertEqual([a for a, _ in buttons(sb.link_blocks(album))], ["play_uri", "import_playlist"])
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
            bot.st = {"state": state, "track": track}
            t += dt
            bot.tick(t)
        bot.clock = t
        return t

    def calls(self, bot, method):
        return [p for u, p in bot.sent if u.endswith(method)]

    def test_posts_once_then_rotates_with_played(self):
        bot = make()
        bot.credits.add([TRACK["uri"]], {"name": "Ada", "avatar": None})
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4), ("playing", TRACK, 1)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)
        self.assertIn("Queued by Ada", json.dumps(self.calls(bot, "chat.postMessage")[0]["blocks"]))
        self.run_feed(bot, [("playing", TRACK2, 0), ("playing", TRACK2, 4)])
        upd, posts = self.calls(bot, "chat.update"), self.calls(bot, "chat.postMessage")
        self.assertEqual(len(posts), 2)
        self.assertEqual(len(upd), 1)
        self.assertNotIn("button", json.dumps(upd[0]["blocks"]))
        self.assertEqual([u.rsplit("/", 1)[1] for u, _ in bot.sent][-2:], ["chat.update", "chat.postMessage"])

    def test_restart_adopts_or_collapses_previous_message(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "feed.json")
        bot = make()
        bot.state_path = path
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4)])
        self.assertEqual(len(self.calls(bot, "chat.postMessage")), 1)

        again = sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), QueueCredits(), SECRET, state_path=path)
        again.sent = []
        again.http = bot.http = lambda url, payload, token=None: (again.sent.append((url, payload)) or (200, {"ok": True, "ts": "2.2"}, {}))
        self.run_feed(again, [("playing", TRACK, 0), ("playing", TRACK, 4), ("paused", TRACK, 6)])
        self.assertEqual(self.calls(again, "chat.postMessage"), [])
        self.assertTrue(all(p["ts"] == "1.1" for p in self.calls(again, "chat.update")))

        third = sb.SlackBot(FakeSlack(), FakePlayer(), FakeApi(), QueueCredits(), SECRET, state_path=path)
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
        self.run_feed(bot, [("playing", TRACK, 0), ("playing", TRACK, 4)])
        self.run_feed(bot, [("paused", TRACK, 1), ("paused", TRACK, 1)])
        self.assertEqual(len(self.calls(bot, "chat.update")), 0)
        self.run_feed(bot, [("paused", TRACK, 4)])
        self.assertEqual(len(self.calls(bot, "chat.update")), 1)
        self.run_feed(bot, [("paused", TRACK, 60), ("paused", TRACK, 60)])
        self.assertEqual(len(self.calls(bot, "chat.update")), 1)

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


class Credits(unittest.TestCase):
    def test_lookup_consume(self):
        c = QueueCredits()
        c.add(["u"], {"name": "A", "avatar": None})
        c.add(["u"], {"name": "B", "avatar": None})
        self.assertEqual(c.lookup("u")["name"], "A")
        self.assertEqual(c.lookup("u", consume=True)["name"], "A")
        self.assertEqual(c.lookup("u", consume=True)["name"], "B")
        self.assertIsNone(c.lookup("u"))


if __name__ == "__main__":
    unittest.main()
