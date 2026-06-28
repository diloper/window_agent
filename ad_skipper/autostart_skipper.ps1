<#
.SYNOPSIS
    Phase 6 launcher - start the YouTube ad-skipper hidden in the background.

.DESCRIPTION
    Resolves the repo virtual-env pythonw.exe (no console window) and launches
    youtube_ad_skipper.py with the Phase 6 runtime flags. The script's own
    single-instance guard ensures a second launch exits cleanly, so this can be
    invoked at every logon safely.

    This is used both by the scheduled task (see install_autostart.ps1) and for
    manual testing.
#>
[CmdletBinding()]
param(
    [int]    $Monitor = 1,
    [double] $Conf = 0.9,
    [ValidateSet('title', 'none', 'watch')]
    [string] $Fallback = 'title'
)

$ErrorActionPreference = 'Stop'

$ScriptDir = $PSScriptRoot
$RepoRoot = Split-Path $ScriptDir -Parent

$Pythonw = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
$Skipper = Join-Path $ScriptDir 'youtube_ad_skipper.py'
$Model = Join-Path $ScriptDir 'models\skip_ad_yolo.pt'
$LogDir = Join-Path $ScriptDir 'logs'
$LogFile = Join-Path $LogDir 'skipper.log'

if (-not (Test-Path $Pythonw)) { throw "pythonw.exe not found: $Pythonw" }
if (-not (Test-Path $Skipper)) { throw "Skipper script not found: $Skipper" }
if (-not (Test-Path $Model)) { Write-Warning "Model not found yet: $Model (Phase 4 output)" }
New-Item -ItemType Directory -Force $LogDir | Out-Null

$argList = @(
    "`"$Skipper`"",
    '--model', "`"$Model`"",
    '--monitor', $Monitor,
    '--conf', $Conf,
    '--only-youtube-watch',
    '--single-instance',
    '--fallback', $Fallback,
    '--log-file', "`"$LogFile`""
)

Start-Process -FilePath $Pythonw -ArgumentList $argList -WorkingDirectory $RepoRoot -WindowStyle Hidden
Write-Host "Launched ad-skipper (hidden). Log: $LogFile"
