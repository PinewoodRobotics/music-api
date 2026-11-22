import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "display"))

import now_playing_display as npd


class Gate(unittest.TestCase):
    def setUp(self):
        self.b = npd.Blanker(delay=30, now=0.0)

    def test_blanks_after_30s_idle(self):
        self.assertIsNone(self.b.update(False, 29.9))
        self.assertEqual(self.b.update(False, 30.0), "blank")
        self.assertTrue(self.b.blanked)
        self.assertIsNone(self.b.update(False, 60))

    def test_wakes_when_playing(self):
        self.b.update(False, 31)
        self.assertEqual(self.b.update(True, 40), "wake")
        self.assertFalse(self.b.blanked)
        self.assertIsNone(self.b.update(True, 41))

    def test_quick_pause_resume_never_blanks(self):
        self.b.update(True, 0)
        self.assertIsNone(self.b.update(False, 10))
        self.assertIsNone(self.b.update(True, 25))
        self.assertIsNone(self.b.update(False, 26))
        self.assertIsNone(self.b.update(False, 55))
        self.assertEqual(self.b.update(False, 56), "blank")

    def test_timer_restarts_after_playing(self):
        self.b.update(False, 20)
        self.b.update(True, 25)
        self.assertIsNone(self.b.update(False, 26))
        self.assertIsNone(self.b.update(False, 55))
        self.assertEqual(self.b.update(False, 56), "blank")

    def test_remaining(self):
        self.assertEqual(self.b.remaining(10), 20)
        self.b.update(True, 10)
        self.assertIsNone(self.b.remaining(11))
        self.b.update(False, 12)
        self.assertEqual(self.b.remaining(20), 22)
        self.b.update(False, 42)
        self.assertIsNone(self.b.remaining(43))

    def test_is_playing(self):
        self.assertTrue(npd.is_playing({"state": "playing"}))
        self.assertTrue(npd.is_playing({"state": "playing", "source": "airplay"}))
        self.assertTrue(npd.is_playing({"state": "buffering"}))
        for st in (None, {}, {"state": "paused"}, {"state": "idle"},
                   {"state": "paused", "quiet_hours": {"phase": "locked"}}):
            self.assertFalse(npd.is_playing(st))


class FakeFb:
    size = (64, 36)

    def __init__(self):
        self.calls = []

    def black(self):
        self.calls.append("black")

    def power(self, on):
        self.calls.append("on" if on else "off")

    def refresh(self):
        return False


class DisplayFlow(unittest.TestCase):
    def test_blank_then_wake_redraws(self):
        fb = FakeFb()
        d = npd.Display(None, fb)
        d.render = lambda: fb.calls.append("render")
        d.status = {"state": "paused"}
        d.apply_blank(d.blanker.update(False, d.blanker.since + 31))
        self.assertEqual(fb.calls, ["black", "off"])
        d.status = {"state": "playing"}
        d.apply_blank(d.blanker.update(True, 100))
        self.assertEqual(fb.calls, ["black", "off", "render", "on"])


class MissingNames(unittest.TestCase):
    def test_track_renders_with_none_fields(self):
        st = {"state": "playing", "track": {"name": None, "artists": [{"name": None}, {"name": "C418"}],
                                            "album": {"name": None}, "artwork": None}}
        ups = [{"item": {"name": None, "artists": [{"name": None}], "artwork": None}}]
        img, box = npd.Scene(640, 360).track(st, ups, False)
        self.assertEqual(img.size, (640, 360))



if __name__ == "__main__":
    unittest.main()
