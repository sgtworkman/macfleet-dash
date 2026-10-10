#!/usr/bin/env python3
"""Fixture-based tests for the macfleet-dash row parser.

Run:  python3 tests/test_parse.py

Stdlib unittest only. Fixtures are recorded-shaped probe payloads — the tests
never ssh anywhere and never touch the network. Expected values are embedded
as literals, computed independently of the parser's own formulas.
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "collector"))

import macfleet  # noqa: E402

AT = "2026-10-10T12:00:00Z"

# macOS probe payload — kern.boottime with the usec trap (awk $4 = sec, the
# usec value must never be mistaken for the epoch), top-style CPU_LINE,
# vm_stat pages, vm.swapusage, netstat -ib bytes, df -k blocks.
MACOS_FIXTURE = "\n".join([
    'PROBE_OK=1',
    'HOSTNAME=studio.local',
    'OS_NAME=macOS 15.2',
    'ARCH=arm64',
    'CHIP=Apple M4 Pro',
    'MEM_BYTES=25769803776',
    'LOADAVG={ 1.71 2.42 2.90 }',
    'BOOT_EPOCH={ sec = 1760000000 usec = 123456 } Mon Oct  9 10:00:00 2026',
    'UPTIME_SECS=',
    'CPU_LINE=CPU usage: 5.20% user, 4.10% sys, 90.70% idle',
    'GPU_UTIL="Device Utilization %"=7',
    'VMSTAT=Pages free: 450000;Pages speculative: 50000;',
    'SWAP=total = 3072.00M used = 1024.00M free = 2048.00M (encrypted)',
    'NET_B=1234567890 223456789',
    'DISK_K=994662936 12345678 982317258',
]) + "\n"

# Linux probe payload — /proc/stat 1s delta for CPU, MemAvailable, byte-swap
# pair, /proc/uptime (BOOT_EPOCH empty), gpu_busy_percent.
LINUX_FIXTURE = "\n".join([
    'PROBE_OK=1',
    'HOSTNAME=mbp2013',
    'OS_NAME=Linux 6.8.0-45-generic',
    'ARCH=x86_64',
    'CHIP=Intel(R) Core(TM) i7-3667U CPU @ 2.00GHz',
    'MEM_BYTES=8589934592',
    'LOADAVG=0.52 0.58 0.59 1/867 12345',
    'BOOT_EPOCH=',
    'UPTIME_SECS=987654',
    'CPU_A=123456789 543210987',
    'CPU_B=124000000 543500000',
    'GPU_UTIL=12',
    'MEM_AVAIL=2147483648',
    'SWAP=2147483648 1073741824',
    'NET_B=5000000000 1000000000',
    'DISK_K=976762584 400000000 576762584',
]) + "\n"

# 2013 MacBook shape: x86_64 macOS (4K pages, not arm64's 16K).
INTEL_MAC_FIXTURE = MACOS_FIXTURE.replace('ARCH=arm64', 'ARCH=x86_64').replace(
    'CHIP=Apple M4 Pro', 'CHIP=i7').replace('HOSTNAME=studio.local', 'HOSTNAME=mbp2013.local')


class TestMacOsRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = macfleet.parse_fleet_row("macstudio", "Mac Studio", MACOS_FIXTURE, AT, role="canary")

    def test_available_and_identity(self):
        self.assertEqual(self.row["status"], "available")
        self.assertEqual(self.row["chip"], "Apple M4 Pro")
        self.assertEqual(self.row["os"], "macOS 15.2")
        self.assertEqual(self.row["arch"], "arm64")
        self.assertEqual(self.row["role"], "canary")
        self.assertEqual(self.row["host"], "macstudio")
        self.assertEqual(self.row["name"], "Mac Studio")

    def test_ram_and_memory_pages_16k_on_arm64(self):
        self.assertEqual(self.row["ramGb"], 24.0)
        # (25769803776 - (450000 + 50000) * 16384) / 2**30 = 16.4
        self.assertEqual(self.row["memUsedGb"], 16.4)

    def test_cpu_from_top_header_user_plus_sys(self):
        self.assertEqual(self.row["cpuUsedPct"], 9.3)

    def test_gpu_from_ioaccelerator(self):
        self.assertEqual(self.row["gpuUtilPct"], 7)

    def test_swap_macos_M_format(self):
        self.assertEqual(self.row["swapUsedGb"], 1.0)  # 1024.00M / 1024

    def test_disk_and_load(self):
        self.assertEqual(self.row["diskTotalGb"], 948.6)
        self.assertEqual(self.row["diskUsedGb"], 11.8)
        self.assertEqual(self.row["diskFreeGb"], 936.8)
        self.assertEqual(self.row["load1m"], 1.71)
        self.assertEqual(self.row["load5m"], 2.42)

    def test_net_cumulative_mb(self):
        self.assertEqual(self.row["netRxMb"], 1234.6)
        self.assertEqual(self.row["netTxMb"], 223.5)

    def test_boot_epoch_sec_not_usec(self):
        # The trap: kern.boottime is "{ sec = 1760000000 usec = 123456 } ...".
        # The parser must take the *first* integer (sec), never the usec, and
        # uptime must be a sane positive number of days, not 2e9 days.
        self.assertGreaterEqual(self.row["uptimeDays"], 0)
        self.assertLess(self.row["uptimeDays"], 36500)
        expected = max((datetime.now(timezone.utc).timestamp() - 1760000000) / 86400.0, 0.0)
        self.assertAlmostEqual(self.row["uptimeDays"], round(expected, 1), delta=0.2)


class TestIntelMacRow(unittest.TestCase):
    def test_4k_pages_on_x86_64(self):
        row = macfleet.parse_fleet_row("mbp2013", "2013 MacBook", INTEL_MAC_FIXTURE, AT)
        # (25769803776 - 500000 * 4096) / 2**30 = 22.1
        self.assertEqual(row["memUsedGb"], 22.1)


class TestLinuxRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = macfleet.parse_fleet_row("mbp2013", "2013 MacBook", LINUX_FIXTURE, AT)

    def test_identity(self):
        self.assertEqual(self.row["status"], "available")
        self.assertEqual(self.row["os"], "Linux 6.8.0-45-generic")
        self.assertEqual(self.row["arch"], "x86_64")
        self.assertEqual((self.row["chip"] or "").strip(),
                         "Intel(R) Core(TM) i7-3667U CPU @ 2.00GHz")
        self.assertEqual(self.row["ramGb"], 8.0)

    def test_cpu_proc_stat_delta(self):
        # busy = 124000000 - 123456789 = 543211
        # total = (124000000 + 543500000) - (123456789 + 543210987) = 832224
        # 543211 / 832224 * 100 = 65.3
        self.assertEqual(self.row["cpuUsedPct"], 65.3)

    def test_memory_from_memavailable(self):
        self.assertEqual(self.row["memUsedGb"], 6.0)

    def test_swap_byte_pair(self):
        self.assertEqual(self.row["swapUsedGb"], 1.0)

    def test_gpu_busy_percent(self):
        self.assertEqual(self.row["gpuUtilPct"], 12)

    def test_uptime_from_proc(self):
        self.assertEqual(self.row["uptimeDays"], 11.4)

    def test_disk_and_net(self):
        self.assertEqual((self.row["diskTotalGb"], self.row["diskUsedGb"],
                          self.row["diskFreeGb"]), (931.5, 381.5, 550.0))
        self.assertEqual(self.row["netRxMb"], 5000.0)
        self.assertEqual(self.row["netTxMb"], 1000.0)


class TestUnavailable(unittest.TestCase):
    def test_missing_probe_ok_raises(self):
        with self.assertRaises(RuntimeError):
            macfleet.parse_fleet_row("x", "X", "ssh: Connection refused\n", AT)

    def test_unavailable_row_shape(self):
        row = macfleet.unavailable_row("x", "X", AT, "probe timeout", role="r")
        self.assertEqual(row["status"], "unavailable")
        self.assertEqual(row["refreshFailure"], "probe timeout")
        self.assertEqual(row["role"], "r")
        self.assertNotIn("cpuUsedPct", row)  # never zero — absent means unknown


class TestRates(unittest.TestCase):
    def test_rate_over_60s_window(self):
        rows = [{"host": "h", "status": "available", "observedAt": "2026-10-10T12:00:00Z",
                 "netRxMb": 1060.0, "netTxMb": 500.5}]
        prev = {"hosts": [{"host": "h", "status": "available",
                           "observedAt": "2026-10-10T11:59:00Z",
                           "netRxMb": 1000.0, "netTxMb": 500.0}]}
        macfleet.compute_rates(rows, prev)
        self.assertEqual(rows[0]["netRxMbps"], 1.0)   # 60 MB over 60 s
        self.assertEqual(rows[0]["netTxMbps"], 0.01)

    def test_counter_reset_stays_null(self):
        rows = [{"host": "h", "status": "available", "observedAt": "2026-10-10T12:00:00Z",
                 "netRxMb": 5.0, "netTxMb": 2.0}]
        prev = {"hosts": [{"host": "h", "status": "available",
                           "observedAt": "2026-10-10T11:59:00Z",
                           "netRxMb": 1000.0, "netTxMb": 500.0}]}
        macfleet.compute_rates(rows, prev)
        self.assertNotIn("netRxMbps", rows[0])
        self.assertNotIn("netTxMbps", rows[0])

    def test_no_previous_snapshot_no_rates(self):
        rows = [{"host": "h", "status": "available", "observedAt": AT, "netRxMb": 1.0, "netTxMb": 1.0}]
        macfleet.compute_rates(rows, None)
        self.assertNotIn("netRxMbps", rows[0])

    def test_unavailable_previous_never_rated(self):
        rows = [{"host": "h", "status": "available", "observedAt": AT, "netRxMb": 2.0, "netTxMb": 2.0}]
        prev = {"hosts": [{"host": "h", "status": "unavailable",
                           "observedAt": "2026-10-10T11:59:00Z", "netRxMb": 1.0, "netTxMb": 1.0}]}
        macfleet.compute_rates(rows, prev)
        self.assertNotIn("netRxMbps", rows[0])


class TestConfigAndHistory(unittest.TestCase):
    def test_toml_subset(self):
        cfg = macfleet._parse_simple_toml(
            'interval = 300  # cycle\n'
            '[hosts.mini1]\nmethod = "ssh"  # no sudo\n'
            'host = "you@mini1"\nrole = "Services · sparkDash host"\n'
            '[hosts.macstudio]\nmethod = "http"\nurl = "http://100.64.0.5:8791/metrics.txt"\n'
        )
        self.assertEqual(cfg["interval"], 300)
        self.assertEqual(cfg["hosts"]["mini1"],
                         {"method": "ssh", "host": "you@mini1", "role": "Services · sparkDash host"})
        self.assertEqual(cfg["hosts"]["macstudio"]["url"],
                         "http://100.64.0.5:8791/metrics.txt")

    def test_json_config(self):
        cfg = macfleet._normalize_config(
            {"hosts": {"mini1": {"method": "ssh", "host": "mini1"}}})
        self.assertEqual(cfg["hosts"]["mini1"]["name"], "mini1")

    def test_history_shape_and_unavailable_skipped(self):
        history = macfleet.update_history({"schema": 1, "hosts": {}}, [
            {"host": "h", "status": "available", "observedAt": AT, "cpuUsedPct": 1.0,
             "gpuUtilPct": None, "memUsedGb": 2.0, "netRxMbps": 0.5, "netTxMbps": 0.1,
             "load1m": 0.5},
            {"host": "down", "status": "unavailable", "observedAt": AT},
        ])
        self.assertEqual(len(history["hosts"]["h"]), 1)
        self.assertNotIn("down", history["hosts"])
        point = history["hosts"]["h"][0]
        self.assertEqual(len(point), 7)
        self.assertEqual(point[0], AT)

    def test_history_capped_at_288(self):
        # 300 in-window points + this cycle's point -> the cap keeps the last 288.
        base = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=23)
        recent = [
            [(base + __import__("datetime").timedelta(minutes=i)).isoformat(),
             1, 2, 3, 4, 5, 6]
            for i in range(300)
        ]
        history = {"schema": 1, "hosts": {"h": list(recent)}}
        result = macfleet.update_history(history, [
            {"host": "h", "status": "available", "observedAt": AT}])
        points = result["hosts"]["h"]
        self.assertEqual(len(points), 288)
        self.assertEqual(points[-1][0], AT)  # newest point survives

    def test_history_prunes_stale_outside_24h(self):
        # 30-hour-old points are dropped by the 24h window, cap or no cap.
        old = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=30)
        stale = [[old.isoformat(), 1, 2, 3, 4, 5, 6]] * 300
        result = macfleet.update_history({"schema": 1, "hosts": {"h": list(stale)}}, [
            {"host": "h", "status": "available", "observedAt": AT}])
        self.assertEqual(len(result["hosts"]["h"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
