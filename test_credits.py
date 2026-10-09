import json
import os
import tempfile
import time
import unittest

from accounts import Credits
from player import Player

def _load(path):
    with open(path) as f:
        return json.load(f)


A = {"id": "U1", "name": "Ada", "avatar": "http://a", "admin": False, "kind": "slack"}
B = {"id": "U2", "name": "Bob", "avatar": None}
T1, T2 = "spotify:track:aaaaaaaaaaaaaaaaaaaaaa", "spotify:track:bbbbbbbbbbbbbbbbbbbbbb"
ALBUM = "spotify:album:cccccccccccccccccccccc"


def st(uri, ctx=None):
    return {"track": {"uri": uri}, "context": {"uri": ctx} if ctx else None}


class CreditsTest(unittest.TestCase):
    def test_queued_credit_popped_once_and_stable(self):
        c = Credits()
        c.add([T1], A)
        c.add([T1], B)
        for _ in range(20):
            self.assertEqual(c.for_status(st(T1)), {"by": {"id": "U1", "name": "Ada", "avatar": "http://a"}, "how": "queued"})
        self.assertEqual(len(c.by_uri[T1]), 1)
        self.assertEqual(c.for_status(st(T2)), None)
        self.assertEqual(c.for_status(st(T1))["by"]["name"], "Bob")

    def test_queued_beats_started(self):
        c = Credits()
        c.start([T1], B)
        c.add([T1], A)
        self.assertEqual(c.for_status(st(T1))["how"], "queued")
        self.assertEqual(c.for_status(st(T1))["by"]["id"], "U1")

    def test_started_covers_track_and_context(self):
        c = Credits()
        c.start([ALBUM], B)
        got = c.for_status(st(T1, ALBUM))
        self.assertEqual((got["how"], got["by"]["id"]), ("started", "U2"))
        self.assertIsNone(c.for_status(st(T2, "spotify:playlist:dddddddddddddddddddddd")))
        c.start([T1, T2], A)
        self.assertEqual(c.for_status(st(T1))["by"]["id"], "U1")

    def test_no_track_no_credit_and_current_kept(self):
        c = Credits()
        c.start([T1], A)
        self.assertEqual(c.for_status(st(T1))["how"], "started")
        self.assertIsNone(c.for_status({"track": None}))
        self.assertEqual(c.for_status(st(T1))["how"], "started")

    def test_persistence_round_trip(self):
        path = os.path.join(tempfile.mkdtemp(), "credits.json")
        c = Credits(path)
        c.add([T2], B)
        c.start([ALBUM], A)
        c.for_status(st(T1, ALBUM))
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        d = Credits(path)
        self.assertEqual(d.for_status(st(T1, ALBUM))["by"]["id"], "U1")
        self.assertEqual(d.for_status(st(T2))["by"]["id"], "U2")
        self.assertEqual(_load(path)["current"]["uri"], T2)

    def test_expiry(self):
        c = Credits()
        c.add([T1], A)
        c.by_uri[T1] = [(A, time.time() - 6 * 3600 - 1)]
        c.start([T2], A)
        c.started["time"] -= 12 * 3600 + 1
        self.assertIsNone(c.for_status(st(T1)))
        self.assertIsNone(c.for_status(st(T2)))

    def test_annotate_includes_id(self):
        c = Credits()
        c.add([T1], A)
        q = c.annotate({"upcoming": [{"item": {"uri": T1}, "source": "queue"}]})
        self.assertEqual(q["upcoming"][0]["added_by"]["id"], "U1")


class PlayerCredit(unittest.TestCase):
    def test_status_includes_credit(self):
        p = Player("soloist", None, None, None)
        p._status = lambda fresh=False: {"track": {"uri": T1}}
        self.assertIsNone(p.status()["credit"])
        c = Credits()
        c.start([T1], A)
        p.credit_fn = c.for_status
        self.assertEqual(p.status(fresh=True)["credit"]["how"], "started")


if __name__ == "__main__":
    unittest.main()
