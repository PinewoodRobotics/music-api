import base64
import contextlib
import datetime
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import airplay as ap
import quiet_hours as qh
import server
from accounts import Credits, PersonalTokens, Sessions
from activity import Activity
from guard import Guard
from player import Player, PlayerError
from tokens import Tokens

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + bytes(range(256)) * 12


def raw_item(kind, code, data=b""):
    head = f"<item><type>{kind.encode().hex()}</type><code>{code.encode().hex()}</code><length>{len(data)}</length>"
    if not data:
        return (head + "</item>\n").encode()
    return (head + '\n<data encoding="base64">\n' + base64.b64encode(data).decode() + "</data></item>\n").encode()


SESSION = b"".join([
    raw_item("ssnc", "abeg"),
    raw_item("ssnc", "snam", b"Adam's iPhone"),
    raw_item("ssnc", "pbeg"),
    raw_item("ssnc", "mdst", b"1234"),
    raw_item("core", "minm", "Clair de Lune".encode()),
    raw_item("core", "asar", "Claude Debussy".encode()),
    raw_item("core", "asal", "Suite bergamasque".encode()),
    raw_item("ssnc", "mden", b"1234"),
    raw_item("ssnc", "pcst", b"1234"),
    raw_item("ssnc", "PICT", JPEG),
    raw_item("ssnc", "pcen", b"1234"),
    raw_item("ssnc", "prgr", b"1000000/1441000/14230000"),
])


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class ParserTest(unittest.TestCase):
    def test_items_split_anywhere(self):
        for size in (1, 7, 100, 4096, len(SESSION)):
            p, items = ap.Parser(), []
            for i in range(0, len(SESSION), size):
                items += p.feed(SESSION[i:i + size])
            self.assertEqual([c for _, c, _ in items],
                             ["abeg", "snam", "pbeg", "mdst", "minm", "asar", "asal", "mden", "pcst", "PICT", "pcen", "prgr"])
            self.assertEqual(dict((c, d) for _, c, d in items)["PICT"], JPEG)
            self.assertEqual(items[4], ("core", "minm", b"Clair de Lune"))

    def test_garbage_and_truncated_items_are_skipped(self):
        p = ap.Parser()
        junk = b"noise<item><type>73736e63</type><code>50494354</code><length>9</length>\n<data encoding=\"base64\">\nAAA"
        out = p.feed(junk + raw_item("ssnc", "pend"))
        self.assertEqual([c for _, c, _ in out], ["pend"])
        self.assertEqual(p.feed(b"<item><type>zz"), [])


