import os
import tempfile
import unittest

import system_stats as ss

STAT_1 = """cpu  1000 0 500 8000 500 0 0 0 0 0
cpu0 250 0 125 2000 125 0 0 0 0 0
cpu1 250 0 125 2000 125 0 0 0 0 0
intr 12345
"""
STAT_2 = """cpu  1600 0 650 8600 650 0 0 0 0 0
cpu0 650 0 125 2100 125 0 0 0 0 0
cpu1 250 0 125 2500 125 0 0 0 0 0
"""
MEMINFO = """MemTotal:         921196 kB
MemFree:           81424 kB
MemAvailable:     460598 kB
Buffers:           31420 kB
SwapTotal:        102396 kB
SwapFree:          92160 kB
"""
IW_LINK = """Connected to 74:fe:ce:81:04:c4 (on wlan0)
\tSSID: Pinewood-IoT
\tfreq: 2437.0
\tRX: 123 bytes (4 packets)
\tsignal: -61 dBm
\trx bitrate: 65.0 MBit/s
\ttx bitrate: 72.2 MBit/s MCS 7 short GI
"""
WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
 wlan0: 0000   49.  -61.  -256        0      0      0     2     25        0
"""
ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
wlan0\t00000000\t0144A8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0
wlan0\t0044A8C0\t00000000\t0001\t0\t0\t600\t00FFFFFF\t0\t0\t0
"""
SHOW_USER = """Id=soloist.service
LoadState=loaded
ActiveState=active
SubState=running
UnitFileState=enabled
ActiveEnterTimestampMonotonic=100000000

Id=music-api.service
LoadState=loaded
ActiveState=active
SubState=running
UnitFileState=enabled
ActiveEnterTimestampMonotonic=200000000

Id=airplay.service
LoadState=loaded
ActiveState=failed
SubState=failed
UnitFileState=enabled
ActiveEnterTimestampMonotonic=0

Id=music-display.service
LoadState=not-found
ActiveState=inactive
SubState=dead
UnitFileState=
ActiveEnterTimestampMonotonic=0

Id=quiet-hours.timer
LoadState=loaded
ActiveState=active
SubState=waiting
UnitFileState=enabled
ActiveEnterTimestampMonotonic=15000000
"""
SHOW_SYSTEM = """Id=cloudflared.service
LoadState=loaded
ActiveState=active
SubState=running
UnitFileState=enabled
ActiveEnterTimestampMonotonic=30000000
"""
JOURNAL = """1791900000.123456 music-api kernel: hwmon hwmon1: Undervoltage detected!
1791900005.000000 music-api kernel: hwmon hwmon1: Voltage normalised
1791900100.500000 music-api kernel: hwmon hwmon1: Undervoltage detected!
"""


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Runner:
    def __init__(self, replies=None):
        self.calls, self.replies = [], replies or {}

    def __call__(self, cmd, timeout=10):
        self.calls.append(cmd)
        for key, reply in self.replies.items():
            if " ".join(cmd).startswith(key):
                return reply(cmd) if callable(reply) else reply
        return None, ""


class Parsers(unittest.TestCase):
    def test_proc_stat_and_busy(self):
        a, b = ss.parse_proc_stat(STAT_1), ss.parse_proc_stat(STAT_2)
        self.assertEqual(a["cpu"], (8500, 10000))
        self.assertEqual(ss.busy_percent(a["cpu"], b["cpu"]), 50.0)
        self.assertEqual(ss.busy_percent(a["cpu0"], b["cpu0"]), 80.0)
        self.assertEqual(ss.busy_percent(a["cpu1"], b["cpu1"]), 0.0)
        self.assertEqual(ss.busy_percent(a["cpu"], a["cpu"]), 0.0)

    def test_meminfo(self):
        m = ss.parse_meminfo(MEMINFO)
        self.assertEqual((m["total"], m["available"], m["used"]), (921196 * 1024, 460598 * 1024, (921196 - 460598) * 1024))
        self.assertEqual((m["percent"], m["swap_used"]), (50.0, 10236 * 1024))

    def test_throttled_bits(self):
        now, since = ss.parse_throttled("0x50005")
        self.assertEqual(now, {"under_voltage": True, "freq_capped": False, "throttled": True, "soft_temp_limit": False})
        self.assertEqual(since, {"under_voltage": True, "freq_capped": False, "throttled": True, "soft_temp_limit": False})
        now, since = ss.parse_throttled("0x80000")
        self.assertFalse(any(now.values()))
        self.assertEqual(since["soft_temp_limit"], True)
        self.assertFalse(any(ss.parse_throttled("0x0")[1].values()))

    def test_wifi(self):
        self.assertEqual(ss.parse_iw_link(IW_LINK), {"bssid": "74:fe:ce:81:04:c4", "ssid": "Pinewood-IoT", "signal_dbm": -61,
                                                     "bitrate_mbps": 72.2, "freq_mhz": 2437})
        self.assertEqual(ss.parse_iw_link("Not connected."), {})
        self.assertEqual(ss.parse_proc_wireless(WIRELESS), {"wlan0": -61})
        self.assertEqual((ss.signal_quality(-61), ss.signal_quality(-30), ss.signal_quality(-120), ss.signal_quality(None)),
                         (78, 100, 0, None))

    def test_misc(self):
        self.assertEqual(ss.default_route_iface(ROUTE), "wlan0")
        self.assertIsNone(ss.default_route_iface("Iface\tDestination\n"))
        self.assertEqual(ss.parse_os_release('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n'), "Ubuntu 24.04.1 LTS")
        units = ss.parse_systemctl_show(SHOW_USER)
        self.assertEqual([u["Id"] for u in units], [u for _, u in ss.USER_UNITS])


