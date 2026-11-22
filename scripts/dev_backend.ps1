# Запуск backend в режиме разработки: uvicorn с автоперезагрузкой на http://127.0.0.1:8090.
# Использование: .\scripts\dev_backend.ps1   (нужен backend\.venv, см. backend\README.md)
# Настройки берутся из .env в корне репозитория.
$Backend = Join-Path (Split-Path $PSScriptRoot -Parent) 'backend'
$Python = Join-Path $Backend '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw "Нет виртуального окружения: $Python (см. backend\README.md)" }

Push-Location $Backend
try {
    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8090 --reload
}
finally {
    Pop-Location
}
