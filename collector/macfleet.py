#!/usr/bin/env python3
"""macfleet-dash collector — zero-dependency health polling for a fleet of Macs.

Python 3.9+ standard library only. Read-only: runs the bundled POSIX probe over
SSH (BatchMode, no sudo), a local shell, or an HTTP metrics endpoint; parses
aggregate hardware/load rows; keeps a rolling history; writes the viewer's
data.json. No secrets, no process lists, nothing that needs elevation.

Usage:
  python3 collector/macfleet.py --live                 # probe now, print table
  python3 collector/macfleet.py --live --json          # probe now, print JSON
  python3 collector/macfleet.py --json                 # print last stored state
  python3 collector/macfleet.py --serve 8780           # serve viewer/ on port
  python3 collector/macfleet.py --selftest             # offline fixture check

Hosts come from macfleet.toml or macfleet.json (auto-discovered in the repo
root or the current directory; override with --config). See README.md.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

VERSION = "0.5.0"
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_PATH = os.path.join(APP_ROOT, "probe", "fleet-probe.sh")
DEFAULT_STATE_PATH = os.path.join(APP_ROOT, "state", "macfleet-state.json")
VIEWER_DIR = os.path.join(APP_ROOT, "viewer")
HISTORY_MAX_POINTS = 288          # 24h at a 5-minute cycle
PROBE_TIMEOUT_S = 45
HTTP_TIMEOUT_S = 8
SSH_CONNECT_TIMEOUT_S = 8

SSH_OPTIONS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=%d" % SSH_CONNECT_TIMEOUT_S,
    "-o", "StrictHostKeyChecking=accept-new",
]


# --------------------------------------------------------------------------
# Configuration (macfleet.toml subset or JSON)
# --------------------------------------------------------------------------

def _strip_toml_comment(line: str) -> str:
    """Drop a trailing comment, respecting double-quoted strings."""
    out, in_str = [], False
    for ch in line:
        if ch == '"':
            in_str = not in_str
        if ch == "#" and not in_str:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_toml_value(text: str) -> Any:
    text = text.strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _parse_simple_toml(text: str) -> Dict[str, Any]:
    """Parse the subset of TOML this app's config uses: [a.b] tables and
    key = "string" | number | bool. No arrays, no inline tables."""
    root: Dict[str, Any] = {}
    table = root
    for raw_line in text.splitlines():
        line = _strip_toml_comment(raw_line).strip()
        if not line:
            continue
        m = re.match(r"^\[\s*([A-Za-z0-9_.\-]+)\s*\]$", line)
        if m:
            table = root
            for part in m.group(1).split("."):
                table = table.setdefault(part, {})
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*=\s*(.+)$", line)
        if m:
            table[m.group(1)] = _parse_toml_value(m.group(2))
    return root


def _normalize_config(data: Dict[str, Any]) -> Dict[str, Any]:
    hosts = data.get("hosts")
    if not isinstance(hosts, dict):
        raise ValueError("config must define a [hosts] table (or \"hosts\" object)")
    normalized: Dict[str, Dict[str, Any]] = {}
    for name, entry in hosts.items():
        if not isinstance(entry, dict):
            continue
        entry = dict(entry)
        entry.setdefault("name", name)
        normalized[name] = entry
    fleet = data.get("fleet") if isinstance(data.get("fleet"), dict) else {}
    return {"interval": data.get("interval"), "fleet": fleet, "hosts": normalized}


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load macfleet.toml or macfleet.json from an explicit path, the current
    directory, or the app root — first match wins."""
    candidates: List[str] = []
    if path:
        candidates.append(path)
    else:
        candidates += [
            os.path.join(os.getcwd(), "macfleet.toml"),
            os.path.join(os.getcwd(), "macfleet.json"),
            os.path.join(APP_ROOT, "macfleet.toml"),
            os.path.join(APP_ROOT, "macfleet.json"),
        ]
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        with open(candidate, "r", encoding="utf-8") as fh:
            text = fh.read()
        if candidate.endswith(".json"):
            data = json.loads(text)
        else:
            data = _parse_simple_toml(text)
        return _normalize_config(data)
    raise FileNotFoundError(
        "no macfleet.toml or macfleet.json found (looked in . and %s)" % APP_ROOT
    )


# --------------------------------------------------------------------------
# Probe runners (same contract as the WCC collector: raw text or raise)
# --------------------------------------------------------------------------

