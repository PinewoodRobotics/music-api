import contextlib
import http.server
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer

import effects as fx
import server
from accounts import PersonalTokens, Sessions
from effects import Effects, EffectsError
from guard import Guard
from player import Player, PlayerError
from quiet_hours import QuietHours, parse_window
from tokens import Tokens


def beep(seconds=0.1, rate=48000, channels=2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * channels * int(rate * seconds))
    return buf.getvalue()


class FakeProc:
    def __init__(self, cmd, **kw):
        self.cmd, self.pid, self.returncode = cmd, 4000 + len(cmd), None
        self.done = threading.Event()
        self.terminated = False

    def communicate(self):
        self.done.wait(5)
        return b"", b""

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.done.set()

    def finish(self):
        self.returncode = 0
        self.done.set()


class Rig:
    def __init__(self, d, ffmpeg=False, slider=None, on_quiet=None):
        self.procs = []
        self.slider = 100
        self.volumes = {}
        self.inputs = [
            {"index": 7, "properties": {"application.name": "Spotify Soloist", "application.process.id": "10"},
             "volume": {"front-left": {"value": 65536}, "front-right": {"value": 65536}}},
            {"index": 8, "properties": {"application.name": "pw-play", "application.process.id": "99"},
             "volume": {"front-left": {"value": 65536}}}]
        self.fx = Effects(d, popen=self.popen, ffmpeg=ffmpeg, build_cmd=lambda path, vol: ["play", f"{vol:.2f}", path],
                          sink_inputs=lambda: self.inputs, set_volume=lambda i, v: self.volumes.__setitem__(str(i), list(v)),
                          slider=slider or (lambda: self.slider), on_quiet=on_quiet)

    def popen(self, cmd, **kw):
        p = FakeProc(cmd)
        self.procs.append(p)
        return p

    def settle(self):
        for p in self.procs:
            p.finish()
        for _ in range(200):
            if not self.fx.active:
                return
            threading.Event().wait(0.01)


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rig = Rig(self.tmp.name)
        self.fx = self.rig.fx

    def tearDown(self):
        self.rig.settle()
        self.tmp.cleanup()

    def test_register_list_get_update_delete(self):
        e = self.fx.register("Match Start", beep(0.25), title="Start", volume=70)
        self.assertEqual((e["name"], e["title"], e["volume"], e["duration_ms"], e["rate"]), ("match-start", "Start", 70, 250, 48000))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "effects", "match-start.wav")))
        self.assertEqual([x["name"] for x in self.fx.list()], ["match-start"])
        r = self.fx.update("match-start", {"name": "go", "volume": 50})
        self.assertEqual((r["name"], r["volume"]), ("go", 50))
        self.assertEqual(self.fx.get("go")["title"], "Start")
        with self.assertRaises(EffectsError) as cm:
            self.fx.get("match-start")
        self.assertEqual((cm.exception.status, cm.exception.code), (404, "unknown_effect"))
        self.assertEqual(self.fx.delete("go"), {"deleted": "go"})
        self.assertEqual(self.fx.list(), [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "effects", "go.wav")))

    def test_survives_restart(self):
        self.fx.register("buzzer", beep())
        again = Effects(self.tmp.name)
        self.assertEqual(again.get("buzzer")["duration_ms"], 100)

    def test_duplicates_and_overwrite(self):
        self.fx.register("a", beep(0.1))
        with self.assertRaises(EffectsError) as cm:
            self.fx.register("a", beep())
        self.assertEqual(cm.exception.code, "exists")
        self.assertEqual(self.fx.register("a", beep(0.3), overwrite=True)["duration_ms"], 300)
        self.fx.register("b", beep())
        with self.assertRaises(EffectsError):
            self.fx.update("b", {"name": "a"})

    def test_rejects_bad_input(self):
        for bad in ("", "../x", "stop", "playing", "x" * 60, "Has/Slash"):
            with self.assertRaises(EffectsError) as cm:
                self.fx.register(bad, beep())
            self.assertEqual(cm.exception.code, "bad_name", bad)
        with self.assertRaises(EffectsError) as cm:
            self.fx.register("x", b"definitely not audio")
        self.assertEqual(cm.exception.status, 415)
        with self.assertRaises(EffectsError) as cm:
            self.fx.register("x", b"ID3" + b"\0" * 40)
        self.assertEqual(cm.exception.code, "ffmpeg_missing")
        with self.assertRaises(ValueError):
            self.fx.register("x", beep(), volume=150)
        self.assertEqual(self.fx.list(), [])

    def test_too_long(self):
        with self.assertRaises(EffectsError) as cm:
            self.fx.register("long", beep(fx.MAX_SECONDS + 1, rate=8000, channels=1))
        self.assertEqual(cm.exception.status, 413)

    def test_sniff(self):
        self.assertEqual([fx.sniff(b) for b in (beep(), b"OggS...", b"fLaC...", b"ID3\x04", b"\xff\xfb\x90\x00", b"nope")],
                         ["wav", "ogg", "flac", "mp3", "mp3", None])

    def test_multipart(self):
        body = (b'--B\r\nContent-Disposition: form-data; name="name"\r\n\r\nhorn\r\n'
                b'--B\r\nContent-Disposition: form-data; name="file"; filename="h.wav"\r\n'
                b'Content-Type: audio/wav\r\n\r\n' + beep() + b'\r\n--B--\r\n')
        out = fx.parse_multipart("multipart/form-data; boundary=B", body)
        self.assertEqual((out["name"], out["audio"], out["filename"]), ("horn", beep(), "h.wav"))

    def test_url_must_be_public_http(self):
        for url in ("file:///etc/passwd", "ftp://example.com/a.wav", "http://127.0.0.1/a.wav", "http://localhost:8765/x",
                    "http://192.168.1.5/a.wav"):
            with self.assertRaises(EffectsError) as cm:
                self.fx.register_url("u", url)
            self.assertEqual(cm.exception.code, "bad_url", url)


class PlaybackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rig = Rig(self.tmp.name)
        self.fx = self.rig.fx
        self.fx.register("beep", beep(), volume=80)

    def tearDown(self):
        self.rig.settle()
        self.tmp.cleanup()

    def test_play_uses_default_and_override_volume(self):
        a = self.fx.play("beep")
        b = self.fx.play("beep", volume=25)
        self.assertEqual((a["volume"], b["volume"]), (80, 25))
        self.assertEqual([p.cmd[1] for p in self.rig.procs], ["0.80", "0.25"])
        self.assertTrue(self.rig.procs[0].cmd[2].endswith("effects/beep.wav"))

    def test_overlapping_plays_and_stop(self):
        for _ in range(3):
            self.fx.play("beep")
        self.assertEqual(len(self.fx.playing()), 3)
        self.assertEqual(self.fx.get("beep")["playing"], 3)
        self.assertEqual(self.fx.stop(), {"stopped": 3})
        self.assertTrue(all(p.terminated for p in self.rig.procs))
        self.rig.settle()
        self.assertEqual(self.fx.playing(), [])

    def test_stop_by_name_only_stops_that_effect(self):
        self.fx.register("other", beep())
        self.fx.play("beep")
        self.fx.play("other")
        self.assertEqual(self.fx.stop("beep"), {"stopped": 1})
        self.assertEqual([p.terminated for p in self.rig.procs], [True, False])

    def test_finished_plays_leave_the_list(self):
        self.fx.play("beep")
        self.rig.settle()
        self.assertEqual(self.fx.playing(), [])

    def test_unknown_and_too_many(self):
        with self.assertRaises(EffectsError) as cm:
            self.fx.play("nope")
        self.assertEqual(cm.exception.status, 404)
        for _ in range(fx.MAX_PLAYING):
            self.fx.play("beep")
        with self.assertRaises(EffectsError) as cm:
            self.fx.play("beep")
        self.assertEqual(cm.exception.status, 429)

    def test_missing_player_binary(self):
        def broken(cmd, **kw):
            raise FileNotFoundError("pw-play")
        self.fx.popen = broken
        with self.assertRaises(EffectsError) as cm:
            self.fx.play("beep")
        self.assertEqual(cm.exception.code, "play_failed")
        self.assertEqual(self.fx.playing(), [])

    def test_delete_stops_playing(self):
        self.fx.play("beep")
        self.fx.delete("beep")
        self.assertTrue(self.rig.procs[0].terminated)

    def test_duck_lowers_other_streams_and_restores_after_last_effect(self):
        a = self.fx.play("beep", duck=True, duck_level=40)
        self.assertEqual(self.rig.volumes, {"7": [26214, 26214]})
        self.assertTrue(os.path.exists(self.fx.duck_path))
        self.rig.volumes.clear()
        b = self.fx.play("beep", duck=True)
        self.assertEqual(self.rig.volumes, {})
        self.rig.procs[0].finish()
        self.wait_for(lambda: len(self.fx.active) == 1)
        self.assertEqual(self.rig.volumes, {})
        self.rig.procs[1].finish()
        self.wait_for(lambda: not self.fx.active)
        self.assertEqual(self.rig.volumes, {"7": [65536, 65536]})
        self.assertFalse(os.path.exists(self.fx.duck_path))

    def test_no_duck_leaves_streams_alone(self):
        self.fx.play("beep")
        self.assertEqual(self.rig.volumes, {})

    def test_restores_ducked_streams_after_a_crash(self):
        self.fx.play("beep", duck=True)
        self.assertTrue(os.path.exists(self.fx.duck_path))
        self.rig.volumes.clear()
        Effects(self.tmp.name, sink_inputs=lambda: self.rig.inputs,
                set_volume=lambda i, v: self.rig.volumes.__setitem__(str(i), list(v)))
        self.assertEqual(self.rig.volumes, {"7": [65536, 65536]})

    @staticmethod
    def wait_for(cond):
        for _ in range(300):
            if cond():
                return
            threading.Event().wait(0.01)
        raise AssertionError("timed out")


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class TranscodeTest(unittest.TestCase):
    def test_converts_to_pipewire_rate_stereo_wav(self):
        with tempfile.TemporaryDirectory() as d:
            e = Effects(d)
            src = os.path.join(d, "t.flac")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                            "-ar", "22050", "-ac", "1", src], check=True)
            with open(src, "rb") as f:
                info = e.register("tone", f.read())
            self.assertEqual((info["rate"], info["channels"]), (48000, 2))
            self.assertAlmostEqual(info["duration_ms"], 500, delta=60)
            with self.assertRaises(EffectsError) as cm:
                e.register("junk", b"OggS" + b"\0" * 100)
            self.assertEqual(cm.exception.code, "undecodable")


