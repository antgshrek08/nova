# Dev backend launcher -- Windows-safe alternative to `uvicorn --reload`.
#
# `uvicorn app.main:app --reload` on Windows hands the worker process a
# SelectorEventLoop instead of ProactorEventLoop (uvicorn's own
# `loops/asyncio.py`: `use_subprocess = bool(reload or workers > 1)` forces
# Selector whenever true), and SelectorEventLoop cannot create subprocesses
# at all -- `asyncio.create_subprocess_exec` raises a bare NotImplementedError.
# That's exactly what breaks Claude Code CLI / Codex CLI (both real
# subprocess calls) whenever the dev server runs with --reload. The packaged
# Electron app is unaffected (electron/main.cjs launches uvicorn with neither
# --reload nor --workers). See RESEARCH.md's "Code-tab milestone" section for
# the full root-cause writeup.
#
# This script gets the same "edit and it restarts" convenience without
# --reload: it runs the backend as a single plain process (real
# ProactorEventLoop, subprocess CLIs work) and watches backend/app for .py
# changes itself, restarting the whole process (and any child processes it
# spawned, via `taskkill /T` -- some backend dependencies spawn their own
# multiprocessing workers, which a plain Stop-Process would otherwise orphan)
# whenever a file changes.
#
# Usage: powershell -File scripts/dev-backend.ps1
# Stop with Ctrl+C.

$ErrorActionPreference = "Stop"
$backendDir = Resolve-Path (Join-Path $PSScriptRoot "..\backend")
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Backend venv not found at $venvPython -- see README.md's Setup section."
    exit 1
}

function Start-Backend {
    Write-Host "[dev-backend] starting uvicorn (no --reload)..." -ForegroundColor Green
    return Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $backendDir -NoNewWindow -PassThru
}

function Stop-BackendTree($proc) {
    # taskkill can legitimately fail transiently (e.g. a child already
    # exiting on its own as we try to kill it) -- with the script's own
    # $ErrorActionPreference = "Stop", that stderr output was being treated
    # as a terminating error, silently killing the whole watcher loop rather
    # than just this one restart (confirmed live: the watcher process was
    # gone after exactly this happened, leaving a stale backend running with
    # no further auto-restart). A failed kill here isn't fatal to the watch
    # loop -- Start-Backend still runs right after and will fail loudly on
    # its own if the port is genuinely still held.
    if ($proc -and -not $proc.HasExited) {
        try { & taskkill /PID $proc.Id /T /F 2>$null | Out-Null } catch {}
    }
}

$proc = Start-Backend

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = Join-Path $backendDir "app"
$watcher.Filter = "*.py"
$watcher.IncludeSubdirectories = $true
$watcher.EnableRaisingEvents = $true

Write-Host "[dev-backend] watching backend\app for changes. Ctrl+C to stop." -ForegroundColor Cyan

try {
    while ($true) {
        $result = $watcher.WaitForChanged(
            [System.IO.WatcherChangeTypes]::Changed -bor `
            [System.IO.WatcherChangeTypes]::Created -bor `
            [System.IO.WatcherChangeTypes]::Deleted -bor `
            [System.IO.WatcherChangeTypes]::Renamed,
            1000
        )
        if ($result.TimedOut) { continue }
        Start-Sleep -Milliseconds 300  # debounce rapid saves (editors often fire several events per save)
        Write-Host "[dev-backend] change detected ($($result.Name)) -- restarting..." -ForegroundColor Yellow
        Stop-BackendTree $proc
        Start-Sleep -Milliseconds 500
        $proc = Start-Backend
    }
} finally {
    Stop-BackendTree $proc
}
