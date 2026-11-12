import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import updater as up

GIT = ["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main",
       "-c", "commit.gpgsign=false"]


def git(cwd, *args):
    return subprocess.run(GIT + list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write(root, files):
    for path, text in files.items():
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)


V1 = {"server.py": "print('v1')\n", "README.md": "v1\n", "web/dist/index.html": "<p>v1</p>",
      "web/dist/assets/app-111.js": "v1", "deploy/systemd/music-api.service": "[Service]\nv1\n",
      "deploy/run-airplay.sh": "#!/bin/sh\nv1\n", "display/now_playing_display.py": "v1\n"}


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Rig:
    """A fake GitHub (bare repo with main and pi-build), a deployed app dir and an installed unit dir."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.origin = os.path.join(tmp, "origin.git")
        self.work = os.path.join(tmp, "work")
        self.app = os.path.join(tmp, "app")
        self.units = os.path.join(tmp, "units")
        self.data = os.path.join(tmp, "data")
        subprocess.run(["git", "init", "-q", "--bare", self.origin], check=True)
        os.makedirs(self.work)
        git(self.work, "init", "-q")
        git(self.work, "remote", "add", "origin", self.origin)
        self.files = dict(V1)
        self.v1 = self.commit("First", {})
        os.makedirs(self.units)
        write(self.units, {"music-api.service": V1["deploy/systemd/music-api.service"]})
        write(self.app, {**V1, "BUILD.json": json.dumps({"commit": self.v1, "subject": "First"})})
        self.publish()
        self.calls = []
        self.healthy = [True]
        self.clock = Clock()
        self.enabled = {"music-display.service"}
        self.slacked = []

    def slack(self, token, method, params):
        self.slacked.append((method, params))
        if method == "users.lookupByEmail":
            return {"ok": True, "user": {"id": "U_ADA"}}
        return {"ok": True}

    def dms(self):
        return [p for m, p in self.slacked if m == "chat.postMessage"]

    def commit(self, subject, changes):
        self.files.update(changes)
        write(self.work, changes or self.files)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", subject)
        git(self.work, "push", "-q", "origin", "HEAD:main")
        return git(self.work, "rev-parse", "HEAD")

    def publish(self):
        sha = git(self.work, "rev-parse", "HEAD")
        subject = git(self.work, "log", "-1", "--format=%s")
        build = os.path.join(self.tmp, "build")
        shutil.rmtree(build, ignore_errors=True)
        write(build, {**self.files, "BUILD.json": json.dumps({"commit": sha, "subject": subject, "built_at": 1})})
        git(build, "init", "-q")
        git(build, "add", "-A")
        git(build, "commit", "-q", "-m", f"Build of {sha[:7]}")
        git(build, "push", "-q", "-f", self.origin, "HEAD:refs/heads/pi-build")
        return sha

    def run(self, cmd, timeout=60):
        self.calls.append(cmd)
        if cmd[:3] == ["systemctl", "--user", "is-enabled"]:
            return (0, "enabled\n") if cmd[3] in self.enabled else (1, "disabled\n")
        return 0, ""

    def updater(self, **kw):
        kw.setdefault("environ", {})
        kw.setdefault("slack", self.slack)
        kw.setdefault("safe", lambda: (True, "nothing is playing"))
        u = up.Updater(app_dir=self.app, data_dir=self.data, repo_dir=os.path.join(self.tmp, "repo.git"),
                       remote=self.origin, unit_dir=self.units, run=self.run, health=lambda: self.healthy[0],
                       clock=self.clock, sleep=self.clock.sleep, which=lambda c: "/usr/bin/" + c, **kw)
        u.setup()
        return u

    def read(self, path):
        with open(os.path.join(self.app, path)) as f:
            return f.read()

    def restarts(self):
        return [c[3] for c in self.calls if c[:3] == ["systemctl", "--user", "restart"]]


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.rig = Rig(self.tmpdir.name)
        self.out = contextlib.redirect_stdout(io.StringIO())
        self.out.__enter__()

    def tearDown(self):
        self.out.__exit__(None, None, None)
        self.tmpdir.cleanup()

    def test_up_to_date(self):
        st = self.rig.updater().status(fetch=True)
        self.assertTrue(st["configured"])
        self.assertEqual((st["behind"], st["commits"], st["build"]["ready"]), (0, [], True))
        self.assertEqual(st["deployed"]["short"], self.rig.v1[:7])
        with self.assertRaises(up.UpdateError) as e:
            self.rig.updater().start()
        self.assertIn("up to date", str(e.exception))

    def test_status_lists_commits_and_plan(self):
        self.rig.commit("Fix the thing", {"server.py": "print('v2')\n"})
        v3 = self.rig.commit("Docs", {"README.md": "v2\n", "deploy/systemd/music-api.service": "[Service]\nv2\n",
                                      "deploy/install-airplay.sh": "#!/bin/sh\n"})
        u = self.rig.updater()
        st = u.status(fetch=True)
        self.assertEqual(st["build"]["ready"], False)
        self.assertEqual([c["subject"] for c in st["commits"]], ["Docs", "Fix the thing"])
        self.assertEqual((st["behind"], st["latest"]["commit"]), (2, v3))
        self.rig.publish()
        st = u.status(fetch=True)
        self.assertTrue(st["build"]["ready"])
        ch = st["changes"]
        self.assertEqual(ch["restarts"], ["music-api"])
        self.assertEqual(ch["units"], ["music-api.service"])
        self.assertIn("server.py", ch["files"])
        self.assertTrue(any("install-airplay.sh" in n for n in ch["notes"]))

    def test_update_swaps_restarts_and_installs_units(self):
        self.rig.commit("Server v2", {"server.py": "print('v2')\n", "deploy/systemd/music-api.service": "[Service]\nv2\n",
                                      "web/dist/assets/app-222.js": "v2"})
        os.remove(os.path.join(self.rig.work, "web/dist/assets/app-111.js"))
        del self.rig.files["web/dist/assets/app-111.js"]
        sha = self.rig.commit("Drop old asset", {})
        self.rig.publish()
        write(self.rig.app, {"local-only.txt": "keep me"})
        st = self.rig.updater().update("r1")
        self.assertEqual(st["state"], "succeeded", st["log"])
        self.assertEqual(self.rig.read("server.py"), "print('v2')\n")
        self.assertEqual(json.loads(self.rig.read("BUILD.json"))["commit"], sha)
        self.assertFalse(os.path.exists(os.path.join(self.rig.app, "web/dist/assets/app-111.js")))
        self.assertEqual(self.rig.read("local-only.txt"), "keep me")
        self.assertTrue(os.access(os.path.join(self.rig.app, "deploy/run-airplay.sh"), os.X_OK))
        with open(os.path.join(self.rig.units, "music-api.service")) as f:
            self.assertEqual(f.read(), "[Service]\nv2\n")
        self.assertIn(["systemctl", "--user", "daemon-reload"], self.rig.calls)
        self.assertEqual(self.rig.restarts(), ["music-api"])
        self.assertTrue(os.path.isdir(self.rig.app + ".prev"))
        with open(os.path.join(self.rig.data, up.STATE_FILE)) as f:
            saved = json.load(f)
        self.assertEqual((saved["id"], saved["state"], saved["to"]), ("r1", "succeeded", sha))

    def test_failed_health_check_rolls_back(self):
        self.rig.commit("Broken server", {"server.py": "raise SystemExit\n",
                                          "deploy/systemd/music-api.service": "[Service]\nbroken\n"})
        self.rig.publish()
        self.rig.healthy[0] = False
        u = self.rig.updater()
        real = u.health
        u.health = lambda: real() if self.rig.read("server.py") == "raise SystemExit\n" else True
        st = u.update()
        self.assertEqual(st["state"], "rolled_back", st["log"])
        self.assertEqual(self.rig.read("server.py"), "print('v1')\n")
        self.assertEqual(self.rig.read("README.md"), "v1\n")
        with open(os.path.join(self.rig.units, "music-api.service")) as f:
            self.assertEqual(f.read(), "[Service]\nv1\n")
        with open(os.path.join(self.rig.app + ".failed", "server.py")) as f:
            self.assertEqual(f.read(), "raise SystemExit\n")
        self.assertEqual(self.rig.restarts(), ["music-api", "music-api"])
        self.assertTrue(any(e["level"] == "error" for e in st["log"]))

    def test_rollback_that_still_fails_reports_failed(self):
        self.rig.commit("Broken", {"server.py": "x\n"})
        self.rig.publish()
        self.rig.healthy[0] = False
        st = self.rig.updater().update()
        self.assertEqual(st["state"], "failed")
        self.assertEqual(self.rig.read("server.py"), "print('v1')\n")

    def test_web_only_change_restarts_nothing(self):
        self.rig.commit("Web tweak", {"web/dist/index.html": "<p>v2</p>"})
        self.rig.publish()
        self.rig.healthy[0] = False
        st = self.rig.updater().update()
        self.assertEqual(st["state"], "succeeded", st["log"])
        self.assertEqual((self.rig.restarts(), self.rig.read("web/dist/index.html")), ([], "<p>v2</p>"))

    def test_display_and_later_restarts(self):
        self.rig.commit("Display + airplay", {"display/now_playing_display.py": "v2\n", "deploy/run-airplay.sh": "#!/bin/sh\nv2\n"})
        self.rig.publish()
        u = self.rig.updater()
        u.which = lambda c: None if c == "ffmpeg" else "/usr/bin/" + c
        plan = u.status(fetch=True)["changes"]
        self.assertEqual(plan["restarts"], ["music-display"])
        self.assertTrue(any(n.startswith("airplay keeps running") for n in plan["notes"]))
        self.assertTrue(any("apt-get install -y ffmpeg" in n for n in plan["notes"]))
        self.rig.enabled.clear()
        self.assertEqual(u.status(fetch=False)["changes"]["restarts"], [])
        u.update()
        self.assertEqual(self.rig.restarts(), [])

    def test_unknown_deployed_commit(self):
        os.remove(os.path.join(self.rig.app, "BUILD.json"))
        self.rig.commit("Two", {"server.py": "print('v2')\n"})
        self.rig.publish()
        st = self.rig.updater().status(fetch=True)
        self.assertIsNone(st["deployed"])
        self.assertEqual([c["subject"] for c in st["commits"]], ["Two", "First"])
        self.assertEqual(st["changes"]["restarts"], ["music-api"])

    def test_start_spawns_a_detached_run(self):
        self.rig.commit("Two", {"server.py": "print('v2')\n"})
        self.rig.publish()
        u = self.rig.updater()
        u.which = lambda c: None if c == "systemd-run" else "/usr/bin/" + c
        spawned = []
        u.spawn = lambda cmd, env: spawned.append((cmd, env))
        run = u.start({"id": "U1", "name": "Ada"})
        self.assertEqual((run["state"], run["by"]["name"]), ("running", "Ada"))
        cmd, env = spawned[0]
        self.assertEqual(cmd[-3:], ["update", "--run-id", run["id"]])
        self.assertEqual(env["MUSIC_API_UPDATE_REMOTE"], self.rig.origin)
        self.assertEqual(u.read_state()["state"], "running")
        with self.assertRaises(up.UpdateError):
            u.start()
        self.rig.clock.t += 60
        st = u.read_state()
        self.assertEqual(st["state"], "failed")
        result = u.update(run["id"])
        self.assertEqual((result["id"], result["state"]), (run["id"], "succeeded"))
        self.assertEqual(result["log"][0]["msg"].split(":")[0], "Update requested by Ada")

    def test_start_uses_systemd_run(self):
        self.rig.commit("Two", {"server.py": "print('v2')\n"})
        self.rig.publish()
        u = self.rig.updater()
        run = u.start()
        cmd = next(c for c in self.rig.calls if c[0] == "systemd-run")
        self.assertIn(f"--unit=music-api-update-{run['id']}", cmd)
        self.assertIn(f"--setenv=MUSIC_API_DATA_DIR={self.rig.data}", cmd)

    def test_not_configured(self):
        u = up.Updater(app_dir=self.rig.app, data_dir=self.rig.data, repo_dir=os.path.join(self.rig.tmp, "none.git"),
                       remote="git@github.com:x/y.git", key_path=os.path.join(self.rig.tmp, "nokey"), run=self.rig.run)
        st = u.status()
        self.assertEqual((st["configured"], bool(st["setup_hint"])), (False, True))
        with self.assertRaises(up.UpdateError) as e:
            u.start()
        self.assertEqual(e.exception.status, 503)

    def test_https_remote_needs_no_setup(self):
        u = up.Updater(app_dir=self.rig.app, data_dir=self.rig.data, repo_dir=os.path.join(self.rig.tmp, "fresh.git"),
                       remote="https://github.com/x/y.git", key_path=os.path.join(self.rig.tmp, "nokey"), run=self.rig.run)
        self.assertTrue(u.configured())
        self.assertIsNone(u.status(fetch=False)["setup_hint"])
        self.assertNotIn("GIT_SSH_COMMAND", self._git_env(u))

    def _git_env(self, u):
        seen = {}
        real = up.subprocess.run

        def spy(cmd, **kw):
            seen.update(kw.get("env") or {})
            return real(cmd, **kw)
        with mock.patch.object(up.subprocess, "run", spy):
            u.git("config", "--list", check=False)
        return seen

    def test_fetch_creates_the_repo_and_moves_it_off_an_old_remote(self):
        repo = os.path.join(self.rig.tmp, "lazy.git")
        u = up.Updater(app_dir=self.rig.app, data_dir=self.rig.data, repo_dir=repo, remote=self.rig.origin,
                       unit_dir=self.rig.units, run=self.rig.run, which=lambda c: "/usr/bin/" + c)
        st = u.status(fetch=True)
        self.assertIsNone(st["fetch_error"])
        self.assertEqual(st["latest"]["commit"], self.rig.v1)

        u.git("config", "remote.origin.url", "git@github.com:x/y.git")
        u.fetch()
        self.assertEqual(u._text("config", "remote.origin.url"), self.rig.origin)

    def test_setup_generates_a_key_for_github(self):
        key = os.path.join(self.rig.tmp, "keys", "deploy")

        def keygen(cmd, timeout=60):
            self.rig.calls.append(cmd)
            write(os.path.dirname(key), {"deploy": "private", "deploy.pub": "ssh-ed25519 AAAA music-api-pi-deploy\n"})
            return 0, ""
        u = up.Updater(app_dir=self.rig.app, data_dir=self.rig.data, repo_dir=os.path.join(self.rig.tmp, "gh.git"),
                       remote="git@github.com:x/y.git", key_path=key, run=keygen)
        self.assertEqual(u.setup(), "ssh-ed25519 AAAA music-api-pi-deploy")
        self.assertEqual(self.rig.calls[-1][:3], ["ssh-keygen", "-t", "ed25519"])
        self.assertTrue(u.configured())
        self.assertIn("IdentitiesOnly=yes", u._ssh_command())


def at(hour, minute, days=0):
    d = datetime.date.today() + datetime.timedelta(days=days)
    return datetime.datetime.combine(d, datetime.time(hour, minute)).timestamp()


class AutoUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.rig = Rig(self.tmpdir.name)
        self.rig.clock.t = at(3, 5)
        self.out = contextlib.redirect_stdout(io.StringIO())
        self.out.__enter__()
        self.err = contextlib.redirect_stderr(io.StringIO())
        self.err.__enter__()

    def tearDown(self):
        self.err.__exit__(None, None, None)
        self.out.__exit__(None, None, None)
        self.tmpdir.cleanup()

    def new_build(self, files=None):
        self.rig.commit("Server v2", files or {"server.py": "print('v2')\n"})
        return self.rig.publish()

    def test_settings_default_and_validation(self):
        u = self.rig.updater()
        self.assertEqual({k: u.auto_settings()[k] for k in ("enabled", "time")}, {"enabled": True, "time": "03:00"})
        s = u.save_auto_settings(False, "4:30", {"id": "U1", "name": "Ada"})
        self.assertEqual((s["enabled"], s["time"], s["updated_by"]["name"]), (False, "04:30", "Ada"))
        for bad in ("25:00", "3pm", "", 3):
            with self.assertRaises(up.UpdateError) as e:
                u.save_auto_settings(at=bad)
            self.assertEqual(e.exception.status, 400)
        self.assertEqual(u.status(fetch=False)["auto"]["time"], "04:30")

    def test_auto_does_nothing_when_disabled(self):
        self.new_build()
        u = self.rig.updater()
        u.save_auto_settings(enabled=False)
        self.assertIsNone(u.auto())
        self.assertEqual((u.history(), self.rig.read("server.py")), ([], "print('v1')\n"))

    def test_auto_only_in_the_window(self):
        u = self.rig.updater()
        self.assertEqual(u.auto_night("03:00", at(3, 59)), datetime.date.today().isoformat())
        self.assertIsNone(u.auto_night("03:00", at(4, 0)))
        self.assertIsNone(u.auto_night("03:00", at(2, 59)))
        self.assertEqual(u.auto_night("23:30", at(0, 10, days=1)), datetime.date.today().isoformat())
        self.rig.clock.t = at(12, 0)
        self.new_build()
        self.assertIsNone(u.auto())
        self.assertEqual(u.history(), [])

    def test_auto_skips_when_up_to_date_once_a_night(self):
        u = self.rig.updater()
        entry = u.auto()
        self.assertEqual((entry["outcome"], entry["result"], entry["auto"]), ("skipped", "Already up to date", True))
        self.rig.clock.t += 15 * 60
        self.assertIsNone(u.auto())
        self.rig.clock.t = at(3, 5, days=1)
        u.auto()
        hist = u.history()
        self.assertEqual((len(hist), hist[0]["count"]), (1, 2))

    def test_auto_skips_when_unsafe(self):
        self.new_build()
        u = self.rig.updater(safe=lambda: (False, "music is playing"))
        entry = u.auto()
        self.assertEqual(entry["outcome"], "skipped")
        self.assertIn("music is playing", entry["result"])
        self.assertEqual(self.rig.read("server.py"), "print('v1')\n")
        self.assertEqual(self.rig.restarts(), [])
        self.assertEqual(self.rig.dms(), [])

    def test_auto_skips_until_the_build_is_ready(self):
        self.rig.commit("Not built yet", {"server.py": "print('v2')\n"})
        entry = self.rig.updater().auto()
        self.assertIn("still building", entry["result"])

    def test_auto_skips_when_deployed_is_newer(self):
        v2 = self.new_build()
        u = self.rig.updater()
        u.fetch()
        write(self.rig.app, {"BUILD.json": json.dumps({"commit": v2})})
        git(self.rig.work, "reset", "-q", "--hard", self.rig.v1)
        git(self.rig.work, "push", "-q", "-f", "origin", "HEAD:main")
        self.rig.files = dict(V1)
        self.rig.publish()
        self.assertIn("isn't newer", u.auto()["result"])

    def test_auto_skips_an_unknown_deployed_commit(self):
        self.new_build()
        write(self.rig.app, {"BUILD.json": json.dumps({"commit": "f" * 40})})
        self.assertIn("isn't a commit on GitHub", self.rig.updater().auto()["result"])

    def test_auto_updates_when_safe(self):
        sha = self.new_build()
        u = self.rig.updater()
        st = u.auto()
        self.assertEqual((st["state"], st["auto"], st["to"]), ("succeeded", True, sha))
        self.assertEqual(self.rig.read("server.py"), "print('v2')\n")
        h = u.history()[0]
        self.assertEqual((h["outcome"], h["auto"], h["by"], h["from"], h["to"]), ("updated", True, None, self.rig.v1, sha))
        self.assertEqual(self.rig.dms(), [])
        self.assertIsNone(u.auto())

    def test_auto_rollback_alerts_admins(self):
        self.new_build()
        write(self.rig.data, {"admins.json": json.dumps([{"key": "u_bob", "id": "U_BOB", "email": None}])})
        self.rig.healthy[0] = False
        u = self.rig.updater(environ={"SLACK_BOT_TOKEN": "xoxb-1", "SLACK_ADMINS": "U_CAL, ada@example.com"})
        real = u.health
        u.health = lambda: real() if self.rig.read("server.py") == "print('v2')\n" else True
        st = u.auto()
        self.assertEqual(st["state"], "rolled_back")
        self.assertEqual(u.history()[0]["outcome"], "rolled_back")
        self.assertEqual(sorted(d["channel"] for d in self.rig.dms()), ["U_ADA", "U_BOB", "U_CAL"])
        self.assertIn("rolled back", self.rig.dms()[0]["text"])

    def test_auto_failure_alerts_and_manual_failure_does_not(self):
        self.new_build({"server.py": "x\n"})
        self.rig.healthy[0] = False
        env = {"SLACK_BOT_TOKEN": "xoxb-1", "SLACK_ADMINS": "U_CAL"}
        st = self.rig.updater(environ=env).update()
        self.assertEqual((st["state"], self.rig.dms()), ("failed", []))
        self.rig.clock.t = at(3, 5)
        st = self.rig.updater(environ=env).auto()
        self.assertEqual(st["state"], "failed")
        self.assertEqual([d["channel"] for d in self.rig.dms()], ["U_CAL"])

    def test_slack_env_file_and_unconfigured(self):
        self.new_build()
        self.rig.healthy[0] = False
        env_file = os.path.join(self.rig.tmp, "env")
        write(self.rig.tmp, {"env": "# comment\nSLACK_BOT_TOKEN='xoxb-2'\nSLACK_ADMINS=U_DEE\n"})
        u = self.rig.updater(env_file=env_file)
        self.assertEqual(u.alert("hi"), 1)
        self.assertEqual(self.rig.dms(), [{"channel": "U_DEE", "text": "hi"}])
        u = self.rig.updater(env_file=os.path.join(self.rig.tmp, "missing"))
        self.assertEqual(u.alert("hi"), 0)
        self.assertEqual(len(self.rig.slacked), 1)

    def test_sudo_notes_alert_on_manual_update(self):
        self.new_build({"deploy/install-linux.sh": "#!/bin/sh\nnew\n"})
        u = self.rig.updater(environ={"SLACK_BOT_TOKEN": "xoxb-1", "SLACK_ADMINS": "U_CAL"})
        u.state = None
        st = u.update()
        self.assertEqual(st["state"], "succeeded")
        self.assertEqual(len(self.rig.dms()), 1)
        self.assertIn("install-linux.sh", self.rig.dms()[0]["text"])
        self.assertTrue(any("sudo" in n for n in u.history()[0]["notes"]))

    def test_history_is_capped_and_records_outcomes(self):
        self.new_build()
        u = self.rig.updater()
        u.update()
        self.rig.commit("Broken", {"server.py": "x\n"})
        self.rig.publish()
        self.rig.healthy[0] = False
        u.update()
        self.assertEqual([h["outcome"] for h in u.history()], ["failed", "updated"])
        for i in range(12):
            u.record({"id": str(i), "outcome": "skipped", "auto": True, "result": f"r{i}"}, collapse=True)
        hist = u.history()
        self.assertEqual(len(hist), up.HISTORY_MAX)
        self.assertEqual(hist[0]["id"], "11")

    def test_revert_to_previous(self):
        u = self.rig.updater()
        self.assertIsNone(u.status(fetch=False)["previous"])
        with self.assertRaises(up.UpdateError) as e:
            u.start(action="revert")
        self.assertIn("no previous version", str(e.exception))
        self.assertEqual(u.update(action="revert")["state"], "failed")
        v2 = self.new_build()
        u.update()
        self.assertEqual(u.previous()["commit"], self.rig.v1)
        st = u.update(action="revert")
        self.assertEqual(st["state"], "succeeded", st["log"])
        self.assertEqual((st["from"], st["to"]), (v2, self.rig.v1))
        self.assertEqual(self.rig.read("server.py"), "print('v1')\n")
        self.assertEqual(u.previous()["commit"], v2)
        self.assertEqual(self.rig.restarts(), ["music-api", "music-api"])
        self.assertEqual(u.history()[0]["outcome"], "reverted")

    def test_revert_that_fails_health_swaps_back(self):
        v2 = self.new_build()
        u = self.rig.updater()
        u.update()
        u.health = lambda: self.rig.read("server.py") == "print('v2')\n"
        st = u.update(action="revert")
        self.assertEqual(st["state"], "failed")
        self.assertEqual(json.loads(self.rig.read("BUILD.json"))["commit"], v2)
        self.assertEqual(u.previous()["commit"], self.rig.v1)

    def test_start_revert_spawns(self):
        self.new_build()
        u = self.rig.updater()
        u.update()
        u.which = lambda c: None
        spawned = []
        u.spawn = lambda cmd, env: spawned.append(cmd)
        run = u.start({"id": "U1", "name": "Ada"}, action="revert")
        self.assertEqual((run["action"], run["to"]), ("revert", self.rig.v1))
        self.assertEqual(spawned[0][-3:], ["revert", "--run-id", run["id"]])
        self.assertEqual(u.update(run["id"])["state"], "succeeded")

    def test_plan_installs_and_enables_the_auto_units(self):
        self.new_build({"server.py": "print('v2')\n", "deploy/systemd/auto-update.service": "[Service]\n",
                        "deploy/systemd/auto-update.timer": "[Timer]\n"})
        u = self.rig.updater()
        plan = u.status(fetch=True)["changes"]
        self.assertEqual(plan["enable"], list(up.AUTO_UNITS))
        self.assertFalse(any("auto-update" in n for n in plan["notes"]))
        u.update()
        self.assertTrue(os.path.exists(os.path.join(self.rig.units, "auto-update.timer")))
        self.assertIn(["systemctl", "--user", "enable", "--now", "auto-update.timer"], self.rig.calls)
        self.assertEqual(u.status(fetch=False)["changes"]["enable"], [])


class SafeToUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data = self.tmpdir.name
        self.now = at(3, 0)

    def tearDown(self):
        self.tmpdir.cleanup()

    def state(self, **kw):
        write(self.data, {"quiet-hours.json": json.dumps({"locked_until": None, "idle_since": None, "heartbeat": None,
                                                          "override": None, **kw})})

    def safe(self, flowing=False):
        with mock.patch.dict(os.environ, {"QUIET_HOURS": "21:00-08:00"}), \
                mock.patch.object(up.quiet_hours, "audio_flowing", lambda: flowing):
            return up.safe_to_update(self.data, self.now)

    def test_locked_quiet_hours_are_safe_even_with_audio(self):
        self.state(locked_until=self.now + 3600, heartbeat=self.now)
        self.assertEqual(self.safe(flowing=True)[0], True)

    def test_music_playing(self):
        self.state(heartbeat=self.now - 30)
        self.assertEqual(self.safe(), (False, "music is playing"))

    def test_idle_server_but_sound_effect(self):
        self.state(heartbeat=self.now - 30, idle_since=self.now - 60)
        self.assertEqual(self.safe(flowing=True), (False, "audio is playing"))
        self.assertEqual(self.safe()[0], True)

    def test_server_down_judged_by_sinks(self):
        self.state(heartbeat=self.now - 3600)
        self.assertEqual(self.safe()[0], True)
        self.assertEqual(self.safe(flowing=True)[0], False)


if __name__ == "__main__":
    unittest.main()
