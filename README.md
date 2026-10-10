# macfleet-dash

sparkDash-style health dashboard for a fleet of Macs — Apple Silicon + Intel,
macOS + Linux, zero sudo, zero dependencies.

One small collector polls every Mac you register, one probe script answers on
each of them, and a single-file viewer shows CPU, GPU, memory, swap, disk,
network, load and uptime per host — with 24-hour and 7-day sparklines, a ⌘K
command palette, dark/OLED/light themes, serving-model state (with an opt-in
tok/s generation probe), and tailnet presence. Python 3.9+
standard library only: no node_modules, no build step, no third-party runtime
packages anywhere.

```
macfleet-dash/
├── probe/fleet-probe.sh        POSIX probe — answers on macOS AND Linux
├── endpoint/metrics_server.py  read-only /metrics.txt endpoint (for hosts without SSH)
├── endpoint/install.sh         macOS LaunchAgent installer for the endpoint
├── collector/macfleet.py       collector: probes, parses, rates, history, serves viewer
├── viewer/index.html           single-file dashboard (fetches data.json)
└── tests/test_parse.py        fixture-based unit tests (stdlib unittest)
```

## Quickstart

**1. Install the probe on each Mac** — copy `probe/fleet-probe.sh` to the host
(or leave it where the collector can push it). The collector sends the script
over SSH stdin, so nothing needs to be installed for SSH hosts at all.
For hosts reached by HTTP instead (restricted SSH, forced-command only), run
the endpoint there:

```sh
# on that Mac — binds 127.0.0.1:8791 by default; pass your tailnet IP to publish
./endpoint/install.sh 100.64.0.5:8791     # macOS LaunchAgent (com.macfleet.metrics); 100.64.0.5 = this Mac's Tailscale IP
# or by hand, any platform:
python3 endpoint/metrics_server.py 100.64.0.5:8791
```

Verify it answers: `curl http://<bind>:8791/metrics.txt` — you should see
`PROBE_OK=1` and a dozen KEY=VALUE lines.

**2. Register your hosts** — `macfleet.toml` in the repo root (or pass
`--config`):

```toml
interval = 300   # seconds between cycles, if you drive it from cron/launchd

[hosts.mini1]
method = "ssh"                # BatchMode + ConnectTimeout=8, no sudo, no agents
host = "you@mini1"           # anything ssh(1) accepts, incl. ~/.ssh/config aliases
role = "Services · sparkDash host"

[hosts.localhost]
method = "local"              # probe this machine directly

[fleet]
tailnet_presence = true
tailnet_via = "mini1"   # optional: read the peer map from this ssh host (works under launchd)

[hosts.macstudio]
method = "http"               # restricted SSH? poll its metrics endpoint
url = "http://100.64.0.5:8791/metrics.txt"   # endpoint Mac's Tailscale IP
role = "Gemma canary (MLX)"

[hosts.legacy-box]
method = "ssh"
host = "mbp2013"              # the 2013 MacBook — Linux (Omarchy) works too
```

`macfleet.json` works identically if you prefer JSON.

**3. Run the collector** and open the viewer:

```sh
python3 collector/macfleet.py --live          # one cycle; prints a summary table
python3 collector/macfleet.py --serve 8780    # serves viewer/ on http://127.0.0.1:8780
```

For a standing dashboard, schedule a cycle every few minutes and keep the
viewer up:

```sh
# crontab -e : 5-minute cycles
*/5 * * * * cd /path/to/macfleet-dash && python3 collector/macfleet.py --live >/dev/null 2>&1
# then leave this running (launchd KeepAlive or a plain shell):
python3 collector/macfleet.py --serve 8780
```

**4. Check your work:**

```sh
python3 tests/test_parse.py          # unit tests — fixtures only, no network
python3 collector/macfleet.py --selftest
```

Collector flags: `--live` (probe now — nothing is probed without it),
`--json` (payload to stdout), `--serve PORT [--bind IP]` (viewer), `--config`,
`--state`, `--selftest`. State lives in `state/macfleet-state.json`
(override with `--state` or `MACFLEET_STATE`); the viewer reads
`viewer/data.json`, rewritten atomically every cycle. 288 cycles (24 h at a
5-minute cadence) of per-host history are kept for the sparklines.

## Security model

- **Tailnet-bound.** The HTTP endpoint has no authentication — bind it to a
  loopback or tailscale address only. `metrics_server.py` warns and
  `install.sh` documents this; the server never binds 0.0.0.0 by default.
- **Read-only.** The probe runs `sysctl`, `ps`, `top -l`, `ioreg`, `vm_stat`,
  `netstat -ib`, `df -k`, `uptime` and their `/proc`-based Linux equivalents.
  It reads aggregate counters only: no process lists, no file contents, no
  credentials, nothing that needs sudo. The collector's SSH use is
  `BatchMode=yes` with `ConnectTimeout=8` — key-based, non-interactive, no
  password prompts, no agent hacks.
- **No secrets, no outbound calls.** The collector talks only to your hosts;
  the viewer only fetches `data.json`. Nothing phones home.

## Supported probes

| Metric | macOS (Apple Silicon + Intel) | Linux |
| --- | --- | --- |
| Chip | `sysctl machdep.cpu.brand_string` | `/proc/cpuinfo` model name |
| OS / arch | `sw_vers`, `uname -m` | `/etc/os-release`, `uname -r/-m` |
| RAM | `sysctl hw.memsize` | `/proc/meminfo` MemTotal |
| Memory used | total − (free + speculative) pages (`vm_stat`; 16K pages arm64, 4K x86) | total − MemAvailable |
| Swap | `sysctl vm.swapusage` (`used = NN.M`) | SwapTotal − SwapFree |
| CPU % | `top -l 2` header (user + sys) | 1 s `/proc/stat` busy/total delta |
| GPU % | IOKit IOAccelerator `Device Utilization %` (no sudo) | DRM `gpu_busy_percent` |
| Network | `netstat -ib` cumulative Ibytes/Obytes → MB/s vs previous cycle | `/proc/net/dev` (lo excluded) |
| Disk | `df -k /` | `df -k /` |
| Load | `sysctl vm.loadavg` | `/proc/loadavg` |
| Uptime | `kern.boottime` sec (usec trap handled) | `/proc/uptime` |

A host that does not answer reports **unavailable** — never zero — and never
blocks the other hosts. Network counter resets (reboots) produce null rates
rather than false spikes. Sensor temperature and power draw need sudo
`powermetrics` and are deliberately not collected.

## Design notes

- The probe is one POSIX shell script, identical on macOS and Linux, pushed
  via SSH stdin — nothing to install on SSH hosts.
- Parsing is field-for-field the same math battle-tested in the Workman
  Command Center's Mac Fleet panel; `tests/test_parse.py` pins the macOS and
  Linux fixtures, the kern.boottime usec trap, the `/proc/stat` delta math
  and both swap formats.
- The viewer is one HTML file: inline CSS/JS, dark/light via
  `prefers-color-scheme`, inline-SVG sparklines, no framework, no external
  requests beyond `data.json`.

## License

MIT — see [LICENSE](LICENSE). © 2026 Glen Workman.
