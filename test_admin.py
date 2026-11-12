import contextlib
import datetime
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import quiet_hours as qh
import server
import system_stats
import test_system_stats as fake
from test_effects import beep
import updater
from accounts import AccountError, Admins, Bans, PersonalTokens, Sessions, Slack
from effects import Effects
from guard import Guard
from quiet_hours import QuietHours, parse_window
from tokens import Tokens

ADA = {"id": "U1", "name": "Ada", "avatar": None, "admin": False, "kind": "slack", "email": "ada@pinewood.edu"}
BOB = {"id": "U2", "name": "Bob", "avatar": "http://b", "admin": False, "kind": "slack", "email": "bob@pinewood.edu"}
OLD = {"id": "U3", "name": "Old", "avatar": None, "admin": True, "kind": "slack"}


class AdminsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_and_runtime_merge(self):
        a = Admins(self.tmp.name, ["U9", " Ada@Pinewood.edu ", ""])
        self.assertTrue(a.is_admin(ADA))
        self.assertFalse(a.is_admin(BOB))
        a.add(ADA, id="u2", name="Bob")
        self.assertTrue(a.is_admin(BOB))
        self.assertTrue(Admins(self.tmp.name, []).is_admin(BOB))
        entries = a.entries()
        self.assertEqual([(e["key"], e["source"]) for e in entries],
                         [("u9", "config"), ("ada@pinewood.edu", "config"), ("u2", "admin")])
        self.assertEqual((entries[0]["id"], entries[1]["email"], entries[2]["added_by"]["name"]), ("U9", "ada@pinewood.edu", "Ada"))

    def test_add_validation_and_duplicates(self):
        a = Admins(self.tmp.name, ["u9"])
        for kw in ({}, {"email": "nope"}, {"id": "U1; rm"}):
            with self.assertRaises(AccountError):
                a.add(ADA, **kw)
        with self.assertRaises(AccountError) as e:
            a.add(ADA, id="U9")
        self.assertEqual(e.exception.status, 409)
        a.add(ADA, email="BOB@pinewood.edu")
        with self.assertRaises(AccountError) as e:
            a.add(ADA, email="bob@pinewood.edu")
        self.assertEqual(e.exception.status, 409)
        self.assertTrue(a.is_admin(BOB))

    def test_remove_rules(self):
        a = Admins(self.tmp.name, [])
        a.add(ADA, id="U1")
        with self.assertRaises(AccountError) as e:
            a.remove("u1", ADA)
        self.assertIn("last admin", str(e.exception))
        a.add(ADA, email="bob@pinewood.edu")
        a.remove("U1", ADA)
        self.assertFalse(a.is_admin(ADA))
        with self.assertRaises(AccountError) as e:
            a.remove("u1", BOB)
        self.assertEqual(e.exception.status, 404)
        c = Admins(self.tmp.name, ["u9"])
        with self.assertRaises(AccountError) as e:
            c.remove("U9", ADA)
        self.assertEqual(e.exception.status, 409)
        c.remove("bob@pinewood.edu", BOB)
        self.assertEqual([e["key"] for e in c.entries()], ["u9"])

    def test_resolve(self):
        a = Admins(self.tmp.name, [])
        self.assertFalse(a.resolve({**ADA, "admin": True})["admin"])
        self.assertTrue(a.resolve(OLD)["admin"])
        self.assertIs(a.resolve(server.ADMIN), server.ADMIN)
        a.add(BOB, id="U1")
        self.assertTrue(a.resolve(ADA)["admin"])

    def test_session_user_records_email(self):
        s = Slack("c", "s", "b", "r", "T1", ["ada@pinewood.edu"])
        u = s.session_user("U1", extra={"profile": {"display_name": "Ada", "email": "Ada@Pinewood.edu"}})
        self.assertEqual((u["email"], u["admin"]), ("ada@pinewood.edu", True))


