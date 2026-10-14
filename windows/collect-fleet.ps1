#requires -Version 5.1
<# One-shot local-only pilot. No install, listener, task, credential or file writes.
   Unavailable counters remain null. Run only on the confirmed target computer. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$')]
    [string]$ExpectedComputerName,
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string[]]$ServiceName = @()
)

if (-not [string]::Equals($env:COMPUTERNAME, $ExpectedComputerName, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Target identity mismatch. No collection was performed.'
}
$pilotErrors = New-Object 'System.Collections.Generic.List[string]'
function Read-LocalCim([string]$ClassName, [string[]]$Properties, [string]$Filter = '') {
    try {
        $pilotArgs = @{ ClassName=$ClassName; Property=$Properties; OperationTimeoutSec=10; ErrorAction='Stop' }
        if ($Filter) { $pilotArgs.Filter=$Filter }
        Get-CimInstance @pilotArgs
    } catch { $pilotErrors.Add("$ClassName unavailable") }
}
function Valid-Number($Value) {
    try {
        return ($null -ne $Value -and $Value -is [ValueType] -and $Value -isnot [bool] -and
            -not [double]::IsNaN([double]$Value) -and -not [double]::IsInfinity([double]$Value) -and [double]$Value -ge 0)
    } catch { return $false }
}
$pilotOs = Read-LocalCim 'Win32_OperatingSystem' @('Caption','Version','OSArchitecture','LastBootUpTime','TotalVisibleMemorySize','FreePhysicalMemory')
$pilotProcessors = @(Read-LocalCim 'Win32_Processor' @('LoadPercentage','NumberOfLogicalProcessors','Name'))
$pilotDisks = @(Read-LocalCim 'Win32_LogicalDisk' @('DeviceID','Size','FreeSpace') 'DriveType=3')
$pilotCpu = $null
$pilotCpuWeighted = 0.0
$pilotCpuThreads = 0
$pilotCpuValid = $pilotProcessors.Count -gt 0
foreach ($pilotProcessor in $pilotProcessors) {
    if ((Valid-Number $pilotProcessor.LoadPercentage) -and $pilotProcessor.LoadPercentage -le 100 -and
        (Valid-Number $pilotProcessor.NumberOfLogicalProcessors) -and $pilotProcessor.NumberOfLogicalProcessors -gt 0) {
        $pilotCpuWeighted += [double]$pilotProcessor.LoadPercentage * $pilotProcessor.NumberOfLogicalProcessors
        $pilotCpuThreads += $pilotProcessor.NumberOfLogicalProcessors
    } else { $pilotCpuValid = $false }
}
if ($pilotCpuValid -and $pilotCpuThreads -gt 0) { $pilotCpu = [Math]::Round($pilotCpuWeighted / $pilotCpuThreads, 1) }
$pilotRam = $null
$pilotMemUsed = $null
if ($null -ne $pilotOs -and (Valid-Number $pilotOs.TotalVisibleMemorySize) -and $pilotOs.TotalVisibleMemorySize -gt 0 -and
    (Valid-Number $pilotOs.FreePhysicalMemory) -and $pilotOs.FreePhysicalMemory -le $pilotOs.TotalVisibleMemorySize) {
    $pilotRam = [Math]::Round([double]$pilotOs.TotalVisibleMemorySize / 1MB, 3)
    $pilotMemUsed = [Math]::Round(([double]$pilotOs.TotalVisibleMemorySize - $pilotOs.FreePhysicalMemory) / 1MB, 3)
}
$pilotDiskRows = @()
foreach ($pilotDisk in $pilotDisks) {
    $pilotDiskState = 'unavailable'
    $pilotDiskTotal = $null
    $pilotDiskFree = $null
    $pilotDiskUsed = $null
    if ((Valid-Number $pilotDisk.Size) -and $pilotDisk.Size -gt 0 -and (Valid-Number $pilotDisk.FreeSpace) -and $pilotDisk.FreeSpace -le $pilotDisk.Size) {
        $pilotDiskTotal = [Math]::Round([double]$pilotDisk.Size / 1GB, 3)
        $pilotDiskFree = [Math]::Round([double]$pilotDisk.FreeSpace / 1GB, 3)
        $pilotDiskUsed = [Math]::Round($pilotDiskTotal - $pilotDiskFree, 3)
        $pilotDiskState = 'available'
    }
    $pilotDiskRows += [ordered]@{ drive=$pilotDisk.DeviceID; status=$pilotDiskState; totalGb=$pilotDiskTotal; usedGb=$pilotDiskUsed; freeGb=$pilotDiskFree }
}
$pilotNetworks = @()
$pilotNetworkState = 'unavailable'
try {
    $pilotAdapters = @(Get-NetAdapterStatistics -ErrorAction Stop)
    foreach ($pilotAdapter in $pilotAdapters) {
        $pilotRx = $null
        $pilotTx = $null
        if (Valid-Number $pilotAdapter.ReceivedBytes) { $pilotRx = $pilotAdapter.ReceivedBytes }
        if (Valid-Number $pilotAdapter.SentBytes) { $pilotTx = $pilotAdapter.SentBytes }
        $pilotNetworks += [ordered]@{ name=$pilotAdapter.Name; receivedBytes=$pilotRx; sentBytes=$pilotTx }
    }
    if ($pilotNetworks.Count -gt 0) {
        $pilotNetworkState='available'
        foreach ($pilotNetworkRow in $pilotNetworks) {
            if ($null -eq $pilotNetworkRow.receivedBytes -or $null -eq $pilotNetworkRow.sentBytes) { $pilotNetworkState='partial' }
        }
    }
} catch { $pilotErrors.Add('Network counters unavailable') }
$pilotServices = @()
foreach ($pilotName in @($ServiceName | Sort-Object -Unique)) {
    try {
        $pilotService = Get-Service -Name $pilotName -ErrorAction Stop
        $pilotServices += [ordered]@{ name=$pilotName; status=[string]$pilotService.Status; state='available' }
    } catch { $pilotServices += [ordered]@{ name=$pilotName; status=$null; state='unavailable' } }
}
$pilotAt = [DateTime]::UtcNow
$pilotUptime = $null
if ($null -ne $pilotOs -and $null -ne $pilotOs.LastBootUpTime) {
    try {
        $pilotDays = ($pilotAt - $pilotOs.LastBootUpTime.ToUniversalTime()).TotalDays
        if ($pilotDays -ge 0) { $pilotUptime = [Math]::Round($pilotDays, 3) }
    } catch { $pilotErrors.Add('Boot timestamp unavailable') }
}
$pilotState = 'partial'
$pilotAllDisks = $pilotDiskRows.Count -gt 0
foreach ($pilotDiskRow in $pilotDiskRows) { if ($pilotDiskRow.status -ne 'available') { $pilotAllDisks=$false } }
$pilotAllServices = $true
foreach ($pilotServiceRow in $pilotServices) { if ($pilotServiceRow.state -ne 'available') { $pilotAllServices=$false } }
if ($null -ne $pilotCpu -and $null -ne $pilotRam -and $pilotAllDisks -and $pilotAllServices -and $null -ne $pilotUptime -and $pilotNetworkState -eq 'available' -and $pilotErrors.Count -eq 0) {
    $pilotState='available'
}
[ordered]@{
    schema='workman.windows-fleet-pilot.v1'; status=$pilotState; host=$env:COMPUTERNAME;
    observedAt=$pilotAt.ToString('o'); units='GiB';
    os=$(if ($null -ne $pilotOs) { [string]$pilotOs.Caption } else { $null });
    cpuUsedPct=$pilotCpu; ramGb=$pilotRam; memUsedGb=$pilotMemUsed; uptimeDays=$pilotUptime;
    disks=$pilotDiskRows; networkState=$pilotNetworkState; network=$pilotNetworks; services=$pilotServices;
    gpuUtilPct=$null; temperatureC=$null; powerW=$null; backupState='not collected';
    errors=@($pilotErrors); scope='One local read-only sample; not installed, enrolled or a backup verification'
} | ConvertTo-Json -Depth 8
