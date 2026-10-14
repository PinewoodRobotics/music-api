#!/usr/bin/env python3
"""Update the deployed server from GitHub without stopping the music.

GitHub Actions (.github/workflows/pi-build.yml) runs the tests on every push to main, builds web/dist and publishes
the deployable tree (plus BUILD.json) as the `pi-build` branch. The Pi fetches main and pi-build into a bare repo
with a read-only deploy key, stages the build next to the app dir, swaps it in, restarts music-api (and
music-display if its files changed), health-checks the API and swaps back if it fails. Soloist and the AirPlay
receiver keep running; a music-api restart is safe because both are recovered.

    python3 updater.py setup     # one time: deploy key + bare repo; prints the public key for GitHub
    python3 updater.py status    # fetch and show what an update would do
    python3 updater.py update    # update now (also POST /api/admin/update)
"""
import argparse
import fcntl
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE = "git@github.com:PinewoodRobotics/music-api.git"
MAIN, BUILD = "main", "pi-build"
STATE_FILE = "update.json"
FETCH_EVERY = 600
HEALTH_TIMEOUT = 60
UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
REQUIRED_COMMANDS = {"pw-play": "pipewire-bin", "ffmpeg": "ffmpeg"}
NOTES = {
    "deploy/install-linux.sh": "deploy/install-linux.sh changed: check it for new packages or setup steps and run them on the Pi by hand (they need sudo)",
    "deploy/install-airplay.sh": "The AirPlay installer changed: run sh ~/.local/share/music-api-v2/deploy/install-airplay.sh on the Pi",
    "deploy/update-soloist.sh": "The Soloist updater changed: it runs daily, or run ~/.local/share/music-api-v2/deploy/update-soloist.sh now",
    "deploy/deploy-pi.sh": "deploy/deploy-pi.sh changed: check it for new install steps",
}
LATER = {"soloist": ("deploy/run-soloist.sh", "deploy/systemd/soloist.service"),
         "airplay": ("deploy/run-airplay.sh", "deploy/shairport-sync.conf", "deploy/systemd/airplay.service")}


class UpdateError(Exception):
    def __init__(self, msg, status=409):
        super().__init__(msg)
        self.status = status


def default_data_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.environ.get("MUSIC_API_DATA_DIR") or os.path.join(base, "music-api")


