# Управление локальным PostgreSQL стенда (переносная сборка, без службы Windows).
# Использование: .\scripts\db.ps1 start | stop | status | psql [база]
# Пути можно переопределить переменными окружения PG_HOME и PG_DATA.
# Пароли не хранятся здесь: psql берёт их из %APPDATA%\postgresql\pgpass.conf.
param(
    [Parameter(Position = 0)][ValidateSet('start', 'stop', 'status', 'psql')][string]$Command = 'status',
    [Parameter(Position = 1)][string]$Database = 'delivery_site'
)

$PgHome = if ($env:PG_HOME) { $env:PG_HOME } else { 'C:\_web\pgsql' }
$PgData = if ($env:PG_DATA) { $env:PG_DATA } else { 'C:\_web\pgdata' }
$PgLog = Join-Path (Split-Path $PgData -Parent) 'pglog\postgres.log'
$PgCtl = Join-Path $PgHome 'bin\pg_ctl.exe'

switch ($Command) {
    'start' {
        New-Item -ItemType Directory -Force (Split-Path $PgLog -Parent) | Out-Null
        # Отдельный скрытый процесс: иначе сервер наследует поток вывода и вызов не завершается.
        # Ждём только pg_ctl (Start-Process -Wait ждал бы и дочерний postgres).
        $p = Start-Process -FilePath $PgCtl -ArgumentList @('-D', "`"$PgData`"", '-l', "`"$PgLog`"", '-w', 'start') -WindowStyle Hidden -PassThru
        $p.WaitForExit()
        & $PgCtl -D $PgData status
    }
    'stop' { & $PgCtl -D $PgData -m fast -w stop }
    'status' { & $PgCtl -D $PgData status }
    'psql' { & (Join-Path $PgHome 'bin\psql.exe') -h 127.0.0.1 -p 5433 -U delivery -d $Database }
}