class StateTest(unittest.TestCase):
    def make(self):
        c = Clock()
        a = ap.AirPlay("/nonexistent", clock=c)
        events = []
        a.on_start, a.on_end = lambda: events.append("start"), lambda: events.append("end")
        return a, c, events

    def feed(self, a, data):
        for item in ap.Parser().feed(data):
            a.handle(*item)

    def test_session_snapshot(self):
        a, c, events = self.make()
        self.assertIsNone(a.snapshot())
        self.feed(a, SESSION)
        s = a.snapshot()
        self.assertEqual(events, ["start"])
        self.assertEqual((s["state"], s["sender"]), ("playing", "Adam's iPhone"))
        self.assertEqual(s["track"]["name"], "Clair de Lune")
        self.assertEqual(s["track"]["artists"], [{"uri": None, "name": "Claude Debussy"}])
        self.assertEqual(s["track"]["album"]["name"], "Suite bergamasque")
        self.assertEqual(s["track"]["type"], "airplay")
        self.assertTrue(s["track"]["artwork"].startswith("/api/airplay/artwork?v="))
        self.assertEqual(s["duration_ms"], round(13230000 * 1000 / 44100))
        self.assertEqual(s["position_ms"], 10000)
        self.assertEqual(a.artwork(), (JPEG, "image/jpeg"))
        c.t += 2.5
        self.assertEqual(a.snapshot()["position_ms"], 12500)

    def test_pause_freezes_position_and_resume(self):
        a, c, _ = self.make()
        self.feed(a, SESSION)
        c.t += 1
        self.feed(a, raw_item("ssnc", "paus"))
        c.t += 30
        s = a.snapshot()
        self.assertEqual((s["state"], s["position_ms"]), ("paused", 11000))
        self.feed(a, raw_item("ssnc", "pres"))
        c.t += 1
        self.assertEqual(a.snapshot()["position_ms"], 12000)

    def test_heartbeat_moves_position(self):
        a, c, _ = self.make()
        self.feed(a, SESSION)
        self.feed(a, raw_item("ssnc", "phbt", b"%d/123456789" % (1000000 + 44100 * 60)))
        self.assertEqual(a.snapshot()["position_ms"], 60000)

    def test_new_title_drops_old_art(self):
        a, _, _ = self.make()
        self.feed(a, SESSION)
        self.feed(a, raw_item("core", "minm", b"Reverie"))
        self.assertIsNone(a.snapshot()["track"]["artwork"])

    def test_aend_ends_session(self):
        a, _, events = self.make()
        self.feed(a, SESSION + raw_item("ssnc", "pend") + raw_item("ssnc", "aend"))
        self.assertEqual(events, ["start", "end"])
        self.assertIsNone(a.snapshot())
        self.assertIsNone(a.artwork())

    def test_pend_without_aend_times_out(self):
        a, c, events = self.make()
        self.feed(a, SESSION + raw_item("ssnc", "pend"))
        a.tick()
        self.assertEqual(events, ["start"])
        c.t += ap.END_AFTER_PEND
        a.tick()
        self.assertEqual(events, ["start", "end"])

    def test_heartbeat_picks_up_a_session_already_playing(self):
        a, c, events = self.make()
        self.feed(a, raw_item("ssnc", "phbt", b"1/2"))
        self.assertEqual((events, a.snapshot()["state"]), (["start"], "playing"))
        a.end_session()
        self.feed(a, raw_item("ssnc", "phbt", b"1/2"))
        self.assertIsNone(a.snapshot())
        c.t += 6
        self.feed(a, raw_item("ssnc", "phbt", b"1/2"))
        self.assertEqual(events, ["start", "end", "start"])


class RemoteTest(unittest.TestCase):
    def runner(self, available="b true\n", code=0):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            out = available if "get-property" in cmd else ""
            return type("R", (), {"returncode": code, "stdout": out, "stderr": "boom"})()
        return calls, run

    def test_calls_the_remote_control_method(self):
        calls, run = self.runner()
        ap.remote("next", run)
        self.assertEqual(calls[-1][1:3], ["--user", "--timeout=3"])
        self.assertEqual(calls[-1][3:], ["call", ap.BUS_NAME, ap.BUS_PATH, ap.BUS_INTERFACE, "Next"])

    def test_sender_without_remote_control(self):
        calls, run = self.runner("b false\n")
        with self.assertRaises(ap.RemoteError) as e:
            ap.remote("pause", run)
        self.assertEqual((e.exception.status, e.exception.code), (409, "airplay_remote_unavailable"))
        self.assertEqual(len(calls), 1)

    def test_bus_unreachable_and_busctl_missing(self):
        _, run = self.runner(code=1)
        with self.assertRaises(ap.RemoteError) as e:
            ap.remote("play", run)
        self.assertEqual(e.exception.status, 503)

        def missing(*a, **kw):
            raise FileNotFoundError
        with self.assertRaises(ap.RemoteError) as e:
            ap.remote("play", missing)
        self.assertEqual(e.exception.code, "airplay_remote_unavailable")


class FakeSoloist:
    def __init__(self, status="playing"):
        self.playback = {"status": status, "position_ms": 42000, "options": {},
                         "item": {"uri": "spotify:track:1", "entity_type": "track",
                                  "decorations": {"identity": {"name": "Song"}}}}
        self.connected = True
        self.auth = {"logged_in": True, "is_active": True, "device_name": "dev"}
        self.last_error = None
        self.queue = {"upcoming": [], "previous": []}
        self.calls = []

    def command(self, name, **fields):
        self.calls.append(name)
        if name == "play":
            self.playback["status"] = "playing"
        elif name == "pause":
            self.playback["status"] = "paused"
        elif name == "get_queue":
            return {"upcoming": [], "previous": []}
        return {}

    def position_ms(self):
        return self.playback["position_ms"]