def _probe_script() -> str:
    with open(PROBE_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def probe_host(host: str, method: str = "ssh", url: Optional[str] = None) -> str:
    """Run the read-only fleet probe on one host. Returns raw output; raises
    when the probe does not answer. method: ssh | local | http."""
    if method == "local":
        completed = subprocess.run(
            ["/bin/sh", "-c", _probe_script()],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S,
        )
    elif method == "http":
        target = url or "http://127.0.0.1:8791/metrics.txt"
        try:
            from urllib.request import Request, urlopen
            req = Request(target, headers={"User-Agent": "macfleet-dash/%s" % VERSION})
            with urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - any transport failure is "no answer"
            raise RuntimeError("http probe failed: %s" % str(exc)[:160]) from exc
        completed = subprocess.CompletedProcess(target, 0, raw, "")
    else:  # ssh
        ssh_bin = shutil.which("ssh") or "/usr/bin/ssh"
        completed = subprocess.run(
            [ssh_bin] + SSH_OPTIONS + [host, "/bin/sh", "-s"],
            input=_probe_script(),
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            (completed.stderr or "").strip()[-200:]
            or "probe exit %s" % completed.returncode
        )
    return completed.stdout


# --------------------------------------------------------------------------
# Row parsing — field-for-field the same math as the battle-tested WCC parser
# --------------------------------------------------------------------------

def _parse_probe_fields(raw: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in (raw or "").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()
    return fields


def _first_int(text: Optional[str]) -> Optional[int]:
    match = re.search(r"-?\d+", text or "")
    return int(match.group(0)) if match else None


def parse_fleet_row(host: str, label: str, raw: str, observed_at: str,
                    role: Optional[str] = None, note: Optional[str] = None) -> Dict[str, Any]:
    """Parse one probe payload into a viewer row. Raises RuntimeError when the
    probe did not answer (PROBE_OK missing)."""
    fields = _parse_probe_fields(raw)
    if not fields.get("PROBE_OK"):
        raise RuntimeError("probe script did not answer")
    disk_kb = [int(value) for value in re.findall(r"\d+", fields.get("DISK_K") or "")][:3]
    loads = [float(value) for value in re.findall(r"\d+\.\d+", fields.get("LOADAVG") or "")]
    boot_epoch = _first_int(fields.get("BOOT_EPOCH"))
    uptime_secs = _first_int(fields.get("UPTIME_SECS"))
    if boot_epoch:  # macOS kern.boottime: { sec = N usec = M } — awk $4 keeps sec
        uptime_days = max((time.time() - boot_epoch) / 86400.0, 0.0)
    elif uptime_secs is not None:
        uptime_days = uptime_secs / 86400.0
    else:
        uptime_days = None
    ram_bytes = _first_int(fields.get("MEM_BYTES")) or 0

    # CPU usage: macOS top header (user+sys) or a Linux /proc/stat 1s delta.
    cpu_used_pct = None
    cpu_line = fields.get("CPU_LINE") or ""
    cpu_floats = [float(value) for value in re.findall(r"\d+\.\d+", cpu_line)]
    if "CPU usage" in cpu_line and len(cpu_floats) >= 2:
        cpu_used_pct = round(cpu_floats[0] + cpu_floats[1], 1)
    elif fields.get("CPU_A") and fields.get("CPU_B"):
        a = [int(v) for v in re.findall(r"\d+", fields["CPU_A"])][:2]
        b = [int(v) for v in re.findall(r"\d+", fields["CPU_B"])][:2]
        if len(a) == 2 and len(b) == 2:
            busy = b[0] - a[0]
            total = (b[0] + b[1]) - (a[0] + a[1])
            if total > 0:
                cpu_used_pct = round(busy / total * 100, 1)

    # GPU utilization: IOAccelerator "Device Utilization %" (macOS) or
    # gpu_busy_percent (Linux). Neither needs sudo.
    gpu_raw = fields.get("GPU_UTIL") or ""
    gpu_match = re.search(r'"Device Utilization %"\s*=\s*(\d+)', gpu_raw)
    gpu_util: Optional[int] = int(gpu_match.group(1)) if gpu_match else _first_int(gpu_raw)

    # Memory used: total minus free+speculative pages (macOS, 16K pages on
    # arm64) or total minus MemAvailable (Linux).
    mem_used_gb = None
    if ram_bytes:
        if "macOS" in (fields.get("OS_NAME") or ""):
            page_size = 16384 if fields.get("ARCH") == "arm64" else 4096
            vm_numbers = [int(v) for v in re.findall(r"\d+", fields.get("VMSTAT") or "")]
            if len(vm_numbers) >= 2:
                mem_used_gb = round(
                    (ram_bytes - (vm_numbers[0] + vm_numbers[1]) * page_size) / (1024 ** 3), 1
                )
        else:
            mem_avail = _first_int(fields.get("MEM_AVAIL"))
            if mem_avail:
                mem_used_gb = round((ram_bytes - mem_avail) / (1024 ** 3), 1)

    # Swap: macOS "total = 2048.00M used = 512.00M ..." or Linux "total free" bytes.
    swap_used_gb = None
    swap_raw = fields.get("SWAP") or ""
    swap_match = re.search(r"used\s*=\s*([\d.]+)M", swap_raw)
    if swap_match:
        swap_used_gb = round(float(swap_match.group(1)) / 1024, 1)
    else:
        swap_pair = [int(v) for v in re.findall(r"\d+", swap_raw)][:2]
        if len(swap_pair) == 2 and swap_pair[0] > 0:
            swap_used_gb = round((swap_pair[0] - swap_pair[1]) / (1024 ** 3), 1)

    # Cumulative interface bytes since boot (MB) — compute_rates turns this
    # into per-second rates against the previous snapshot.
    net_pair = [int(v) for v in re.findall(r"\d+", fields.get("NET_B") or "")][:2]
    net_rx_mb = round(net_pair[0] / 1e6, 1) if len(net_pair) == 2 else None
    net_tx_mb = round(net_pair[1] / 1e6, 1) if len(net_pair) == 2 else None

    # Optional root-owned power sampler (power.json written by an approved
    # LaunchDaemon). Absent file = no power data, never a zero.
    power = None
    power_raw = fields.get("POWER_JSON") or ""
    if power_raw.startswith("{"):
        try:
            pdata = json.loads(power_raw)
            if isinstance(pdata, dict) and isinstance(pdata.get("schema"), int) and pdata["schema"] >= 1:
                power = {
                    "cpuW": round(pdata["cpuPowerMw"] / 1000, 1) if pdata.get("cpuPowerMw") is not None else None,
                    "gpuW": round(pdata["gpuPowerMw"] / 1000, 1) if pdata.get("gpuPowerMw") is not None else None,
                    "dieTempC": pdata.get("dieTempC"),
                    "thermalPressure": pdata.get("thermalPressure"),
                    "observedAt": pdata.get("generatedAt"),
                }
        except ValueError:
            power = None

    return {
        "host": host,
        "name": label,
        "role": role,
        "note": note,
        "hostname": fields.get("HOSTNAME") or host,
        "status": "available",
        "observedAt": observed_at,
        "os": fields.get("OS_NAME") or None,
        "arch": fields.get("ARCH") or None,
        "chip": (fields.get("CHIP") or "").strip() or None,
        "ramGb": round(ram_bytes / (1024 ** 3), 1) if ram_bytes else None,
        "memUsedGb": mem_used_gb,
        "swapUsedGb": swap_used_gb,
        "cpuUsedPct": cpu_used_pct,
        "gpuUtilPct": gpu_util,
        "netRxMb": net_rx_mb,
        "netTxMb": net_tx_mb,
        "power": power,
        "diskTotalGb": round(disk_kb[0] / (1024 ** 2), 1) if len(disk_kb) == 3 else None,
        "diskUsedGb": round(disk_kb[1] / (1024 ** 2), 1) if len(disk_kb) == 3 else None,
        "diskFreeGb": round(disk_kb[2] / (1024 ** 2), 1) if len(disk_kb) == 3 else None,
        "load1m": round(loads[0], 2) if loads else None,
        "load5m": round(loads[1], 2) if len(loads) > 1 else None,
        "uptimeDays": round(uptime_days, 1) if uptime_days is not None else None,
    }


def unavailable_row(host: str, label: str, observed_at: str,
                    failure: str, role: Optional[str] = None,
                    note: Optional[str] = None) -> Dict[str, Any]:
    """A host that did not answer reports unavailable — never zero."""
    return {
        "host": host,
        "name": label,
        "role": role,
        "note": note,
        "status": "unavailable",
        "observedAt": observed_at,
        "refreshFailure": str(failure)[:200],
    }


def compute_rates(rows: List[Dict[str, Any]], previous: Optional[Dict[str, Any]]) -> None:
    """Network rates: compare cumulative interface bytes with the previous
    verified snapshot. Negative deltas (counter reset/reboot) stay null."""
    prev_rows = {
        row.get("host"): row
        for row in ((previous or {}).get("hosts") or [])
        if isinstance(row, dict)
    }

    def parse_iso(text: Any) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    for row in rows:
        row.pop("netRxMbps", None)  # stale rates never survive a re-rate
        row.pop("netTxMbps", None)
        if row.get("status") != "available" or row.get("netRxMb") is None:
            continue
        prev = prev_rows.get(row.get("host")) or {}
        if prev.get("status") != "available" or prev.get("netRxMb") is None:
            continue
        observed = parse_iso(row.get("observedAt"))
        prev_at = parse_iso(prev.get("observedAt"))
        if observed is None or prev_at is None:
            continue
        delta_s = (observed - prev_at).total_seconds()
        if delta_s <= 0:
            continue
        rx_delta = row["netRxMb"] - prev["netRxMb"]
        tx_delta = row["netTxMb"] - prev["netTxMb"]
        if rx_delta >= 0:
            row["netRxMbps"] = round(rx_delta * 1e6 / delta_s / 1e6, 2)
        if tx_delta >= 0:
            row["netTxMbps"] = round(tx_delta * 1e6 / delta_s / 1e6, 2)


# --------------------------------------------------------------------------
# History + state
# --------------------------------------------------------------------------

def _point_ts(point: List[Any]) -> float:
    try:
        return datetime.fromisoformat(str(point[0]).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, IndexError):
        return 0.0


def update_history(history: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Append this cycle's available rows to the rolling 24h + 7d history.

    Per host: [observedAt, cpuUsedPct, gpuUtilPct, memUsedGb,
    netRxMbps, netTxMbps, load1m]. "hosts" keeps 288 points (24h at the
    default 5-minute cycle); "week" keeps the same points for 7 days
    (capped at 2100 — the viewer decimates when drawing)."""
    hosts = history.get("hosts") if isinstance(history.get("hosts"), dict) else {}
    week = history.get("week") if isinstance(history.get("week"), dict) else {}
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
    for row in rows:
        if row.get("status") != "available":
            continue
        point = [
            row.get("observedAt"),
            row.get("cpuUsedPct"), row.get("gpuUtilPct"), row.get("memUsedGb"),
            row.get("netRxMbps"), row.get("netTxMbps"), row.get("load1m"),
        ]
        points = hosts.setdefault(row["host"], [])
        points.append(point)
        hosts[row["host"]] = [p for p in points if _point_ts(p) >= cutoff_24h][-HISTORY_MAX_POINTS:]
        week_points = week.setdefault(row["host"], [])
        week_points.append(point)
        week[row["host"]] = [p for p in week_points if _point_ts(p) >= cutoff_7d][-2100:]
    return {"schema": 1, "hosts": hosts, "week": week}


def _state_path(args: argparse.Namespace) -> str:
    return args.state or os.environ.get("MACFLEET_STATE") or DEFAULT_STATE_PATH


def read_state(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {}


def write_state(path: str, state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, path)  # atomic-ish swap; a crash never leaves a torn file


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------

def _host_entries(config: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    return list(config.get("hosts", {}).items())


_TS_CACHE = {"at": 0.0, "data": None}


def _tailscale_presence_cached(max_age_s: int = 300, timeout_s: int = 8, debug: bool = False,
                               via: Optional[str] = None) -> dict:
    """Non-blocking presence: returns the last good result immediately and
    refreshes it in a background thread. The CLI can hang for a long time
    when the collector runs under launchd, so collect() must never wait on it.
    via: optional ssh host to read `tailscale status` from instead (see
    _tailscale_presence_via_ssh).
    """
    import threading
    import time as _time
    now = _time.time()
    if _TS_CACHE["data"] is None or now - _TS_CACHE["at"] > max_age_s:
        def refresh():
            try:
                if via:
                    result = _tailscale_presence_via_ssh(via, debug=debug, timeout_s=timeout_s)
                else:
                    result = _tailscale_presence(debug=debug, timeout_s=timeout_s)
                if result:
                    _TS_CACHE["data"] = result
                    _TS_CACHE["at"] = _time.time()
            except Exception:  # noqa: BLE001 - presence is best-effort
                pass
        threading.Thread(target=refresh, daemon=True).start()
    return _TS_CACHE["data"] or {}


def _parse_presence_lines(stdout: str) -> dict:
    """Parse `tailscale status` text into {interface IP: {online, lastSeen}}."""
    presence = {}
    for line in (stdout or "").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2 or not re.match(r"\d+\.\d+\.\d+\.\d+$", parts[0]):
            continue
        rest = parts[2] if len(parts) > 2 else ""
        if "offline" in rest:
            presence[parts[0]] = {
                "online": False,
                "lastSeen": rest.split("offline,", 1)[-1].strip() or "offline",
            }
        else:
            presence[parts[0]] = {"online": True, "lastSeen": None}
    return presence


def _tailscale_presence_via_ssh(host: str, debug: bool = False, timeout_s: int = 15) -> dict:
    """Read `tailscale status` from another fleet Mac over SSH and return the
    same presence map. Works under launchd, where the local Tailscale CLI's
    XPC IPC hangs; ssh exec on the remote host is a normal session there."""
    ssh_bin = shutil.which("ssh") or "/usr/bin/ssh"
    # Non-interactive shells often lack the Tailscale GUI app in PATH — fall
    # back to the standard macOS app-binary location.
    remote_cmd = 'command -v tailscale >/dev/null 2>&1 && tailscale status || /Applications/Tailscale.app/Contents/MacOS/Tailscale status'
    try:
        completed = subprocess.run(
            [ssh_bin] + SSH_OPTIONS + [host, remote_cmd],
            capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if debug:
            print("macfleet: presence-via-ssh %s -> %s" % (host, exc), file=sys.stderr, flush=True)
        return {}
    if completed.returncode != 0:
        if debug:
            print("macfleet: presence-via-ssh %s rc=%s %s" % (host, completed.returncode, (completed.stderr or "")[:120]), file=sys.stderr, flush=True)
        return {}
    return _parse_presence_lines(completed.stdout)


def _tailscale_presence(debug: bool = False, timeout_s: int = 15) -> dict:
    """Map tailscale interface IP -> {online, lastSeen} from the local CLI.

    Returns {} when the CLI is unavailable; never probes the network.
    """
    for binary in ("/Applications/Tailscale.app/Contents/MacOS/Tailscale", "tailscale"):
        try:
            completed = subprocess.run([binary, "status"], capture_output=True, text=True,
                                       timeout=timeout_s, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            if debug:
                print("macfleet: presence %s -> %s" % (binary, exc), file=sys.stderr, flush=True)
            continue
        if completed.returncode != 0:
            if debug:
                print("macfleet: presence %s rc=%s %s" % (binary, completed.returncode, (completed.stderr or "")[:120]), file=sys.stderr, flush=True)
            continue
        return _parse_presence_lines(completed.stdout)
    return {}


def _fetch_serving(model_url: str) -> Optional[Dict[str, Any]]:
    """Fetch an OpenAI-compatible /v1/models endpoint and return the model id.

    Lets an http-probed host also show what it is serving. Any failure -> None.
    """
    try:
        from urllib.request import Request, urlopen
        req = Request(model_url, headers={"User-Agent": "macfleet-dash/%s" % VERSION})
        with urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        model_id = (data.get("data") or [{}])[0].get("id")
        return {"model": model_id} if model_id else None
    except Exception:  # noqa: BLE001 - serving state is best-effort
        return None


def _bench_tokens(model_url: str, timeout_s: int = 45) -> Optional[Dict[str, Any]]:
    """Measure an end-to-end generation rate from an OpenAI-compatible endpoint.

    Sends one small completion and computes completion_tokens / wall seconds —
    an honest end-to-end figure (includes prompt processing), not a pure
    decode benchmark. Opt-in per host via `bench = true`. Any failure -> None.
    """
    try:
        from urllib.request import Request, urlopen
        ident = _fetch_serving(model_url)
        model_id = (ident or {}).get("model")
        if not model_id:
            return None
        body = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "Count from 1 to 30, digits only."}],
            "max_tokens": 96,
            "temperature": 0,
        }).encode()
        req = Request(model_url.replace("/models", "/chat/completions"),
                      data=body,
                      headers={"User-Agent": "macfleet-dash/%s" % VERSION, "Content-Type": "application/json"})
        started = time.time()
        with urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        elapsed = time.time() - started
        completion_tokens = (data.get("usage") or {}).get("completion_tokens")
        if not completion_tokens or elapsed <= 0:
            return None
        return {
            "tokPerS": round(completion_tokens / elapsed, 1),
            "completionTokens": completion_tokens,
            "wallS": round(elapsed, 2),
        }
    except Exception:  # noqa: BLE001 - benching is best-effort, never fatal
        return None


def collect(config: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """Probe every configured host concurrently; a failed host reports
    unavailable and never blocks the rest of the fleet."""
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = _host_entries(config)
    rows: List[Dict[str, Any]] = []
    failures: List[str] = []
    lock = threading.Lock()

    def probe_one(item: Tuple[str, Dict[str, Any]]) -> None:
        name, entry = item
        label = entry.get("name") or name
        role = entry.get("role")
        note = entry.get("note")
        method = entry.get("method") or "ssh"
        try:
            raw = probe_host(entry.get("host") or name, method, entry.get("url"))
            row = parse_fleet_row(name, label, raw, observed_at, role=role, note=note)
            if entry.get("model_url"):
                serving = _fetch_serving(entry["model_url"])
                if entry.get("bench"):
                    bench = _bench_tokens(entry["model_url"])
                    if bench:
                        serving = dict(serving or {})
                        serving["tokPerS"] = bench["tokPerS"]
                        serving["bench"] = bench
                row["serving"] = serving
        except Exception as exc:  # unreachable host, timeout, probe failure
            with lock:
                failures.append(str(name))
                rows.append(unavailable_row(name, label, observed_at, str(exc), role, note))
            return
        with lock:
            rows.append(row)

    if entries:
        with ThreadPoolExecutor(max_workers=min(4, len(entries))) as pool:
            list(pool.map(probe_one, entries))
    rows.sort(key=lambda r: r["host"])

    compute_rates(rows, state.get("previous"))
    available = sum(1 for row in rows if row.get("status") == "available")

    if (config.get("fleet") or {}).get("tailnet_presence", True):
        fleet_cfg = config.get("fleet") or {}
        presence = _tailscale_presence_cached(debug=bool(os.environ.get("MACFLEET_DEBUG")),
                                              via=fleet_cfg.get("tailnet_via"))
        if os.environ.get("MACFLEET_DEBUG"):
            print("macfleet: presence entries=%d" % len(presence), file=sys.stderr, flush=True)
        for row in rows:
            ts_ip = (config["hosts"][row["host"]] or {}).get("ts_ip") if row["host"] in config.get("hosts", {}) else None
            row["tailnet"] = presence.get(ts_ip) if ts_ip else None

    payload: Dict[str, Any] = {
        "schema": 1,
        "app": "macfleet-dash",
        "version": VERSION,
        "status": "available" if available else "unavailable",
        "observedAt": observed_at,
        "onlineCount": available,
        "totalCount": len(rows),
        "hosts": rows,
        "history": state.get("history") or {"schema": 1, "hosts": {}},
        "source": "Read-only SSH probes (BatchMode, no sudo) + optional HTTP metrics endpoints",
        "integrityBasis": "Live read-only sysctl/df/load aggregates; no credentials, process lists, or secrets",
    }
    if failures:
        payload["refreshFailure"] = "No answer from: " + ", ".join(failures)
    payload["history"] = update_history(payload["history"], rows)

    state["previous"] = payload
    state["history"] = payload["history"]
    state["updatedAt"] = observed_at
    state["version"] = VERSION
    return payload


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

def _fmt(value: Any, suffix: str = "") -> str:
    return "—" if value is None else "%s%s" % (value, suffix)


def print_table(payload: Dict[str, Any]) -> None:
    print("macfleet-dash %s — %s — %d/%d hosts online" % (
        VERSION, payload.get("observedAt") or "—",
        payload.get("onlineCount") or 0, payload.get("totalCount") or 0))
    for row in payload.get("hosts", []):
        if row.get("status") != "available":
            print("  %-12s NO ANSWER — %s" % (row.get("name"), row.get("refreshFailure", "")))
            continue
        print("  %-12s cpu %s%%  gpu %s%%  mem %s/%sGB%s  disk free %sGB  net %s/%s MB/s  load %s  up %sd  (%s)" % (
            row.get("name"),
            _fmt(row.get("cpuUsedPct")), _fmt(row.get("gpuUtilPct")),
            _fmt(row.get("memUsedGb")), _fmt(row.get("ramGb")),
            "" if row.get("swapUsedGb") is None else " +swap %sGB" % row["swapUsedGb"],
            _fmt(row.get("diskFreeGb")),
            _fmt(row.get("netRxMbps")), _fmt(row.get("netTxMbps")),
            _fmt(row.get("load1m")), _fmt(row.get("uptimeDays")),
            row.get("chip") or row.get("os") or "unknown",
        ))


def write_viewer_data(payload: Dict[str, Any]) -> str:
    out = os.path.join(VIEWER_DIR, "data.json")
    os.makedirs(VIEWER_DIR, exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, out)
    return out


# --------------------------------------------------------------------------
# Selftest — fixtures only, zero network
# --------------------------------------------------------------------------

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

GARBAGE_FIXTURE = "ssh: connect to host 10.255.255.1 port 22: Operation timed out\n"


def selftest() -> int:
    """Fixture-based parser check. No network, no ssh, no filesystem writes."""
    checks: List[Tuple[str, bool, str]] = []
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        mac = parse_fleet_row("macstudio", "Mac Studio", MACOS_FIXTURE, at, role="canary")
        checks += [
            ("macos status", mac["status"] == "available", mac["status"]),
            ("macos chip", mac["chip"] == "Apple M4 Pro", mac["chip"]),
            ("macos os", mac["os"] == "macOS 15.2", mac["os"]),
            ("macos ram", mac["ramGb"] == 24.0, mac["ramGb"]),
            ("macos cpu", mac["cpuUsedPct"] == 9.3, mac["cpuUsedPct"]),
            ("macos gpu", mac["gpuUtilPct"] == 7, mac["gpuUtilPct"]),
            ("macos mem", mac["memUsedGb"] == 16.4, mac["memUsedGb"]),
            ("macos swap", mac["swapUsedGb"] == 1.0, mac["swapUsedGb"]),
            ("macos disk free", mac["diskFreeGb"] == 936.8, mac["diskFreeGb"]),
            ("macos net", (mac["netRxMb"], mac["netTxMb"]) == (1234.6, 223.5),
             (mac["netRxMb"], mac["netTxMb"])),
            ("macos load", (mac["load1m"], mac["load5m"]) == (1.71, 2.42),
             (mac["load1m"], mac["load5m"])),
            ("macos boottime sec (not usec)", isinstance(mac["uptimeDays"], float)
             and 0 < mac["uptimeDays"] < 36500, mac["uptimeDays"]),
        ]
    except Exception as exc:  # noqa: BLE001
        checks.append(("macos parse", False, repr(exc)))

    try:
        lin = parse_fleet_row("mbp2013", "2013 MacBook", LINUX_FIXTURE, at)
        checks += [
            ("linux chip", (lin["chip"] or "").strip() == "Intel(R) Core(TM) i7-3667U CPU @ 2.00GHz", lin["chip"]),
            ("linux cpu delta", lin["cpuUsedPct"] == 65.3, lin["cpuUsedPct"]),
            ("linux mem", lin["memUsedGb"] == 6.0, lin["memUsedGb"]),
            ("linux swap", lin["swapUsedGb"] == 1.0, lin["swapUsedGb"]),
            ("linux uptime", lin["uptimeDays"] == 11.4, lin["uptimeDays"]),
            ("linux gpu", lin["gpuUtilPct"] == 12, lin["gpuUtilPct"]),
        ]
    except Exception as exc:  # noqa: BLE001
        checks.append(("linux parse", False, repr(exc)))

    try:
        parse_fleet_row("x", "x", GARBAGE_FIXTURE, at)
        checks.append(("garbage rejected", False, "no exception"))
    except RuntimeError:
        checks.append(("garbage rejected", True, "RuntimeError"))

    prev = {"hosts": [{
        "host": "macstudio", "status": "available",
        "observedAt": "2026-10-10T11:59:00Z", "netRxMb": 1000.0, "netTxMb": 500.0,
    }]}
    rows = [{"host": "macstudio", "status": "available",
             "observedAt": "2026-10-10T12:00:00Z", "netRxMb": 1060.0, "netTxMb": 500.5}]
    compute_rates(rows, prev)
    checks += [
        ("rate rx 60s window", rows[0].get("netRxMbps") == 1.0, rows[0].get("netRxMbps")),
        ("rate tx", rows[0].get("netTxMbps") == 0.01, rows[0].get("netTxMbps")),
    ]
    rows[0]["netRxMb"] = 5.0  # counter reset (reboot)
    compute_rates(rows, prev)
    checks.append(("rate counter reset stays null", "netRxMbps" not in rows[0],
                   rows[0].get("netRxMbps")))

    cfg = _parse_simple_toml('interval = 300  # cycle\n[hosts.mini1]\nmethod = "ssh" # comment\nhost = "you@mini1"\nrole = "Services"')
    checks += [
        ("toml interval", cfg.get("interval") == 300, cfg.get("interval")),
        ("toml host table", cfg["hosts"]["mini1"] == {"method": "ssh", "host": "you@mini1", "role": "Services"},
         cfg["hosts"]["mini1"]),
    ]

    history = update_history({"schema": 1, "hosts": {}}, [
        {"host": "macstudio", "status": "available", "observedAt": at,
         "cpuUsedPct": 9.3, "gpuUtilPct": 7, "memUsedGb": 16.4,
         "netRxMbps": 1.0, "netTxMbps": 0.01, "load1m": 1.71},
        {"host": "down", "status": "unavailable", "observedAt": at},
    ])
    checks += [
        ("history caps at 288", len(history["hosts"]["macstudio"]) == 1
         and len(update_history(history, [])["hosts"].get("down", [])) == 0,
         list(history["hosts"].keys())),
        ("week history keeps 7d and prunes old", len(history["week"]["macstudio"]) == 1
         and history["week"]["macstudio"][0][0] == at
         and len(update_history({"schema": 1, "hosts": {}, "week": {"macstudio": [["2020-01-01T00:00:00Z"] + [None] * 6]}},
                                [{"host": "macstudio", "status": "available", "observedAt": at,
                                  "cpuUsedPct": 9.3, "gpuUtilPct": 7, "memUsedGb": 16.4,
                                  "netRxMbps": 1.0, "netTxMbps": 0.01, "load1m": 1.71}])["week"]["macstudio"]) == 1,
         list(history.get("week", {}).keys())),
    ]

    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print("  %s %s (%s)" % ("ok  " if ok else "FAIL", name, detail))
    print("selftest: %d/%d checks passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macfleet.py",
        description="macfleet-dash collector — read-only fleet health (stdlib only)",
    )
    parser.add_argument("--config", help="path to macfleet.toml or macfleet.json")
    parser.add_argument("--state", help="state file path (default: state/macfleet-state.json)")
    parser.add_argument("--live", action="store_true",
                        help="probe the fleet now (network/ssh). Without it nothing is probed.")
    parser.add_argument("--json", action="store_true",
                        help="print the payload as JSON (fresh with --live, else last state)")
    parser.add_argument("--serve", type=int, metavar="PORT",
                        help="serve the viewer on 127.0.0.1:PORT (writes viewer/data.json first)")
    parser.add_argument("--interval", type=int, default=300, metavar="SECONDS",
                        help="with --serve --live: re-probe every SECONDS (default 300)")
    parser.add_argument("--bind", default="127.0.0.1",
                        help="bind address for --serve (default 127.0.0.1)")
    parser.add_argument("--selftest", action="store_true",
                        help="offline fixture test of the parser; no network")
    return parser


def serve_viewer(port: int, bind: str, payload: Dict[str, Any],
                 refresher: Optional[callable] = None,
                 interval: int = 300) -> int:
    write_viewer_data(payload)
    if refresher is not None:
        def refresh_loop():
            import time
            first = True
            while True:
                # first refresh lands quickly so presence (read asynchronously)
                # is attached without waiting a full interval after startup
                time.sleep(15 if first else max(30, interval))
                first = False
                try:
                    write_viewer_data(refresher())
                except Exception:  # noqa: BLE001 - keep serving the last good data
                    continue
        threading.Thread(target=refresh_loop, daemon=True).start()
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(
        *args, directory=VIEWER_DIR, **kwargs)
    server = ThreadingHTTPServer((bind, port), handler)
    url = "http://%s:%d/" % (bind, port)
    print("macfleet-dash viewer serving %s%s — press Ctrl-C to stop" % (
        url, " (live re-probe every %ss)" % max(30, interval) if refresher else ""))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.selftest:
        return selftest()

    state = read_state(_state_path(args))

    if args.live:
        try:
            config = load_config(args.config)
        except (FileNotFoundError, ValueError) as exc:
            print("error: %s" % exc, file=sys.stderr)
            print("create a macfleet.toml — see README.md", file=sys.stderr)
            return 2
        payload = collect(config, state)
        write_state(_state_path(args), state)
        if not args.json:
            print_table(payload)
    else:
        payload = state.get("previous") or {}
        if not args.json and not args.serve:
            if payload:
                print_table(payload)
                print("(last stored state; run with --live to probe now)")
            else:
                print("no state yet — run: python3 collector/macfleet.py --live")
                return 0

    if args.serve is not None:
        refresher = None
        if args.live:
            def refresher(config=config, state=state):
                fresh = collect(config, state)
                write_state(_state_path(args), state)
                return fresh
        return serve_viewer(args.serve, args.bind, payload, refresher, args.interval)
    if args.json:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
