$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Install Docker Desktop and start it before running this script.'
}
docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running.' }
if (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonExe = 'python'
    $PythonArgs = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonExe = 'py'
    $PythonArgs = @('-3')
} else { throw 'Install Python 3.10 or later, then run this script again.' }
& $PythonExe @PythonArgs tools/mvp.py init
if ($LASTEXITCODE -ne 0) { throw 'Initialization failed.' }
# Windows PowerShell 5.1 can treat native stderr as a terminating error.
# A missing image is expected on the first run; redirect inside cmd.exe.
cmd.exe /d /c 'docker image inspect iecho/maps:1.18.1-verified >nul 2>&1'
if ($LASTEXITCODE -ne 0) {
    & $PythonExe @PythonArgs tools/build_maps.py
    if ($LASTEXITCODE -ne 0) { throw 'Verified scraper build failed; CRM can still run with docker compose up -d.' }
}
docker compose --profile maps up -d
if ($LASTEXITCODE -ne 0) { throw 'Container startup failed.' }
& $PythonExe @PythonArgs tools/mvp.py setup
if ($LASTEXITCODE -ne 0) { throw 'France CRM configuration failed.' }
& $PythonExe @PythonArgs tools/mvp.py health
if ($LASTEXITCODE -ne 0) { throw 'Readiness check failed.' }
& $PythonExe @PythonArgs tools/check_maps.py
if ($LASTEXITCODE -ne 0) { throw 'Scraper readiness check failed.' }
if (Test-Path 'starter/france-lyon-candidates.csv') {
    & $PythonExe @PythonArgs tools/mvp.py import starter/france-lyon-candidates.csv
    if ($LASTEXITCODE -ne 0) { throw 'Starter candidate import failed.' }
}
Write-Host 'Ready. CRM: local port 8080. Maps: local port 8082.'
Write-Host 'Login: admin. Read CRM_ADMIN_PASSWORD from your local .env file; keep it private.'
Start-Process 'http://localhost:8080'
