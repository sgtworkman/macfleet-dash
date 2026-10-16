# macfleet-dash change log

## [0.9.3] - 2026-10-15

Prepared 2026-10-15 · Codex

- Replace the no-data loading state with first-computer setup, a local-only
  starter configuration download and a published-snapshot connection check.
- Put Workspace before the computer list; add overview shortcuts and a direct
  Edit location action that focuses the chosen computer's field.
- Add multi-select location drafts, explicit browser-only save wording and
  clear shared-setting application instructions. Drafts do not save themselves.
- Add bounded private browser activity for reading-status changes, important
  alerts and effective location changes, plus separate timestamped public
  application notes identifying version and author/agent. Disclose history scope.
- Check actual public archives for private runtime files and unsafe members;
  add fresh-install, bulk-assignment and activity regression coverage.
- Version every transitive browser-module URL, fixing upgrades that could load
  the new interface but retain an older cached model/version after refresh.
- Distinguish failed check times from successful readings on cards and alerts;
  show an unknown last success honestly and expose a safe monitoring failure
  reason in Mac/Linux details without dumping private endpoint errors.
- Keep health collector/probe v0.6.0, existing services, access policy and
  private inventory unchanged. A viewer update does not repair an endpoint,
  wake an offline computer or claim missing telemetry is healthy.

## [0.9.2] - 2026-10-15

Prepared 2026-10-15 · Codex

- Add a Locations screen with editable per-computer labels, browser-persistent
  overrides, explicit save scope, reset and a small shared-settings download.
- Add a standard-library command to apply shared locations with an exact
  private registry backup, atomic writes and concurrent-change preservation.
- Apply shared labels consistently to Mac, Linux, Windows and pending entries;
  keep source locations when no override is configured. Labels do not alter
  telemetry, source identities, enrollment, freshness or resource arithmetic.
- Include a generic configuration example and self-service setup instructions
  in the public release. No real machine inventory or private labels shipped.
- Preserve unsaved edits through automatic data refresh, disclose browser
  storage failures and validate host IDs and location text before saving.
- Viewer-only update: health collector/probe stay v0.6.0; no service restart,
  new writable network endpoint, VPN enrollment or access change is required.

## [0.9.1] - 2026-10-14

Prepared 2026-10-14 · Codex

- Put actionable health warnings before computer cards, within the selected
  location/use filters. Missed updates include the actual last-update age.
- Show each Windows drive's available capacity directly on its computer card;
  combined free space cannot hide a low system drive. Correct drive punctuation.
- Show whether a Windows clock is ahead or behind the receiving cockpit.
- Separate pilots from inventory without a connection while preserving the
  exclusion of both from automatic monitoring and resource totals.
- Replay one timed-out Windows-client OS listener scan without changing its
  timeout or weakening loopback-only, nonempty binding validation. Invalid
  binding results are never retried into success.
- Preserve unknown values and source identity checks. This source release does
  not assert per-host installation, clock repair, scheduled or startup proof.

## [0.9.0] - 2026-10-14

Prepared 2026-10-14 21:20 UTC · Codex

- Add intersecting CCW/classroom, POS and 4473 use/location filters.
- Add an optional ingest-only, stable-device-pinned private Tailscale receiver
  and reviewed native Windows sender/installer. No shared secret, public
  listener, remote-control port, policy bypass or automatic VPN enrollment.
- Keep incoming samples separate from the existing WinRM publisher, with a
  unique-identity merge that replaces pending records and rejects conflicts.
- Show actual pilot readings without counting them as automatic monitoring;
  stale/replayed or rejected samples do not refresh last-seen.
- Preserve all fixed-drive arithmetic, per-adapter counters, source-clock
  warnings and unknown values. No customer, checkout or 4473 records collected.
- Deployment/security approval, natural scheduled updates and startup outcome
  remain per-host operational verification, not claims of this source release.

## [0.8.0] - 2026-10-14

### Added

- One fleet with separate All computers, Mac/Linux, Windows, Servers and Range
  computers views. Location filters intersect the groups without duplicating
  host counts. Pending inventory is visible but excluded from monitored totals.
- Optional private encrypted WinRM bridge executing the reviewed Windows
  collector in memory. It uses existing operator-selected access; no Windows
  install, listener, firewall, VPN or credential changes are performed.
- Individual fixed-drive health and per-adapter network counters/rates in
  Windows details, with last authenticated poll and original Windows timestamp.
- Explicit expected-hours policies for availability warnings. Unknown schedules
  and unverified inventory remain unknown rather than assumed operational.

### Fixed

- Native WinRM command-line limits are handled by a bounded in-memory compressed
  invocation of the same collector, preserving its identity and metric checks.
- Windows clock skew is reported separately from authenticated receipt freshness.
  The original strict one-shot clock validator still rejects future timestamps.
- Failed polls retain last successful timestamps; malformed/duplicate identities
  are rejected instead of overwriting another source's computer or counting
  the same native Windows computer twice. Changed targets do not inherit
  another computer's readings. Reboots invalidate cross-boot network rates.
- Low system-drive space cannot be hidden by another drive's free capacity.

### Coverage and scheduling

- Viewer v0.8.0 and optional bridge v0.1.0; original health collector/probe/endpoint
  remain v0.6.0 and require no restart.
- Optional scheduling needs a verified operator-approved client with existing
  private network access. A successful manual command, installed task, or a
  zero-exit snapshot publication is not proof that unattended host polls work.
- This source release does not enroll a range computer or claim particular
  deployments. Runtime configuration, telemetry and actual machine inventory
  are private, separate from the released source.

## [0.7.0] - 2026-10-14

### Added

- Independently versioned v0.7.0 viewer: sparkDash-style metric panels,
  clear CPU/GPU/memory/storage bars, focused computer details and a compact
  mobile menu. The health collector, probe and endpoint remain v0.6.0.
- Optional 24-hour and 7-day hourly history with a common 0–100% CPU scale,
  sample averages/peaks and explicit missing-hour coverage. The overview's
  CPU squiggles are removed.
- Local-model and cloud/subscription token views from retained local Hermes
  session/model counters. Input, output and cache counters stay separate;
  unclassified sources and incomplete coverage remain visible. Benchmarks
  are separate from token totals and are not passive live throughput.
- A macOS-only, loopback-verified, read-only token publisher for existing
  local scheduling integrations. Private runtime snapshots, host configuration,
  prompt contents, credentials and session identifiers are not release assets.
- A prepared one-shot Windows PowerShell pilot and offline validator. No
  Windows computer is installed/enrolled or counted as healthy by this release.
- JavaScript model/release checks in CI alongside Python 3.9/3.13 tests,
  collector self-tests and secret scanning.

### Fixed

- Storage used/free/total shares one capacity basis; raw APFS filesystem-used
  stays in Details rather than being added to available bytes.
- Missing or malformed hosts, samples, token payloads and timestamps remain
  unverified instead of reporting healthy or zero. Backup-running state
  stays separate from the last completed backup.
- Token result chronology handles whole-second and fractional timestamps
  consistently. The Windows validator accepts the native seven-digit .NET
  fractional timestamp without inventing missing metrics.
- Public pilot guidance uses generic host references instead of internal
  machine inventory or a specific operator's home directory.

### Coverage and upgrade notes

- These are recorded counters on the computer running the publisher, not
  fleet-wide usage, Codex desktop usage, daily allocations or provider invoices.
  No costs or combined input/cache totals are inferred.
- Refresh open browser tabs to load the released viewer. No collector,
  sampler or endpoint restart is required. Keep dashboards loopback/tailnet
  private; do not publish telemetry files or widen a listener for this update.

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
