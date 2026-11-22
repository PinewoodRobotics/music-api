import contextlib
import datetime
import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

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


class Override(unittest.TestCase):
    def make(self, t, path=None):
        c = Clock(t)
        return qh.QuietHours(qh.parse_window("21:00-08:00"), path, clock=c), c

    def test_unlock_until_morning_then_normal_rules(self):
        q, c = self.make(at(12, 22))
        q.observe(False)
        c.t = at(12, 22, 5)
        self.assertEqual(q.observe(False), "locked")
        q.set_override("unlock", {"id": "U1", "name": "Ada"})
        self.assertFalse(q.locked())
        st = q.status()
        self.assertEqual((st["phase"], st["override"]["kind"], st["override"]["until_ts"]), ("open", "unlocked", round(at(13, 8))))
        c.t = at(13, 3)
        self.assertIsNone(q.observe(False))
        self.assertFalse(q.locked())
        c.t = at(13, 8)
        q.observe(False)
        self.assertIsNone(q.override)
        c.t = at(13, 21, 5)
        self.assertEqual(q.observe(False), "locked")

    def test_unlock_outside_window_covers_tonight(self):
        q, c = self.make(at(12, 15))
        q.set_override("unlock")
        c.t = at(12, 23)
        self.assertIsNone(q.observe(False))
        self.assertEqual(q.status()["override"]["until_ts"], round(at(13, 8)))

    def test_lock_now_only_inside_window(self):
        q, c = self.make(at(12, 15))
        with self.assertRaises(ValueError):
            q.set_override("lock")
        c.t = at(12, 21, 1)
        q.observe(True)
        q.set_override("lock", {"id": "U1", "name": "Ada"})
        self.assertTrue(q.locked())
        st = q.status()
        self.assertEqual((st["phase"], st["override"]["kind"], st["override"]["by"]["name"]), ("locked", "locked", "Ada"))
        c.t = at(13, 8)
        self.assertEqual(q.observe(False), "unlocked")
        self.assertIsNone(q.status()["override"])

    def test_clear_lock_restarts_idle_clock(self):
        q, c = self.make(at(12, 22))
        q.observe(False)
        q.set_override("lock")
        c.t = at(12, 23)
        q.set_override("clear")
        self.assertFalse(q.locked())
        self.assertIsNone(q.observe(False))
        c.t = at(12, 23, 5)
        self.assertEqual(q.observe(False), "locked")

    def test_bad_action(self):
        q, _ = self.make(at(12, 22))
        with self.assertRaises(ValueError):
            q.set_override("explode")

    def test_override_is_shared_with_the_watchdog(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, qh.STATE_FILE)
            q, c = self.make(at(12, 22), path)
            q.observe(False)
            q.set_override("unlock")
            q2, c2 = self.make(at(12, 23), path)
            self.assertIsNone(q2.observe(False, heartbeat=False))
            self.assertFalse(q2.locked())

    def test_configure_changes_window_and_grace(self):
        q, c = self.make(at(12, 22))
        q.observe(False)
        q.configure(qh.parse_window("23:00-06:00"), 60)
        self.assertEqual(q.status()["phase"], "open")
        c.t = at(12, 23, 1)
        self.assertEqual(q.observe(False), "locked")
        q.configure(None, 60)
        self.assertEqual(q.observe(False), "unlocked")


