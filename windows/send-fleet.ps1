#requires -Version 5.1
<# Local read-only sampling and outbound private telemetry. No policy changes. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$fleetConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($fleetConfig.schema -ne 'macfleet.windows.sender.v1' -or
    $fleetConfig.hostId -notmatch '^[a-z0-9][a-z0-9.-]{0,62}$' -or
    $fleetConfig.expectedComputerName -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$' -or
    -not [string]::Equals($env:COMPUTERNAME, $fleetConfig.expectedComputerName, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Sender configuration/native identity mismatch'
}
$fleetAddress = $null
if (-not [Net.IPAddress]::TryParse([string]$fleetConfig.receiverAddress, [ref]$fleetAddress) -or
    $fleetAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'Exact receiver IPv4 required' }
$fleetBytes = $fleetAddress.GetAddressBytes()
if ($fleetBytes[0] -ne 100 -or $fleetBytes[1] -lt 64 -or $fleetBytes[1] -gt 127 -or
    $fleetConfig.port -isnot [int] -or $fleetConfig.port -lt 1024 -or $fleetConfig.port -gt 65535 -or $fleetConfig.port -eq 8791 -or
    $fleetConfig.receiverNodeId -notmatch '^n[A-Za-z0-9]{4,62}$' -or $fleetConfig.nodeId -notmatch '^n[A-Za-z0-9]{4,62}$') {
    throw 'Private receiver/peer configuration unverified'
}
$fleetTailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (-not (Test-Path -LiteralPath $fleetTailscale -PathType Leaf)) { throw 'Existing Tailscale installation unavailable' }
$fleetStatusText = & $fleetTailscale status --json
if ($LASTEXITCODE -ne 0) { throw 'Tailscale status unavailable' }
$fleetStatus = $fleetStatusText | ConvertFrom-Json
if ($fleetStatus.BackendState -ne 'Running' -or $fleetStatus.Self.ID -ne $fleetConfig.nodeId) { throw 'Sender Tailscale identity mismatch/offline' }
$fleetPeerText = & $fleetTailscale whois --json ([string]$fleetConfig.receiverAddress)
if ($LASTEXITCODE -ne 0) { throw 'Receiver Tailscale identity unavailable' }
$fleetPeer = $fleetPeerText | ConvertFrom-Json
if ($fleetPeer.Node.StableID -ne $fleetConfig.receiverNodeId -or
    @($fleetPeer.Node.Addresses) -notcontains ($fleetConfig.receiverAddress + '/32')) { throw 'Receiver Tailscale identity mismatch' }
$fleetServiceNames = @($fleetConfig.services)
if (@($fleetServiceNames | Where-Object {$_ -isnot [string] -or $_ -notmatch '^[A-Za-z0-9_.-]{1,128}$'}).Count -gt 0) { throw 'Exact service allowlist required' }
$fleetSample = & (Join-Path $PSScriptRoot 'collect-fleet.ps1') -ExpectedComputerName $fleetConfig.expectedComputerName -ServiceName $fleetServiceNames
if (-not $fleetSample) { throw 'Native collection unavailable' }
$fleetPayload = [Text.Encoding]::UTF8.GetBytes(($fleetSample | Out-String))
if ($fleetPayload.Length -gt 131072) { throw 'Native payload exceeds size bound' }
$fleetUri = 'http://' + $fleetConfig.receiverAddress + ':' + $fleetConfig.port + '/v1/samples/' + $fleetConfig.hostId
# The exact pinned IP is inside WireGuard. No redirects, proxy or TLS bypass.
Invoke-RestMethod -Method Post -Uri $fleetUri -ContentType 'application/json' -Body $fleetPayload -TimeoutSec 20 -MaximumRedirection 0 -Proxy $null | Out-Null
Write-Output 'MacFleet private sample accepted'
