import threading
import unittest

from accounts import Credits
from player import Player, PlayerError, REMOVED_GONE, REMOVED_TTL

ADA = {"id": "U1", "name": "Ada", "avatar": None}


def uri(n):
    return f"spotify:track:{n:022d}"


def ent(uid, n, source="queue"):
    return {"uid": uid, "source": source, "item": {"uri": uri(n), "entity_type": "track",
                                                   "decorations": {"identity": {"name": f"T{n}"}}}}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeSoloist:
    def __init__(self, upcoming):
        self.queue = {"previous": [], "upcoming": upcoming}
        self.playback = None
        self.connected = True
        self.auth = {"logged_in": True, "is_active": True, "device_name": "dev"}
        self.last_error = None
        self.calls = []
        self.skipped = threading.Event()

    def command(self, name, **fields):
        self.calls.append(name)
        if name == "get_queue":
            up = self.queue["upcoming"]
            return {"upcoming": up[:fields["limit"]] if fields.get("limit") else up, "previous": []}
        if name == "skip_next":
            self.skipped.set()
            if self.queue["upcoming"]:
                self.play(self.queue["upcoming"].pop(0)["item"])
        return {}

    def play(self, item):
        self.playback = {"status": "playing", "item": item, "options": {}}

    def position_ms(self):
        return 0


def make(ids):
    sol = FakeSoloist([ent(f"u{n}", n) for n in ids])
    p = Player("soloist", None, sol)
    p.clock = Clock()
    return p, sol


def uids(q):
    return [e["uid"] for e in q["upcoming"]]


class QueueRemoveTest(unittest.TestCase):
    def test_remove_filters_queue_and_event(self):
        p, sol = make([1, 2, 3])
        sub = p.subscribe()
        res = p.remove_from_queue({"uid": "u2"}, ADA)
        self.assertEqual(uids(res["queue"]), ["u1", "u3"])
        self.assertEqual(uids(p.queue()), ["u1", "u3"])
        self.assertEqual(uids(p.queue(1)), ["u1"])
        self.assertEqual(uids(sub.get_nowait()[1]), ["u1", "u3"])
        p.on_soloist_event("queue_changed", {"upcoming": sol.queue["upcoming"], "previous": []})
        ev = []
        while not sub.empty():
            ev.append(sub.get_nowait())
        queues = [d for n, d in ev if n == "queue"]
        self.assertEqual(uids(queues[0]), ["u1", "u3"])

    def test_bulk_and_index(self):
        p, _ = make([1, 2, 3, 4])
        p.remove_from_queue({"uids": ["u1", "u4"]}, ADA)
        self.assertEqual(uids(p.queue()), ["u2", "u3"])
        p.remove_from_queue({"index": 1}, ADA)
        self.assertEqual(uids(p.queue()), ["u2"])

    def test_404_and_atomic(self):
        p, _ = make([1, 2])
        with self.assertRaises(PlayerError) as c:
            p.remove_from_queue({"uids": ["u1", "nope"]}, ADA)
        self.assertEqual(c.exception.status, 404)
        self.assertEqual(uids(p.queue()), ["u1", "u2"])
        p.remove_from_queue({"uid": "u1"}, ADA)
        with self.assertRaises(PlayerError):
            p.remove_from_queue({"uid": "u1"}, ADA)
        with self.assertRaises(PlayerError) as c:
            p.remove_from_queue({"index": 5}, ADA)
        self.assertEqual(c.exception.status, 404)

    def test_jump_indexes_filtered_but_skips_real(self):
        p, sol = make([1, 2, 3, 4])
        p.remove_from_queue({"uid": "u2"}, ADA)
        p.jump({"index": 1})
        self.assertEqual(sol.calls.count("skip_next"), 3)
        self.assertEqual(sol.playback["item"]["uri"], uri(3))

    def test_jump_by_uid_with_removed_before(self):
        p, sol = make([1, 2, 3, 4])
        p.remove_from_queue({"uids": ["u1", "u2"]}, ADA)
        p.jump({"uid": "u3"})
        self.assertEqual(sol.calls.count("skip_next"), 3)
        self.assertEqual(sol.playback["item"]["uri"], uri(3))

    def test_autoskip_once_when_removed_becomes_current(self):
        p, sol = make([1, 2, 3])
        sol.play(ent("x", 9)["item"])
        p.status()
        self.assertNotIn("removed", p.status())
        p.remove_from_queue({"uid": "u1"}, ADA)
        sol.playback["item"] = sol.queue["upcoming"].pop(0)["item"]
        st = p.status()
        self.assertTrue(st["removed"])
        self.assertIsNone(st["credit"])
        self.assertTrue(sol.skipped.wait(2))
        for _ in range(5):
            p.status()
        self.assertEqual(sol.calls.count("skip_next"), 1)
        sol.playback["item"] = sol.queue["upcoming"].pop(0)["item"]
        self.assertNotIn("removed", p.status())
        self.assertEqual(sol.calls.count("skip_next"), 1)

    def test_not_next_entry_is_not_skipped(self):
        p, sol = make([1, 2, 3])
        sol.play(ent("x", 9)["item"])
        p.status()
        p.status()
        p.remove_from_queue({"uid": "u3"}, ADA)
        sol.playback["item"] = ent("y", 3)["item"]
        self.assertNotIn("removed", p.status())
        self.assertEqual(sol.calls.count("skip_next"), 0)

    def test_expiry_after_leaving_queue(self):
        p, sol = make([1, 2])
        p.remove_from_queue({"uid": "u1"}, ADA)
        sol.queue["upcoming"] = [ent("u2", 2)]
        p.queue()
        p.clock.t += REMOVED_GONE - 1
        p.queue()
        self.assertEqual(len(p.removed), 1)
        p.clock.t += 2
        p.queue()
        self.assertEqual(len(p.removed), 0)

    def test_ttl_expiry_and_limited_fetch_keeps(self):
        p, sol = make([1, 2, 3])
        p.remove_from_queue({"uid": "u3"}, ADA)
        p.clock.t += REMOVED_GONE + 5
        p.queue(1)
        self.assertEqual(len(p.removed), 1)
        p.clock.t += REMOVED_TTL
        p.queue(1)
        self.assertEqual(len(p.removed), 0)

    def test_occurrence_keys_without_uid(self):
        sol = FakeSoloist([{"uid": None, "source": None, "item": {"uri": uri(1), "entity_type": "track"}}
                           for _ in range(3)])
        p = Player("soloist", None, sol)
        p.remove_from_queue({"index": 1}, ADA)
        self.assertEqual(len(p.queue()["upcoming"]), 2)

    def test_credit_dropped(self):
        c = Credits()
        c.add([uri(2)], ADA)
        p, _ = make([1, 2])
        p.uncredit_fn = c.unqueue
        p.remove_from_queue({"uid": "u2"}, ADA)
        self.assertNotIn(uri(2), c.by_uri)


if __name__ == "__main__":
    unittest.main()
