# Остановка стенда сайта: backend (8090), фронтенд (3000) и PostgreSQL.
# Использование:  .\scripts\stop.ps1          — всё
#                 .\scripts\stop.ps1 -KeepDb  — оставить базу работать
# Останавливаются только процессы этого проекта (проверка по командной строке).
param([switch]$KeepDb)

function Stop-ProjectPort([int]$Port, [string]$Pattern, [string]$Name) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conn) { Write-Host "${Name}: не запущен"; return }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)"
    if ($proc.CommandLine -like $Pattern) {
        # uvicorn --reload держит дочерний процесс: останавливаем и родителя.
        if ($proc.ParentProcessId) {
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)"
            if ($parent -and $parent.CommandLine -like $Pattern) { Stop-Process -Id $parent.ProcessId -Force -ErrorAction SilentlyContinue }
        }
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "${Name}: остановлен"
    } else {
        Write-Host "${Name}: порт $Port занят другим процессом ($($proc.Name)) — не трогаю" -ForegroundColor Yellow
    }
}

Stop-ProjectPort 8090 '*uvicorn*app.main*' 'Backend (8090)'
Stop-ProjectPort 3000 '*delivery_site*frontend*' 'Фронтенд (3000)'
if (-not $KeepDb) { & (Join-Path $PSScriptRoot 'db.ps1') stop }
