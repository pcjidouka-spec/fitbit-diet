$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$gitDir = Join-Path $projectRoot ".git"
$sourceHook = Join-Path $projectRoot ".githooks/post-commit"
$targetHook = Join-Path $gitDir "hooks/post-commit"

if (-not (Test-Path $gitDir)) {
    Write-Error "'.git' not found. Run 'git init' first."
}

if (-not (Test-Path $sourceHook)) {
    Write-Error "Hook template not found: $sourceHook"
}

Copy-Item $sourceHook $targetHook -Force

try {
    & git update-index --chmod=+x ".githooks/post-commit" 2>$null | Out-Null
} catch {
}

Write-Host "post-commit hook installed: $targetHook"
Write-Host "MEMORY_PENDING.md will be auto-updated on each commit."