class FakePi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.files = {"proc/stat": STAT_1, "proc/meminfo": MEMINFO, "proc/uptime": "1000.50 3000.00\n",
                      "proc/loadavg": "0.52 0.41 0.30 1/200 1234\n", "proc/net/route": ROUTE, "proc/net/wireless": WIRELESS,
                      "proc/device-tree/model": "Raspberry Pi 3 Model B Plus Rev 1.3\0",
                      "sys/class/thermal/thermal_zone0/temp": "54768\n", "sys/class/thermal/thermal_zone0/type": "cpu-thermal\n",
                      "sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq": "1200000\n",
                      "sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq": "1400000\n",
                      "etc/os-release": 'PRETTY_NAME="Ubuntu 24.04.1 LTS"\n'}
        for path, text in self.files.items():
            self.write(path, text)
        self.clock = Clock(10_000.0)
        self.runner = Runner({"systemctl --user show": (0, SHOW_USER), "systemctl show": (0, SHOW_SYSTEM),
                              "iw dev wlan0 link": (0, IW_LINK), "journalctl -k": (0, JOURNAL)})
        self.app = os.path.join(self.root, "app")
        os.makedirs(self.app)
        self.stats = ss.Stats(root=self.root, run=self.runner, clock=self.clock, app_dir=self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, text):
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)

    def test_snapshot(self):
        self.stats.cpu()
        self.write("proc/stat", STAT_2)
        self.clock.t += 2
        snap = self.stats.snapshot()
        self.assertEqual(snap["cpu"]["percent"], 50.0)
        self.assertEqual(snap["cpu"]["cores"], [80.0, 0.0])
        self.assertEqual((snap["cpu"]["count"], snap["cpu"]["freq_mhz"], snap["cpu"]["max_mhz"]), (2, 1200, 1400))
        self.assertEqual((snap["temp_c"], snap["load"], snap["uptime_s"]), (54.8, [0.52, 0.41, 0.3], 1000.5))
        self.assertEqual(snap["model"], "Raspberry Pi 3 Model B Plus Rev 1.3")
        self.assertEqual(snap["memory"]["percent"], 50.0)
        net = snap["network"]
        self.assertEqual((net["interface"], net["ssid"], net["signal_dbm"], net["quality"], net["bitrate_mbps"]),
                         ("wlan0", "Pinewood-IoT", -61, 78, 72.2))
        self.assertEqual(snap["versions"]["os"], "Ubuntu 24.04.1 LTS")
        self.assertIn("history", snap)
        self.assertNotIn("history", self.stats.snapshot(history=False))

    def test_cpu_reads_less_than_half_a_second_apart_reuse_the_last_value(self):
        self.stats.cpu()
        self.write("proc/stat", STAT_2)
        self.clock.t += 0.2
        self.assertIsNone(self.stats.cpu()["percent"])
        self.clock.t += 1
        self.assertEqual(self.stats.cpu()["percent"], 50.0)

    def test_services(self):
        svc = {s["name"]: s for s in self.stats.services()}
        boot = 10_000.0 - 1000.5
        self.assertEqual((svc["soloist"]["state"], svc["soloist"]["since"], svc["soloist"]["restartable"]),
                         ("active", round(boot + 100), True))
        self.assertEqual((svc["music-api"]["restartable"], svc["airplay"]["state"]), (False, "failed"))
        self.assertEqual((svc["music-display"]["state"], svc["music-display"]["sub"], svc["music-display"]["restartable"]),
                         ("unknown", "not installed", False))
        self.assertEqual((svc["cloudflared"]["scope"], svc["cloudflared"]["state"]), ("system", "active"))
        calls = len(self.runner.calls)
        self.stats.services()
        self.assertEqual(len(self.runner.calls), calls)
        self.clock.t += 6
        self.stats.services()
        self.assertGreater(len(self.runner.calls), calls)

    def test_power_from_vcgencmd(self):
        self.runner.replies["vcgencmd get_throttled"] = (0, "throttled=0x50000\n")
        p = self.stats.power()
        self.assertEqual((p["source"], p["raw"]), ("vcgencmd", "0x50000"))
        self.assertFalse(p["now"]["under_voltage"])
        self.assertTrue(p["since_boot"]["under_voltage"])
        self.assertEqual((p["events"], p["last_event_at"]), (2, 1791900100))

    def test_power_prefers_sysfs(self):
        self.write("sys/devices/platform/soc/soc:firmware/get_throttled", "1\n")
        p = self.stats.power()
        self.assertEqual((p["source"], p["raw"], p["now"]["under_voltage"]), ("sysfs", "0x1", True))
        self.assertFalse(any("vcgencmd" in c[0] for c in self.runner.calls))

    def test_power_from_hwmon_remembers_since_boot(self):
        self.write("sys/class/hwmon/hwmon0/name", "cpu_thermal\n")
        self.write("sys/class/hwmon/hwmon1/name", "rpi_volt\n")
        self.write("sys/class/hwmon/hwmon1/in0_lcrit_alarm", "1\n")
        self.runner.replies["journalctl -k"] = (0, "")
        p = self.stats.power()
        self.assertEqual((p["source"], p["now"]["under_voltage"], p["since_boot"]["under_voltage"]), ("hwmon", True, True))
        self.assertIsNone(p["now"]["throttled"])
        self.write("sys/class/hwmon/hwmon1/in0_lcrit_alarm", "0\n")
        p = self.stats.power()
        self.assertEqual((p["now"]["under_voltage"], p["since_boot"]["under_voltage"]), (False, True))

    def test_power_unknown(self):
        self.runner.replies["journalctl -k"] = (None, "")
        p = self.stats.power()
        self.assertEqual((p["source"], p["events"], p["now"]["under_voltage"]), (None, None, None))

    def test_history_ring(self):
        for i in range(ss.HISTORY + 5):
            self.clock.t += 5
            self.stats.sample()
        self.assertEqual(len(self.stats.history), ss.HISTORY)
        self.assertEqual(self.stats.history[-1]["temp"], 54.8)

    def test_versions_from_build_file(self):
        with open(os.path.join(self.app, "BUILD.json"), "w") as f:
            f.write('{"commit": "abcdef1234567", "subject": "Admin: x", "built_at": 5}')
        v = self.stats.versions()
        self.assertEqual((v["commit_short"], v["subject"], v["built_at"]), ("abcdef1", "Admin: x", 5))

    def test_restart_and_logs(self):
        self.runner.replies["systemctl --user restart"] = (0, "")
        self.assertEqual(self.stats.restart("soloist"), {"name": "soloist", "state": "active"})
        self.assertIn(["systemctl", "--user", "restart", "soloist.service"], self.runner.calls)
        with self.assertRaises(ss.StatsError) as e:
            self.stats.restart("music-api")
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(ss.StatsError) as e:
            self.stats.restart("nope")
        self.assertEqual(e.exception.status, 404)
        self.runner.replies["journalctl --user -u airplay.service"] = (0, "line 1\nline 2\n")
        self.runner.replies["journalctl -u cloudflared.service"] = (1, "-- No entries --\n")
        self.assertEqual(self.stats.logs("airplay", 50)["lines"], ["line 1", "line 2"])
        self.assertIn("-n", self.runner.calls[-1])
        cf = self.stats.logs("cloudflared")
        self.assertEqual((cf["lines"], bool(cf["error"])), ([], True))


if __name__ == "__main__":
    unittest.main()
