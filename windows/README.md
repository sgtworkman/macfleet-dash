# Windows monitoring — private bridge and local pilot

Bridge/receiver/sender version 0.1.0 · viewer release v0.9.0 · 2026-10-14.

## Private Tailnet push · v0.9.0

`collector/tailnet_receiver.py` is an optional, ingest-only receiver. It binds
one exact verified local Tailscale IPv4 address in `100.64.0.0/10`, on a dedicated
unprivileged port other than the viewer's 8791. It refuses public, wildcard,
ordinary LAN and loopback addresses. The selected local `tailscale whois --json`
must verify the collector stable ID before startup. Each POST must come directly
from an allowlisted address AND its currently authenticated stable node ID.
Proxy/forwarded headers are never identity. No account data, API keys or
credentials are published. Plain HTTP exists only inside the encrypted tailnet.
No public exposure/Funnel, subnet routes or exit nodes are enabled by this code.
If the local Tailscale CLI cannot answer from a background job, optional
`--identity-via AN_EXISTING_TRUSTED_SSH_ALIAS` performs only the same bounded
`whois` read through that existing management connection. SSH host-key checking
and BatchMode remain required; it creates no key, account or access permission.
The existing lookup host must be on the same tailnet and be trusted to supply
identity evidence. Test that route in its actual scheduled context too.

Use an owner-only, private `tailnet-fleet.json` with schema
`macfleet.tailnet.config.v1`, `bindAddress`, integer `port`, `collectorNodeId`,
and `hosts`. Each confirmed host needs unique `id`, exact `expectedComputerName`,
`nodeId`, `address`, `kind` (`range`, `server`, `computer`), `site`, optional
`purpose` (`ccw`, `pos`, `4473`, `other`) and an exact `services` allowlist.
`automaticVerified` defaults false: accepted readings are pilots, not automatic
coverage. Set true only after native task readback and a naturally scheduled
delivery are independently verified. Configuration is reread on requests;
listener address/port/identity changes require an explicit restart. Removing a
peer stops acceptance; revoke its policy grant as part of offboarding too.

```sh
python3 collector/tailnet_receiver.py --config /private/tailnet-fleet.json
```

It owns only `viewer/tailnet-windows.json`, with atomic mode-0600 publication and
one non-overlapping receiver lock. The original WinRM publisher still owns
`windows.json`. The viewer performs the unique-identity merge, so a later WinRM
run cannot overwrite a confirmed range reading with its old pending row.
GET/read routes do not exist; oversized/malformed samples, replayed source
timestamps, unapproved services, wrong native names and peer mismatches are
rejected without advancing last-seen. Extra payload fields are discarded.
History and counters retain their actual receipt timestamps. Clock warnings are
visible; a failed or stale sender never becomes a new healthy sample.

Review the current tailnet policy before deployment. Narrow grants do not
override an existing wildcard allow-all rule: matching grants are combined.
Preserve established management and Mac/Linux flows while limiting range
senders to the exact collector/port. Keep a checked policy rollback; validate
positive and negative rules before saving. Peer inventory alone is not proof
of restricted network access or telemetry.

### Windows sender and installation

`send-fleet.ps1` reads a protected sender JSON file with schema
`macfleet.windows.sender.v1`, `hostId`, `expectedComputerName`, `nodeId`,
`receiverAddress`, `receiverNodeId`, integer `port` and `services` (array).
It checks the local and destination Tailscale stable identities, invokes the
unchanged local collector, and posts only that native payload. No proxy,
redirect, password, remote listener or certificate-validation bypass is used.

Stage the three reviewed `.ps1` files and that computer's exact private config
through existing approved access. Inspect native identity, execution policy,
existing task/directory ownership and active work first. Obtain the required
action-time approval for persistent access/security changes. The installer
does not alter execution policy or evade a blocked script. If policy blocks
deployment, stop that step and resolve the policy with its authorized owner;
do not add Bypass, an encoded-script workaround or automatic elevation.

```powershell
.\send-fleet.ps1 -ConfigPath 'C:\APPROVED-STAGING\sender.json'
.\install-sender.ps1 -ConfigPath 'C:\APPROVED-STAGING\sender.json'
```

The installer requires an already approved administrator context. It first
requires a real accepted pilot, then refuses an existing owned task/directory,
and creates a SYSTEM task named `Workman MacFleet Telemetry`, repeating every
five minutes and at startup. Files under ProgramData are restricted to SYSTEM
and local administrators; no passwords are saved. Task overlap is ignored and
execution is bounded to two minutes. A saved task is not natural-operation or
reboot proof. Check its actual later delivery, task result and startup settings;
do not reboot a working POS/classroom solely for verification.

