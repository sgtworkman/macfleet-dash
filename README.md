# macfleet-dash

[![CI](https://github.com/sgtworkman/macfleet-dash/actions/workflows/ci.yml/badge.svg)](https://github.com/sgtworkman/macfleet-dash/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

sparkDash-style health dashboard for a fleet of Macs — Apple Silicon + Intel,
macOS + Linux, zero sudo, zero dependencies.

**Viewer release v0.7.0.** The health collector and probe remain v0.6.0;
their existing protocol and running services are unchanged. See the
[change log](CHANGELOG.md) and [release notes](https://github.com/sgtworkman/macfleet-dash/releases/tag/v0.7.0).

The screenshots below are synthetic examples from the earlier viewer.
Version 0.7.0 uses resource bars and hourly history instead of overview CPU lines.

![macfleet-dash fleet view](docs/screenshot.png)

One small collector polls every Mac you register, one probe script answers on
each of them, and a static viewer shows CPU, GPU, memory, swap, disk,
network, load and uptime per host — with clear resource bars, focused details,
24-hour and 7-day hourly activity, a ⌘K command palette, dark/OLED/light themes,
serving-model state (with an opt-in end-to-end completion benchmark), tailnet presence, and Time Machine backup health on
macOS. Python 3.9+
standard library only: no node_modules, no build step, no third-party runtime
packages anywhere.

Focused host detail — full metrics, optional hourly history, benchmark rate and (where the
owner approved a sampler) power/thermal:

![expanded host detail](docs/detail.png)

```
macfleet-dash/
├── probe/fleet-probe.sh        POSIX probe — answers on macOS AND Linux
├── endpoint/metrics_server.py  read-only /metrics.txt endpoint (for hosts without SSH)
├── endpoint/install.sh         macOS LaunchAgent installer for the endpoint
├── collector/macfleet.py       collector: probes, parses, rates, history, serves viewer
├── viewer/index.html           static dashboard shell
├── viewer/fleet-app.mjs        rendering/controls; reads local snapshots only
├── viewer/fleet-model.mjs      validated metrics and fixed-scale hourly history
├── collector/token_usage.py   aggregate-only read of local Hermes usage
├── collector/publish_token_usage.py  private token snapshot; existing WCC cadence
├── windows/                   prepared one-shot Windows pilot, not enrolled
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
python3 -m unittest discover -s tests -p 'test_*.py'  # fixture tests; no network
python3 collector/macfleet.py --selftest
node --test tests/*.test.mjs         # development checks; Node 22+, not a runtime dependency
```

Collector flags: `--live` (probe now — nothing is probed without it),
`--json` (payload to stdout), `--serve PORT [--bind IP]` (viewer), `--config`,
`--state`, `--selftest`. State lives in `state/macfleet-state.json`
(override with `--state` or `MACFLEET_STATE`); the viewer reads
`viewer/data.json`, rewritten atomically every cycle. 288 cycles (24 h at a
5-minute cadence) of per-host history are kept, plus bounded 7-day history.

## Security model

- **Tailnet-bound.** The HTTP endpoint has no authentication — bind it to a
  loopback or tailscale address only. `metrics_server.py` warns and
  `install.sh` documents this; the server never binds 0.0.0.0 by default.
- **Read-only.** The probe runs `sysctl`, `ps`, `top -l`, `ioreg`, `vm_stat`,
  `netstat -ib`, `df -k`, `uptime`, `tmutil` (destination info + latest backup
  lookup only — never starts or deletes a backup) and their `/proc`-based
  Linux equivalents.
  It reads aggregate counters only: no process lists, no file contents, no
  credentials, nothing that needs sudo. The collector's SSH use is
  `BatchMode=yes` with `ConnectTimeout=8` — key-based, non-interactive, no
  password prompts, no agent hacks.
- **No secrets.** The viewer fetches only local `data.json` and `token-usage.json`.
  The collector talks only to registered hosts. An already opted-in benchmark
  sends one fixed short completion; it is not passive traffic measurement.

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
| Backup health | `tmutil destinationinfo` + `tmutil latestbackup` (last backup age, destination, running state) | — (not reported) |

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
- The viewer is static HTML/CSS/native JavaScript modules: no framework, no
  runtime dependencies and no external browser requests. Overview has no CPU
  line graphs. Hourly CPU bars use the same 0–100% scale and disclose missing
  hours and sample counts. Unknown values are not rendered as zero.

## Viewer release v0.7.0 · 2026-10-14

The viewer is versioned independently of the unchanged running collector
(v0.6.0). This update needs no service restart. Source freshness remains
separate from viewer version. Storage capacity used is total minus available;
raw filesystem-used remains in Details to explain APFS shared-container space.

Tokens reads the existing local Hermes `session_model_usage` table, including
immediate profile databases only. A retained profile is not proof of a running agent. No messages, prompts, credentials,
session IDs or billing URLs are exported. Profile aliases and migrated duplicate
session/model records are counted once. Local and cloud/subscription categories
come from saved endpoints, not model names or guessed prices. Record timestamps
are not daily allocation, lifetime counts or provider invoices. Historical
model attribution may be a session's last saved model, not each prior call.
Recorded input, output, cache-read and cache-write counters stay separate; no
combined total is inferred across legacy/subscription accounting. The MLX
benchmark is separate from both usage and all-service traffic totals.

The Workman Command Center integration invokes `collector/publish_token_usage.py`
after its existing local refresh. This optional macOS publisher expects an
already-running loopback viewer on port 8791 and the private `macfleet.toml`
configuration; it does not install a scheduler or start a viewer. Other
installations must explicitly configure their own local invocation before
calling token coverage available. The publisher verifies the loopback listener,
reads SQLite in `mode=ro`, and atomically replaces the gitignored, mode-0600
`viewer/token-usage.json`. A failed read preserves the previous timestamp;
the viewer marks token snapshots older than 10 minutes stale. No new job,
Hermes config change, remote install or listener widening is included. Do not
publish that private runtime snapshot or widen the viewer binding.

Offline checks: `node --test tests/*.test.mjs` and
`python3 -m unittest discover -s tests -p 'test_*.py'`. The Windows package is
preparation only; see [pilot limits and verification](windows/README.md).

## License

MIT — see [LICENSE](LICENSE). © 2026 Glen Workman.
