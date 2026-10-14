#requires -Version 5.1
<# Operator-approved install only. Refuses collisions and blocked script policy.
   No Windows policy, firewall, Tailscale or checkout/printer changes. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
$fleetPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $fleetPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Approved administrator context required; no automatic elevation' }
if ((Get-ExecutionPolicy) -notin @('RemoteSigned','AllSigned','Unrestricted')) { throw 'Script policy blocks deployment; no bypass performed' }
$fleetTaskName = 'Workman MacFleet Telemetry'
$fleetInstall = Join-Path $env:ProgramData 'Workman\MacFleet'
if (Get-ScheduledTask -TaskName $fleetTaskName -ErrorAction SilentlyContinue) { throw 'Monitoring task already exists; preserve its owner' }
if (Test-Path -LiteralPath $fleetInstall) { throw 'Monitoring directory already exists; no overwrite performed' }
$fleetInstallConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($fleetInstallConfig.schema -ne 'macfleet.windows.sender.v1' -or
    -not [string]::Equals($env:COMPUTERNAME, $fleetInstallConfig.expectedComputerName, [StringComparison]::OrdinalIgnoreCase)) { throw 'Native installation target mismatch' }
# Prove identity, collection and actual durable receiver acceptance first.
& (Join-Path $PSScriptRoot 'send-fleet.ps1') -ConfigPath $ConfigPath
New-Item -ItemType Directory -Path $fleetInstall | Out-Null
$fleetAcl = New-Object Security.AccessControl.DirectorySecurity
$fleetAcl.SetAccessRuleProtection($true,$false)
foreach ($fleetSid in @('S-1-5-18','S-1-5-32-544')) {
    $fleetIdentity = New-Object Security.Principal.SecurityIdentifier($fleetSid)
    $fleetRule = New-Object Security.AccessControl.FileSystemAccessRule($fleetIdentity,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $fleetAcl.AddAccessRule($fleetRule)
}
Set-Acl -LiteralPath $fleetInstall -AclObject $fleetAcl
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'collect-fleet.ps1'),(Join-Path $PSScriptRoot 'send-fleet.ps1') -Destination $fleetInstall
Copy-Item -LiteralPath $ConfigPath -Destination (Join-Path $fleetInstall 'sender.json')
$fleetPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$fleetArguments = '-NoProfile -NonInteractive -File "' + (Join-Path $fleetInstall 'send-fleet.ps1') + '" -ConfigPath "' + (Join-Path $fleetInstall 'sender.json') + '"'
$fleetAction = New-ScheduledTaskAction -Execute $fleetPowerShell -Argument $fleetArguments
$fleetRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$fleetStartup = New-ScheduledTaskTrigger -AtStartup
$fleetSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$fleetOwner = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Limited
Register-ScheduledTask -TaskName $fleetTaskName -Action $fleetAction -Trigger @($fleetRepeat,$fleetStartup) -Settings $fleetSettings -Principal $fleetOwner | Out-Null
Get-ScheduledTask -TaskName $fleetTaskName | Select-Object TaskName,State,@{Name='RunAs';Expression={$_.Principal.UserId}},@{Name='Command';Expression={$_.Actions.Execute}},@{Name='Arguments';Expression={$_.Actions.Arguments}} | ConvertTo-Json
# This proves a saved task, not its later natural execution or reboot outcome.
