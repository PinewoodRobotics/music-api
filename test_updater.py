import contextlib
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


if __name__ == "__main__":
    unittest.main()