Rollback: disable/remove only the owned telemetry task, stop only the owned
receiver, revoke only its approved grants and recoverably retain the installed
files/config and samples. Restore any explicitly changed script policy to its
recorded prior scope/value. Preserve unrelated jobs, tailnet nodes, recovery
VM isolation, checkout, printers and existing management access. Offline or
unidentified records stay pending; never wake a computer or manufacture data
just to improve the coverage count.

Deployment is operator-specific. These scripts are packaged, not installed by
publishing a GitHub release. The guide makes no claim that all range machines
are enrolled or that any particular customer's network has been changed.

## Existing private WinRM connection

`collector/windows_snapshot.py` runs the reviewed PowerShell collector in memory
on exact confirmed computers using existing WinRM access. The native script is
gzip-encoded only to fit WinRM's command-line bound; its checks are not removed.
NTLM message encryption is required (`message_encryption='always'`), even with
an existing HTTP WinRM endpoint. HTTPS endpoints retain certificate validation.
No credentials are sent to a different guessed computer, copied into snapshots
or logged. Configured enabled endpoints must be exact private IP addresses.

Only this optional bridge requires `pywinrm` and `python-dotenv`. If they are
already installed on the selected client, reuse that runtime. Do not change
Windows authentication, execution policy, services, firewall or VPN settings to
make a failed read succeed. Original health collector/probe/endpoint code is
unchanged and has no new runtime dependency.

Create a private `windows-fleet.json` with schema `macfleet.windows.config.v1`
and `hosts` rows: unique lowercase `id`, `name`, unique exact `expectedComputerName`,
existing private WinRM `endpoint`, `kind` (`server`, `range` or `computer`),
`site`, and boolean `enabled`. Disabled rows instead carry a `pendingReason`;
unknown native computer names/OS can stay unset with `platform: 'unknown'`.
Never put passwords in the configuration. The selected owner-only dotenv file
supplies `WORKMAN_WINDOWS_SERVER_USERNAME` and `WORKMAN_WINDOWS_SERVER_PASSWORD`.

```sh
python3 collector/windows_snapshot.py --config /private/windows-fleet.json \
  --credentials-file /private/existing-credentials.env
```

The macOS CLI verifies the already-running viewer is loopback-only on port 8791.
It atomically writes mode-0600, gitignored `viewer/windows.json`; each failed
host retains its actual last successful timestamps. Adapters are not summed,
and partial/unavailable drive readings do not produce an invented machine total.
Receipts use the client's actual authenticated poll completion. Original Windows
timestamps and any clock warning remain visible; the strict one-shot validator
below still rejects an unverified future clock.

## Scheduling and actual enrollment

Use an existing supported client scheduler or a dedicated operator-approved
client job at a five-minute cadence. On macOS, a user LaunchAgent can use the
explicit Python/config/credential-file arguments above, `StartInterval: 300`,
`RunAtLoad: true`, owner-only logs and umask 077. Do not duplicate an existing
owner. Keep a checked copy of its prior state; unloading only that owned job
and restoring its configuration provides rollback without changing Windows.

Check the actual scheduled samples and source-host results before calling
monitoring automatic. macOS Local Network permissions may block a background
client even when an interactive command works. Report that permission failure;
do not weaken security or relabel a failed background poll as connected.
Verify startup persistence at an ordinary later login/startup; do not reboot an
active computer solely to produce a receipt.

Range computers need an existing protected automatic route before enrollment.
Interactive Getscreen access alone is not a polling credential. Never reuse
server credentials against an unconfirmed client, open a port, enroll a VPN
peer or generate an API credential without the required specific authority.
Leave active recovery/classroom owners and POS transactions untouched.

Optional `expectedHours` can be `"always"`, or an explicit policy such as
`{"timeZone":"America/New_York","days":{"mon":[{"start":"09:00","end":"17:00"}]}}`.
This is an illustrative schedule, not a range's business hours. A missing day
or policy is unknown; an explicit empty interval list means not expected that
day. Availability warnings are suppressed only outside configured intervals;
readings and last-seen states remain truthful.

## Local one-shot pilot — prepared, not installed

Collector version 0.1.0 · 2026-10-14. The one-shot script installs nothing and
does not itself establish automatic enrollment. The bridge above contacts only
configured, identity-checked endpoints; this public guide does not assert any
particular operator's deployment or coverage.

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
inventory are tested locally. These checks do not prove any particular host's
PowerShell execution, permissions, physical readings or startup persistence;
verify those through that operator's real protected route. No sample fixture
is injected into live data.

References: [local Get-CimInstance behavior](https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance?view=powershell-5.1),
[processor counters](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processor),
[fixed-drive fields](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-logicaldisk),
[network counters](https://learn.microsoft.com/en-us/powershell/module/netadapter/get-netadapterstatistics?view=windowsserver2025-ps).
