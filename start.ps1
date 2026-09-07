# SCALPER AGENT V4 - Gelistirme Baslatici (Windows)
# Backend (8004) + Frontend (3004) ayri pencerelerde acilir.

$ErrorActionPreference = "Stop"

Write-Host "=== SCALPER AGENT V4 BASLATILIYOR ===" -ForegroundColor Cyan

# Port kontrolu: ayni portta calisan bir surec varsa uvicorn 10048 ile coker.
foreach ($port in 8004, 3004) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        Write-Host "[!] Port $port zaten kullanimda (PID: $($listener[0].OwningProcess)). Once o sureci durdur." -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-Path "backend\venv\Scripts\Activate.ps1")) {
    Write-Host "[!] backend\venv bulunamadi. Once: python -m venv backend\venv" -ForegroundColor Red
    exit 1
}

Write-Host "[+] Backend (Port 8004) baslatiliyor..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; .\venv\Scripts\activate; uvicorn app.main:app --reload --port 8004"

Write-Host "[+] Frontend (Port 3004) baslatiliyor..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"

Write-Host "`n[+] Servisler baslatildi!" -ForegroundColor Green
Write-Host "Frontend: http://localhost:3004" -ForegroundColor Green
