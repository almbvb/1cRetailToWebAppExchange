# Запуск dev-сервера фронтенда (Vite) на http://localhost:3000.
# Запросы /api и /media проксируются на backend http://127.0.0.1:8090
# (другой адрес: $env:BACKEND_URL = 'http://127.0.0.1:8091' перед запуском).
# Использование: .\scripts\dev_frontend.ps1   (остановка — Ctrl+C)
$ErrorActionPreference = 'Stop'
$Frontend = Join-Path (Split-Path $PSScriptRoot -Parent) 'frontend'

Push-Location $Frontend
try {
    if (-not (Test-Path 'node_modules')) { npm ci }
    npm run dev
}
finally {
    Pop-Location
}
