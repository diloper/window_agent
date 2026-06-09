$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $repoRoot 'tools\hooks'
$targetDir = Join-Path $repoRoot '.git\hooks'

if (-not (Test-Path $targetDir)) {
    throw "Cannot find .git/hooks at $targetDir"
}

$hookNames = @('pre-commit', 'pre-push')

foreach ($hook in $hookNames) {
    $source = Join-Path $sourceDir $hook
    $target = Join-Path $targetDir $hook

    if (-not (Test-Path $source)) {
        throw "Missing source hook: $source"
    }

    Copy-Item -Path $source -Destination $target -Force
    Write-Host "Installed hook: $hook"
}

Write-Host 'Hook installation complete.'
