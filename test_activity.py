import json
import os
import stat
import tempfile
import unittest

import activity as act
from activity import Activity

ADA = {"id": "U1", "name": "Ada", "avatar": "http://a", "admin": False}
BOB = {"id": "U2", "name": "Bob", "avatar": None}


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "activity.jsonl")
        self.clock = Clock()
        self.a = Activity(self.path, self.clock)

    def line_count(self):
        with open(self.path) as f:
            return len(f.readlines())

    def reopen(self):
        return Activity(self.path, self.clock)

    def test_record_and_since(self):
        e1 = self.a.record(ADA, "pause", None, "web")
        e2 = self.a.record(BOB, "next", {"from": "Song"}, "slack")
        self.assertEqual((e1["id"], e2["id"]), (1, 2))
        self.assertEqual(e2["by"], {"id": "U2", "name": "Bob", "avatar": None})
        self.assertEqual(e1["detail"], {})
        self.assertEqual(e1["at"], 1_000_000_000)
        self.assertEqual([e["id"] for e in self.a.since()], [1, 2])
        self.assertEqual([e["id"] for e in self.a.since(1)], [2])
        self.assertEqual(self.a.since(2), [])
        self.assertEqual([e["id"] for e in self.a.since(limit=1)], [2])
        self.assertEqual([e["id"] for e in self.a.since(0, limit=1)], [1])
        self.assertEqual(self.a.latest, 2)

    def test_returned_entries_are_copies(self):
        e = self.a.record(ADA, "play", {"x": 1})
        e["detail"]["x"] = 2
        self.assertEqual(self.a.since()[0]["detail"], {"x": 1})

    def test_file_mode_and_persist_round_trip(self):
        self.a.record(ADA, "pause")
        self.a.record(BOB, "queue_add", {"uris": ["u"], "count": 1}, "api")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        again = self.reopen()
        self.assertEqual(again.since(), self.a.since())
        self.assertEqual(again.record(ADA, "play")["id"], 3)

    def test_prune_after_24h_on_load_and_hourly(self):
        self.a.record(ADA, "pause")
        self.clock.t += 23 * 3600
        self.a.record(BOB, "play")
        self.clock.t += 2 * 3600
        self.a.record(ADA, "next")
        self.assertEqual([e["id"] for e in self.a.since()], [2, 3])
        with open(self.path) as f:
            lines = [json.loads(line) for line in f]
        self.assertNotIn(1, [e.get("id") for e in lines])
        self.clock.t += 23 * 3600
        again = self.reopen()
        self.assertEqual([e["id"] for e in again.since()], [3])

    def test_ids_stay_monotonic_after_everything_is_pruned(self):
        self.a.record(ADA, "pause")
        self.clock.t += 30 * 3600
        again = self.reopen()
        self.assertEqual(again.since(), [])
        self.assertEqual(again.record(ADA, "play")["id"], 2)
        self.assertEqual(self.reopen().latest, 2)

    def test_malformed_lines_are_skipped(self):
        self.a.record(ADA, "pause")
        with open(self.path, "a") as f:
            f.write("not json\n[1]\n")
        self.assertEqual(len(self.reopen().since()), 1)

    def test_volume_coalesces_per_user_within_10s(self):
        seen = []
        self.a.publish = seen.append
        v1 = self.a.record(ADA, "volume", {"volume": 10})
        self.clock.t += 5
        v2 = self.a.record(ADA, "volume", {"volume": 30})
        self.assertEqual(v2["id"], v1["id"])
        self.assertEqual(v2["detail"], {"volume": 30})
        self.assertEqual(v2["at"], v1["at"] + 5000)
        self.assertEqual(len(self.a.since()), 1)
        self.assertEqual([e["id"] for e in seen], [1, 1])
        self.assertEqual(seen[-1]["detail"], {"volume": 30})
        other = self.a.record(BOB, "volume", {"volume": 5})
        self.assertEqual(other["id"], 2)
        self.clock.t += 11
        later = self.a.record(ADA, "volume", {"volume": 50})
        self.assertEqual(later["id"], 3)
        again = self.reopen()
        self.assertEqual([(e["id"], e["detail"]["volume"]) for e in again.since()], [(1, 30), (2, 5), (3, 50)])

    def test_volume_does_not_coalesce_across_other_actions_of_same_user_window(self):
        self.a.record(ADA, "volume", {"volume": 10})
        self.a.record(ADA, "pause")
        self.clock.t += 2
        self.assertEqual(self.a.record(ADA, "volume", {"volume": 20})["id"], 1)

    def test_update_republishes_same_id_and_persists(self):
        seen = []
        self.a.publish = seen.append
        e = self.a.record(ADA, "queue_add", {"uris": ["u"], "count": 1})
        out = self.a.update(e["id"], names=["Song"])
        self.assertEqual(out["id"], e["id"])
        self.assertEqual([s["id"] for s in seen], [1, 1])
        self.assertEqual(seen[-1]["detail"]["names"], ["Song"])
        self.assertEqual(self.reopen().since()[0]["detail"], {"uris": ["u"], "count": 1, "names": ["Song"]})
        self.assertIsNone(self.a.update(99, names=[]))

    def test_enrich_runs_in_background_and_ignores_failures(self):
        e = self.a.record(ADA, "play_item", {"uri": "u"})
        self.a.enrich(e, lambda: {"name": "Album", "empty": None}).join(5)
        self.assertEqual(self.a.since()[0]["detail"], {"uri": "u", "name": "Album"})
        n = self.line_count()

        def boom():
            raise RuntimeError("nope")
        self.a.enrich(e, boom).join(5)
        self.assertEqual(self.line_count(), n)

    def test_publish_errors_do_not_break_record(self):
        def bad(_):
            raise RuntimeError("subscriber")
        self.a.publish = bad
        self.assertEqual(self.a.record(ADA, "pause")["id"], 1)

    def test_in_memory_without_path(self):
        a = Activity(None, self.clock)
        a.record(ADA, "pause")
        self.assertEqual(len(a.since()), 1)


