# macfleet-dash change log

## [0.3.0] - 2026-10-10

- sparkDash-style layout: fixed left rail with the brand, a per-host nav
  (status dots mirror the probe result; clicking a host expands and scrolls
  to its card), theme toggle, and integrity note; content column has a
  summary stat row. Collapses to a top bar under 940px.

## [0.2.0] - 2026-10-10

- sparkDash-style viewer: amber/dark palette with light theme toggle, utilization bars, status chips, fleet summary header, click-to-expand per-host detail, and 24h sparklines
- Live serve mode: `--serve PORT --live --interval S` re-probes the fleet in a background thread and rewrites data.json; the viewer refetches every 60s
- Serving state: an http host with `model_url` in its config shows the OpenAI-compatible model id it is serving
- Tailnet presence: the collector reads local `tailscale status` and maps hosts by `ts_ip`; hosts show online/offline with last-seen
- Power and die temperature parsed from an optional root-owned sampler JSON (power.json), same as WCC
- Probe re-synced with the battle-tested WCC probe (adds POWER_JSON)

## [0.1.0] - 2026-10-10

- Initial release: POSIX probe (macOS + Linux), stdlib collector with
  ssh/local/http probes, single-file viewer with 24h sparklines, read-only
  tailnet-bound metrics endpoint with a LaunchAgent installer.
- Per-host rows carry chip, os, arch, ram, memory used of total with swap,
  CPU %, GPU %, disk free, network MB/s vs the previous cycle (counter resets
  stay null), load and uptime; a host that does not answer reports
  unavailable, never zero.
- Fixture-based tests and an offline `--selftest` pin the kern.boottime usec
  trap, the /proc/stat CPU delta math and both swap formats.
