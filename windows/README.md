# Windows fleet pilot — prepared, not installed

Version 0.1.0 · 2026-10-14. No Windows host has been contacted or enrolled by
this package. The dashboard's Windows page is preparation status, not health.

The first pilot is a one-shot read on one confirmed computer. Keep the actual
host inventory in private operator records; this public package does not
identify or confirm any server or range computer. Do not run a pilot on a
computer with active recovery work or without its existing owner's agreement.

## What it does

`collect-fleet.ps1` uses native local CIM reads for CPU load, visible RAM,
fixed-drive capacity and uptime, plus per-adapter network byte counters.
Named services can be explicitly allowlisted. It does not list processes,
read user files, collect IP/MAC addresses or prompts, accept credentials,
contact remote hosts, open a listener, change firewall/VPN settings, install
software, create a scheduled task or write files. Missing data is null, not 0.
CPU load is a logical-processor-weighted sample, not 24-hour activity.
Network counters are per adapter; virtual and physical adapters are not summed
because that could count the same traffic twice. Storage uses one fixed-drive
capacity basis; sizes are GiB. GPU, temperature, power and backup health are
explicitly not collected in this pilot.

## First host verification (after identity/access approval)

1. Confirm the exact computer name and that its current work can tolerate a
   small read-only diagnostic. Copy this reviewed script through an existing
   approved channel. No transport is established by this package.
2. Run in the host's existing Windows PowerShell 5.1 session:

   ```powershell
   .\collect-fleet.ps1 -ExpectedComputerName 'CONFIRMED-HOST-NAME'
   ```

   The placeholder is deliberately not a real target. The script refuses a
   hostname mismatch before collection. Do not bypass execution policy or
   elevate automatically if local policy blocks it.
3. Compare its timestamp, CPU, memory, fixed-drive used/free/total and uptime
   with Windows. Check every unavailable value; do not replace it with zero.
   Run a second sample to verify network-counter direction without assuming
   a byte counter is a speed reading. Optional service names must be confirmed
   exact names, e.g. `-ServiceName 'A_CONFIRMED_SERVICE'`; no wildcard inputs.
4. Validate the saved JSON with `validate-pilot.py --expected-host NAME PATH`
   on the cockpit. A structurally valid sample is not a persistent collector.
5. Only then decide the existing protected transport and a per-host schedule.
   Verify a natural later sample, reboot persistence and last-seen behavior
   before calling enrollment or unattended monitoring complete.

No install was performed, so there is no service/task/network change to roll
back. Discard a captured pilot JSON through normal file recovery if unneeded.

## Local verification and limits

The JSON validator, arithmetic/unknown-value fixtures and read-only command
inventory are tested locally. This Mac has no PowerShell runtime; actual
PowerShell execution, Windows permissions, physical-host readings and reboot
persistence remain unverified. No sample fixture is injected into live data.

References: [local Get-CimInstance behavior](https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance?view=powershell-5.1),
[processor counters](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processor),
[fixed-drive fields](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-logicaldisk),
[network counters](https://learn.microsoft.com/en-us/powershell/module/netadapter/get-netadapterstatistics?view=windowsserver2025-ps).