class HelpersTest(unittest.TestCase):
    def test_origin_mapping(self):
        self.assertEqual(act.origin_for({"X-Client-Origin": "media-session"}, False), "media-session")
        self.assertEqual(act.origin_for({"X-Client-Origin": "media-session:lockscreen"}, True), "media-session")
        self.assertEqual(act.origin_for({"X-Client-Origin": "web"}, False), "web")
        self.assertEqual(act.origin_for({}, True), "api")
        self.assertEqual(act.origin_for({}, False), "web")

    def test_track_names_prefers_queue_and_caps_lookups(self):
        class Api:
            calls = []

            def get(self, path):
                self.calls.append(path)
                return {"name": "N" + path[-1]}
        uris = [f"spotify:track:{i}" for i in "abcdefgh"]
        queue = {"upcoming": [{"item": {"uri": uris[0], "name": "Queued"}}]}
        api = Api()
        names = act.track_names(api, uris, queue)
        self.assertEqual(names, ["Queued"] + ["N" + c for c in "bcdef"])
        self.assertEqual(len(api.calls), act.MAX_LOOKUPS)

    def test_track_names_survives_lookup_errors(self):
        class Api:
            def get(self, path):
                raise RuntimeError("403")
        self.assertEqual(act.track_names(Api(), ["spotify:track:a"]), [])

    def test_item_name_by_kind(self):
        class Api:
            def get(self, path):
                return {"name": path}
        self.assertEqual(act.item_name(Api(), "spotify:playlist:abc"), "/playlists/abc")
        self.assertEqual(act.item_name(Api(), "spotify:album:abc"), "/albums/abc")
        self.assertIsNone(act.item_name(Api(), "spotify:user:abc"))


class SlackWiringTest(unittest.TestCase):
    def bot(self):
        import test_slack_bot as t
        from accounts import Credits
        a = Activity(None)
        self.threads, enrich = [], a.enrich
        a.enrich = lambda e, fn: self.threads.append(enrich(e, fn))
        bot = t.make()
        bot.activity = a
        bot.credits = Credits()
        bot.user = lambda uid, fallback=None: {"id": uid, "name": "Ada", "avatar": None}
        return bot, a, t

    def test_transport_records_slack_origin(self):
        bot, a, _ = self.bot()
        bot.transport("skip", "U1")
        bot.transport("pause", "U1")
        bot.transport("play", "U1")
        rows = a.since()
        self.assertEqual([e["action"] for e in rows], ["next", "pause", "play"])
        self.assertEqual({e["origin"] for e in rows}, {"slack"})
        self.assertTrue(rows[0]["detail"]["from"])

    def test_queue_add_button_records_and_enriches(self):
        bot, a, t = self.bot()
        bot.on_interaction(t.Interactions.payload(None, {"action_id": "queue_add", "value": t.TRACK["uri"]}))
        for th in self.threads:
            th.join(5)
        e = a.since()[0]
        self.assertEqual((e["action"], e["origin"], e["detail"]["uris"], e["detail"]["count"]),
                         ("queue_add", "slack", [t.TRACK["uri"]], 1))
        self.assertEqual(e["detail"]["names"], ["T"])


if __name__ == "__main__":
    unittest.main()
