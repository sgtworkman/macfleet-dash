# macfleet-dash change log

## [0.6.0] - 2026-10-11

### Added

- Backup health: the probe reports Time Machine state on macOS (read-only
  `tmutil destinationinfo` + `tmutil latestbackup`, plus a `pgrep` check for
  `backupd` — no sudo, nothing is started or deleted), and the viewer shows a
  `TM` chip per host: green while the last backup is under 26 h old, amber to
  50 h, red past that or when a configured destination has no backups yet,
  and "TM now" while a backup is running. Expanded host detail adds the last
  backup time (UTC) and destination; the `--live` summary table gains a
  `tm …` field. Hosts without backup data (Linux, or tmutil unavailable)
  show nothing new — absent means unknown, never a fabricated status.
  The collector parses `BACKUP_JSON` behind a `schema >= 1` gate, same
  tolerance rules as `POWER_JSON`.

## [0.5.0] - 2026-10-11

### Fixed

- Power data disappeared from dashboards for sampler users running sampler
  schema 2+: the collector only accepted `schema: 1`. The parser now accepts
  any schema >= 1 with the same field contract, so watts flow again for all
  released sampler versions (old and new).

### Added

- `thermalPressure` in the power block and in the host card's Power &
  thermal line. Apple Silicon's powermetrics exposes no numeric die
  temperature — its thermal sampler reports a pressure level ("Nominal",
  "Moderate", …), which is now surfaced verbatim. `dieTempC` remains in
  the schema and still appears when a platform provides it (Intel Macs);
  on Apple Silicon it stays null rather than a fabricated value.

## [0.4.1] - 2026-10-11

### Fixed

- macOS probes never reported the optional power/thermal values: the
  `POWER_JSON` read sat in the Linux branch of the probe script. It is now
  verbatim back in sync with the reference probe, so sampler users get
  watts on their dashboard. No behavior change without the optional sampler.

## [0.4.0] - 2026-10-10

- Serving-chip generation rate: opt-in `bench = true` per host runs one small
  completion per cycle and shows end-to-end tok/s next to the model id.
- 7-day history: the collector keeps a second, 7-day series per host and the
  viewer has a 24h/7d toggle (long series are decimated when drawn).
- ⌘K / Ctrl+K command palette: jump to any host, fleet overview, theme, refresh.
- OLED theme (true black); the theme button cycles dark → OLED → light.

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
