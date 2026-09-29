param([switch]$SkipBuild, [int]$DebugPort = 0, [switch]$Miniplayer, [switch]$PetOnly)
$ErrorActionPreference = 'Stop'
$novaRoot = Split-Path $PSScriptRoot -Parent
$frontendRoot = Join-Path $novaRoot 'frontend'
$electronPath = Join-Path $frontendRoot 'node_modules\electron\dist\electron.exe'
$nodePath = (Get-Command node.exe -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $electronPath)) { throw 'Nova dependencies are missing.' }

# Build the local checkout directly; this does not create an installer.
if (-not $SkipBuild) {
    Push-Location $frontendRoot
    try {
        & $nodePath (Join-Path $frontendRoot 'node_modules\vite\bin\vite.js') build
        if ($LASTEXITCODE -ne 0) { throw 'Nova frontend build failed.' }
    } finally { Pop-Location }
}

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $ownerId = @($listener)[0].OwningProcess
    $ownerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId"
    $parentProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($ownerProcess.ParentProcessId)"
    $expectedPython = Join-Path $novaRoot 'backend\.venv\Scripts\python.exe'
    $owned = ($ownerProcess.ExecutablePath -eq $expectedPython -or $parentProcess.ExecutablePath -eq $expectedPython) -and $ownerProcess.CommandLine -match 'uvicorn\s+app.main:app'
    if (-not $owned) { throw 'Port 8000 belongs to another process; Nova did not stop it.' }
    $tasks = Invoke-RestMethod 'http://127.0.0.1:8000/workspace/tasks' -TimeoutSec 5
    if (@($tasks | Where-Object { $_.status -in @('running', 'queued') }).Count) {
        throw 'Nova has active workspace tasks. Let them finish or cancel them before restarting.'
    }
}

# Only this checkout’s Electron processes are stopped.
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $electronPath } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
}
if ($listener -and (Get-Process -Id $ownerId -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $ownerId
}
$env:NODE_ENV = 'production'
$launchArgs = @('.')
if ($Miniplayer) { $launchArgs += '--nova-miniplayer' }
# -PetOnly starts the miniplayer as Nova's ONLY window, with a tray icon to
# open the full app or quit. -Miniplayer above still means "pet alongside the
# main window"; these are different modes, not degrees of the same one.
if ($PetOnly) { $launchArgs += '--nova-miniplayer-only' }
if ($DebugPort -gt 0) { $launchArgs += "--remote-debugging-port=$DebugPort" }
Start-Process -FilePath $electronPath -ArgumentList $launchArgs -WorkingDirectory $frontendRoot