def _blob_sha(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        data = f.read()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def _run(cmd, timeout=60, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)


def http_health(port):
    """Any HTTP answer below 500 from /api/status means the new server is serving (401 without a token is fine)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except (OSError, ValueError):
        return False


def summarize(files):
    """Changed paths for display, with web/dist collapsed to one line."""
    dist = [f for f in files if f.startswith("web/dist/")]
    rest = [f for f in files if not f.startswith("web/dist/")]
    return rest + ([f"web/dist ({len(dist)} file{'s' if len(dist) != 1 else ''})"] if dist else [])


class Updater:
    def __init__(self, app_dir=HERE, data_dir=None, repo_dir=None, remote=None, key_path=None, unit_dir=UNIT_DIR,
                 run=_run, health=None, port=None, clock=time.time, sleep=time.sleep, which=shutil.which, spawn=None):
        self.app_dir = os.path.abspath(app_dir)
        self.data_dir = data_dir or default_data_dir()
        self.repo_dir = repo_dir or os.environ.get("MUSIC_API_UPDATE_REPO") or \
            os.path.join(os.path.dirname(self.app_dir), "music-api-repo.git")
        self.remote = remote or os.environ.get("MUSIC_API_UPDATE_REMOTE") or REMOTE
        self.key_path = key_path or os.path.expanduser("~/.ssh/music-api-deploy")
        self.unit_dir, self.run, self.clock, self.sleep, self.which = unit_dir, run, clock, sleep, which
        self.port = port or int(os.environ.get("MUSIC_API_PORT") or 8765)
        self.health = health or (lambda: http_health(self.port))
        self.spawn = spawn or (lambda cmd, env: subprocess.Popen(
            cmd, env=env, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL))
        self.state_path = os.path.join(self.data_dir, STATE_FILE)
        self.lock = threading.Lock()
        self.fetched_at, self.fetch_error = None, None
        self.state = None

    def _local_remote(self):
        return not self.remote.startswith(("git@", "ssh://", "https://", "http://"))

    def _ssh_command(self):
        return f"ssh -i {self.key_path} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

    def git(self, *args, timeout=60, check=True):
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if not self._local_remote():
            env["GIT_SSH_COMMAND"] = self._ssh_command()
        try:
            r = subprocess.run(["git", "--git-dir", self.repo_dir, *args], capture_output=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            raise UpdateError(f"git {args[0]} timed out", 504)
        if check and r.returncode != 0:
            raise UpdateError(f"git {args[0]} failed: {r.stderr.decode(errors='replace').strip()[-400:]}", 502)
        return r.stdout if r.returncode == 0 else None

    def _text(self, *args, **kw):
        out = self.git(*args, **kw)
        return out.decode().strip() if out is not None else None

    def configured(self):
        return os.path.isdir(self.repo_dir) and (self._local_remote() or os.path.exists(self.key_path))

    def setup(self):
        """Create the deploy key (if missing) and the bare repo; returns the public key."""
        if not self._local_remote() and not os.path.exists(self.key_path):
            os.makedirs(os.path.dirname(self.key_path), mode=0o700, exist_ok=True)
            rc, out = self.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "music-api-pi-deploy", "-f", self.key_path])
            if rc != 0:
                raise UpdateError(f"ssh-keygen failed: {out.strip()}", 500)
        if not os.path.isdir(self.repo_dir):
            subprocess.run(["git", "init", "-q", "--bare", self.repo_dir], check=True)
        self.git("config", "remote.origin.url", self.remote)
        self.git("config", "--replace-all", "remote.origin.fetch", f"+refs/heads/{MAIN}:refs/remotes/origin/{MAIN}")
        self.git("config", "--add", "remote.origin.fetch", f"+refs/heads/{BUILD}:refs/remotes/origin/{BUILD}")
        pub = self.key_path + ".pub"
        if os.path.exists(pub):
            with open(pub) as f:
                return f.read().strip()
        return None

    def fetch(self):
        if not self.configured():
            raise UpdateError("updates aren't set up on this server yet (python3 updater.py setup)", 503)
        try:
            self.git("fetch", "--prune", "--quiet", "origin", timeout=90)
            self.fetched_at, self.fetch_error = round(self.clock()), None
        except UpdateError as e:
            self.fetched_at, self.fetch_error = round(self.clock()), str(e)
            raise

    def _commit(self, ref):
        out = self._text("log", "-1", "--format=%H%x00%h%x00%s%x00%an%x00%ct", ref, "--", check=False)
        if not out:
            return None
        sha, short, subject, author, ts = out.split("\0")
        return {"commit": sha, "short": short, "subject": subject, "author": author, "date": int(ts)}

    def _has(self, sha):
        return bool(sha) and self.git("cat-file", "-e", f"{sha}^{{commit}}", check=False) is not None

    def deployed(self):
        try:
            with open(os.path.join(self.app_dir, "BUILD.json")) as f:
                b = json.load(f)
        except (OSError, ValueError):
            return None
        sha = b.get("commit")
        return {"commit": sha, "short": (sha or "")[:7] or None, "subject": b.get("subject"), "date": b.get("date"),
                "built_at": b.get("built_at"), "dirty": bool(b.get("dirty"))} if sha else None

    def build_info(self):
        raw = self.git("show", f"refs/remotes/origin/{BUILD}:BUILD.json", check=False)
        if raw is None:
            return None
        try:
            b = json.loads(raw)
        except ValueError:
            return None
        return {"commit": b.get("commit"), "short": (b.get("commit") or "")[:7], "subject": b.get("subject"),
                "built_at": b.get("built_at")}

    def changed_files(self):
        """Paths whose content differs between the app dir and the pi-build tree (or that exist on one side only,
        for files the build owns)."""
        listing = self.git("ls-tree", "-r", "-z", f"refs/remotes/origin/{BUILD}", check=False)
        if listing is None:
            return []
        changed, tracked = [], set()
        for entry in listing.decode().split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            sha = meta.split()[2]
            tracked.add(path)
            local = os.path.join(self.app_dir, path)
            if path != "BUILD.json" and (not os.path.isfile(local) or _blob_sha(local) != sha):
                changed.append(path)
        dist = os.path.join(self.app_dir, "web", "dist")
        for root, _, files in os.walk(dist):
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), self.app_dir)
                if rel not in tracked:
                    changed.append(rel)
        return sorted(changed)

    def plan(self, files):
        restarts, units, notes = [], [], []
        if any(f.endswith(".py") and "/" not in f for f in files) or "deploy/systemd/music-api.service" in files:
            restarts.append("music-api")
        if any(f.startswith("display/") for f in files) or "deploy/systemd/music-display.service" in files:
            if self._enabled("music-display.service"):
                restarts.append("music-display")
        for f in files:
            if f.startswith("deploy/systemd/") and f.endswith((".service", ".timer")):
                name = os.path.basename(f)
                if os.path.exists(os.path.join(self.unit_dir, name)):
                    units.append(name)
                else:
                    notes.append(f"New unit {name} isn't installed; install and enable it by hand if it's needed")
            if f in NOTES:
                notes.append(NOTES[f])
        for svc, paths in LATER.items():
            if any(p in files for p in paths):
                notes.append(f"{svc} keeps running the old version until it restarts (Services tab), so the music isn't interrupted")
        for cmd, pkg in REQUIRED_COMMANDS.items():
            if not self.which(cmd):
                notes.append(f"{cmd} is missing: sudo apt-get install -y {pkg}")
        return {"files": summarize(files), "restarts": restarts, "units": units, "notes": notes}

    def _enabled(self, unit):
        rc, out = self.run(["systemctl", "--user", "is-enabled", unit], timeout=10)
        return rc == 0 and out.strip() in ("enabled", "enabled-runtime")

    def status(self, fetch=None):
        """Everything the admin page shows. fetch=None fetches when the last fetch is older than FETCH_EVERY."""
        out = {"configured": self.configured(), "setup_hint": None, "deployed": self.deployed(), "latest": None,
               "build": None, "behind": 0, "commits": [], "changes": {"files": [], "restarts": [], "units": [], "notes": []},
               "fetched_at": self.fetched_at, "fetch_error": self.fetch_error, "run": self.read_state()}
        if not out["configured"]:
            out["setup_hint"] = ("Updates from GitHub aren't set up on this Pi yet. On the Pi run "
                                 "python3 ~/.local/share/music-api-v2/updater.py setup and add the public key it prints "
                                 "as a read-only deploy key of PinewoodRobotics/music-api on GitHub.")
            return out
        if fetch or (fetch is None and (not self.fetched_at or self.clock() - self.fetched_at > FETCH_EVERY)):
            try:
                self.fetch()
            except UpdateError:
                pass
            out.update(fetched_at=self.fetched_at, fetch_error=self.fetch_error)
        latest = self._commit(f"refs/remotes/origin/{MAIN}")
        out["latest"] = latest and {k: latest[k] for k in ("commit", "short", "subject", "date")}
        build = self.build_info()
        if build:
            build["ready"] = bool(latest and build["commit"] == latest["commit"])
            out["build"] = build
        deployed = out["deployed"]
        if latest:
            base = deployed["commit"] if deployed and self._has(deployed["commit"]) else None
            rng = [f"{base}..refs/remotes/origin/{MAIN}"] if base else ["-n", "20", f"refs/remotes/origin/{MAIN}"]
            log = self._text("log", "--format=%H%x00%h%x00%s%x00%an%x00%ct", *rng, "--", check=False) or ""
            out["commits"] = [dict(zip(("commit", "short", "subject", "author", "date"), line.split("\0")))
                              for line in log.splitlines() if line.count("\0") == 4]
            for c in out["commits"]:
                c["date"] = int(c["date"])
            out["behind"] = len(out["commits"]) if base else (0 if deployed and deployed["commit"] == latest["commit"] else len(out["commits"]))
        if build and (not deployed or deployed["commit"] != build["commit"]):
            out["changes"] = self.plan(self.changed_files())
        return out

    def read_state(self):
        try:
            with open(self.state_path) as f:
                st = json.load(f)
        except (OSError, ValueError):
            return None
        if st.get("state") == "running" and self.clock() - st.get("started_at", 0) > 30 and not self._locked():
            last = (st.get("log") or [{}])[-1].get("t")
            st.update(state="failed", result="The updater stopped unexpectedly; see the log", finished_at=last)
        return st

    def _write_state(self):
        os.makedirs(self.data_dir, mode=0o700, exist_ok=True)
        tmp = f"{self.state_path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.state_path)

    def log(self, msg, level="info"):
        print(("" if level == "info" else level.upper() + ": ") + msg, flush=True)
        if self.state is not None:
            self.state["log"].append({"t": round(self.clock(), 1), "msg": msg, "level": level})
            self._write_state()

    def _lock_path(self):
        return os.path.join(self.data_dir, "update.lock")

    def _locked(self):
        try:
            with open(self._lock_path(), "a") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True
        except OSError:
            return False

    def start(self, by=None):
        """Run the update in its own process (a transient systemd unit when available) so it survives the
        music-api restart it triggers. Returns the new run's state."""
        st = self.status(fetch=True)
        if not st["configured"]:
            raise UpdateError(st["setup_hint"], 503)
        if (st["run"] or {}).get("state") == "running":
            raise UpdateError("an update is already running")
        if not st["build"]:
            raise UpdateError("there's no build on GitHub yet (the pi-build branch is missing)")
        if st["deployed"] and st["deployed"]["commit"] == st["build"]["commit"]:
            raise UpdateError("already up to date")
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        self.state = {"id": run_id, "state": "running", "started_at": round(self.clock()), "finished_at": None,
                      "from": (st["deployed"] or {}).get("commit"), "to": st["build"]["commit"], "result": None,
                      "by": by, "log": []}
        self.log(f"Update requested{' by ' + by['name'] if by and by.get('name') else ''}: "
                 f"{(st['deployed'] or {}).get('short') or 'unknown'} -> {st['build']['short']}")
        cmd = [sys.executable, os.path.join(self.app_dir, "updater.py"), "update", "--run-id", run_id]
        env = {"MUSIC_API_DATA_DIR": self.data_dir, "MUSIC_API_UPDATE_REPO": self.repo_dir,
               "MUSIC_API_UPDATE_REMOTE": self.remote, "MUSIC_API_PORT": str(self.port)}
        if self.which("systemd-run"):
            cmd = ["systemd-run", "--user", "--collect", "--quiet", f"--unit=music-api-update-{run_id}"] + \
                  [f"--setenv={k}={v}" for k, v in env.items()] + cmd
            rc, out = self.run(cmd, timeout=30)
            if rc != 0:
                self.finish("failed", f"couldn't start the updater: {out.strip()}")
                raise UpdateError(f"couldn't start the updater: {out.strip()}", 500)
        else:
            self.spawn(cmd, {**os.environ, **env})
        return self.state

    def finish(self, state, result):
        self.state.update(state=state, result=result, finished_at=round(self.clock()))
        self.log(result, "info" if state == "succeeded" else "error" if state == "failed" else "warn")

    def update(self, run_id=None):
        os.makedirs(self.data_dir, mode=0o700, exist_ok=True)
        with open(self._lock_path(), "a") as lf:
            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise UpdateError("an update is already running")
            st = self.read_state()
            if run_id and st and st.get("id") == run_id:
                self.state = st
                self.state["state"] = "running"
            else:
                self.state = {"id": run_id or time.strftime("%Y%m%d-%H%M%S"), "state": "running",
                              "started_at": round(self.clock()), "finished_at": None, "from": None, "to": None,
                              "result": None, "by": None, "log": []}
            try:
                return self._update()
            except Exception as e:  # noqa: BLE001 - always leave a final state for the admin page
                self.finish("failed", f"Update failed: {e}")
                return self.state

    def _update(self):
        self.log("Fetching from GitHub")
        self.fetch()
        build, deployed = self.build_info(), self.deployed()
        if not build:
            self.finish("failed", "There's no build on GitHub yet (pi-build branch missing)")
            return self.state
        self.state.update(to=build["commit"], **({"from": deployed["commit"]} if deployed and not self.state.get("from") else {}))
        if deployed and deployed["commit"] == build["commit"]:
            self.finish("succeeded", f"Already up to date ({build['short']})")
            return self.state
        files = self.changed_files()
        plan = self.plan(files)
        self.log(f"{len(files)} changed file{'s' if len(files) != 1 else ''}; restarting: {', '.join(plan['restarts']) or 'nothing'}")
        new, prev = self.app_dir + ".new", self.app_dir + ".prev"
        self._stage(new)
        self.log(f"Staged {build['short']} in {os.path.basename(new)}")
        if os.path.exists(prev):
            shutil.rmtree(prev)
        os.rename(self.app_dir, prev)
        os.rename(new, self.app_dir)
        self.log("Swapped the new version in")
        try:
            self._apply(plan, self.app_dir)
            healthy = self._healthy(plan)
        except Exception as e:  # noqa: BLE001
            self.log(f"Applying the update failed: {e}", "error")
            healthy = False
        if healthy:
            for note in plan["notes"]:
                self.log(note, "warn")
            self.finish("succeeded", f"Updated to {build['short']}: {build.get('subject') or ''}".rstrip(": "))
            return self.state
        self.log("The new version failed its health check; rolling back", "error")
        failed = self.app_dir + ".failed"
        if os.path.exists(failed):
            shutil.rmtree(failed)
        os.rename(self.app_dir, failed)
        os.rename(prev, self.app_dir)
        try:
            self._apply(plan, self.app_dir)
            ok = self._healthy(plan)
        except Exception as e:  # noqa: BLE001
            self.log(f"Rollback restart failed: {e}", "error")
            ok = False
        if ok:
            self.finish("rolled_back", f"Rolled back to {(deployed or {}).get('short') or 'the previous version'}; "
                                       f"the failed build is kept in {os.path.basename(failed)}")
        else:
            self.finish("failed", "Rolled back, but the server still isn't healthy; check journalctl --user -u music-api")
        return self.state

    def _stage(self, new):
        if os.path.exists(new):
            shutil.rmtree(new)
        os.makedirs(new)
        raw = self.git("archive", "--format=tar", f"refs/remotes/origin/{BUILD}", timeout=120)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
            for m in tar.getmembers():
                if m.name.startswith("/") or ".." in m.name.split("/") or not (m.isfile() or m.isdir()):
                    raise UpdateError(f"refusing to extract {m.name!r}", 500)
            if hasattr(tarfile, "data_filter"):
                tar.extractall(new, filter="data")
            else:
                tar.extractall(new)
        for name in os.listdir(self.app_dir):
            if name != "__pycache__" and not os.path.exists(os.path.join(new, name)):
                src = os.path.join(self.app_dir, name)
                (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, os.path.join(new, name))
        deploy = os.path.join(new, "deploy")
        if os.path.isdir(deploy):
            for name in os.listdir(deploy):
                if name.endswith(".sh"):
                    os.chmod(os.path.join(deploy, name), 0o755)

    def _apply(self, plan, app_dir):
        if plan["units"]:
            for name in plan["units"]:
                shutil.copy2(os.path.join(app_dir, "deploy", "systemd", name), os.path.join(self.unit_dir, name))
            self._systemctl("daemon-reload")
            self.log(f"Installed unit files: {', '.join(plan['units'])}")
        for unit in plan["restarts"]:
            self.log(f"Restarting {unit}")
            self._systemctl("restart", unit)

    def _systemctl(self, *args):
        rc, out = self.run(["systemctl", "--user", *args], timeout=90)
        if rc != 0:
            raise UpdateError(f"systemctl {' '.join(args)} failed: {out.strip()[-300:]}", 500)

    def _healthy(self, plan):
        if "music-api" not in plan["restarts"]:
            return True
        deadline = self.clock() + HEALTH_TIMEOUT
        while self.clock() < deadline:
            if self.health():
                self.sleep(3)
                if self.health():
                    self.log("Health check passed")
                    return True
            self.sleep(1)
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["setup", "status", "update"])
    ap.add_argument("--run-id")
    a = ap.parse_args(argv)
    u = Updater()
    try:
        if a.command == "setup":
            pub = u.setup()
            print(f"Bare repo: {u.repo_dir}\nRemote: {u.remote}")
            if pub:
                print("\nAdd this public key on GitHub: PinewoodRobotics/music-api > Settings > Deploy keys > Add deploy key"
                      " (leave 'Allow write access' off):\n\n" + pub + "\n")
            print("Then check it works with: python3 updater.py status")
            return 0
        if a.command == "status":
            print(json.dumps(u.status(fetch=True), indent=1))
            return 0
        st = u.update(a.run_id)
        return 0 if st["state"] == "succeeded" else 1
    except UpdateError as e:
        sys.stderr.write(f"{e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
