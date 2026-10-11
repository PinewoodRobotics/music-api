import datetime
import json
import os
import tempfile
import unittest

import quiet_hours as qh


def at(day, h, m=0, s=0):
    return datetime.datetime(2026, 10, day, h, m, s).timestamp()


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Window(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(qh.parse_window("21:00-08:00"), (21 * 60, 8 * 60))
        self.assertEqual(qh.parse_window(" 9:30 - 17:05 "), (9 * 60 + 30, 17 * 60 + 5))
        for off in ("off", "", None, "none"):
            self.assertIsNone(qh.parse_window(off))
        for bad in ("21-08", "25:00-08:00", "21:00-21:00", "21:60-08:00"):
            with self.assertRaises(ValueError):
                qh.parse_window(bad)

    def test_wraparound_boundaries(self):
        w = qh.parse_window("21:00-08:00")
        inside = [21 * 60, 23 * 60 + 59, 0, 3 * 60, 7 * 60 + 59]
        outside = [8 * 60, 12 * 60, 20 * 60 + 59]
        self.assertTrue(all(qh.in_window(w, m) for m in inside))
        self.assertFalse(any(qh.in_window(w, m) for m in outside))

    def test_same_day_window(self):
        w = qh.parse_window("01:00-05:00")
        self.assertTrue(qh.in_window(w, 60))
        self.assertFalse(qh.in_window(w, 5 * 60))
        self.assertFalse(qh.in_window(w, 0))
        self.assertEqual(qh.bounds(w, at(12, 6)), (at(13, 1), at(13, 5)))
        self.assertEqual(qh.bounds(w, at(12, 2)), (at(12, 1), at(12, 5)))

    def test_bounds_wrap(self):
        w = qh.parse_window("21:00-08:00")
        self.assertEqual(qh.bounds(w, at(12, 22)), (at(12, 21), at(13, 8)))
        self.assertEqual(qh.bounds(w, at(13, 3)), (at(12, 21), at(13, 8)))
        self.assertEqual(qh.bounds(w, at(13, 12)), (at(13, 21), at(14, 8)))

    def test_clock12(self):
        self.assertEqual(qh.clock12(8 * 60), "8:00 AM")
        self.assertEqual(qh.clock12(21 * 60 + 5), "9:05 PM")
        self.assertEqual(qh.clock12(0), "12:00 AM")


class Lock(unittest.TestCase):
    def make(self, t, path=None, window="21:00-08:00"):
        c = Clock(t)
        return qh.QuietHours(qh.parse_window(window), path, clock=c), c

    def test_open_before_window(self):
        q, c = self.make(at(12, 20, 50))
        self.assertIsNone(q.observe(False))
        c.t = at(12, 20, 59)
        self.assertIsNone(q.observe(False))
        self.assertEqual(q.status()["phase"], "open")

    def test_grace_while_playing_never_locks(self):
        q, c = self.make(at(12, 20, 30))
        for minute in range(0, 120, 1):
            c.t = at(12, 20, 30) + minute * 60
            self.assertIsNone(q.observe(True))
        self.assertEqual(q.status()["phase"], "grace")
        self.assertFalse(q.locked())

    def test_locks_after_five_idle_minutes(self):
        q, c = self.make(at(12, 22))
        q.observe(True)
        c.t = at(12, 22, 1)
        self.assertIsNone(q.observe(False))
        st = q.status()
        self.assertEqual((st["phase"], st["locks_at"]), ("grace", round(at(12, 22, 6))))
        c.t = at(12, 22, 5, 59)
        self.assertIsNone(q.observe(False))
        c.t = at(12, 22, 6)
        self.assertEqual(q.observe(False), "locked")
        st = q.status()
        self.assertEqual((st["phase"], st["locked"], st["until"], st["until_ts"]), ("locked", True, "08:00", round(at(13, 8))))

    def test_resume_resets_idle_clock(self):
        q, c = self.make(at(12, 22))
        q.observe(False)
        c.t = at(12, 22, 4)
        q.observe(True)
        c.t = at(12, 22, 5)
        q.observe(False)
        c.t = at(12, 22, 9)
        self.assertIsNone(q.observe(False))
        c.t = at(12, 22, 10)
        self.assertEqual(q.observe(False), "locked")

    def test_idle_before_window_locks_at_start_plus_grace(self):
        q, c = self.make(at(12, 19))
        q.observe(False)
        c.t = at(12, 21, 4)
        self.assertIsNone(q.observe(False))
        self.assertEqual(q.status()["locks_at"], round(at(12, 21, 5)))
        c.t = at(12, 21, 5)
        self.assertEqual(q.observe(False), "locked")

    def test_stays_locked_even_if_audio_reported_then_unlocks_at_end(self):
        q, c = self.make(at(12, 21, 10))
        q.observe(False)
        c.t = at(12, 21, 15)
        self.assertEqual(q.observe(False), "locked")
        c.t = at(13, 3)
        self.assertIsNone(q.observe(True))
        self.assertTrue(q.locked())
        c.t = at(13, 7, 59, 59)
        self.assertTrue(q.locked())
        c.t = at(13, 8)
        self.assertFalse(q.locked())
        self.assertEqual(q.observe(False), "unlocked")
        self.assertEqual(q.status()["phase"], "open")

    def test_off_never_locks(self):
        q, c = self.make(at(12, 23), window="off")
        q.observe(False)
        c.t = at(13, 2)
        self.assertIsNone(q.observe(False))
        self.assertEqual(q.status(), {"enabled": False, "window": None, "phase": "open", "locked": False})

    def test_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, qh.STATE_FILE)
            q, c = self.make(at(12, 22), path)
            q.observe(False)
            c.t = at(12, 22, 5)
            self.assertEqual(q.observe(False), "locked")
            q2, _ = self.make(at(12, 23), path)
            self.assertTrue(q2.locked())

    def test_restart_keeps_idle_clock(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, qh.STATE_FILE)
            q, c = self.make(at(12, 22), path)
            q.observe(False)
            with open(path) as f:
                self.assertEqual(json.load(f)["idle_since"], at(12, 22))
            q2, c2 = self.make(at(12, 22, 3), path)
            self.assertIsNone(q2.observe(False))
            c2.t = at(12, 22, 5)
            self.assertEqual(q2.observe(False), "locked")

    def test_boot_at_night_with_nothing_playing_locks_after_grace(self):
        q, c = self.make(at(13, 2))
        self.assertIsNone(q.observe(False))
        c.t = at(13, 2, 5)
        self.assertEqual(q.observe(False), "locked")

    def test_watchdog_observe_keeps_server_heartbeat(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, qh.STATE_FILE)
            q, c = self.make(at(12, 22), path)
            q.observe(True)
            q2, _ = self.make(at(12, 22, 10), path)
            q2.observe(False, heartbeat=False)
            with open(path) as f:
                self.assertEqual(json.load(f)["heartbeat"], at(12, 22))


if __name__ == "__main__":
    unittest.main()
