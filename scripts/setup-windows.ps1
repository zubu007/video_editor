[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Require-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$InstallHint
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. $InstallHint"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-Host "`n==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Video Editor Windows setup" -ForegroundColor Green
Write-Host "Repository: $RepoRoot"

Require-Command "git" "Install Git for Windows from https://git-scm.com/download/win and reopen PowerShell."
Require-Command "uv" "Install uv from https://docs.astral.sh/uv/getting-started/installation/ and reopen PowerShell."
Require-Command "node" "Install the current Node.js LTS release from https://nodejs.org/."
Require-Command "npm" "npm is installed with Node.js; reinstall Node.js LTS if it is missing."

$NodeVersion = (& node --version).Trim().TrimStart("v")
$NodeParts = $NodeVersion.Split(".")
$NodeMajor = [int]$NodeParts[0]
$NodeMinor = [int]$NodeParts[1]
$NodeSupported = `
    ($NodeMajor -eq 20 -and $NodeMinor -ge 19) -or `
    ($NodeMajor -ge 22 -and ($NodeMajor -gt 22 -or $NodeMinor -ge 12))
if (-not $NodeSupported) {
    throw "Vite requires Node.js 20.19+ (20.x) or 22.12+; found $NodeVersion. Install the current LTS release."
}

Push-Location $RepoRoot
try {
    Invoke-Checked "Installing the locked Python 3.11 environment" {
        & uv sync --python 3.11 --locked --no-dev
    }

    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        Invoke-Checked "Installing frontend dependencies" {
            & npm ci
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Run: powershell -ExecutionPolicy Bypass -File scripts/start-windows.ps1"
Write-Host "Death detection and death cuts need no API keys and no Tesseract installation."
if (-not (Get-Command "tesseract" -ErrorAction SilentlyContinue)) {
    Write-Host "Optional: install Tesseract and add it to PATH only if you want K/D/A timeline markers." -ForegroundColor Yellow
}