class Settings(unittest.TestCase):
    def test_env_default_then_admin_settings(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = qh.settings(d, "22:00-07:00")
            self.assertEqual((cfg["window"], cfg["grace"], cfg["source"]), ((22 * 60, 7 * 60), qh.GRACE, "env"))
            qh.save_settings(d, qh.parse_window("20:30-06:15"), 600, {"id": "U1", "name": "Ada"}, now=5)
            cfg = qh.settings(d, "22:00-07:00")
            self.assertEqual((cfg["window"], cfg["grace"], cfg["source"], cfg["updated_by"]["name"], cfg["updated_at"]),
                             ((20 * 60 + 30, 6 * 60 + 15), 600, "admin", "Ada", 5))
            qh.save_settings(d, None, 600, times=qh.parse_window("20:30-06:15"))
            cfg = qh.settings(d, "22:00-07:00")
            self.assertEqual((cfg["window"], cfg["times"]), (None, (20 * 60 + 30, 6 * 60 + 15)))
            qh.reset_settings(d)
            qh.reset_settings(d)
            self.assertEqual(qh.settings(d, "22:00-07:00")["source"], "env")

    def test_bad_files_fall_back(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, qh.SETTINGS_FILE), "w") as f:
                json.dump({"window": "nonsense"}, f)
            with contextlib.redirect_stderr(io.StringIO()):
                cfg = qh.settings(d, "bad")
            self.assertEqual((cfg["window"], cfg["source"]), (qh.parse_window(qh.DEFAULT_WINDOW), "env"))

    def test_watchdog_cli_reads_admin_settings(self):
        with tempfile.TemporaryDirectory() as d:
            qh.save_settings(d, qh.parse_window("01:00-02:00"), 120)
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"MUSIC_API_DATA_DIR": d, "QUIET_HOURS": "21:00-08:00"}), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(qh.main(["quiet_hours.py", "status"]), 0)
            st = json.loads(out.getvalue())
            self.assertEqual((st["window"], st["grace_s"]), ("01:00-02:00", 120))

    def test_receiver_allowed_follows_lock(self):
        with tempfile.TemporaryDirectory() as d:
            now = time.time()
            with open(os.path.join(d, qh.STATE_FILE), "w") as f:
                json.dump({"locked_until": now + 3600, "idle_since": now - 600, "heartbeat": now}, f)
            minute = datetime.datetime.fromtimestamp(now)
            start = (minute.hour * 60 + minute.minute - 10) % 1440
            qh.save_settings(d, (start, (start + 120) % 1440), 300)
            with mock.patch.dict(os.environ, {"MUSIC_API_DATA_DIR": d}):
                self.assertEqual(qh.main(["quiet_hours.py", "receiver-allowed"]), 1)
                qh.save_settings(d, None, 300)
                self.assertEqual(qh.main(["quiet_hours.py", "receiver-allowed"]), 0)



class EnforceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cmds = []
        patches = [mock.patch.object(qh.sys, "platform", "linux"),
                   mock.patch.object(qh, "_sinks", lambda: [["1", "a"], ["2", "b"]]),
                   mock.patch.object(qh, "_muted", lambda name: name == "b"),
                   mock.patch.object(qh, "_run", lambda *cmd: self.cmds.append(cmd)),
                   mock.patch.object(qh, "receiver", lambda action: self.cmds.append(("receiver", action)))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def mutes(self):
        out = [(c[2], c[3]) for c in self.cmds if c[:2] == ("pactl", "set-sink-mute")]
        self.cmds.clear()
        return out

    def test_effects_open_the_lock_mute_until_they_end_or_expire(self):
        d = self.tmp.name
        qh.enforce(True, d, now=100)
        self.assertEqual(self.mutes(), [("a", "1"), ("b", "1")])
        qh.open_for_effects(110, d, now=100)
        self.assertEqual(self.mutes(), [("a", "0")])
        qh.enforce(True, d, now=105)
        self.assertEqual((self.mutes(), self.cmds), ([], []))
        qh.open_for_effects(0, d, now=106)
        self.assertEqual(self.mutes(), [("a", "1"), ("b", "1")])
        qh.open_for_effects(120, d, now=110)
        self.mutes()
        qh.enforce(True, d, now=121)
        self.assertEqual(self.mutes(), [("a", "1"), ("b", "1")])
        qh.enforce(False, d)
        self.assertEqual(self.mutes(), [("a", "0"), ("b", "1")])
        qh.open_for_effects(200, d, now=100)
        qh.open_for_effects(0, d, now=100)
        self.assertEqual(self.mutes(), [])


if __name__ == "__main__":
    unittest.main()
