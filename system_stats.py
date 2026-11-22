"""System health for the admin page: CPU, temperature, power and throttling, memory, disk, Wi-Fi, services, versions.

Everything comes from /proc and /sys except a few cached subprocesses (systemctl, iw, vcgencmd, journalctl), so a
2 s poll stays cheap on a Pi 3. A background sampler keeps ~10 minutes of CPU and temperature history.
"""
import collections
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
USER_UNITS = [("soloist", "soloist.service"), ("music-api", "music-api.service"), ("airplay", "airplay.service"),
              ("music-display", "music-display.service"), ("quiet-hours", "quiet-hours.timer")]
SYSTEM_UNITS = [("cloudflared", "cloudflared.service")]
RESTARTABLE = {"soloist", "airplay", "music-display"}
SAMPLE_EVERY = 5
HISTORY = 120
THROTTLE_BITS = {"under_voltage": 0, "freq_capped": 1, "throttled": 2, "soft_temp_limit": 3}
UNDERVOLTAGE = re.compile(r"under-?voltage detected", re.I)


class StatsError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _run(cmd, timeout=10):
    """(returncode, stdout); (None, "") when the command is missing or hangs."""
    if not shutil.which(cmd[0]):
        return None, ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, ""


def parse_proc_stat(text):
    """{"cpu": (idle, total), "cpu0": ...} in jiffies."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith("cpu"):
            continue
        vals = [int(v) for v in parts[1:9]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        out[parts[0]] = (idle, sum(vals))
    return out


def busy_percent(prev, cur):
    d_total = cur[1] - prev[1]
    if d_total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (d_total - (cur[0] - prev[0])) / d_total)), 1)


def parse_meminfo(text):
    kb = {}
    for line in text.splitlines():
        m = re.match(r"(\w+):\s+(\d+)", line)
        if m:
            kb[m.group(1)] = int(m.group(2)) * 1024
    total = kb.get("MemTotal", 0)
    available = kb.get("MemAvailable", kb.get("MemFree", 0))
    used = total - available
    return {"total": total, "available": available, "used": used,
            "percent": round(100.0 * used / total, 1) if total else 0.0,
            "swap_total": kb.get("SwapTotal", 0), "swap_used": kb.get("SwapTotal", 0) - kb.get("SwapFree", 0)}


def parse_throttled(value):
    """Firmware get_throttled bits: 0-3 happening now, 16-19 the same since boot."""
    n = int(value, 16) if isinstance(value, str) else int(value)
    return ({k: bool(n >> b & 1) for k, b in THROTTLE_BITS.items()},
            {k: bool(n >> (b + 16) & 1) for k, b in THROTTLE_BITS.items()})


def parse_iw_link(text):
    out = {}
    m = re.search(r"Connected to ([0-9a-f:]{17})", text, re.I)
    if m:
        out["bssid"] = m.group(1).lower()
    for key, rx, conv in (("ssid", r"^\s*SSID: (.*)$", str), ("signal_dbm", r"signal: (-?\d+)", int),
                          ("bitrate_mbps", r"tx bitrate: ([\d.]+) MBit/s", float), ("freq_mhz", r"freq: ([\d.]+)", float)):
        m = re.search(rx, text, re.M)
        if m:
            out[key] = conv(m.group(1).strip())
    if "freq_mhz" in out:
        out["freq_mhz"] = int(out["freq_mhz"])
    return out


def parse_proc_wireless(text):
    """{iface: signal dBm} from /proc/net/wireless."""
    out = {}
    for line in text.splitlines()[2:]:
        m = re.match(r"\s*(\w+):\s+\S+\s+([-\d.]+)\.?\s+([-\d.]+)\.?", line)
        if m:
            out[m.group(1)] = int(float(m.group(3)))
    return out


def signal_quality(dbm):
    return None if dbm is None else max(0, min(100, 2 * (dbm + 100)))


def parse_systemctl_show(text):
    units, cur = [], {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur:
                units.append(cur)
            cur = {}
            continue
        k, _, v = line.partition("=")
        cur[k] = v
    return units


def parse_os_release(text):
    m = re.search(r'^PRETTY_NAME="?([^"\n]*)"?', text, re.M)
    return m.group(1) if m else None


def default_route_iface(text):
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 2 and parts[1] == "00000000":
            return parts[0]
    return None


class Stats:
    def __init__(self, root="/", run=_run, clock=time.time, app_dir=HERE):
        self.root, self.run, self.clock, self.app_dir = root, run, clock, app_dir
        self.lock = threading.Lock()
        self.history = collections.deque(maxlen=HISTORY)
        self._prev = None
        self._cpu = {"percent": None, "cores": []}
        self._cache = {}
        self._uv_seen = False

    def _read(self, path):
        try:
            with open(os.path.join(self.root, path.lstrip("/"))) as f:
                return f.read()
        except OSError:
            return None

    def _cached(self, key, ttl, fn):
        now = self.clock()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        val = fn()
        self._cache[key] = (now + ttl, val)
        return val

    def cpu(self):
        text = self._read("/proc/stat")
        if not text:
            return self._cpu
        now, cur = self.clock(), parse_proc_stat(text)
        with self.lock:
            if self._prev and now - self._prev[0] >= 0.5:
                prev = self._prev[1]
                cores = sorted((k for k in cur if k != "cpu" and k in prev), key=lambda k: int(k[3:]))
                self._cpu = {"percent": busy_percent(prev["cpu"], cur["cpu"]) if "cpu" in prev else None,
                             "cores": [busy_percent(prev[k], cur[k]) for k in cores]}
            if not self._prev or now - self._prev[0] >= 0.5:
                self._prev = (now, cur)
            return self._cpu

    def temperature(self):
        best = None
        for i in range(8):
            raw = self._read(f"/sys/class/thermal/thermal_zone{i}/temp")
            if raw is None:
                break
            kind = (self._read(f"/sys/class/thermal/thermal_zone{i}/type") or "").strip()
            try:
                c = round(int(raw.strip()) / 1000, 1)
            except ValueError:
                continue
            if best is None or "cpu" in kind or "soc" in kind:
                best = c
                if "cpu" in kind or "soc" in kind:
                    break
        return best

    def _hwmon_alarm(self):
        for i in range(10):
            name = self._read(f"/sys/class/hwmon/hwmon{i}/name")
            if name is None:
                continue
            if name.strip() == "rpi_volt":
                raw = self._read(f"/sys/class/hwmon/hwmon{i}/in0_lcrit_alarm")
                return None if raw is None else raw.strip() == "1"
        return None

    def _undervoltage_events(self):
        rc, out = self.run(["journalctl", "-k", "-b", "--no-pager", "-o", "short-unix", "--grep", "voltage"])
        if rc is None or (rc != 0 and not out):
            rc, out = self.run(["journalctl", "-k", "-b", "--no-pager", "-o", "short-unix", "-n", "3000"])
            if rc is None:
                return None, None
        hits = [line for line in out.splitlines() if UNDERVOLTAGE.search(line)]
        last = None
        if hits:
            try:
                last = round(float(hits[-1].split()[0]))
            except (ValueError, IndexError):
                pass
        return len(hits), last

    def power(self):
        raw, source = None, None
        sysfs = self._read("/sys/devices/platform/soc/soc:firmware/get_throttled")
        if sysfs and sysfs.strip():
            raw, source = sysfs.strip(), "sysfs"
        else:
            def vcgencmd():
                rc, out = self.run(["vcgencmd", "get_throttled"], timeout=5)
                m = re.search(r"throttled=(0x[0-9a-fA-F]+)", out or "") if rc == 0 else None
                return m.group(1) if m else None
            raw = self._cached("vcgencmd", 10, vcgencmd)
            source = "vcgencmd" if raw else None
        events, last = self._cached("uv_events", 60, self._undervoltage_events)
        unknown = dict.fromkeys(THROTTLE_BITS)
        if raw:
            raw = raw if raw.startswith("0x") else "0x" + raw
            now, since = parse_throttled(raw)
        else:
            now, since = dict(unknown), dict(unknown)
            alarm = self._hwmon_alarm()
            if alarm is not None:
                source = "hwmon"
                self._uv_seen = self._uv_seen or alarm
                now["under_voltage"] = alarm
                since["under_voltage"] = self._uv_seen or bool(events)
        return {"source": source, "raw": raw, "now": now, "since_boot": since, "events": events, "last_event_at": last}

    def memory(self):
        text = self._read("/proc/meminfo")
        return parse_meminfo(text) if text else None

    def disk(self, path="/"):
        try:
            st = os.statvfs(os.path.join(self.root, path.lstrip("/")) if self.root != "/" else path)
        except OSError:
            return None
        total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        used = total - st.f_bfree * st.f_frsize
        return {"path": path, "total": total, "used": used, "free": free,
                "percent": round(100.0 * used / total, 1) if total else 0.0}

    def network(self):
        iface = default_route_iface(self._read("/proc/net/route") or "")
        wireless = parse_proc_wireless(self._read("/proc/net/wireless") or "")
        if not iface and wireless:
            iface = next(iter(wireless))
        out = {"interface": iface, "ip": self._cached("ip", 30, self._local_ip), "ssid": None, "bssid": None,
               "signal_dbm": wireless.get(iface), "quality": None, "bitrate_mbps": None, "freq_mhz": None}
        if iface and iface in wireless:
            def iw():
                rc, text = self.run(["iw", "dev", iface, "link"], timeout=5)
                return parse_iw_link(text) if rc == 0 else {}
            out.update(self._cached("iw", 10, iw))
        out["quality"] = signal_quality(out["signal_dbm"])
        return out

    @staticmethod
    def _local_ip():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 9))  # UDP connect picks the outbound address without sending anything
                return s.getsockname()[0]
        except OSError:
            return None

    def uptime(self):
        raw = self._read("/proc/uptime")
        try:
            return float(raw.split()[0]) if raw else None
        except ValueError:
            return None

    def services(self):
        return self._cached("services", 5, self._services)

    def _services(self):
        uptime = self.uptime()
        boot = self.clock() - uptime if uptime is not None else None
        props = "Id,LoadState,ActiveState,SubState,UnitFileState,ActiveEnterTimestampMonotonic"
        out = []
        for scope, units in (("user", USER_UNITS), ("system", SYSTEM_UNITS)):
            cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + ["show", "-p", props, "--"]
            rc, text = self.run(cmd + [u for _, u in units])
            shown = {u.get("Id"): u for u in parse_systemctl_show(text)} if rc is not None else {}
            for name, unit in units:
                u = shown.get(unit) or {}
                found = u and u.get("LoadState") != "not-found"
                mono = int(u.get("ActiveEnterTimestampMonotonic") or 0)
                out.append({"name": name, "unit": unit, "scope": scope,
                            "state": u.get("ActiveState", "unknown") if found else "unknown",
                            "sub": (u.get("SubState") or None) if found else ("not installed" if u else None),
                            "since": round(boot + mono / 1e6) if boot is not None and mono and found else None,
                            "enabled": (u.get("UnitFileState") or None) if found else None,
                            "restartable": bool(found) and name in RESTARTABLE})
        return out

    def build(self):
        info = {}
        try:
            with open(os.path.join(self.app_dir, "BUILD.json")) as f:
                info = json.load(f)
        except (OSError, ValueError):
            rc, out = self.run(["git", "-C", self.app_dir, "log", "-1", "--format=%H%x00%s%x00%ct"])
            if rc == 0 and out.count("\0") == 2:
                sha, subject, ts = out.strip().split("\0")
                info = {"commit": sha, "subject": subject, "date": int(ts)}
        return info

    def versions(self):
        def slow():
            soloist = os.environ.get("SOLOIST_BIN") or os.path.expanduser("~/.local/bin/soloist")
            rc, out = self.run([soloist, "--version"], timeout=5) if os.path.exists(soloist) else (None, "")
            shairport = None
            rc2, out2 = self.run(["shairport-sync", "-V"], timeout=5)
            if rc2 is not None and out2.strip():
                shairport = out2.strip().split("-")[0]
            return {"soloist": (out.strip().splitlines() or [None])[0] if rc == 0 else None, "shairport_sync": shairport,
                    "os": parse_os_release(self._read("/etc/os-release") or "")}
        b = self.build()
        commit = b.get("commit")
        return {"commit": commit, "commit_short": commit[:7] if commit else None, "subject": b.get("subject"),
                "built_at": b.get("built_at"), "python": platform.python_version(), "kernel": platform.release(),
                **self._cached("versions", 600, slow)}

    def model(self):
        raw = self._read("/proc/device-tree/model") or self._read("/sys/firmware/devicetree/base/model")
        return raw.strip("\0\n ") if raw else None

    def frequency(self):
        def mhz(path):
            raw = self._read(path)
            try:
                return round(int(raw.strip()) / 1000) if raw else None
            except ValueError:
                return None
        return (mhz("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"),
                mhz("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"))

    def sample(self):
        cpu, temp = self.cpu(), self.temperature()
        if self._hwmon_alarm():
            self._uv_seen = True
        self.history.append({"t": round(self.clock()), "cpu": cpu["percent"], "temp": temp})

    def loop(self):
        while True:
            try:
                self.sample()
            except Exception as e:  # noqa: BLE001 - history is best effort
                sys.stderr.write(f"stats: {e!r}\n")
            time.sleep(SAMPLE_EVERY)

    def snapshot(self, history=True):
        cpu = self.cpu()
        cur, top = self.frequency()
        load = (self._read("/proc/loadavg") or "").split()[:3]
        out = {"sampled_at": round(self.clock(), 3), "hostname": socket.gethostname(), "model": self.model(),
               "uptime_s": self.uptime(),
               "cpu": {**cpu, "count": len(cpu["cores"]) or os.cpu_count(), "freq_mhz": cur, "max_mhz": top},
               "load": [float(v) for v in load] if len(load) == 3 else None,
               "temp_c": self.temperature(), "power": self.power(), "memory": self.memory(), "disk": self.disk(),
               "network": self.network(), "services": self.services(), "versions": self.versions()}
        if history:
            out["history"] = list(self.history)
        return out

    def _unit(self, name):
        for scope, units in (("user", USER_UNITS), ("system", SYSTEM_UNITS)):
            for n, unit in units:
                if n == name:
                    return scope, unit
        raise StatsError(f"unknown service {name!r}", 404)

    def restart(self, name):
        scope, unit = self._unit(name)
        if name not in RESTARTABLE:
            raise StatsError(f"{name} can't be restarted from here", 403)
        rc, _ = self.run(["systemctl", "--user", "restart", unit], timeout=60)
        if rc is None:
            raise StatsError("systemctl isn't available on this server", 503)
        self._cache.pop("services", None)
        state = next((s for s in self.services() if s["name"] == name), {})
        if rc != 0:
            raise StatsError(f"couldn't restart {unit} (state: {state.get('state', 'unknown')}); see its logs", 502)
        return {"name": name, "state": state.get("state")}

    def logs(self, name, lines=200):
        scope, unit = self._unit(name)
        lines = max(1, min(int(lines), 1000))
        cmd = ["journalctl"] + (["--user"] if scope == "user" else []) + \
              ["-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"]
        rc, out = self.run(cmd, timeout=15)
        if rc is None:
            return {"name": name, "unit": unit, "lines": [], "error": "journalctl isn't available on this server"}
        rows = [line for line in out.splitlines() if line.strip() and not line.startswith("-- ")]
        error = None if rc == 0 or rows else f"journalctl exited with {rc} (no permission to read this unit's logs?)"
        return {"name": name, "unit": unit, "lines": rows[-lines:], "error": error}
