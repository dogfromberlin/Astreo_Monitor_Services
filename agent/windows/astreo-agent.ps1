#Requires -Version 5.1
<#
  Astreo Monitor - agente per Windows (4.2).
  Raccoglie i dati di questo server e li invia al server centrale. Avviato ogni minuto da un'attivita'
  pianificata come SYSTEM; non apre porte. Cio' che non si riesce a inviare resta in coda fino a 24 ore.
    servizi: a ogni cambio di stato e comunque ogni 5 minuti
    metriche (CPU, memoria, file di paging, disco di sistema, uptime): ogni 5 minuti
    riavvio: quando l'ora di avvio cambia
    4.2: stato dei dischi fisici e aggiornamenti di Windows: ogni 6 ore; container Docker: ogni 5 minuti
  Guida: docs/it/agents.md
#>
param(
  [string]$ConfigPath = (Join-Path $env:ProgramData 'AstreoAgent\agent.json'),
  [switch]$DryRun,
  [switch]$TestConnection
)
$ErrorActionPreference = 'Stop'
$AgentVersion = '4.2.0'
$Dir = Split-Path -Parent $ConfigPath
$QueueDir = Join-Path $Dir 'queue'
$StatePath = Join-Path $Dir 'state.json'
$LogPath = Join-Path $Dir 'agent.log'
$MetricsEvery = 290
$HealthEvery = 21600
$Batch = 200

function Write-AgentLog([string]$Level, [string]$Message) {
  $line = '{0} {1} {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
  if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 1MB) { Move-Item $LogPath "$LogPath.1" -Force }
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
  if ($DryRun -or $TestConnection) { Write-Output $line }
}

# --- verifica del certificato del centrale con la sua CA, senza installarla in Windows
. (Join-Path $PSScriptRoot 'AstreoTls.ps1')

function Invoke-Central([string]$Url, [string]$Token, [string]$Json) {
  $req = [System.Net.HttpWebRequest]::Create($Url)
  $req.Method = 'POST'
  $req.ContentType = 'application/json; charset=utf-8'
  $req.Timeout = 30000
  $req.UserAgent = "astreo-agent-windows/$AgentVersion"
  $req.Headers.Add('Authorization', "Bearer $Token")
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)
  $req.ContentLength = $bytes.Length
  $s = $req.GetRequestStream(); $s.Write($bytes, 0, $bytes.Length); $s.Close()
  try {
    $resp = $req.GetResponse()
  } catch [System.Net.WebException] {
    if ($_.Exception.Response) { $resp = $_.Exception.Response } else { throw }
  }
  $reader = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
  $body = $reader.ReadToEnd(); $reader.Close()
  return @{ Status = [int]$resp.StatusCode; Body = $body }
}

function Get-StateValue($Name, $Default) { if ($state.PSObject.Properties[$Name]) { return $state.$Name } return $Default }
function Set-StateValue($Name, $Value) { $state | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force }

