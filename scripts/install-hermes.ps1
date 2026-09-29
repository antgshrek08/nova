# Install Nova's isolated, pinned Hermes ACP runtime (no second desktop app).
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$novaRoot = Split-Path $PSScriptRoot -Parent
$backendRoot = Join-Path $novaRoot 'backend'
$sourceRoot = Join-Path $backendRoot 'vendor\hermes-agent'
$runtimeRoot = Join-Path $backendRoot '.venv-hermes'
$runtimePython = Join-Path $runtimeRoot 'Scripts\python.exe'
$revision = '1021a0325696e9070e6659f95fcd84c3e7e114df'
if (-not (Test-Path -LiteralPath $sourceRoot)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $sourceRoot -Parent) | Out-Null
    git clone https://github.com/NousResearch/hermes-agent.git $sourceRoot
    if ($LASTEXITCODE -ne 0) { throw 'Hermes checkout failed.' }
    git -C $sourceRoot checkout --detach $revision
    if ($LASTEXITCODE -ne 0) { throw 'Could not select the tested Hermes revision.' }
}
$actualRevision = git -C $sourceRoot rev-parse HEAD
if ($actualRevision -ne $revision) { throw 'Existing Hermes source differs from the tested revision; left untouched.' }
if (-not (Test-Path -LiteralPath $runtimePython)) {
    & (Join-Path $backendRoot '.venv\Scripts\python.exe') -m venv $runtimeRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Hermes virtual environment.' }
}
& $runtimePython -m pip install -e "${sourceRoot}[acp]"
if ($LASTEXITCODE -ne 0) { throw 'Hermes dependency installation failed.' }
& $runtimePython -m acp_adapter --check
if ($LASTEXITCODE -ne 0) { throw 'Hermes ACP startup check failed.' }
Write-Host 'Hermes is installed. Select Hermes in Nova after restarting Nova.'