def night(h, m=0):
    day = 12 if h >= 12 else 13
    return datetime.datetime(2026, 10, day, h, m).timestamp()


class Rig:
    def __init__(self, status="playing", t=None):
        self.clock = Clock(t or night(19))
        self.sol = FakeSoloist(status)
        self.player = Player("soloist", None, self.sol)
        self.quiet = qh.QuietHours(qh.parse_window("21:00-08:00"), clock=self.clock)
        self.air = ap.AirPlay("/nonexistent", clock=self.clock)
        self.enforced, self.receiver_calls, self.remote_calls, self.remote_error = [], [], [], None
        self.guard = Guard(self.player, self.quiet, self.air, enforce=self.enforced.append,
                           receiver=lambda action: self.receiver_calls.append(action) or True,
                           remote=self.remote, clock=self.clock)

    def remote(self, action):
        if self.remote_error:
            raise self.remote_error
        self.remote_calls.append(action)

    def start_airplay(self):
        for item in ap.Parser().feed(SESSION):
            self.air.handle(*item)

    def end_airplay(self):
        for item in ap.Parser().feed(raw_item("ssnc", "pend") + raw_item("ssnc", "aend")):
            self.air.handle(*item)


class LifecycleTest(unittest.TestCase):
    def test_session_pauses_spotify_and_resumes_after(self):
        r = Rig("playing")
        r.start_airplay()
        self.assertEqual(r.sol.calls, ["pause"])
        st = r.player.status()
        self.assertEqual((st["source"], st["state"], st["track"]["name"]), ("airplay", "playing", "Clair de Lune"))
        self.assertEqual(st["spotify"]["track"]["uri"], "spotify:track:1")
        self.assertEqual(st["airplay"]["sender"], "Adam's iPhone")
        self.assertTrue(st["airplay"]["resume_spotify"])
        r.end_airplay()
        self.assertEqual(r.sol.calls, ["pause", "play"])
        st = r.player.status()
        self.assertEqual((st["source"], st["state"], st["position_ms"]), (None, "playing", 42000))

    def test_stays_paused_if_it_was_paused(self):
        r = Rig("paused")
        r.start_airplay()
        r.end_airplay()
        self.assertEqual(r.sol.calls, [])
        self.assertEqual(r.player.status()["state"], "paused")

    def test_spotify_controls_refused_during_airplay(self):
        r = Rig("playing")
        r.start_airplay()
        for call in (lambda: r.player.play({"uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"}),
                     lambda: r.player.seek({"position": 3}), lambda: r.player.jump({"index": 0})):
            with self.assertRaises(PlayerError) as e:
                call()
            self.assertEqual((e.exception.status, e.exception.body()["error"]), (409, "airplay_active"))
            self.assertEqual(e.exception.body()["sender"], "Adam's iPhone")
        r.player.enqueue({"uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"})
        self.assertIn("add_to_queue", r.sol.calls)

    def test_transport_controls_the_airplay_sender(self):
        r = Rig("playing")
        r.start_airplay()
        r.player.pause()
        r.player.play({})
        r.player.next()
        r.player.previous()
        r.player.playpause()
        self.assertEqual(r.remote_calls, ["pause", "play", "next", "previous", "pause"])
        self.assertEqual(r.sol.calls, ["pause"])

    def test_playpause_resumes_a_paused_sender(self):
        r = Rig("playing")
        r.start_airplay()
        r.air.handle("ssnc", "pfls", b"")
        self.assertEqual(r.player.status()["state"], "paused")
        r.player.playpause()
        self.assertEqual(r.remote_calls, ["play"])

    def test_remote_failure_is_reported(self):
        r = Rig("playing")
        r.start_airplay()
        r.remote_error = ap.RemoteError("no remote", 409, "airplay_remote_unavailable")
        with self.assertRaises(PlayerError) as e:
            r.player.pause()
        self.assertEqual((e.exception.status, e.exception.body()["error"]), (409, "airplay_remote_unavailable"))

    def test_without_airplay_transport_stays_with_spotify(self):
        r = Rig("playing")
        r.player.pause()
        r.player.next()
        self.assertEqual(r.remote_calls, [])
        self.assertEqual(r.sol.calls, ["pause", "skip_next"])

    def test_stop_from_web_restarts_receiver_and_resumes(self):
        r = Rig("playing")
        r.start_airplay()
        st = r.guard.stop_airplay()
        self.assertEqual(r.receiver_calls, ["restart"])
        self.assertEqual(st["source"], None)
        self.assertEqual(r.sol.calls, ["pause", "play"])
        with self.assertRaises(PlayerError) as e:
            r.guard.stop_airplay()
        self.assertEqual(e.exception.body()["error"], "airplay_inactive")

    def test_no_resume_when_locked(self):
        r = Rig("playing", night(22))
        r.start_airplay()
        r.quiet.locked_until = night(8)
        r.end_airplay()
        self.assertEqual(r.sol.calls, ["pause"])

    def test_resume_allowed_in_grace_and_handoff_keeps_idle_clock_still(self):
        r = Rig("playing", night(22))
        r.guard.tick()
        r.start_airplay()
        r.sol.playback["status"] = "paused"
        r.air.handle("ssnc", "paus", b"")
        r.clock.t += 280
        r.guard.tick()
        r.end_airplay()
        r.sol.playback["status"] = "paused"
        r.clock.t += 15
        r.guard.tick()
        self.assertEqual(r.quiet.status()["phase"], "grace")
        self.assertIsNone(r.quiet.idle_since)
        self.assertEqual(r.sol.calls[-1], "play")

    def test_airplay_during_lock_is_cut(self):
        r = Rig("paused", night(23))
        r.quiet.locked_until = night(8)
        r.start_airplay()
        self.assertTrue(r.enforced and all(r.enforced))
        self.assertIsNone(r.air.snapshot())

    def test_spotify_started_elsewhere_during_airplay_is_paused(self):
        r = Rig("paused")
        r.start_airplay()
        r.sol.playback["status"] = "playing"
        r.guard.tick()
        self.assertEqual(r.sol.calls, ["pause"])