# --------------------------------------------------------------------------- avvio
$cfg = Get-Content -Path $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
[AstreoTls]::Enable($cfg.ca_file)
New-Item -ItemType Directory -Force -Path $QueueDir | Out-Null
$state = [pscustomobject]@{}
if (Test-Path $StatePath) { try { $state = Get-Content $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { } }
$ingest = ($cfg.central.TrimEnd('/')) + '/api/v1/agents/ingest'

if ($TestConnection) {
  $r = Invoke-Central $ingest $cfg.token '{"agent":{"kind":"windows"},"items":[]}'
  if ($r.Status -eq 200) { Write-AgentLog 'INFO' 'Collegamento al server centrale: OK'; exit 0 }
  Write-AgentLog 'ERROR' ("Il centrale ha risposto {0}: {1}" -f $r.Status, $r.Body); exit 1
}

$now = Get-Date
$iso = $now.ToString('yyyy-MM-ddTHH:mm:ss')
$epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$items = New-Object System.Collections.ArrayList
$os = Get-CimInstance -ClassName Win32_OperatingSystem

# --- riavvio
$boot = $os.LastBootUpTime.ToString('yyyy-MM-ddTHH:mm:ss')
$prevBoot = Get-StateValue 'boot' $null
if ($prevBoot -ne $boot) {
  if ($prevBoot) { [void]$items.Add(@{ type = 'boot'; time = $iso; boot_time = $boot }) }
  Set-StateValue 'boot' $boot
}

# --- servizi (elenco ricevuto dal centrale)
$units = @(Get-StateValue 'services' @())
if ($units.Count -gt 0) {
  $current = @(foreach ($u in $units) {
    $svc = Get-Service -Name $u -ErrorAction SilentlyContinue
    if ($svc) { @{ unit = $u; label = $svc.DisplayName; up = ($svc.Status -eq 'Running'); state = $svc.Status.ToString().ToLower() } }
    else { @{ unit = $u; label = $u; up = $false; state = 'not-found' } }
  })
  $sig = ($current | ForEach-Object { '{0}={1}' -f $_.unit, $_.up }) -join ','
  if ($sig -ne (Get-StateValue 'services_sig' '') -or ($epoch - [int](Get-StateValue 'services_sent' 0)) -ge $MetricsEvery) {
    [void]$items.Add(@{ type = 'services'; time = $iso; services = $current })
    Set-StateValue 'services_sig' $sig; Set-StateValue 'services_sent' $epoch
  }
}

# --- metriche
if (($epoch - [int](Get-StateValue 'metrics_sent' 0)) -ge $MetricsEvery) {
  $samples = @(1..5 | ForEach-Object {
    (Get-CimInstance -ClassName Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime
    Start-Sleep -Milliseconds 800
  })
  $cpu = [math]::Round(($samples | Measure-Object -Average).Average, 2)
  $totalKb = [double]$os.TotalVisibleMemorySize; $freeKb = [double]$os.FreePhysicalMemory
  $page = Get-CimInstance -ClassName Win32_PageFileUsage -ErrorAction SilentlyContinue
  $pageAlloc = ($page | Measure-Object -Property AllocatedBaseSize -Sum).Sum
  $pageUsed = ($page | Measure-Object -Property CurrentUsage -Sum).Sum
  $sysDisk = Get-CimInstance -ClassName Win32_LogicalDisk -Filter ("DeviceID='{0}'" -f $env:SystemDrive)
  $item = @{
    type = 'metrics'; time = $iso; cpu_pct = $cpu
    mem_used_pct = [math]::Round(($totalKb - $freeKb) / $totalKb * 100, 1)
    mem_used_mb = [int](($totalKb - $freeKb) / 1024); mem_total_mb = [int]($totalKb / 1024)
    uptime_s = [int]($now - $os.LastBootUpTime).TotalSeconds
  }
  if ($pageAlloc -gt 0) { $item.swap_used_pct = [math]::Round($pageUsed / $pageAlloc * 100, 1) }
  if ($sysDisk -and $sysDisk.Size -gt 0) { $item.disk_used_pct = [math]::Round(($sysDisk.Size - $sysDisk.FreeSpace) / $sysDisk.Size * 100, 1) }
  # 4.0.1: tutti i dischi fissi (unità locali, DriveType 3)
  $item.disks = @(Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object { $_.Size -gt 0 } | Select-Object -First 32 | ForEach-Object {
    @{ mountpoint = $_.DeviceID; device = $_.DeviceID; fstype = [string]$_.FileSystem; label = [string]$_.VolumeName
       total_mb = [math]::Round($_.Size / 1MB); used_mb = [math]::Round(($_.Size - $_.FreeSpace) / 1MB)
       free_mb = [math]::Round($_.FreeSpace / 1MB); used_pct = [math]::Round(($_.Size - $_.FreeSpace) / $_.Size * 100, 1) }
  })
  [void]$items.Add($item)
  Set-StateValue 'metrics_sent' $epoch

  # 4.2: container Docker, se Docker e' installato
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if ($docker) {
    try {
      $conts = @(& $docker.Source ps -a --no-trunc --format '{{json .}}' 2>$null | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json } | Select-Object -First 200)
      $list = @(foreach ($c in $conts) {
        $pol = ''; $hl = $null
        try {
          $ins = (& $docker.Source inspect $c.ID 2>$null | Out-String | ConvertFrom-Json)[0]
          $pol = [string]$ins.HostConfig.RestartPolicy.Name
          if ($ins.State.Health) { $hl = [string]$ins.State.Health.Status }
        } catch { }
        @{ name = [string]$c.Names; image = [string]$c.Image; state = [string]$c.State; status = [string]$c.Status; health = $hl; restart_policy = $pol }
      })
      [void]$items.Add(@{ type = 'containers'; time = $iso; containers = $list })
    } catch { Write-AgentLog 'WARN' ('Docker non leggibile: {0}' -f $_.Exception.Message) }
  }
}

# --- 4.2: dischi fisici e aggiornamenti di Windows, ogni 6 ore
if (($epoch - [int](Get-StateValue 'health_sent' 0)) -ge $HealthEvery) {
  Set-StateValue 'health_sent' $epoch
  $disks = @()
  try {
    $disks = @(Get-PhysicalDisk -ErrorAction Stop | Select-Object -First 16 | ForEach-Object {
      $d = @{ device = ('disk{0}' -f $_.DeviceId); model = [string]$_.FriendlyName; os_health = [string]$_.HealthStatus }
      if ($_.HealthStatus -eq 'Healthy') { $d.passed = $true } elseif ($_.HealthStatus -eq 'Unhealthy') { $d.passed = $false }
      try {
        $rc = $_ | Get-StorageReliabilityCounter -ErrorAction Stop
        if ($rc.Temperature -gt 0) { $d.temperature = [int]$rc.Temperature }
        if ($null -ne $rc.Wear) { $d.wear_used_pct = [int]$rc.Wear }
        if ($rc.ReadErrorsUncorrected -gt 0) { $d.uncorrectable = [int]$rc.ReadErrorsUncorrected }
      } catch { }
      $d
    })
  } catch { Write-AgentLog 'WARN' ('Stato dei dischi non leggibile: {0}' -f $_.Exception.Message) }
  $upd = @{ total = 0; security = @(); security_count = 0; reboot = @{ required = $false } }
  try {
    # ricerca di Windows Update: puo' richiedere qualche minuto, per questo solo ogni 6 ore
    $searcher = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
    $res = $searcher.Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
    $sec = @(foreach ($u in $res.Updates) {
      if (@($u.Categories | Where-Object { $_.Name -eq 'Security Updates' }).Count -gt 0 -or $u.MsrcSeverity) { [string]$u.Title }
    })
    $upd.total = [int]$res.Updates.Count; $upd.security = @($sec | Select-Object -First 100); $upd.security_count = $sec.Count
  } catch { $upd.error = ('Windows Update non leggibile: {0}' -f $_.Exception.Message) }
  $rb = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
        (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')
  $upd.reboot = @{ required = [bool]$rb }
  [void]$items.Add(@{ type = 'health'; time = $iso; smart_available = ($disks.Count -gt 0); disks = $disks; updates = $upd })
}

if ($DryRun) { $items | ConvertTo-Json -Depth 6; exit 0 }

# --------------------------------------------------------------------- coda e invio
$i = 0
foreach ($it in $items) {
  $name = Join-Path $QueueDir ('{0}-{1:000}.json' -f [DateTime]::UtcNow.Ticks, $i); $i++
  [System.IO.File]::WriteAllText("$name.tmp", ($it | ConvertTo-Json -Depth 6 -Compress), (New-Object System.Text.UTF8Encoding($false)))
  Move-Item "$name.tmp" $name -Force
}
Get-ChildItem $QueueDir -Filter '*.json' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-24) } | Remove-Item -Force
$files = @(Get-ChildItem $QueueDir -Filter '*.json' | Sort-Object Name)
$sent = 0
while ($files.Count -gt 0) {
  $chunk = @($files | Select-Object -First $Batch)
  $files = @($files | Select-Object -Skip $Batch)
  $parts = foreach ($f in $chunk) { [System.IO.File]::ReadAllText($f.FullName) }
  $agentInfo = @{ version = $AgentVersion; kind = 'windows'; hostname = $env:COMPUTERNAME; os = ('{0} {1}' -f $os.Caption, $os.Version) } | ConvertTo-Json -Compress
  $json = '{"agent":' + $agentInfo + ',"items":[' + ($parts -join ',') + ']}'
  try {
    $r = Invoke-Central $ingest $cfg.token $json
  } catch {
    Write-AgentLog 'WARN' ('Server centrale non raggiungibile ({0}): {1} dati in coda' -f $_.Exception.GetType().Name, ($chunk.Count + $files.Count))
    break
  }
  if ($r.Status -eq 200) {
    $chunk | Remove-Item -Force
    $sent += $chunk.Count
    $answer = $r.Body | ConvertFrom-Json
    Set-StateValue 'services' @($answer.services | Where-Object { $_ -is [string] } | Select-Object -First 60)
  } elseif ($r.Status -eq 400) {
    Write-AgentLog 'ERROR' ('Dati rifiutati dal centrale: {0}' -f $r.Body)
    $chunk | Remove-Item -Force
  } else {
    Write-AgentLog 'ERROR' ('Il centrale ha risposto {0}: riprovo al prossimo giro' -f $r.Status)
    break
  }
}
($state | ConvertTo-Json -Depth 4 -Compress) | Set-Content -Path $StatePath -Encoding UTF8
if ($sent -gt 0) { Write-AgentLog 'INFO' ('Inviati {0} dati al server centrale' -f $sent) }
