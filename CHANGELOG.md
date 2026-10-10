# macfleet-dash change log

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
