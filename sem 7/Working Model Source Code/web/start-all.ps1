# Quant Plus: start the backend, connect Fyers if needed, then start the frontend.
# Usage:  powershell -ExecutionPolicy Bypass -File .\start-all.ps1   (or double-click start-all.cmd)
# Options: -SkipFyers   don't check or prompt for the Fyers login
#          -NoBrowser   don't open the app in the browser at the end

param(
    [switch]$SkipFyers,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$FrontendDir = $PSScriptRoot
$BackendDir  = Join-Path (Split-Path $PSScriptRoot -Parent) "agent"
$Python      = Join-Path $BackendDir ".venv\Scripts\python.exe"
$BackendUrl  = "http://127.0.0.1:8000"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    $msg" -ForegroundColor Yellow }

function Test-Port([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return [bool]$conn
}

function Get-EnvValue([string]$file, [string]$name) {
    if (-not (Test-Path $file)) { return "" }
    foreach ($line in Get-Content $file) {
        if ($line -match "^\s*$name\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return ""
}

# ---- Pre-flight checks -------------------------------------------------------
Write-Step "Checking setup"
if (-not (Test-Path $BackendDir)) { throw "Backend folder not found: $BackendDir" }
if (-not (Test-Path $Python))     { throw "Backend Python not found: $Python" }
if (-not (Test-Path "$FrontendDir\node_modules")) {
    Write-Warn2 "node_modules missing - running npm install"
    Push-Location $FrontendDir; npm install; Pop-Location
}
$ApiKey = Get-EnvValue "$BackendDir\.env" "WEBSITE_API_KEY"
$FrontKey = Get-EnvValue "$FrontendDir\.env.local" "AGENT_SERVICE_API_KEY"
if (-not $ApiKey) { throw "WEBSITE_API_KEY is not set in $BackendDir\.env" }
if ($ApiKey -ne $FrontKey) {
    Write-Warn2 "AGENT_SERVICE_API_KEY (.env.local) does not match WEBSITE_API_KEY (backend .env) - expect 401 errors."
} else {
    Write-Ok "API keys match"
}

# ---- 1. Backend --------------------------------------------------------------
Write-Step "Backend (port 8000)"
if (Test-Port 8000) {
    Write-Ok "Already running - not starting a second copy"
} else {
    $cmd = "`$Host.UI.RawUI.WindowTitle = 'Quant Plus - Backend'; Set-Location '$BackendDir'; & '$Python' -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $cmd | Out-Null
    Write-Ok "Started in a new window"
}

Write-Host "    Waiting for health check" -NoNewline
$healthy = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        Invoke-RestMethod "$BackendUrl/api/v1/health" -TimeoutSec 3 | Out-Null
        $healthy = $true; break
    } catch { Write-Host "." -NoNewline; Start-Sleep -Seconds 2 }
}
Write-Host ""
if (-not $healthy) { throw "Backend did not become healthy within 3 minutes. Check the backend window for errors." }
Write-Ok "Backend is healthy"

# ---- 2. Fyers live market data ----------------------------------------------
if (-not $SkipFyers) {
    Write-Step "Fyers live market data"
    $headers = @{ "X-Quantplus-Key" = $ApiKey }
    $status = $null
    try { $status = Invoke-RestMethod "$BackendUrl/api/v1/fyers/status" -Headers $headers -TimeoutSec 10 }
    catch { Write-Warn2 "Could not read Fyers status: $($_.Exception.Message)" }

    if ($status -and -not $status.app_configured) {
        Write-Warn2 "FYERS_CLIENT_ID / FYERS_SECRET_KEY are not set in $BackendDir\.env - skipping."
    } elseif ($status -and -not $status.login_required) {
        Write-Ok "Fyers token is valid (expires $($status.expires_at))"
    } elseif ($status) {
        Write-Warn2 "Fyers login required - opening the login page in your browser."
        Write-Warn2 "Complete the login + 2FA; the backend saves the token automatically."
        Push-Location $BackendDir
        & $Python scripts/connect_fyers.py --open | Out-Null
        Pop-Location

        Write-Host "    Waiting for Fyers login (up to 5 min)" -NoNewline
        $connected = $false
        for ($i = 0; $i -lt 100; $i++) {
            Start-Sleep -Seconds 3
            try {
                $s = Invoke-RestMethod "$BackendUrl/api/v1/fyers/status" -Headers $headers -TimeoutSec 5
                if (-not $s.login_required) { $connected = $true; break }
            } catch {}
            Write-Host "." -NoNewline
        }
        Write-Host ""
        if ($connected) { Write-Ok "Fyers connected" }
        else { Write-Warn2 "Fyers not connected - continuing with delayed/research data. Re-run this script to retry." }
    }
}

# ---- 3. Frontend -------------------------------------------------------------
Write-Step "Frontend (Vite)"
$frontPort = $null
foreach ($p in 8080, 5173) { if (Test-Port $p) { $frontPort = $p; break } }
if ($frontPort) {
    Write-Ok "Already running on port $frontPort - not starting a second copy"
} else {
    $cmd = "`$Host.UI.RawUI.WindowTitle = 'Quant Plus - Frontend'; Set-Location '$FrontendDir'; npm run dev"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $cmd | Out-Null
    Write-Ok "Started in a new window"
    Write-Host "    Waiting for Vite" -NoNewline
    for ($i = 0; $i -lt 60 -and -not $frontPort; $i++) {
        Start-Sleep -Seconds 2
        foreach ($p in 8080, 5173) { if (Test-Port $p) { $frontPort = $p; break } }
        Write-Host "." -NoNewline
    }
    Write-Host ""
}

if ($frontPort) {
    $appUrl = "http://localhost:$frontPort"
    Write-Ok "App: $appUrl"
    if (-not $NoBrowser) { Start-Process $appUrl }
} else {
    Write-Warn2 "Vite has not opened a port yet - check the Frontend window for the URL."
}

Write-Step "All set"
Write-Host "    Backend : $BackendUrl  (window 'Quant Plus - Backend')"
Write-Host "    Frontend: see window 'Quant Plus - Frontend'"
Write-Host "    To stop : close those two windows (or press Ctrl+C in each)."
