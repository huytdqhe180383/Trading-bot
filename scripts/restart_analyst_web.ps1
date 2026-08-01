<#
.SYNOPSIS
Restart the local analyst web stack.

.DESCRIPTION
Stops listeners on the backend/frontend ports, then starts:
- FastAPI private UI / analyst API on 127.0.0.1:8080
- Next.js TradingView-style analyst frontend on 127.0.0.1:3000

Logs are written to logs/analyst_web_backend_*.log and
logs/analyst_web_frontend_*.log.
#>

[CmdletBinding()]
param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8080,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 3000,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendRoot = Join-Path $RepoRoot "frontend"
$LogsRoot = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogsRoot | Out-Null

function Test-Executable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$Args = @("--version")
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    try {
        $process = Start-Process -FilePath $Path -ArgumentList $Args -NoNewWindow -PassThru -Wait -RedirectStandardOutput "$env:TEMP\analyst_web_probe_stdout.txt" -RedirectStandardError "$env:TEMP\analyst_web_probe_stderr.txt"
        return $process.ExitCode -eq 0
    } catch {
        return $false
    }
}

function Resolve-Python {
    $candidates = @(
        $env:PYTHON,
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (Test-Executable -Path $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command -and (Test-Executable -Path $command.Source)) {
        return $command.Source
    }

    throw "Could not find a working Python executable. Set `$env:PYTHON to python.exe and retry."
}

function Resolve-Pnpm {
    $candidates = @(
        $env:PNPM,
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd")
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $command = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    if (-not $command) {
        $command = Get-Command pnpm -ErrorAction SilentlyContinue
    }
    if ($command) {
        return $command.Source
    }

    throw "Could not find pnpm. Install pnpm or set `$env:PNPM to pnpm.cmd and retry."
}

function Add-NodeToPath {
    $codexNodeBin = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
    if (Test-Path -LiteralPath (Join-Path $codexNodeBin "node.exe")) {
        $env:PATH = "$codexNodeBin;$env:PATH"
    }
}

function Stop-ListenersOnPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    $pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -and $_ -ne $PID })
    foreach ($processId in $pids) {
        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            Write-Host "Stopping PID $processId ($($process.ProcessName)) on port $Port..."
            Stop-Process -Id $processId -Force -ErrorAction Stop
        } catch {
            Write-Warning "Could not stop PID $processId on port ${Port}: $($_.Exception.Message)"
        }
    }
}

function Wait-ForPort {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

Write-Host "Restarting analyst web stack from $RepoRoot"

Stop-ListenersOnPort -Port $BackendPort
if (-not $SkipFrontend) {
    Stop-ListenersOnPort -Port $FrontendPort
}

$python = Resolve-Python
Write-Host "Using Python: $python"

$backendStdout = Join-Path $LogsRoot "analyst_web_backend_stdout.log"
$backendStderr = Join-Path $LogsRoot "analyst_web_backend_stderr.log"
$backend = Start-Process -FilePath $python `
    -ArgumentList @("scripts/run_ui.py") `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendStdout `
    -RedirectStandardError $backendStderr `
    -PassThru

if (-not (Wait-ForPort -Port $BackendPort -TimeoutSeconds 30)) {
    Write-Warning "Backend did not bind port $BackendPort within 30 seconds. Check $backendStderr"
} else {
    Write-Host "Backend ready: http://${BackendHost}:$BackendPort (PID $($backend.Id))"
}

if (-not $SkipFrontend) {
    Add-NodeToPath
    $pnpm = Resolve-Pnpm
    Write-Host "Using pnpm: $pnpm"

    if (-not (Test-Path -LiteralPath (Join-Path $FrontendRoot "node_modules"))) {
        Write-Host "frontend/node_modules not found. Running pnpm install..."
        Push-Location $FrontendRoot
        try {
            & $pnpm install
            if ($LASTEXITCODE -ne 0) {
                throw "pnpm install failed with exit code $LASTEXITCODE"
            }
        } finally {
            Pop-Location
        }
    }

    $frontendStdout = Join-Path $LogsRoot "analyst_web_frontend_stdout.log"
    $frontendStderr = Join-Path $LogsRoot "analyst_web_frontend_stderr.log"
    $frontend = Start-Process -FilePath $pnpm `
        -ArgumentList @("dev", "--hostname", $FrontendHost, "--port", [string]$FrontendPort) `
        -WorkingDirectory $FrontendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendStdout `
        -RedirectStandardError $frontendStderr `
        -PassThru

    if (-not (Wait-ForPort -Port $FrontendPort -TimeoutSeconds 45)) {
        Write-Warning "Frontend did not bind port $FrontendPort within 45 seconds. Check $frontendStderr"
    } else {
        Write-Host "Frontend ready: http://${FrontendHost}:$FrontendPort (PID $($frontend.Id))"
    }
}

Write-Host ""
Write-Host "Open frontend: http://${FrontendHost}:$FrontendPort"
Write-Host "Backend API: http://${BackendHost}:$BackendPort"
