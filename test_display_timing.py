import io
import os
import random
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "display"))

from PIL import Image, ImageChops

import now_playing_display as npd


def legacy_pack(img):
    lut = {
        "r": [v & 0xF8 for v in range(256)],
        "g_hi": [v >> 5 for v in range(256)],
        "g_lo": [((v >> 2) & 7) << 5 for v in range(256)],
        "b": [v >> 3 for v in range(256)],
    }
    r, g, b = img.split()
    hi = ImageChops.add(r.point(lut["r"]), g.point(lut["g_hi"]))
    lo = ImageChops.add(g.point(lut["g_lo"]), b.point(lut["b"]))
    return Image.merge("LA", (lo, hi)).tobytes()


def noise(w, h, seed):
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(w * h)])
    return img


class Pack(unittest.TestCase):
    def test_small_image_matches_legacy(self):
        img = noise(37, 23, 1)
        self.assertEqual(npd.pack(img, 16), legacy_pack(img))

    def test_parallel_path_matches_legacy(self):
        img = noise(700, 301, 2)
        self.assertGreaterEqual(img.width * img.height, npd.PACK_PARALLEL_MIN)
        self.assertEqual(npd.pack(img, 16), legacy_pack(img))

    def test_known_pixels(self):
        img = Image.new("RGB", (2, 1))
        img.putpixel((0, 0), (255, 0, 0))
        img.putpixel((1, 0), (0, 255, 255))
        self.assertEqual(npd.pack(img, 16), bytes([0x00, 0xF8, 0xFF, 0x07]))

    def test_32bpp(self):
        img = Image.new("RGB", (1, 1), (1, 2, 3))
        self.assertEqual(npd.pack(img, 32), bytes([3, 2, 1, 0]))

    def test_dither_tiles(self):
        w, h = 20, 12
        ref = Image.new("RGB", (w, h))
        tile = Image.new("RGB", (4, 4))
        tile.putdata([(v // 2, v // 4, v // 2) for v in npd._BAYER])
        for y in range(0, h, 4):
            for x in range(0, w, 4):
                ref.paste(tile, (x, y))
        self.assertEqual(npd.dither(w, h).tobytes(), ref.tobytes())


class Ticks(unittest.TestCase):
    def test_interpolates_while_playing(self):
        p = npd.Playhead()
        p.sync(10_000, 100.0, True, 200_000)
        self.assertAlmostEqual(p.position(102.5), 12_500)

    def test_holds_while_paused(self):
        p = npd.Playhead()
        p.sync(10_000, 100.0, False, 200_000)
        self.assertEqual(p.position(150.0), 10_000)
        self.assertIsNone(p.until_next_second(150.0))

    def test_clamps_to_duration(self):
        p = npd.Playhead()
        p.sync(9_500, 0.0, True, 10_000)
        self.assertEqual(p.position(30.0), 10_000)
        self.assertIsNone(p.until_next_second(30.0))

    def test_wakes_just_after_the_boundary(self):
        p = npd.Playhead()
        p.sync(12_250, 50.0, True, 200_000)
        wait = p.until_next_second(50.0)
        self.assertAlmostEqual(wait, 0.755, places=3)
        self.assertEqual(p.second(50.0), 12)
        self.assertEqual(p.second(50.0 + wait), 13)

    def test_wakes_a_whole_second_later_on_the_boundary(self):
        p = npd.Playhead()
        p.sync(5_000, 0.0, True, 200_000)
        wait = p.until_next_second(0.0)
        self.assertGreater(wait, 1.0)
        self.assertEqual(p.second(wait), 6)

    def test_second_counter_advances_once_per_second(self):
        p = npd.Playhead()
        rnd = random.Random(3)
        p.sync(0, 0.0, True, 600_000)
        now, shown, seen = 0.0, p.second(0.0), [0]
        while now < 120:
            now += p.until_next_second(now)
            if int(now) % 7 == 0:
                p.sync(p.position(now) + rnd.uniform(-100, 100), now, True, 600_000)
            sec = p.second(now)
            if sec != shown:
                seen.append(sec)
                shown = sec
        self.assertEqual(seen, list(range(len(seen))))
        self.assertGreaterEqual(len(seen), 119)

    def test_small_drift_is_ignored_large_drift_resyncs(self):
        p = npd.Playhead()
        p.sync(1_000, 0.0, True, 200_000)
        p.sync(2_100, 1.0, True, 200_000)
        self.assertAlmostEqual(p.position(1.0), 2_000)
        p.sync(9_000, 1.0, True, 200_000)
        self.assertAlmostEqual(p.position(1.0), 9_000)

    def test_force_and_state_change_resync(self):
        p = npd.Playhead()
        p.sync(1_000, 0.0, True, 200_000)
        p.sync(1_050, 0.0, True, 200_000, force=True)
        self.assertEqual(p.position(0.0), 1_050)
        p.sync(1_050, 0.0, False, 200_000)
        self.assertFalse(p.running)


class Art(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = npd.CACHE_DIR
        npd.CACHE_DIR = self.tmp.name
        self.addCleanup(setattr, npd, "CACHE_DIR", old)
        self.art = npd.Artwork()
        self.gate = threading.Event()
        buf = io.BytesIO()
        Image.new("RGB", (80, 60), (200, 10, 10)).save(buf, "PNG")
        self.png = buf.getvalue()
        self.calls = []

        def fetch(url):
            self.calls.append(url)
            self.gate.wait(5)
            return self.png
        self.art.fetch = fetch
        self.done = []
        self.art.notify = self.done.append

    def test_slow_art_returns_none_then_notifies(self):
        self.assertIsNone(self.art.get("http://x/a.png", 32, 32, time.monotonic() + 0.05))
        self.gate.set()
        deadline = time.monotonic() + 3
        while not self.done and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.done, ["http://x/a.png"])
        tile = self.art.get("http://x/a.png", 32, 32, time.monotonic())
        self.assertEqual(tile.size, (32, 32))
        self.assertEqual(self.art.mini("http://x/a.png", 32).size, (64, 64))

    def test_concurrent_requests_share_one_fetch(self):
        self.gate.set()
        for _ in range(3):
            self.art.get("http://x/b.png", 32, 32)
        self.assertEqual(len(self.calls), 1)

    def test_failure_backs_off(self):
        def boom(url):
            self.calls.append(url)
            raise OSError("down")
        self.art.fetch = boom
        self.assertIsNone(self.art.get("http://x/c.png", 32, 32))
        self.assertIsNone(self.art.get("http://x/c.png", 32, 32))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.art.failing("http://x/c.png", 32))


if __name__ == "__main__":
    unittest.main()
