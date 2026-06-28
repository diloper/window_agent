<#
.SYNOPSIS
    Phase 6 - remove the auto-start Scheduled Task and stop any running skipper.

.DESCRIPTION
    Stops the task if running, then unregisters it. Does not delete the trained
    model or logs.

    Usage:
        Set-Location R:\SAM
        powershell -ExecutionPolicy Bypass -File ad_skipper\uninstall_autostart.ps1
#>
[CmdletBinding()]
param(
    [string] $TaskName = 'SAM YouTube Ad Skipper'
)

$ErrorActionPreference = 'Stop'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Scheduled task '$TaskName' not found; nothing to remove."
    return
}

try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch { }
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task '$TaskName'."
Write-Host "Note: a currently-running skipper process (pythonw) is not force-killed; it stops on next logoff or via Task Manager."