class QuietGuardTest(unittest.TestCase):
    def test_grace_allows_then_lock_refuses(self):
        r = Rig("playing", night(21, 30))
        r.guard.tick()
        r.player.next()
        r.player.pause()
        r.guard.tick()
        r.clock.t += 299
        r.guard.tick()
        r.player.play({})
        r.player.pause()
        r.clock.t += 301
        r.guard.tick()
        self.assertEqual(r.enforced, [True])
        self.assertEqual(r.quiet.status()["phase"], "locked")
        for call in (lambda: r.player.play({}), r.player.next, r.player.previous, r.player.playpause,
                     lambda: r.player.transfer({"device": "soloist", "play": True})):
            with self.assertRaises(PlayerError) as e:
                call()
            body = e.exception.body()
            self.assertEqual((e.exception.status, body["error"], body["until"]), (423, "quiet_hours", "08:00"))
        r.player.pause()
        r.player.volume({"volume": 10})
        r.player.enqueue({"uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"})

    def test_lock_pauses_rogue_playback_and_unlocks_in_the_morning(self):
        r = Rig("paused", night(23))
        r.guard.tick()
        r.clock.t += 300
        r.guard.tick()
        r.sol.playback["status"] = "playing"
        r.guard.tick()
        self.assertEqual(r.sol.calls[-1], "pause")
        r.clock.t = night(8)
        r.guard.tick()
        self.assertEqual(r.enforced, [True, False])
        r.player.play({})

    def test_paused_airplay_session_locks_and_ends(self):
        r = Rig("paused", night(22))
        r.start_airplay()
        r.air.handle("ssnc", "paus", b"")
        r.guard.tick()
        r.clock.t += 300
        r.guard.tick()
        self.assertEqual(r.enforced, [True])
        self.assertIsNone(r.air.snapshot())


def dbus_reply(**props):
    return json.dumps({"type": "a{sv}", "data": [props]})


def typed(t, v):
    return {"type": t, "data": v}


