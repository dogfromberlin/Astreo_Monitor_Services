#Requires -Version 5.1
<#
  Astreo Monitor - installazione dell'agente per Windows.
  Da PowerShell come amministratore, nella cartella del progetto:
    powershell -ExecutionPolicy Bypass -File .\agent\windows\install-agent.ps1 -Central https://CENTRALE:5443 -Token agt_... -CaSha256 ...
  Per rimuoverlo:
    powershell -ExecutionPolicy Bypass -File .\agent\windows\install-agent.ps1 -Uninstall
  Guida: docs/it/agents.md
#>
param(
  [string]$Central,
  [string]$Token,
  [string]$CaSha256,
  [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$TaskName = 'Astreo Monitor Agent'
$Dir = Join-Path $env:ProgramData 'AstreoAgent'

function Fail([string]$Message) { Write-Host "ERRORE: $Message" -ForegroundColor Red; exit 1 }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail 'avvia PowerShell come amministratore' }

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force }
  Write-Host 'Agente rimosso.'
  exit 0
}

if ($Central -notmatch '^https://[^\s/]+$') { Fail 'indirizzo del centrale non valido: usa https://IP-o-NOME:PORTA' }
if ($Token -notmatch '^agt_[A-Za-z0-9_\-]{20,}$') { Fail 'token non valido: copialo dalla dashboard (Impostazioni, Server collegati)' }
$Central = $Central.TrimEnd('/')

# --- cartella riservata a SYSTEM e amministratori
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
& icacls $Dir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null

# --- CA del centrale: scaricata e verificata con l'impronta mostrata dalla dashboard
$agentScript = Join-Path $PSScriptRoot 'astreo-agent.ps1'
if (-not (Test-Path $agentScript)) { Fail "astreo-agent.ps1 non trovato accanto a questo script" }
. (Join-Path $PSScriptRoot 'AstreoTls.ps1')
[AstreoTls]::AcceptAny = $true
[AstreoTls]::Enable($null)
try {
  $wc = New-Object System.Net.WebClient
  $ca = $wc.DownloadData("$Central/astreo-ca.crt")
} catch { Fail ("server centrale non raggiungibile: {0}" -f $_.Exception.Message) }
[AstreoTls]::AcceptAny = $false
$sha = -join ([System.Security.Cryptography.SHA256]::Create().ComputeHash($ca) | ForEach-Object { $_.ToString('x2') })
if ($CaSha256) {
  if ($sha -ne $CaSha256.ToLower()) { Fail "l'impronta della CA non coincide ($sha): possibile intercettazione, installazione interrotta" }
} else {
  Write-Host "Impronta SHA256 della CA del centrale: $sha"
  if ((Read-Host 'Coincide con quella mostrata dalla dashboard? [s/N]') -notmatch '^(s|si|y|yes)$') { Fail 'installazione annullata' }
}
$caFile = Join-Path $Dir 'central-ca.crt'
[System.IO.File]::WriteAllBytes($caFile, $ca)

# --- configurazione e script
@{ central = $Central; token = $Token; ca_file = $caFile } | ConvertTo-Json | Set-Content -Path (Join-Path $Dir 'agent.json') -Encoding UTF8
Copy-Item $agentScript (Join-Path $Dir 'astreo-agent.ps1') -Force
Copy-Item (Join-Path $PSScriptRoot 'AstreoTls.ps1') (Join-Path $Dir 'AstreoTls.ps1') -Force

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir 'astreo-agent.ps1') -TestConnection
if ($LASTEXITCODE -ne 0) { Fail "collegamento non riuscito: controlla indirizzo, VPN e token (dettagli in $Dir\agent.log)" }

# --- attivita' pianificata: ogni minuto come SYSTEM
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f (Join-Path $Dir 'astreo-agent.ps1'))
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$boot = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($trigger, $boot) -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Agente installato: i dati compaiono nella dashboard del centrale entro un paio di minuti."