class NoWebApi:
    def __init__(self):
        self.calls = []
        self.auth = type("A", (), {"logged_in": True})()

    def req(self, *a, **kw):
        self.calls.append(a)
        raise AssertionError("the Web API must not be called")

    def get(self, *a, **kw):
        return self.req("GET", *a)


class FakeSoloist:
    def __init__(self, volume):
        self.playback = {"volume": volume} if volume is not None else None
        self.commands = []

    def command(self, name, **fields):
        self.commands.append((name, fields))
        if name == "set_volume":
            self.playback = {**(self.playback or {}), "volume": fields["volume"]}
        return {}


class SliderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rig = Rig(self.tmp.name)
        self.rig.fx.register("beep", beep(), volume=100)

    def tearDown(self):
        self.rig.settle()
        self.tmp.cleanup()

    def test_effect_volume_is_scaled_by_the_slider(self):
        self.rig.slider = 50
        a = self.rig.fx.play("beep")
        b = self.rig.fx.play("beep", volume=10)
        self.assertEqual((a["volume"], a["slider_volume"], a["effective_volume"]), (100, 50, 50))
        self.assertEqual((b["volume"], b["slider_volume"], b["effective_volume"]), (10, 50, 5))
        self.assertEqual([p.cmd[1] for p in self.rig.procs], ["0.50", "0.05"])
        self.assertEqual({(p["volume"], p["effective_volume"]) for p in self.rig.fx.playing()}, {(100, 50), (10, 5)})

    def test_slider_change_applies_to_the_next_play(self):
        self.rig.slider = 40
        self.rig.fx.play("beep")
        self.rig.slider = 80
        self.assertEqual(self.rig.fx.play("beep", volume=50)["effective_volume"], 40)
        self.assertEqual([p.cmd[1] for p in self.rig.procs], ["0.40", "0.40"])

    def test_unknown_live_slider_uses_the_last_one_seen(self):
        self.rig.slider = 30
        self.rig.fx.play("beep")
        self.rig.slider = None
        self.assertEqual(self.rig.fx.play("beep")["slider_volume"], 30)
        self.rig.fx.note_slider(60)
        self.assertEqual(self.rig.fx.play("beep")["effective_volume"], 60)

    def test_persisted_slider_survives_restart_and_default_is_50(self):
        self.assertEqual(Effects(tempfile.mkdtemp(dir=self.tmp.name)).slider_volume, fx.DEFAULT_SLIDER)
        self.rig.fx.note_slider(35)
        again = Rig(self.tmp.name, slider=lambda: None)
        self.assertEqual(again.fx.play("beep")["effective_volume"], 35)
        again.settle()

    def test_broken_slider_source_still_plays(self):
        def boom():
            raise RuntimeError("down")
        self.rig.fx.note_slider(45)
        rig = Rig(self.tmp.name, slider=boom)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(rig.fx.play("beep")["slider_volume"], 45)
        rig.settle()

    def test_follow_mode_is_the_default_and_reports_media(self):
        self.rig.slider = 60
        r = self.rig.fx.play("beep", volume=50)
        self.assertEqual((r["slider_volume"], r["volume_source"], r["effective_volume"]), (60, "media", 30))
        self.assertEqual(self.rig.fx.playing()[0]["volume_source"], "media")
        cfg = self.rig.fx.volume_settings()
        self.assertEqual((cfg["mode"], cfg["level"], cfg["media_volume"]), ("follow", 60, 60))

    def test_fixed_mode_ignores_the_slider_and_applies_to_the_next_play(self):
        self.rig.slider = 80
        self.rig.fx.set_volume_settings("fixed", 20, {"id": "U1", "name": "Ada"})
        r = self.rig.fx.play("beep", volume=50)
        self.assertEqual((r["slider_volume"], r["volume_source"], r["effective_volume"]), (20, "fixed", 10))
        self.rig.slider = 10
        self.assertEqual(self.rig.fx.play("beep")["effective_volume"], 20)
        self.rig.fx.set_volume_settings(level=40)
        self.assertEqual(self.rig.fx.play("beep", volume=50)["effective_volume"], 20)
        self.rig.fx.set_volume_settings("follow")
        r = self.rig.fx.play("beep", volume=50)
        self.assertEqual((r["slider_volume"], r["volume_source"], r["effective_volume"]), (10, "media", 5))
        self.assertEqual([p.cmd[1] for p in self.rig.procs], ["0.10", "0.20", "0.20", "0.05"])
        cfg = self.rig.fx.volume_settings()
        self.assertEqual((cfg["mode"], cfg["level"], cfg["media_volume"], cfg["updated_by"]), ("follow", 40, 10, None))

    def test_fixed_without_a_level_starts_at_the_slider(self):
        self.rig.slider = 35
        self.assertEqual(self.rig.fx.set_volume_settings("fixed")["level"], 35)
        self.rig.slider = 90
        self.assertEqual(self.rig.fx.play("beep")["effective_volume"], 35)

    def test_volume_settings_validation(self):
        for kw in ({"mode": "loud"}, {"level": 101}, {"level": -1}, {"level": "x"}):
            with self.assertRaises(ValueError):
                self.rig.fx.set_volume_settings(**kw)
        self.assertEqual(self.rig.fx.volume_settings()["mode"], "follow")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "effects", "volume.json")))

    def test_volume_settings_survive_restart(self):
        self.rig.fx.set_volume_settings("fixed", 25, {"id": "U1", "name": "Ada"})
        again = Rig(self.tmp.name)
        again.slider = 100
        cfg = again.fx.volume_settings()
        self.assertEqual((cfg["mode"], cfg["level"], cfg["updated_by"]["name"]), ("fixed", 25, "Ada"))
        self.assertEqual(again.fx.play("beep")["effective_volume"], 25)
        again.settle()
        with open(os.path.join(self.tmp.name, "effects", "volume.json"), "w") as f:
            f.write('{"mode": "bogus", "level": 500}')
        cfg = Rig(self.tmp.name).fx.volume_settings()
        self.assertEqual((cfg["mode"], cfg["level"]), ("follow", 100))

    def test_play_during_quiet_hours_defaults_on_validates_and_persists(self):
        self.assertTrue(self.rig.fx.volume_settings()["play_during_quiet_hours"])
        self.assertTrue(self.rig.fx.plays_during_quiet_hours())
        for bad in ("maybe", 2):
            with self.assertRaises(ValueError):
                self.rig.fx.set_volume_settings(play_during_quiet_hours=bad)
        cfg = self.rig.fx.set_volume_settings(play_during_quiet_hours=False, by={"id": "U1", "name": "Ada"})
        self.assertEqual((cfg["play_during_quiet_hours"], cfg["mode"]), (False, "follow"))
        self.assertFalse(Rig(self.tmp.name).fx.plays_during_quiet_hours())
        self.rig.fx.set_volume_settings("fixed", 30)
        self.assertFalse(Rig(self.tmp.name).fx.volume_settings()["play_during_quiet_hours"])
        self.assertTrue(self.rig.fx.set_volume_settings(play_during_quiet_hours="true")["play_during_quiet_hours"])
        with open(os.path.join(self.tmp.name, "effects", "volume.json"), "w") as f:
            f.write('{"mode": "fixed", "level": 30}')
        self.assertTrue(Rig(self.tmp.name).fx.plays_during_quiet_hours())

    def test_quiet_plays_keep_the_outputs_open_until_the_last_one_ends(self):
        opened = []
        rig = Rig(self.tmp.name, on_quiet=opened.append)
        rig.fx.register("long", beep(1.0))
        rig.fx.play("beep")
        self.assertEqual(opened, [])
        a = rig.fx.play("beep", quiet=True)
        b = rig.fx.play("long", quiet=True)
        self.assertEqual((a["quiet_hours"], b["quiet_hours"]), (True, True))
        self.assertEqual(len(opened), 2)
        self.assertAlmostEqual(opened[0] - a["started_at"], 0.1 + fx.QUIET_MARGIN, delta=0.5)
        self.assertAlmostEqual(opened[1] - b["started_at"], 1.0 + fx.QUIET_MARGIN, delta=0.5)
        rig.procs[1].finish()
        for _ in range(200):
            if len(rig.fx.active) == 2:
                break
            threading.Event().wait(0.01)
        self.assertEqual(len(opened), 2)
        rig.settle()
        self.assertEqual(opened[2:], [0])
        with self.assertRaises(EffectsError):
            rig.fx.play("nope", quiet=True)
        self.assertEqual(len(opened), 3)
        with self.assertRaises(ValueError):
            rig.fx.play("beep", volume=500, quiet=True)
        self.assertEqual((len(opened), opened[-1], rig.fx.quiet_plays), (5, 0, 0))

    def test_soloist_play_path_reads_local_volume_without_the_web_api(self):
        api, sol = NoWebApi(), FakeSoloist(40)
        player = Player("soloist", api, sol)
        rig = Rig(self.tmp.name, slider=player.local_volume)
        player.volume_fn = rig.fx.note_slider
        self.assertEqual(rig.fx.play("beep")["effective_volume"], 40)
        sol.playback["volume"] = 70
        self.assertEqual(rig.fx.play("beep")["effective_volume"], 70)
        sol.playback = None
        self.assertEqual(rig.fx.play("beep")["slider_volume"], 70)
        self.assertEqual(api.calls, [])
        rig.settle()

    def test_connect_play_path_uses_the_last_volume_set_or_seen(self):
        api = NoWebApi()
        player = Player("connect", api)
        rig = Rig(self.tmp.name, slider=player.local_volume)
        player.volume_fn = rig.fx.note_slider
        player._cache = (player.clock(), {"volume": 55, "state": "paused", "track": None})
        player.spotify_status()
        self.assertEqual(rig.fx.play("beep")["effective_volume"], 55)
        self.assertEqual(api.calls, [])
        rig.settle()

    def test_player_volume_set_updates_the_slider(self):
        player = Player("soloist", NoWebApi(), FakeSoloist(20))
        seen = []
        player.volume_fn = seen.append
        player.status = lambda fresh=False: {}
        player.volume({"volume": 65})
        self.assertEqual(seen, [65])


class RoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        server.tokens, server.sessions, server.personal = Tokens(d), Sessions(d), PersonalTokens(d)
        cls.rig = Rig(d)
        server.effects = cls.rig.fx
        cls.now = [0]
        cls.quiet = QuietHours(parse_window("21:00-08:00"), clock=lambda: cls.now[0])
        server.guard = Guard(type("P", (), {})(), cls.quiet)
        cls.quiet_logs = contextlib.redirect_stderr(io.StringIO())
        cls.quiet_logs.__enter__()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.rig.settle()
        cls.srv.shutdown()
        cls.quiet_logs.__exit__(None, None, None)
        cls.tmp.cleanup()

    def setUp(self):
        import datetime
        self.now[0] = datetime.datetime(2026, 10, 13, 12).timestamp()
        self.quiet.locked_until = None

    def call(self, method, path, body=None, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_address[1]}{path}", data=data, method=method,
                                     headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_raw_upload_play_and_delete(self):
        code, res = self.call("POST", "/api/effects?name=Raw&volume=60", beep(), "audio/wav")
        self.assertEqual((code, res["result"]["name"], res["result"]["volume"]), (200, "raw", 60))
        self.assertEqual(self.call("POST", "/api/effects?name=raw", beep(), "audio/wav")[0], 409)
        self.assertEqual(self.call("POST", "/api/effects?name=raw&overwrite=true", beep(), "audio/wav")[0], 200)
        self.rig.slider = 50
        code, res = self.call("POST", "/api/effects/raw/play", {"volume": 30})
        self.assertEqual((code, res["result"]["volume"], res["result"]["name"]), (200, 30, "raw"))
        self.assertEqual((res["result"]["slider_volume"], res["result"]["effective_volume"]), (50, 15))
        playing = self.call("GET", "/api/effects/playing")[1]["result"][0]
        self.assertEqual((playing["name"], playing["effective_volume"]), ("raw", 15))
        self.rig.slider = 100
        self.assertEqual(self.call("POST", "/api/effects/stop", {})[1]["result"], {"stopped": 1})
        self.rig.settle()
        self.assertEqual(self.call("GET", "/api/effects/raw")[1]["result"]["name"], "raw")
        self.assertEqual(self.call("PATCH", "/api/effects/raw", {"name": "renamed", "title": "T"})[1]["result"]["title"], "T")
        self.assertEqual(self.call("DELETE", "/api/effects/renamed")[1]["result"], {"deleted": "renamed"})
        self.assertEqual(self.call("GET", "/api/effects/renamed")[0], 404)

    def test_multipart_and_json_url_upload(self):
        body = (b'--B\r\nContent-Disposition: form-data; name="name"\r\n\r\nhorn\r\n'
                b'--B\r\nContent-Disposition: form-data; name="file"; filename="h.wav"\r\n'
                b'Content-Type: audio/wav\r\n\r\n' + beep() + b'\r\n--B--\r\n')
        code, res = self.call("POST", "/api/effects", body, "multipart/form-data; boundary=B")
        self.assertEqual((code, res["result"]["name"]), (200, "horn"))

        class Serve(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(beep())

            def log_message(self, *a):
                pass
        site = ThreadingHTTPServer(("127.0.0.1", 0), Serve)
        threading.Thread(target=site.serve_forever, daemon=True).start()
        real = fx._public_host
        fx._public_host = lambda host: None
        try:
            code, res = self.call("POST", "/api/effects", {"name": "fetched", "url": f"http://127.0.0.1:{site.server_address[1]}/a.wav"})
        finally:
            fx._public_host = real
            site.shutdown()
        self.assertEqual((code, res["result"]["name"], res["result"]["source"].startswith("http://")), (200, "fetched", True))
        self.assertEqual(self.call("POST", "/api/effects", {"name": "private", "url": "http://10.0.0.1/a.wav"})[1]["error"], "bad_url")

    def test_errors(self):
        self.assertEqual(self.call("POST", "/api/effects", {"name": "x"})[1]["error"], "no_audio")
        self.assertEqual(self.call("POST", "/api/effects?name=x", b"junk", "audio/wav")[0], 415)
        self.assertEqual(self.call("POST", "/api/effects/nope/play", {})[1]["error"], "unknown_effect")
        self.call("POST", "/api/effects?name=v", beep(), "audio/wav")
        self.assertEqual(self.call("POST", "/api/effects/v/play", {"volume": 500})[0], 400)
        self.call("DELETE", "/api/effects/v")

    def _lock(self):
        import datetime
        self.call("POST", "/api/effects?name=q", beep(), "audio/wav")
        self.now[0] = datetime.datetime(2026, 10, 13, 22).timestamp()
        self.assertEqual(self.call("POST", "/api/effects/q/play", {})[1]["result"]["quiet_hours"], False)
        self.quiet.locked_until = datetime.datetime(2026, 10, 14, 8).timestamp()
        self.quiet.idle_since = self.now[0] - 600

    def _unlock(self):
        self.rig.fx.set_volume_settings(play_during_quiet_hours=True)
        self.rig.fx.on_quiet = lambda until: None
        self.assertEqual(self.call("POST", "/api/effects/stop", {})[0], 200)
        self.rig.settle()
        self.assertEqual(self.call("DELETE", "/api/effects/q")[0], 200)

    def test_quiet_hours_lock_lets_effects_through_by_default_but_not_music(self):
        self._lock()
        opened = []
        self.rig.fx.on_quiet = opened.append
        before = (self.quiet.status(), self.quiet.locked_until, self.quiet.idle_since)
        try:
            code, res = self.call("POST", "/api/effects/q/play", {"volume": 10})
            self.assertEqual((code, res["result"]["quiet_hours"]), (200, True))
            self.assertEqual(len(opened), 1)
            self.assertEqual((self.quiet.status(), self.quiet.locked_until, self.quiet.idle_since), before)
            for action in ("play", "next", "previous", "jump", "transfer_play"):
                with self.assertRaises(PlayerError) as e:
                    server.guard.check(action)
                self.assertEqual((e.exception.status, e.exception.code), (423, "quiet_hours"))
            self.rig.settle()
            self.assertEqual(opened[1:], [0])
            self.assertEqual((self.quiet.status(), self.quiet.locked_until, self.quiet.idle_since), before)
        finally:
            self._unlock()

    def test_quiet_hours_lock_refuses_effects_when_the_setting_is_off(self):
        self._lock()
        self.rig.fx.set_volume_settings(play_during_quiet_hours=False)
        opened = []
        self.rig.fx.on_quiet = opened.append
        try:
            code, res = self.call("POST", "/api/effects/q/play", {})
            self.assertEqual((code, res["error"], res["until"]), (423, "quiet_hours", "08:00"))
            self.assertEqual(opened, [])
            self.assertEqual(self.call("GET", "/api/effects")[0], 200)
        finally:
            self._unlock()

    def test_only_admins_manage_effects(self):
        server._req.user = {"id": "U1", "name": "Ada", "admin": False}
        server._req.bearer = True
        h = object.__new__(server.Handler)
        self.assertIsNone(h._forbidden("GET", "/api/effects"))
        self.assertIsNone(h._forbidden("POST", "/api/effects/x/play"))
        self.assertIsNone(h._forbidden("POST", "/api/effects/stop"))
        for method, path in (("POST", "/api/effects"), ("PATCH", "/api/effects/x"), ("DELETE", "/api/effects/x")):
            self.assertEqual(h._forbidden(method, path), "admins only", (method, path))


if __name__ == "__main__":
    unittest.main()
