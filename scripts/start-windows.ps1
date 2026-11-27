[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$FrontendDir = Join-Path $RepoRoot "frontend"
$FrontendModules = Join-Path $FrontendDir "node_modules"
$Backend = $null

if (-not (Test-Path $Python -PathType Leaf)) {
    throw "The Python environment is missing. Run scripts/setup-windows.ps1 first."
}
if (-not (Test-Path $FrontendModules -PathType Container)) {
    throw "Frontend dependencies are missing. Run scripts/setup-windows.ps1 first."
}
if (-not (Get-Command "npm" -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js 20 or newer and reopen PowerShell."
}

try {
    Write-Host "Starting backend at http://127.0.0.1:8000 ..." -ForegroundColor Cyan
    $Backend = Start-Process `
        -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $RepoRoot `
        -PassThru `
        -WindowStyle Hidden

    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        if ($Backend.HasExited) {
            throw "The backend exited during startup with code $($Backend.ExitCode)."
        }
        try {
            $Response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8000/health" `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($Response.StatusCode -eq 200) {
                $Ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }

    if (-not $Ready) {
        throw "The backend did not become ready within 30 seconds."
    }

    Write-Host "Starting editor at http://127.0.0.1:5173" -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop both services."
    Push-Location $FrontendDir
    try {
        & npm run dev -- --host 127.0.0.1
        if ($LASTEXITCODE -ne 0) {
            throw "The frontend exited with code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($null -ne $Backend -and -not $Backend.HasExited) {
        Write-Host "Stopping backend ..." -ForegroundColor Cyan
        Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
        $Backend.WaitForExit()
    }
}
