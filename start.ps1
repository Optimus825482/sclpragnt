Write-Host "=== SCALPER AGENT V4 BASLATILIYOR ===" -ForegroundColor Cyan
Write-Host "[+] Backend (Port 8004) baslatiliyor..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; .\venv\Scripts\activate; uvicorn app.main:app --reload --port 8004"
Write-Host "[+] Frontend (Port 3004) baslatiliyor..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"
Write-Host "`n[+] Servisler baslatildi!" -ForegroundColor Green
Write-Host "Frontend: http://localhost:3004" -ForegroundColor Green
