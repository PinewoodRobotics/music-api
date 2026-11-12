#!/usr/bin/env python3
"""Update the deployed server from GitHub without stopping the music.

GitHub Actions (.github/workflows/pi-build.yml) runs the tests on every push to main, builds web/dist and publishes
the deployable tree (plus BUILD.json) as the `pi-build` branch. The Pi fetches main and pi-build into a bare repo
over HTTPS (the repo is public, so no credentials are needed), stages the build next to the app dir, swaps it in, restarts music-api (and
music-display if its files changed), health-checks the API and swaps back if it fails. Soloist and the AirPlay
receiver keep running; a music-api restart is safe because both are recovered.

    python3 updater.py setup     # optional: create the bare repo now (fetch creates it on demand)
    python3 updater.py status    # fetch and show what an update would do
    python3 updater.py update    # update now (also POST /api/admin/update)
    python3 updater.py revert    # swap music-api-v2.prev back in (also POST /api/admin/update/revert)
    python3 updater.py auto      # nightly: update if it's time, a build is ready and nothing is playing (auto-update.timer)
"""
import argparse
import datetime
import fcntl
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import quiet_hours

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE = "https://github.com/PinewoodRobotics/music-api.git"
MAIN, BUILD = "main", "pi-build"
STATE_FILE = "update.json"
SETTINGS_FILE = "update-settings.json"
HISTORY_FILE = "update-history.json"
HISTORY_MAX = 10
DEFAULT_AUTO_TIME = "03:00"
AUTO_WINDOW = 3600
AUTO_UNITS = ("auto-update.service", "auto-update.timer")
ENV_FILE = os.path.expanduser("~/.config/music-api/env")
SLACK_API = "https://slack.com/api"
FETCH_EVERY = 600
HEALTH_TIMEOUT = 60
UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
REQUIRED_COMMANDS = {"pw-play": "pipewire-bin", "ffmpeg": "ffmpeg"}
NOTES = {
    "deploy/install-linux.sh": "deploy/install-linux.sh changed: check it for new packages or setup steps and run them on the Pi by hand (they need sudo)",
    "deploy/install-airplay.sh": "The AirPlay installer changed: run sh ~/.local/share/music-api-v2/deploy/install-airplay.sh on the Pi",
    "deploy/update-soloist.sh": "The Soloist updater changed: it runs daily, or run ~/.local/share/music-api-v2/deploy/update-soloist.sh now",
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


def tree_diff(a, b):
    """Relative paths that differ between two directory trees (content, or present on one side only)."""
    def files(root):
        out = {}
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for n in names:
                full = os.path.join(d, n)
                if os.path.isfile(full):
                    out[os.path.relpath(full, root)] = full
        return out
    fa, fb = files(a), files(b)
    changed = [p for p in set(fa) | set(fb) if p not in fa or p not in fb or _blob_sha(fa[p]) != _blob_sha(fb[p])]
    return sorted(changed)


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def parse_hhmm(value):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip()) if isinstance(value, str) else None
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise UpdateError("time must look like 03:00", 400)
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def read_env_file(path):
    out = {}
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def slack_call(token, method, params):
    req = urllib.request.Request(f"{SLACK_API}/{method}", urllib.parse.urlencode(params).encode(),
                                 {"Authorization": "Bearer " + token,
                                  "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"{}")
    except (OSError, ValueError) as e:
        return {"ok": False, "error": str(e)}


def safe_to_update(data_dir, now):
    """(safe, reason): quiet hours have the speakers locked, or nothing is playing. Spotify and AirPlay come from the
    server's idle clock in quiet-hours.json; sound effects (and everything else, also when the server is down) from
    PipeWire sink activity."""
    cfg = quiet_hours.settings(data_dir)
    qh = quiet_hours.QuietHours(cfg["window"], os.path.join(data_dir, quiet_hours.STATE_FILE), grace=cfg["grace"])
    if qh.locked(now):
        return True, "quiet hours have the speakers locked"
    server_up = bool(qh.heartbeat) and now - qh.heartbeat <= quiet_hours.HEARTBEAT_STALE
    if server_up and qh.idle_since is None:
        return False, "music is playing"
    if quiet_hours.audio_flowing():
        return False, "audio is playing"
    return True, "nothing is playing"


class Updater:
    def __init__(self, app_dir=HERE, data_dir=None, repo_dir=None, remote=None, key_path=None, unit_dir=UNIT_DIR,
                 run=_run, health=None, port=None, clock=time.time, sleep=time.sleep, which=shutil.which, spawn=None,
                 safe=None, slack=slack_call, environ=None, env_file=None):
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
        self.settings_path = os.path.join(self.data_dir, SETTINGS_FILE)
        self.history_path = os.path.join(self.data_dir, HISTORY_FILE)
        self.safe = safe or (lambda: safe_to_update(self.data_dir, self.clock()))
        self.slack = slack
        self.environ = os.environ if environ is None else environ
        self.env_file = env_file or os.environ.get("MUSIC_API_ENV_FILE") or ENV_FILE
        self.lock = threading.Lock()
        self.fetched_at, self.fetch_error = None, None
        self.state = None

    def _ssh_remote(self):
        return self.remote.startswith(("git@", "ssh://"))

    def _ssh_command(self):
        return f"ssh -i {self.key_path} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

    def git(self, *args, timeout=60, check=True):
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if self._ssh_remote():
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
        return not self._ssh_remote() or (os.path.isdir(self.repo_dir) and os.path.exists(self.key_path))

    def _ensure_repo(self):
        if not os.path.isdir(self.repo_dir):
            r = subprocess.run(["git", "init", "-q", "--bare", self.repo_dir], capture_output=True)
            if r.returncode != 0:
                raise UpdateError(f"git init failed: {r.stderr.decode(errors='replace').strip()[-400:]}", 500)
        if self._text("config", "remote.origin.url", check=False) != self.remote:
            self.git("config", "remote.origin.url", self.remote)
            self.git("config", "--replace-all", "remote.origin.fetch", f"+refs/heads/{MAIN}:refs/remotes/origin/{MAIN}")
            self.git("config", "--add", "remote.origin.fetch", f"+refs/heads/{BUILD}:refs/remotes/origin/{BUILD}")

    def setup(self):
        """Create the bare repo, plus a deploy key when the remote is SSH; returns the public key, if any."""
        if self._ssh_remote() and not os.path.exists(self.key_path):
            os.makedirs(os.path.dirname(self.key_path), mode=0o700, exist_ok=True)
            rc, out = self.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "music-api-pi-deploy", "-f", self.key_path])
            if rc != 0:
                raise UpdateError(f"ssh-keygen failed: {out.strip()}", 500)
        self._ensure_repo()
        pub = self.key_path + ".pub"
        if self._ssh_remote() and os.path.exists(pub):
            with open(pub) as f:
                return f.read().strip()
        return None

    def fetch(self):
        if not self.configured():
            raise UpdateError("updates aren't set up on this server yet (python3 updater.py setup)", 503)
        try:
            self._ensure_repo()
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
        enable = [u for u in AUTO_UNITS if not os.path.exists(os.path.join(self.unit_dir, u))]
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
                elif name not in AUTO_UNITS:
                    notes.append(f"New unit {name} isn't installed; install and enable it by hand if it's needed")
            if f in NOTES:
                notes.append(NOTES[f])
        for svc, paths in LATER.items():
            if any(p in files for p in paths):
                notes.append(f"{svc} keeps running the old version until it restarts (Services tab), so the music isn't interrupted")
        for cmd, pkg in REQUIRED_COMMANDS.items():
            if not self.which(cmd):
                notes.append(f"{cmd} is missing: sudo apt-get install -y {pkg}")
        return {"files": summarize(files), "restarts": restarts, "units": units, "enable": enable, "notes": notes}

    def _enabled(self, unit):
        rc, out = self.run(["systemctl", "--user", "is-enabled", unit], timeout=10)
        return rc == 0 and out.strip() in ("enabled", "enabled-runtime")

    def status(self, fetch=None):
        """Everything the admin page shows. fetch=None fetches when the last fetch is older than FETCH_EVERY."""
        out = {"configured": self.configured(), "setup_hint": None, "deployed": self.deployed(), "latest": None,
               "build": None, "behind": 0, "commits": [],
               "changes": {"files": [], "restarts": [], "units": [], "enable": [], "notes": []},
               "fetched_at": self.fetched_at, "fetch_error": self.fetch_error, "run": self.read_state(),
               "auto": self.auto_settings(), "history": self.history(), "previous": self.previous()}
        if not out["configured"]:
            out["setup_hint"] = (f"The update remote {self.remote} uses SSH, which needs a deploy key. On the Pi run "
                                 "python3 ~/.local/share/music-api-v2/updater.py setup and add the public key it prints "
                                 "as a read-only deploy key on GitHub, or unset MUSIC_API_UPDATE_REMOTE to use HTTPS.")
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

    def start(self, by=None, action="update"):
        """Run the update (or the revert to music-api-v2.prev) in its own process (a transient systemd unit when
        available) so it survives the music-api restart it triggers. Returns the new run's state."""
        revert = action == "revert"
        st = self.status(fetch=not revert)
        if (st["run"] or {}).get("state") == "running":
            raise UpdateError("an update is already running")
        who = f" by {by['name']}" if by and by.get("name") else ""
        if revert:
            prev = st["previous"]
            if not prev:
                raise UpdateError("there's no previous version to roll back to")
            target = prev
            msg = f"Rollback requested{who}: {(st['deployed'] or {}).get('short') or 'unknown'} -> {prev.get('short') or 'previous version'}"
        else:
            if not st["configured"]:
                raise UpdateError(st["setup_hint"], 503)
            if not st["build"]:
                raise UpdateError("there's no build on GitHub yet (the pi-build branch is missing)")
            if st["deployed"] and st["deployed"]["commit"] == st["build"]["commit"]:
                raise UpdateError("already up to date")
            target = st["build"]
            msg = f"Update requested{who}: {(st['deployed'] or {}).get('short') or 'unknown'} -> {st['build']['short']}"
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        self.state = {"id": run_id, "action": action, "auto": False, "state": "running",
                      "started_at": round(self.clock()), "finished_at": None,
                      "from": (st["deployed"] or {}).get("commit"), "to": target.get("commit"), "result": None,
                      "by": by, "log": []}
        self.log(msg)
        cmd = [sys.executable, os.path.join(self.app_dir, "updater.py"), action, "--run-id", run_id]
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
        try:
            self.record(self._history_entry())
            self._alert_run()
        except Exception as e:  # noqa: BLE001 - history and alerts must never break an update
            print(f"couldn't record the run: {e}", file=sys.stderr, flush=True)

    def update(self, run_id=None, action="update", auto=False, reason=None):
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
                self.state = {"id": run_id or time.strftime("%Y%m%d-%H%M%S"), "action": action, "auto": auto,
                              "state": "running", "started_at": round(self.clock()), "finished_at": None,
                              "from": None, "to": None, "result": None, "by": None, "log": []}
            if auto:
                self.log(f"Automatic update: {reason or 'scheduled'}")
            try:
                return self._revert() if self.state.get("action") == "revert" else self._update()
            except Exception as e:  # noqa: BLE001 - always leave a final state for the admin page
                what = "Rollback" if self.state.get("action") == "revert" else "Update"
                self.finish("failed", f"{what} failed: {e}")
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
            self.state["noop"] = True
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
            self.state["notes"] = plan["notes"]
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

    def _revert(self):
        prev = self.app_dir + ".prev"
        if not os.path.isdir(prev):
            self.finish("failed", "There's no previous version to roll back to")
            return self.state
        deployed, target = self.deployed(), self.previous()
        self.state.update(**{"from": (deployed or {}).get("commit") or self.state.get("from"),
                             "to": (target or {}).get("commit") or self.state.get("to")})
        files = tree_diff(self.app_dir, prev)
        plan = self.plan(files)
        name = (target or {}).get("short") or "the previous version"
        self.log(f"{len(files)} changed file{'s' if len(files) != 1 else ''}; restarting: {', '.join(plan['restarts']) or 'nothing'}")
        self._swap(prev)
        self.log(f"Swapped {name} back in")
        try:
            self._apply(plan, self.app_dir)
            healthy = self._healthy(plan)
        except Exception as e:  # noqa: BLE001
            self.log(f"Applying the rollback failed: {e}", "error")
            healthy = False
        if healthy:
            self.finish("succeeded", f"Rolled back to {name}; {(deployed or {}).get('short') or 'the newer version'} "
                                     "is kept as the previous version")
            return self.state
        self.log(f"{name} failed its health check; swapping back", "error")
        self._swap(prev)
        try:
            self._apply(plan, self.app_dir)
            ok = self._healthy(plan)
        except Exception as e:  # noqa: BLE001
            self.log(f"Restart after swapping back failed: {e}", "error")
            ok = False
        self.finish("failed", f"{name} failed its health check, so {(deployed or {}).get('short') or 'the current version'} "
                              "was put back" if ok else
                    "Rollback failed and the server still isn't healthy; check journalctl --user -u music-api")
        return self.state

    def _swap(self, other):
        tmp = self.app_dir + ".swap"
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        os.rename(self.app_dir, tmp)
        os.rename(other, self.app_dir)
        os.rename(tmp, other)

    def previous(self):
        prev = self.app_dir + ".prev"
        if not os.path.isdir(prev):
            return None
        b = _load_json(os.path.join(prev, "BUILD.json"), {})
        sha = b.get("commit") if isinstance(b, dict) else None
        return {"commit": sha, "short": (sha or "")[:7] or None, "subject": b.get("subject") if sha else None,
                "built_at": b.get("built_at") if sha else None}

    def auto_settings(self):
        saved = _load_json(self.settings_path, {})
        saved = saved if isinstance(saved, dict) else {}
        try:
            at = parse_hhmm(saved.get("time") or DEFAULT_AUTO_TIME)
        except UpdateError:
            at = DEFAULT_AUTO_TIME
        return {"enabled": bool(saved.get("enabled", True)), "time": at,
                "updated_by": saved.get("updated_by"), "updated_at": saved.get("updated_at")}

    def save_auto_settings(self, enabled=None, at=None, by=None):
        cur = self.auto_settings()
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise UpdateError("auto must be true or false", 400)
            cur["enabled"] = enabled
        if at is not None:
            cur["time"] = parse_hhmm(at)
        _save_json(self.settings_path, {"enabled": cur["enabled"], "time": cur["time"], "updated_by": by,
                                        "updated_at": round(self.clock())})
        return self.auto_settings()

    def _history_file(self):
        h = _load_json(self.history_path, {})
        return h if isinstance(h, dict) else {}

    def history(self):
        return self._history_file().get("runs") or []

    def record(self, entry, collapse=False):
        h = self._history_file()
        runs = h.get("runs") or []
        last = runs[0] if runs else None
        if collapse and last and last.get("outcome") == "skipped" and last.get("auto") and \
                last.get("result") == entry["result"] and last.get("to") == entry.get("to"):
            entry = {**entry, "count": last.get("count", 1) + 1}
            runs = runs[1:]
        h["runs"] = [entry] + runs[:HISTORY_MAX - 1]
        _save_json(self.history_path, h)

    def _history_entry(self):
        st = self.state
        revert = st.get("action") == "revert"
        if st["state"] == "succeeded":
            outcome = "reverted" if revert else "skipped" if st.get("noop") else "updated"
        else:
            outcome = "rolled_back" if st["state"] == "rolled_back" else "failed"
        return {"id": st["id"], "action": st.get("action") or "update", "auto": bool(st.get("auto")),
                "outcome": outcome, "result": st.get("result"), "from": st.get("from"), "to": st.get("to"),
                "started_at": st.get("started_at"), "at": st.get("finished_at"), "by": st.get("by"),
                "notes": st.get("notes") or []}

    def auto(self):
        """One tick of auto-update.timer. Returns the run's state, a skip entry, or None when there's nothing to do
        this tick (disabled, outside the window, or already tried tonight)."""
        cfg = self.auto_settings()
        if not cfg["enabled"]:
            print("Auto-update is off")
            return None
        night = self.auto_night(cfg["time"])
        if night is None:
            return None
        h = self._history_file()
        if h.get("last_night") == night:
            return None
        h["last_night"] = night
        _save_json(self.history_path, h)
        deployed = self.deployed()
        why, build = None, None
        if self._locked():
            why = "an update was already running"
        else:
            try:
                self.fetch()
                build = self.build_info()
                latest = self._commit(f"refs/remotes/origin/{MAIN}")
                why = self._auto_blocker(deployed, build, latest)
            except UpdateError as e:
                why = f"couldn't fetch from GitHub: {e}"
        if not why:
            safe, reason = self.safe()
            if not safe:
                why = f"not safe to restart: {reason}"
            else:
                print(f"Updating: {reason}", flush=True)
                try:
                    return self.update(f"auto-{time.strftime('%Y%m%d-%H%M%S')}", auto=True, reason=reason)
                except UpdateError as e:
                    why = str(e)
        entry = {"id": f"auto-{night}", "action": "update", "auto": True, "outcome": "skipped",
                 "result": why[:1].upper() + why[1:], "from": (deployed or {}).get("commit"),
                 "to": (build or {}).get("commit"), "started_at": round(self.clock()), "at": round(self.clock()),
                 "by": None, "notes": []}
        self.record(entry, collapse=True)
        print(f"Skipped: {why}", flush=True)
        return entry

    def _auto_blocker(self, deployed, build, latest):
        if not build:
            return "there's no build on GitHub yet"
        if not latest or build["commit"] != latest["commit"]:
            return "GitHub is still building the latest version"
        if deployed and deployed["commit"] == build["commit"]:
            return "already up to date"
        if deployed and deployed.get("dirty"):
            return f"the deployed version ({deployed['short']}) is a local build with uncommitted changes"
        if not deployed or not self._has(deployed["commit"]):
            return "the deployed version isn't a commit on GitHub; update by hand once"
        if self.git("merge-base", "--is-ancestor", deployed["commit"], build["commit"], check=False) is None:
            return f"the build ({build['short']}) isn't newer than the deployed version ({deployed['short']})"
        return None

    def auto_night(self, at, now=None):
        """The date of tonight's auto-update slot when `now` is within AUTO_WINDOW after `at` (local time), else None."""
        dt = datetime.datetime.fromtimestamp(self.clock() if now is None else now)
        h, m = map(int, at.split(":"))
        start = dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if start > dt:
            start -= datetime.timedelta(days=1)
        return start.date().isoformat() if (dt - start).total_seconds() < AUTO_WINDOW else None

    def _env(self, key):
        if key in self.environ:
            return self.environ[key]
        if not hasattr(self, "_env_cache"):
            self._env_cache = read_env_file(self.env_file)
        return self._env_cache.get(key)

    def _alert_run(self):
        st = self.state
        if st.get("action") == "revert":
            return
        to = (st.get("to") or "")[:7] or "the new build"
        kind = "Automatic update" if st.get("auto") else "Update"
        if st.get("auto") and st["state"] in ("rolled_back", "failed"):
            self.alert(f"{kind} to {to} {'was rolled back' if st['state'] == 'rolled_back' else 'failed'}: "
                       f"{st.get('result')}\nSee the Updates tab on the admin page for the log.")
        sudo = [n for n in st.get("notes") or [] if "sudo" in n]
        if st["state"] == "succeeded" and sudo:
            by = "" if st.get("auto") else f" (by {(st.get('by') or {}).get('name') or 'an admin'})"
            self.alert(f"{kind} to {to}{by} needs a manual step on the Pi:\n" + "\n".join(f"- {n}" for n in sudo))

    def admin_keys(self):
        """Slack user IDs or emails, lowercased, as accounts.Admins sees them: SLACK_ADMINS plus admins.json."""
        keys = [k.strip().lower() for k in (self._env("SLACK_ADMINS") or "").split(",") if k.strip()]
        added = _load_json(os.path.join(self.data_dir, "admins.json"), [])
        for e in added if isinstance(added, list) else []:
            k = (e.get("id") or e.get("key") or "").lower() if isinstance(e, dict) else ""
            if k and k not in keys:
                keys.append(k)
        return keys

    def alert(self, text):
        """DM every admin through the Slack bot. Quietly does nothing when Slack isn't configured."""
        token = self._env("SLACK_BOT_TOKEN")
        if not token:
            return 0
        sent, seen = 0, set()
        for key in self.admin_keys():
            uid = key.upper() if "@" not in key else \
                (self.slack(token, "users.lookupByEmail", {"email": key}).get("user") or {}).get("id")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            res = self.slack(token, "chat.postMessage", {"channel": uid, "text": text})
            if res.get("ok"):
                sent += 1
            else:
                print(f"Slack alert to {uid} failed: {res.get('error')}", file=sys.stderr, flush=True)
        return sent

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
        src = os.path.join(app_dir, "deploy", "systemd")
        new = [u for u in plan.get("enable", []) if os.path.exists(os.path.join(src, u))]
        if plan["units"] or new:
            for name in plan["units"] + new:
                shutil.copy2(os.path.join(src, name), os.path.join(self.unit_dir, name))
            self._systemctl("daemon-reload")
            self.log(f"Installed unit files: {', '.join(plan['units'] + new)}")
        for name in new:
            if name.endswith(".timer"):
                self._systemctl("enable", "--now", name)
                self.log(f"Enabled {name}")
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
    ap.add_argument("command", choices=["setup", "status", "update", "revert", "auto"])
    ap.add_argument("--run-id")
    a = ap.parse_args(argv)
    u = Updater()
    try:
        if a.command == "setup":
            pub = u.setup()
            print(f"Bare repo: {u.repo_dir}\nRemote: {u.remote}")
            if pub:
                print("\nAdd this public key on GitHub: repo Settings > Deploy keys > Add deploy key"
                      " (leave 'Allow write access' off):\n\n" + pub + "\n")
            print("Then check it works with: python3 updater.py status")
            return 0
        if a.command == "status":
            print(json.dumps(u.status(fetch=True), indent=1))
            return 0
        if a.command == "auto":
            st = u.auto()
            return 0 if not st or st.get("outcome") == "skipped" or st.get("state") == "succeeded" else 1
        st = u.update(a.run_id, action=a.command)
        return 0 if st["state"] == "succeeded" else 1
    except UpdateError as e:
        sys.stderr.write(f"{e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