class BansTest(unittest.TestCase):
    def test_ban_by_email_or_id(self):
        with tempfile.TemporaryDirectory() as d:
            bans = Bans(d)
            bans.add(ADA, email="Bob@Pinewood.edu", reason="**spam**")
            bans.add(ADA, id="u3", reason="r")
            self.assertEqual(bans.ban_for(BOB)["reason"], "**spam**")
            self.assertTrue(bans.is_banned(OLD))
            self.assertFalse(bans.is_banned(ADA))
            self.assertFalse(bans.is_banned({}))
            with self.assertRaises(AccountError):
                bans.add(ADA, email="bob@pinewood.edu", reason="r")
            with self.assertRaises(AccountError):
                bans.add(ADA, id="U1", reason="r")
            self.assertTrue(Bans(d).is_banned(BOB))
            bans.remove("bob@pinewood.edu")
            self.assertFalse(Bans(d).is_banned(BOB))
            with self.assertRaises(AccountError):
                bans.remove("bob@pinewood.edu")

    def test_reason_required_and_expiry(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as d:
            bans = Bans(d, clock=lambda: now[0])
            for kw in ({}, {"reason": "  "}, {"reason": "x" * 2001}, {"reason": "r", "until": 999},
                       {"reason": "r", "until": "soon"}, {"reason": "r", "until": True}):
                with self.assertRaises(AccountError):
                    bans.add(ADA, email="bob@pinewood.edu", **kw)
            bans.add(ADA, email="bob@pinewood.edu", reason="r", until=2000)
            self.assertEqual(bans.list()[0]["until"], 2000)
            now[0] = 2000
            self.assertFalse(bans.is_banned(BOB))
            self.assertEqual(bans.list(), [])
            bans.add(ADA, email="bob@pinewood.edu", reason="again")
            self.assertEqual(len(bans.entries), 1)
            self.assertIsNone(bans.ban_for(BOB)["until"])


class Player:
    def spotify_status(self):
        return {"state": "paused"}

    def _emit_status(self):
        pass

    def pause(self, force=False):
        pass


class RoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        server.tokens, server.sessions, server.personal = Tokens(d), Sessions(d), PersonalTokens(d)
        server.slack = Slack(None, None, None, "r")
        server.DATA_DIR, server.QUIET_DEFAULT = d, "21:00-08:00"
        cls.now = [datetime.datetime(2026, 10, 13, 12).timestamp()]
        server.quiet = cls.quiet = QuietHours(parse_window("21:00-08:00"), os.path.join(d, qh.STATE_FILE),
                                              clock=lambda: cls.now[0])
        cls.enforced = []
        server.guard = Guard(Player(), cls.quiet, enforce=cls.enforced.append, clock=lambda: cls.now[0])
        root = os.path.join(d, "root")
        for path, text in {"proc/stat": fake.STAT_1, "proc/meminfo": fake.MEMINFO, "proc/uptime": "100 1\n",
                           "proc/loadavg": "0.5 0.4 0.3 1/2 3\n"}.items():
            os.makedirs(os.path.dirname(os.path.join(root, path)), exist_ok=True)
            with open(os.path.join(root, path), "w") as f:
                f.write(text)
        cls.runner = fake.Runner({"systemctl --user show": (0, fake.SHOW_USER), "systemctl --user restart": (0, ""),
                                  "journalctl --user": (0, "a\nb\n")})
        server.stats = system_stats.Stats(root=root, run=cls.runner)
        server.updates = updater.Updater(app_dir=d, data_dir=d, repo_dir=os.path.join(d, "missing.git"),
                                         remote="git@github.com:x/y.git", key_path=os.path.join(d, "nokey"))
        cls.slider = [70]
        server.effects = Effects(d, build_cmd=lambda path, vol: ["true"], slider=lambda: cls.slider[0])
        cls.logs = contextlib.redirect_stderr(io.StringIO())
        cls.logs.__enter__()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.logs.__exit__(None, None, None)
        server.admins = server.bans = server.effects = None
        cls.tmp.cleanup()

    def setUp(self):
        server.admins = Admins(self.tmp.name, ["u9"])
        for f in ("admins.json", qh.SETTINGS_FILE):
            try:
                os.remove(os.path.join(self.tmp.name, f))
            except FileNotFoundError:
                pass
        server.admins.added = []
        server.bans = Bans(self.tmp.name)
        server.bans.entries = []
        self.quiet.configure(parse_window("21:00-08:00"), qh.GRACE)
        self.quiet.locked_until = self.quiet.override = None
        self.now[0] = datetime.datetime(2026, 10, 13, 12).timestamp()
        self.ada = server.sessions.create(ADA)
        self.bob = server.sessions.create(BOB)

    def call(self, method, path, body=None, sid=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if sid:
            headers["Cookie"] = f"mapi_session={sid}"
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_address[1]}{path}", data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_ban_blocks_sessions(self):
        server.admins.add({"id": "x"}, id="U1")
        self.assertEqual(self.call("POST", "/api/admin/bans", {"email": "bob@pinewood.edu"}, self.bob)[0], 403)
        self.assertEqual(self.call("POST", "/api/admin/bans", {"email": "bob@pinewood.edu"}, self.ada)[0], 400)
        status, out = self.call("POST", "/api/admin/bans", {"email": "Bob@pinewood.edu", "reason": "*spam*"}, self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(out["result"]["bans"][0]["key"], "bob@pinewood.edu")
        status, out = self.call("GET", "/api/status", sid=self.bob)
        self.assertEqual(status, 403)
        self.assertEqual(out["error"], "you're banned from the music API")
        self.assertEqual((out["ban"]["reason"], out["ban"]["until"]), ("*spam*", None))
        self.assertEqual(self.call("DELETE", "/api/admin/bans/bob@pinewood.edu", sid=self.ada)[1]["result"], {"bans": []})
        self.assertNotEqual(self.call("GET", "/api/admin/bans", sid=self.bob)[1].get("error"),
                            "you're banned from the music API")

    def test_web_app_may_only_be_framed_by_the_fms_panel(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.srv.server_address[1]}/library") as res:
            csp = res.headers["Content-Security-Policy"]
        self.assertEqual(csp, "frame-ancestors 'self' http://localhost:8080 http://127.0.0.1:8080 http://fms.local:8080")

    def test_non_admins_get_403_everywhere(self):
        routes = [(m, p.replace("{name}", "soloist").replace("{key}", "u9")) for m, _, p, _, _ in server.ROUTES
                  if p.startswith("/api/admin")]
        self.assertGreaterEqual(len(routes), 12)
        for method, path in routes:
            code, res = self.call(method, path, {} if method != "GET" else None, sid=self.bob)
            self.assertEqual((method, path, code, res), (method, path, 403, {"error": "admins only"}))

    def test_runtime_admin_takes_effect_on_existing_sessions(self):
        self.assertEqual(self.call("GET", "/api/admin/system", sid=self.ada)[0], 403)
        self.assertFalse(self.call("GET", "/api/app/me", sid=self.ada)[1]["result"]["admin"])
        server.admins.add(BOB, id="U1")
        self.assertTrue(self.call("GET", "/api/app/me", sid=self.ada)[1]["result"]["admin"])
        self.assertEqual(self.call("GET", "/api/admin/system", sid=self.ada)[0], 200)

    def test_admins_routes(self):
        server.admins.add(ADA, id="U1")
        code, res = self.call("GET", "/api/admin/admins", sid=self.ada)
        self.assertEqual(code, 200)
        admins = res["result"]["admins"]
        self.assertEqual([(a["key"], a["source"], a["you"]) for a in admins], [("u9", "config", False), ("u1", "admin", True)])
        self.assertEqual(admins[1]["name"], "Ada")
        known = {k["id"]: k for k in res["result"]["known"]}
        self.assertEqual((known["U1"]["admin"], known["U2"]["admin"], known["U2"]["email"]), (True, False, "bob@pinewood.edu"))
        code, res = self.call("POST", "/api/admin/admins", {"id": "bob@pinewood.edu"}, sid=self.ada)
        self.assertEqual(code, 200)
        added = res["result"]["admins"][-1]
        self.assertEqual((added["key"], added["name"], added["avatar"], added["added_by"]["name"]),
                         ("bob@pinewood.edu", "Bob", "http://b", "Ada"))
        self.assertEqual(self.call("POST", "/api/admin/admins", {"email": "bob@pinewood.edu"}, sid=self.ada)[0], 409)
        self.assertEqual(self.call("DELETE", "/api/admin/admins/u9", sid=self.ada)[0], 409)
        self.assertEqual(self.call("GET", "/api/admin/system", sid=self.bob)[0], 200)
        code, res = self.call("DELETE", "/api/admin/admins/" + urllib.parse.quote("bob@pinewood.edu"), sid=self.ada)
        self.assertEqual((code, [a["key"] for a in res["result"]["admins"]]), (200, ["u9", "u1"]))
        self.assertEqual(self.call("GET", "/api/admin/system", sid=self.bob)[0], 403)

    def test_cant_remove_yourself_as_last_admin(self):
        server.admins = Admins(self.tmp.name, [])
        server.admins.add(ADA, id="U1")
        code, res = self.call("DELETE", "/api/admin/admins/U1", sid=self.ada)
        self.assertEqual(code, 409)
        self.assertIn("last admin", res["error"])

    def test_quiet_hours_settings_persist_and_reach_the_watchdog(self):
        code, res = self.call("GET", "/api/admin/quiet-hours")
        self.assertEqual((code, res["result"]["settings"]["source"], res["result"]["settings"]["grace_min"]), (200, "env", 5))
        code, res = self.call("PUT", "/api/admin/quiet-hours", {"start": "22:30", "end": "06:00", "grace_min": 10})
        s = res["result"]["settings"]
        self.assertEqual((code, s["start"], s["end"], s["grace_min"], s["source"], s["updated_by"]["name"]),
                         (200, "22:30", "06:00", 10, "admin", "Field"))
        self.assertEqual((res["result"]["status"]["window"], self.quiet.grace), ("22:30-06:00", 600))
        cfg = qh.settings(self.tmp.name, "21:00-08:00")
        self.assertEqual((cfg["window"], cfg["grace"]), (parse_window("22:30-06:00"), 600))
        code, res = self.call("PUT", "/api/admin/quiet-hours", {"enabled": False})
        self.assertEqual((res["result"]["settings"]["enabled"], res["result"]["settings"]["start"]), (False, "22:30"))
        self.assertIsNone(qh.settings(self.tmp.name, "21:00-08:00")["window"])
        self.assertFalse(res["result"]["status"]["enabled"])
        self.assertEqual(self.call("PUT", "/api/admin/quiet-hours", {"enabled": True})[1]["result"]["status"]["window"], "22:30-06:00")
        self.assertEqual(self.call("PUT", "/api/admin/quiet-hours", {"start": "25:00"})[0], 400)
        self.assertEqual(self.call("PUT", "/api/admin/quiet-hours", {"grace_min": 999})[0], 400)
        code, res = self.call("PUT", "/api/admin/quiet-hours", {"reset": True})
        self.assertEqual((res["result"]["settings"]["source"], res["result"]["status"]["window"]), ("env", "21:00-08:00"))

    def test_effects_volume_is_admin_only_and_persists(self):
        code, res = self.call("GET", "/api/admin/effects-volume", sid=self.ada)
        self.assertEqual(code, 403)
        self.assertEqual(self.call("PUT", "/api/admin/effects-volume", {"mode": "fixed", "level": 5}, sid=self.bob)[0], 403)
        self.assertEqual(server.effects.volume_cfg["mode"], "follow")
        code, res = self.call("GET", "/api/admin/effects-volume")
        self.assertEqual((code, res["result"]["mode"], res["result"]["media_volume"]), (200, "follow", 70))
        server.admins.add(ADA, id="U1")
        code, res = self.call("PUT", "/api/admin/effects-volume", {"mode": "fixed", "level": 30}, sid=self.ada)
        r = res["result"]
        self.assertEqual((code, r["mode"], r["level"], r["media_volume"], r["updated_by"]["name"]), (200, "fixed", 30, 70, "Ada"))
        self.assertEqual(self.call("PUT", "/api/admin/effects-volume", {"mode": "loud"})[0], 400)
        self.assertEqual(self.call("PUT", "/api/admin/effects-volume", {"level": 150})[0], 400)
        again = Effects(self.tmp.name, slider=lambda: None)
        self.assertEqual((again.volume_cfg["mode"], again.volume_cfg["level"]), ("fixed", 30))
        code, res = self.call("PUT", "/api/admin/effects-volume", {"mode": "follow"})
        self.assertEqual((res["result"]["mode"], res["result"]["level"]), ("follow", 30))

    def test_play_during_quiet_hours_is_admin_only_and_persists(self):
        code, res = self.call("GET", "/api/admin/effects-volume")
        self.assertEqual((code, res["result"]["play_during_quiet_hours"]), (200, True))
        self.assertEqual(self.call("PUT", "/api/admin/effects-volume", {"play_during_quiet_hours": False}, sid=self.bob)[0], 403)
        self.assertTrue(server.effects.plays_during_quiet_hours())
        self.assertEqual(self.call("PUT", "/api/admin/effects-volume", {"play_during_quiet_hours": "maybe"})[0], 400)
        mode = server.effects.volume_cfg["mode"]
        code, res = self.call("PUT", "/api/admin/effects-volume", {"play_during_quiet_hours": False})
        self.assertEqual((code, res["result"]["play_during_quiet_hours"], res["result"]["mode"]), (200, False, mode))
        self.assertFalse(Effects(self.tmp.name, slider=lambda: None).plays_during_quiet_hours())
        self.now[0] = datetime.datetime(2026, 10, 13, 23).timestamp()
        self.quiet.locked_until = datetime.datetime(2026, 10, 14, 8).timestamp()
        server.effects.register("horn", beep())
        try:
            self.assertEqual(self.call("POST", "/api/effects/horn/play")[0], 423)
            self.call("PUT", "/api/admin/effects-volume", {"play_during_quiet_hours": True})
            code, res = self.call("POST", "/api/effects/horn/play")
            self.assertEqual((code, res["result"]["quiet_hours"]), (200, True))
            with self.assertRaises(Exception) as e:
                server.guard.check("play")
            self.assertEqual((e.exception.status, e.exception.code), (423, "quiet_hours"))
            self.assertTrue(self.quiet.locked())
        finally:
            server.effects.stop()
            server.effects.delete("horn")
            server.effects.set_volume_settings(play_during_quiet_hours=True)

    def test_override_locks_and_unlocks_now(self):
        self.assertEqual(self.call("POST", "/api/admin/quiet-hours/override", {"action": "lock"})[0], 409)
        self.now[0] = datetime.datetime(2026, 10, 13, 22).timestamp()
        self.enforced.clear()
        code, res = self.call("POST", "/api/admin/quiet-hours/override", {"action": "lock"})
        self.assertEqual((code, res["result"]["status"]["phase"], res["result"]["status"]["override"]["kind"]), (200, "locked", "locked"))
        self.assertTrue(self.enforced[0])
        self.assertEqual(self.call("GET", "/api/quiet-hours")[1]["result"]["locked"], True)
        code, res = self.call("POST", "/api/admin/quiet-hours/override", {"action": "unlock"})
        self.assertEqual((res["result"]["status"]["phase"], res["result"]["status"]["override"]["kind"]), ("open", "unlocked"))
        self.assertFalse(self.enforced[-1])
        self.assertEqual(self.call("POST", "/api/admin/quiet-hours/override", {"action": "bogus"})[0], 409)

    def test_system_services_and_logs(self):
        code, res = self.call("GET", "/api/admin/system")
        r = res["result"]
        self.assertEqual((code, r["memory"]["percent"], r["load"]), (200, 50.0, [0.5, 0.4, 0.3]))
        self.assertEqual([s["name"] for s in r["services"]][:3], ["soloist", "music-api", "airplay"])
        self.assertNotIn("history", self.call("GET", "/api/admin/system?history=0")[1]["result"])
        self.assertEqual(self.call("POST", "/api/admin/services/soloist/restart")[1]["result"], {"name": "soloist", "state": "active"})
        self.assertEqual(self.call("POST", "/api/admin/services/music-api/restart")[0], 403)
        self.assertEqual(self.call("POST", "/api/admin/services/nope/restart")[0], 404)
        self.assertEqual(self.call("GET", "/api/admin/logs/soloist?lines=5")[1]["result"]["lines"], ["a", "b"])

    def test_update_routes_without_setup(self):
        code, res = self.call("GET", "/api/admin/update")
        self.assertEqual((code, res["result"]["configured"]), (200, False))
        self.assertIn("updater.py setup", res["result"]["setup_hint"])
        self.assertEqual(self.call("POST", "/api/admin/update")[0], 503)
        self.assertEqual(self.call("POST", "/api/admin/update/check")[1]["result"]["configured"], False)


if __name__ == "__main__":
    unittest.main()
