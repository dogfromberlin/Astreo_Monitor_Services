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
$AgentVersion = '4.5.0'
$Dir = Split-Path -Parent $ConfigPath
$QueueDir = Join-Path $Dir 'queue'
$StatePath = Join-Path $Dir 'state.json'
$LogPath = Join-Path $Dir 'agent.log'
$MetricsEvery = 290
$HealthEvery = 21600
$Batch = 200

# 4.4.0.dev2: esegue un comando esterno raccogliendo uscita ed errori senza mai interrompere lo script
function Invoke-Native([scriptblock]$Command) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $all = @(& $Command 2>&1)
    $code = $LASTEXITCODE
  } catch { return @{ ok = $false; out = @(); err = $_.Exception.Message } }
  finally { $ErrorActionPreference = $prev }
  $err = @($all | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() }) -join ' '
  $out = @($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | ForEach-Object { [string]$_ })
  return @{ ok = ($code -eq 0); out = $out; err = $err }
}

function Write-AgentLog([string]$Level, [string]$Message) {
  $line = '{0} {1} {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
  if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 1MB) { Move-Item $LogPath "$LogPath.1" -Force }
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
  if ($DryRun -or $TestConnection) { Write-Output $line }
}

# 4.4.0.dev2: un errore non previsto finisce nel registro (riga e messaggio) invece di chiudere l'agente in silenzio
trap {
  try { Write-AgentLog 'ERROR' ('Errore non previsto alla riga {0}: {1}' -f $_.InvocationInfo.ScriptLineNumber, $_.Exception.Message) } catch { }
  exit 1
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
  # 4.4: scheda di rete principale (quella con il gateway), per il Wake-on-LAN dal centrale
  try {
    $nic = Get-NetIPConfiguration -ErrorAction Stop | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1
    if ($nic) {
      $item.mac = [string]$nic.NetAdapter.MacAddress
      $item.ip = [string](@($nic.IPv4Address)[0].IPAddress)
    }
  } catch { }
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
    # 4.3: Docker installato ma motore fermo (es. Docker Desktop chiuso): nessun errore nel registro a ogni giro
    # 4.4.0.dev2: un comando esterno che scrive su stderr non deve mai interrompere l'agente
    # (con ErrorActionPreference = Stop, Windows PowerShell 5.1 lo tratta come errore bloccante)
    $dockerUp = Invoke-Native { & $docker.Source info --format '{{.ServerVersion}}' }
    if (-not $dockerUp.ok) {
      [void]$items.Add(@{ type = 'containers'; time = $iso; running = $false; detail = 'Docker installato ma non in esecuzione'; containers = @() })
      $docker = $null
    }
  }
  if ($docker) {
    try {
      $ps = Invoke-Native { & $docker.Source ps -a --no-trunc --format '{{json .}}' }
      if (-not $ps.ok) { throw ('docker ps: ' + $ps.err) }
      $conts = @($ps.out | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json } | Select-Object -First 200)
      $list = @(foreach ($c in $conts) {
        $pol = ''; $hl = $null
        try {
          $ins = ((Invoke-Native { & $docker.Source inspect $c.ID }).out | Out-String | ConvertFrom-Json)[0]
          $pol = [string]$ins.HostConfig.RestartPolicy.Name
          if ($ins.State.Health) { $hl = [string]$ins.State.Health.Status }
        } catch { }
        @{ name = [string]$c.Names; image = [string]$c.Image; state = [string]$c.State; status = [string]$c.Status; health = $hl; restart_policy = $pol }
      })
      [void]$items.Add(@{ type = 'containers'; time = $iso; running = $true; containers = $list })
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
# --- 4.3: comandi firmati dal centrale (avvia / ferma / riavvia un servizio controllato)
function ConvertFrom-Hex([string]$h) {
  if ($h.Length % 2) { $h = '0' + $h }
  $b = New-Object byte[] ($h.Length / 2)
  for ($k = 0; $k -lt $b.Length; $k++) { $b[$k] = [Convert]::ToByte($h.Substring($k * 2, 2), 16) }
  return ,$b
}
function Test-CommandSignature($pub, [string]$payload, [string]$sigB64) {
  try {
    $p = New-Object System.Security.Cryptography.RSAParameters
    $p.Modulus = ConvertFrom-Hex ([string]$pub.n)
    if ($p.Modulus.Length -lt 256) { return $false }
    $e = [int]$pub.e; $eb = @(); while ($e -gt 0) { $eb = ,([byte]($e -band 255)) + $eb; $e = $e -shr 8 }
    $p.Exponent = [byte[]]$eb
    $rsa = New-Object System.Security.Cryptography.RSACryptoServiceProvider
    $rsa.ImportParameters($p)
    return $rsa.VerifyData([System.Text.Encoding]::UTF8.GetBytes($payload), 'SHA256', [Convert]::FromBase64String($sigB64))
  } catch { return $false }
}
function Get-TokenTag([string]$tok) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $h = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($tok))
  return (($h | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 24)
}
function Add-QueueItem($it) {
  $name = Join-Path $QueueDir ('{0}-{1:000}.json' -f [DateTime]::UtcNow.Ticks, (Get-Random -Maximum 999))
  [System.IO.File]::WriteAllText("$name.tmp", ($it | ConvertTo-Json -Depth 6 -Compress), (New-Object System.Text.UTF8Encoding($false)))
  Move-Item "$name.tmp" $name -Force
}
function Update-AgentFiles($pub, [string]$tag) {
  # 4.3: scarica i file nuovi dal centrale, verifica firma e impronte, controlla la sintassi, poi sostituisce
  $url = ($cfg.central.TrimEnd('/')) + '/api/v1/agents/update-package'
  $r = Invoke-Central $url $cfg.token '{}'
  if ($r.Status -ne 200) { return @{ ok = $false; detail = ('pacchetto non disponibile ({0})' -f $r.Status) } }
  $pkg = $r.Body | ConvertFrom-Json
  if (-not (Test-CommandSignature $pub ([string]$pkg.payload) ([string]$pkg.sig))) { return @{ ok = $false; detail = 'firma del pacchetto non valida' } }
  $m = [string]$pkg.payload | ConvertFrom-Json
  if ($m.agent -ne $tag -or $m.kind -ne 'windows') { return @{ ok = $false; detail = 'pacchetto destinato a un altro agente' } }
  if ([DateTimeOffset]::UtcNow -gt [DateTimeOffset]::Parse([string]$m.expires)) { return @{ ok = $false; detail = 'pacchetto scaduto' } }
  $allowed = @('astreo-agent.ps1', 'AstreoTls.ps1')
  $staged = @()
  foreach ($f in @($m.files)) {
    if ($allowed -notcontains [string]$f.name) { return @{ ok = $false; detail = ('file non ammesso: {0}' -f $f.name) } }
    $content = @($pkg.files | Where-Object { $_.name -eq $f.name })[0].content
    $bytes = [Convert]::FromBase64String([string]$content)
    $sha = -join ([System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    if ($sha -ne [string]$f.sha256) { return @{ ok = $false; detail = ('impronta non valida: {0}' -f $f.name) } }
    $tmp = Join-Path $Dir ($f.name + '.new')
    [System.IO.File]::WriteAllBytes($tmp, $bytes)
    $errs = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($tmp, [ref]$null, [ref]$errs)
    if ($errs) { Remove-Item $tmp -Force; return @{ ok = $false; detail = ('script non valido: {0}' -f $f.name) } }
    $staged += @{ name = [string]$f.name; tmp = $tmp }
  }
  foreach ($s in $staged) {
    $dest = Join-Path $Dir $s.name
    if (Test-Path $dest) { Copy-Item $dest ($dest + '.bak') -Force }
  }
  try {
    foreach ($s in $staged) { Move-Item $s.tmp (Join-Path $Dir $s.name) -Force }
  } catch {
    foreach ($s in $staged) { $d = Join-Path $Dir $s.name; if (Test-Path ($d + '.bak')) { Copy-Item ($d + '.bak') $d -Force } }
    return @{ ok = $false; detail = ('sostituzione non riuscita, ripristinati i file precedenti: {0}' -f $_.Exception.Message) }
  }
  return @{ ok = $true; detail = ('agente {0} installato (prima {1}); attivo dal prossimo giro' -f $m.version, $AgentVersion) }
}

function Invoke-AgentCommands($cmds) {
  $pubPath = Join-Path $Dir 'commands.pub.json'
  $pub = $null
  if (Test-Path $pubPath) { $pub = Get-Content $pubPath -Raw -Encoding UTF8 | ConvertFrom-Json }
  $done = [System.Collections.ArrayList]@(Get-StateValue 'commands_done' @())
  $tag = Get-TokenTag $cfg.token
  $allowed = @(Get-StateValue 'services' @())
  $any = $false
  foreach ($c in @($cmds | Select-Object -First 10)) {
    $cid = [string]$c.id
    $reason = $null; $p = $null
    if (-not $cfg.allow_commands) { $reason = "comandi non permessi su questo server (reinstalla l'agente con -AllowCommands)" }
    elseif (-not $pub) { $reason = "chiave dei comandi mancante su questo server (reinstalla l'agente con -AllowCommands)" }
    elseif (-not (Test-CommandSignature $pub ([string]$c.payload) ([string]$c.sig))) { $reason = 'firma non valida' }
    else {
      try { $p = [string]$c.payload | ConvertFrom-Json } catch { $reason = 'comando non leggibile' }
      if (-not $reason) {
        $now = [DateTimeOffset]::UtcNow
        if ($p.agent -ne $tag) { $reason = 'comando destinato a un altro agente' }
        elseif ($done -contains [string]$p.id) { $reason = 'comando già eseguito' }
        elseif ([string]$p.action -eq 'update') { if (-not $cfg.allow_update) { $reason = "aggiornamento non permesso su questo server (reinstalla l'agente con -AllowUpdate)" } }
        elseif (@('start', 'stop', 'restart') -notcontains [string]$p.action) { $reason = 'azione non ammessa' }
        elseif ($allowed -notcontains [string]$p.unit) { $reason = 'servizio non tra quelli controllati' }
        elseif ($now -gt [DateTimeOffset]::Parse([string]$p.expires) -or ([DateTimeOffset]::Parse([string]$p.issued) - $now).TotalMinutes -gt 5) { $reason = 'comando scaduto' }
      }
    }
    if ($reason) {
      Write-AgentLog 'WARN' ('Comando {0} rifiutato: {1}' -f $cid, $reason)
      if ($reason -ne 'comando già eseguito') { Add-QueueItem @{ type = 'command_result'; time = (Get-Date).ToString('s'); id = $cid; ok = $false; detail = $reason } }
      $any = $true
      continue
    }
    [void]$done.Add([string]$p.id)
    if ([string]$p.action -eq 'update') {
      Set-StateValue 'commands_done' @($done | Select-Object -Last 200)
      $u = Update-AgentFiles $pub $tag
      Write-AgentLog $(if ($u.ok) { 'INFO' } else { 'WARN' }) ('Aggiornamento dell''agente da {0}: {1}' -f $p.by, $u.detail)
      Add-QueueItem @{ type = 'command_result'; time = (Get-Date).ToString('s'); id = [string]$p.id; ok = [bool]$u.ok; detail = [string]$u.detail }
      $any = $true
      continue
    }
    $ok = $true; $detail = ''
    try {
      switch ([string]$p.action) {
        'start'   { Start-Service -Name $p.unit -ErrorAction Stop }
        'stop'    { Stop-Service -Name $p.unit -Force -ErrorAction Stop }
        'restart' { Restart-Service -Name $p.unit -Force -ErrorAction Stop }
      }
      $detail = 'stato: ' + (Get-Service -Name $p.unit).Status.ToString().ToLower()
    } catch { $ok = $false; $detail = $_.Exception.Message }
    Write-AgentLog $(if ($ok) { 'INFO' } else { 'WARN' }) ('Comando {0} {1} da {2}: {3}' -f $p.action, $p.unit, $p.by, $(if ($ok) { 'ok' } else { $detail }))
    Add-QueueItem @{ type = 'command_result'; time = (Get-Date).ToString('s'); id = [string]$p.id; ok = $ok; detail = $detail }
    $any = $true
  }
  Set-StateValue 'commands_done' @($done | Select-Object -Last 200)
  if ($any) {
    # stato dei servizi subito dopo il comando
    $cur = @(foreach ($u in $allowed) {
      $svc = Get-Service -Name $u -ErrorAction SilentlyContinue
      if ($svc) { @{ unit = $u; label = $svc.DisplayName; up = ($svc.Status -eq 'Running'); state = $svc.Status.ToString().ToLower() } }
      else { @{ unit = $u; label = $u; up = $false; state = 'not-found' } }
    })
    Add-QueueItem @{ type = 'services'; time = (Get-Date).ToString('s'); services = $cur }
    Set-StateValue 'services_sig' (($cur | ForEach-Object { '{0}={1}' -f $_.unit, $_.up }) -join ',')
  }
  return $any
}

function Send-Queue([bool]$Poll) {
  $files = @(Get-ChildItem $QueueDir -Filter '*.json' | Sort-Object Name)
  $count = 0; $first = $true; $ranCommands = $false
  # 4.3: anche con la coda vuota si fa una richiesta, così i comandi arrivano entro un minuto
  while ($files.Count -gt 0 -or ($first -and $Poll)) {
    $first = $false
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
      if ($chunk.Count) { $chunk | Remove-Item -Force }
      $count += $chunk.Count
      $answer = $r.Body | ConvertFrom-Json
      $newUnits = @($answer.services | Where-Object { $_ -is [string] } | Select-Object -First 60)
      if ((@(Get-StateValue 'services' @()) -join ',') -ne ($newUnits -join ',') -or $answer.refresh) { $script:refreshNow = $true }
      Set-StateValue 'services' $newUnits
      if ($answer.commands) { if (Invoke-AgentCommands $answer.commands) { $ranCommands = $true } }
    } elseif ($r.Status -eq 400) {
      Write-AgentLog 'ERROR' ('Dati rifiutati dal centrale: {0}' -f $r.Body)
      if ($chunk.Count) { $chunk | Remove-Item -Force }
    } else {
      Write-AgentLog 'ERROR' ('Il centrale ha risposto {0}: riprovo al prossimo giro' -f $r.Status)
      break
    }
  }
  return @{ sent = $count; commands = $ranCommands }
}

$script:refreshNow = $false
$res = Send-Queue $true
$sent = $res.sent
if ($script:refreshNow -and -not $res.commands) {
  # 4.3: servizi cambiati o "Aggiorna" dalla dashboard: stato dei servizi nello stesso giro
  $cur = @(foreach ($u in @(Get-StateValue 'services' @())) {
    $svc = Get-Service -Name $u -ErrorAction SilentlyContinue
    if ($svc) { @{ unit = $u; label = $svc.DisplayName; up = ($svc.Status -eq 'Running'); state = $svc.Status.ToString().ToLower() } }
    else { @{ unit = $u; label = $u; up = $false; state = 'not-found' } }
  })
  Add-QueueItem @{ type = 'services'; time = (Get-Date).ToString('s'); services = $cur }
  Set-StateValue 'services_sig' (($cur | ForEach-Object { '{0}={1}' -f $_.unit, $_.up }) -join ',')
  Set-StateValue 'services_sent' $epoch
}
if ($res.commands -or $script:refreshNow) { $sent += (Send-Queue $false).sent }       # esiti e stato, inviati subito
($state | ConvertTo-Json -Depth 4 -Compress) | Set-Content -Path $StatePath -Encoding UTF8
if ($sent -gt 0) { Write-AgentLog 'INFO' ('Inviati {0} dati al server centrale' -f $sent) }
