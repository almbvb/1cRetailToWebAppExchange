# Запуск стенда сайта одной командой: PostgreSQL, backend (8090) и, по желанию, фронтенд (3000).
# Использование:  .\scripts\start.ps1            — база + backend
#                 .\scripts\start.ps1 -Frontend  — база + backend + фронтенд
# Backend и фронтенд открываются в отдельных окнах PowerShell; закрыть окно = остановить сервер.
param([switch]$Frontend)

$Root = Split-Path $PSScriptRoot -Parent

function Test-Port([int]$Port) {
    [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

# 1. База данных
Write-Host '1. PostgreSQL...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'db.ps1') start | Select-Object -First 1

# 2. Backend
Write-Host '2. Backend (http://127.0.0.1:8090)...' -ForegroundColor Cyan
if (Test-Port 8090) {
    Write-Host '   Порт 8090 уже занят — backend, вероятно, уже запущен.' -ForegroundColor Yellow
} else {
    Start-Process powershell -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $PSScriptRoot 'dev_backend.ps1')) -WorkingDirectory $Root
}

# 3. Фронтенд (по желанию)
if ($Frontend) {
    Write-Host '3. Фронтенд (http://localhost:3000)...' -ForegroundColor Cyan
    if (Test-Port 3000) {
        Write-Host '   Порт 3000 уже занят (другой проект или уже запущен).' -ForegroundColor Yellow
    } else {
        Start-Process powershell -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File',
            (Join-Path $PSScriptRoot 'dev_frontend.ps1')) -WorkingDirectory $Root
    }
}

# 4. Проверка
Write-Host 'Проверка сайта...' -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8090/api/health' -TimeoutSec 3
        if ($r.db) { $ok = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if ($ok) {
    Write-Host 'Готово: сайт работает, база доступна.' -ForegroundColor Green
    Write-Host '  Обмен для 1С:  http://localhost:8090/exchange/1c'
    Write-Host '  Админпанель:   http://127.0.0.1:8090/admin'
    if ($Frontend) { Write-Host '  Витрина:       http://localhost:3000' }
} else {
    Write-Host 'Сайт не ответил за 30 секунд — посмотрите окно backend (ошибки) и docs\ЗАПУСК.md.' -ForegroundColor Red
}
