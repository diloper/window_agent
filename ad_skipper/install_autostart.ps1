<#
.SYNOPSIS
    Phase 6 - register a Windows Scheduled Task that auto-starts the YouTube
    ad-skipper at user logon (hidden, no console).

.DESCRIPTION
    Creates an "At log on" task for the current user that runs the venv
    pythonw.exe against youtube_ad_skipper.py with the Phase 6 flags
    (--only-youtube-watch --single-instance --conf 0.9 ...). The skipper's
    named-mutex guard means re-triggering is harmless if it is already running,
    satisfying "check if already started, otherwise auto-start".

    Run this once from a normal (non-elevated) PowerShell:
        Set-Location R:\SAM
        powershell -ExecutionPolicy Bypass -File ad_skipper\install_autostart.ps1
#>
[CmdletBinding()]
param(
    [string] $TaskName = 'SAM YouTube Ad Skipper',
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
if (-not (Test-Path $Model)) { Write-Warning "Model not found yet: $Model (train it in Phase 4 before relying on the task)" }
New-Item -ItemType Directory -Force $LogDir | Out-Null

$argLine = @(
    "`"$Skipper`"",
    '--model', "`"$Model`"",
    '--monitor', $Monitor,
    '--conf', $Conf,
    '--only-youtube-watch',
    '--single-instance',
    '--fallback', $Fallback,
    '--log-file', "`"$LogFile`""
) -join ' '

$action = New-ScheduledTaskAction -Execute $Pythonw -Argument $argLine -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' (At log on)."
Write-Host "Test now without logging off:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Log file: $LogFile"