class RecoveryTest(unittest.TestCase):
    META = {"xesam:title": typed("s", "Town Meeting Song"), "xesam:album": typed("s", "Nightmare"),
            "xesam:artist": typed("as", ["Danny Elfman", "Other"]), "mpris:length": typed("x", 176706000)}

    def runner(self, active=True, fail=False, art=None, state="Playing", sinks="[]"):
        calls = []
        meta = dict(self.META)
        if art:
            meta["mpris:artUrl"] = typed("s", "file://" + art)

        def run(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == "pactl":
                return subprocess.CompletedProcess(cmd, 0, sinks, "")
            if fail:
                return subprocess.CompletedProcess(cmd, 1, "", "no bus")
            if "get-property" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(typed("b", active)), "")
            out = dbus_reply(PlayerState=typed("s", state), ClientName=typed("s", ""), Available=typed("b", True),
                             ProgressString=typed("s", "1000000/1441000/14230000"), Metadata=typed("a{sv}", meta))
            return subprocess.CompletedProcess(cmd, 0, out, "")
        return run, calls

    def make(self, **kw):
        run, calls = self.runner(**kw)
        c = Clock()
        a = ap.AirPlay("/nonexistent", clock=c, probe=lambda: ap.probe_dbus(run), sink_probe=lambda: ap.probe_sink(run))
        return a, c, calls

    def test_probe_parses_dbus(self):
        run, _ = self.runner()
        info = ap.probe_dbus(run)
        self.assertEqual((info["title"], info["artist"], info["album"], info["duration_ms"], info["state"]),
                         ("Town Meeting Song", "Danny Elfman, Other", "Nightmare", 176706, "playing"))
        self.assertIsNone(info["sender"])

    def test_probe_inactive_and_unreachable(self):
        self.assertEqual(ap.probe_dbus(self.runner(active=False)[0]), {"active": False})
        self.assertIsNone(ap.probe_dbus(self.runner(fail=True)[0]))

    def test_poll_recovers_session_with_metadata(self):
        a, c, _ = self.make()
        started = []
        a.on_start = lambda: started.append(a.recovered)
        a.poll()
        s = a.snapshot()
        self.assertEqual(started, [True])
        self.assertEqual((s["state"], s["track"]["name"], s["track"]["album"]["name"]),
                         ("playing", "Town Meeting Song", "Nightmare"))
        self.assertEqual(s["track"]["artists"][0]["name"], "Danny Elfman, Other")
        c.t += 5
        self.assertGreater(a.snapshot()["position_ms"], 9000)
        a.poll()
        self.assertEqual(started, [True])

    def sender_state(self, **kw):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = os.path.join(d.name, "sender.json")
        a, c, _ = self.make(**kw)
        a.state_path = path
        return a, path

    def feed_items(self, a, *items):
        for item in ap.Parser().feed(b"".join(raw_item(*i) for i in items)):
            a.handle(*item)

    def test_sender_persists_and_is_restored_on_recovery(self):
        a, path = self.sender_state()
        self.feed_items(a, ("ssnc", "abeg"), ("ssnc", "clip", b"10.0.0.7"), ("ssnc", "snam", b"John's iPhone"))
        self.assertTrue(os.path.exists(path))
        b, _ = self.sender_state()
        b.state_path = path
        b.poll()
        self.assertEqual(b.snapshot()["sender"], "John's iPhone")

    def test_sender_not_restored_for_a_different_client(self):
        a, path = self.sender_state()
        self.feed_items(a, ("ssnc", "abeg"), ("ssnc", "clip", b"10.0.0.7"), ("ssnc", "snam", b"John's iPhone"))
        b, _ = self.sender_state()
        b.state_path = path
        b.recover({"active": True, "state": "playing", "client": "10.0.0.9"})
        self.assertIsNone(b.snapshot()["sender"])

    def test_sender_cleared_when_session_ends(self):
        a, path = self.sender_state()
        self.feed_items(a, ("ssnc", "abeg"), ("ssnc", "snam", b"John's iPhone"))
        self.feed_items(a, ("ssnc", "aend"))
        self.assertFalse(os.path.exists(path))

    def test_stale_sender_dropped_when_nothing_is_playing(self):
        a, path = self.sender_state(active=False)
        with open(path, "w") as f:
            json.dump({"sender": "Old", "client": None}, f)
        a.poll()
        self.assertFalse(os.path.exists(path))

    def test_recovered_session_picks_up_snam_later(self):
        a, path = self.sender_state()
        a.poll()
        self.assertIsNone(a.snapshot()["sender"])
        self.feed_items(a, ("ssnc", "snam", b"John's iPhone"))
        self.assertEqual(a.snapshot()["sender"], "John's iPhone")

    def test_recovered_art_read_from_cache_file(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(JPEG)
            f.flush()
            a, _, _ = self.make(art=f.name)
            a.poll()
        self.assertEqual(a.artwork()[0], JPEG)
        self.assertIn("/api/airplay/artwork", a.snapshot()["track"]["artwork"])

    def test_paused_state(self):
        a, _, _ = self.make(state="Paused")
        a.poll()
        self.assertEqual(a.snapshot()["state"], "paused")

    def test_inactive_does_nothing(self):
        a, _, _ = self.make(active=False)
        a.poll()
        self.assertIsNone(a.snapshot())

    def test_sink_fallback_without_dbus(self):
        sinks = json.dumps([{"corked": True, "properties": {"application.name": "Spotify"}},
                            {"corked": False, "properties": {"application.name": "AirPlay"}}])
        a, _, _ = self.make(fail=True, sinks=sinks)
        a.poll()
        s = a.snapshot()
        self.assertEqual((s["state"], s["track"]["name"], s["sender"]), ("playing", "AirPlay", None))

    def test_corked_sink_is_not_a_session(self):
        a, _, _ = self.make(fail=True, sinks=json.dumps([{"corked": True, "properties": {"application.name": "AirPlay"}}]))
        a.poll()
        self.assertIsNone(a.snapshot())

    def test_pipe_items_fill_in_later(self):
        a, _, _ = self.make(fail=True, sinks=json.dumps([{"corked": False, "properties": {"application.name": "AirPlay"}}]))
        a.poll()
        for item in ap.Parser().feed(SESSION):
            a.handle(*item)
        s = a.snapshot()
        self.assertEqual((s["sender"], s["track"]["name"]), ("Adam's iPhone", "Clair de Lune"))

    def test_recovered_session_ends_when_receiver_goes_inactive(self):
        a, _, _ = self.make()
        ended = []
        a.on_end = lambda: ended.append(1)
        a.poll()
        a.probe = lambda: {"active": False}
        a.poll()
        self.assertIsNone(a.snapshot())
        self.assertEqual(ended, [1])

    def test_ignored_right_after_end_session(self):
        a, _, _ = self.make()
        a.end_session()
        a.poll()
        self.assertIsNone(a.snapshot())


class RecoveryGuardTest(unittest.TestCase):
    def make(self, spotify="paused"):
        r = Rig(spotify)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        r.guard.resume_path = os.path.join(self.dir.name, "airplay-resume")
        r.air.probe = lambda: {"active": True, "state": "playing", "title": "Song"}
        return r

    def test_resume_flag_persists_and_clears(self):
        r = self.make("playing")
        r.start_airplay()
        self.assertTrue(os.path.exists(r.guard.resume_path))
        r.end_airplay()
        self.assertFalse(os.path.exists(r.guard.resume_path))

    def test_flag_survives_restart(self):
        r = self.make("playing")
        r.start_airplay()
        r2 = self.make("paused")
        r2.guard.resume_path = r.guard.resume_path
        r2.air.poll()
        self.assertTrue(r2.guard.resume_after)
        self.assertEqual(r2.guard.overlay(r2.player.status())["source"], "airplay")
        r2.end_airplay()
        self.assertFalse(r2.guard.resume_after)
        self.assertEqual(r2.sol.calls[-1], "play")

    def test_recovered_without_flag_does_not_resume(self):
        r = self.make("paused")
        r.air.poll()
        self.assertFalse(r.guard.resume_after)
        self.assertIsNotNone(r.guard._airplay())

    def test_recovered_session_counts_as_audio_and_blocks_spotify(self):
        r = self.make("paused")
        r.air.poll()
        self.assertTrue(r.guard.audio_playing())
        with self.assertRaises(PlayerError) as cm:
            r.guard.check("jump")
        self.assertEqual(cm.exception.code, "airplay_active")


class RoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        server.tokens, server.sessions, server.personal = Tokens(d), Sessions(d), PersonalTokens(d)
        server.credits = Credits(os.path.join(d, "credits.json"))
        server.activity = Activity(os.path.join(d, "activity.jsonl"))
        server.api = type("Api", (), {"auth": type("A", (), {"logged_in": False})()})()
        cls.quiet_logs = contextlib.redirect_stderr(io.StringIO())
        cls.quiet_logs.__enter__()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.quiet_logs.__exit__(None, None, None)
        cls.tmp.cleanup()

    def setUp(self):
        self.r = Rig("paused", night(23))
        server.player, server.guard, server.quiet, server.airplay = self.r.player, self.r.guard, self.r.quiet, self.r.air
        server.player.credit_fn = server.credits.for_status

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_address[1]}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_locked_refuses_play_routes_but_not_library_or_queue(self):
        self.r.quiet.locked_until = night(8)
        for path, body in [("/api/play", {}), ("/api/playpause", None), ("/api/next", None), ("/api/previous", None),
                           ("/api/back", None), ("/api/queue/jump", {"index": 0}),
                           ("/api/play", {"uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"}),
                           ("/api/spotify/me/player/play", {}), ("/api/spotify/me/player/next", None)]:
            code, res = self.call("POST", path, body)
            self.assertEqual((code, res["error"], res["until"]), (423, "quiet_hours", "08:00"), path)
            self.assertIn("8:00 AM", res["message"])
        code, res = self.call("PUT", "/api/spotify/me/player", {"device_ids": ["x"], "play": True})
        self.assertEqual(code, 423)
        code, _ = self.call("POST", "/api/pause")
        self.assertEqual(code, 200)
        code, res = self.call("POST", "/api/queue", {"uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"})
        self.assertEqual(code, 200)
        code, res = self.call("GET", "/api/quiet-hours")
        self.assertEqual((res["result"]["phase"], res["result"]["until"]), ("locked", "08:00"))
        code, res = self.call("GET", "/api/status")
        self.assertEqual(res["result"]["quiet_hours"]["phase"], "locked")

    def test_airplay_refuses_transport_and_serves_status_and_art(self):
        self.r.start_airplay()
        for path in ("/api/seek", "/api/spotify/me/player/pause"):
            code, res = self.call("POST", path, {"position": 1})
            self.assertEqual((code, res["error"]), (409, "airplay_active"), path)
        code, res = self.call("POST", "/api/play", {"uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"})
        self.assertEqual((code, res["error"]), (409, "airplay_active"))
        for path in ("/api/play", "/api/pause", "/api/playpause", "/api/next", "/api/previous"):
            code, res = self.call("POST", path)
            self.assertEqual((code, res["result"]["source"]), (200, "airplay"), path)
        self.assertEqual(self.r.remote_calls, ["play", "pause", "pause", "next", "previous"])
        code, res = self.call("POST", "/api/queue", {"uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6"})
        self.assertEqual(code, 200)
        code, res = self.call("GET", "/api/status")
        st = res["result"]
        self.assertEqual((st["source"], st["track"]["name"], st["airplay"]["sender"]),
                         ("airplay", "Clair de Lune", "Adam's iPhone"))
        url = f"http://127.0.0.1:{self.srv.server_address[1]}{st['track']['artwork']}"
        with urllib.request.urlopen(url) as res:
            self.assertEqual((res.headers["Content-Type"], res.read()), ("image/jpeg", JPEG))
        code, res = self.call("GET", "/api/airplay")
        self.assertTrue(res["result"]["active"])
        code, res = self.call("POST", "/api/airplay/stop")
        self.assertEqual((code, res["result"]["source"]), (200, None))
        code, res = self.call("GET", "/api/airplay")
        self.assertEqual(res["result"], {"active": False})


if __name__ == "__main__":
    unittest.main()
