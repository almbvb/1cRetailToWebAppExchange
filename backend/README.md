# Backend сайта доставки

FastAPI + SQLAlchemy 2 (синхронно, psycopg 3) + Alembic, PostgreSQL. Python 3.14.

Настройки читаются из `.env` в корне репозитория (ключи — в `.env.example`, умолчания — в `app/config.py`).
Для тестов нужна переменная `TEST_DATABASE_URL` (отдельная база, например `delivery_site_test`).

## Установка

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Версии зависимостей закреплены в `pyproject.toml`.

## Запуск

```powershell
.\scripts\dev_backend.ps1        # из корня репозитория
```

Проверка: http://127.0.0.1:8090/api/health → `{"status": "ok", "db": true}` (503 и `db: false`, если база
недоступна). Документация API: http://127.0.0.1:8090/docs

## Тесты и линтер

```powershell
cd backend
.\.venv\Scripts\pytest
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format .
```

Тесты работают только с `TEST_DATABASE_URL`: перед запуском схема приводится к head миграциями, каждый тест
выполняется в транзакции с откатом.

## Миграции

```powershell
cd backend
.\.venv\Scripts\alembic upgrade head                     # основная база (DATABASE_URL)
.\.venv\Scripts\alembic -x db=test upgrade head          # тестовая база (TEST_DATABASE_URL)
.\.venv\Scripts\alembic revision --autogenerate -m "..."  # новая ревизия
```

Адрес базы берётся из настроек, а не из `alembic.ini`. Новые модели нужно импортировать в
`app/models/__init__.py`, иначе autogenerate их не увидит. `alembic.ini` — только ASCII (Alembic читает его
в кодировке ОС).

## Приём из 1С

Базовый адрес для настроек обмена в 1С: `http://localhost:8090/exchange/1c` (пути `/catalog`, `/prices`,
`/stock`, `/images/{product_id}`, `/orders/status` — `api_spec.md` разд. 3; проект — `docs/c1_exchange.md`).

- **Вход:** HTTP Basic (`EXCHANGE_BASIC_USER` / `EXCHANGE_BASIC_PASSWORD`) или `Authorization: Bearer <токен>`
  (`EXCHANGE_BEARER_TOKENS`). Без верных данных — `401 UNAUTHORIZED` и `WWW-Authenticate: Basic realm="exchange"`.
- **Ошибки** внутри `/exchange/1c` — всегда `{"error": {"code", "message", "details": []}}`: `400 INVALID_FORMAT`
  (`details` — поля вида `products[3].id`), `401`, `404 NOT_FOUND`, `405 METHOD_NOT_ALLOWED`,
  `413 PAYLOAD_TOO_LARGE` (JSON больше 20 МБ), `500 INTERNAL_ERROR` (текст исключения — только в лог).
- **Порция** — одна транзакция; `200 {"ok": true, "counts": {...}}` — только после фиксации.
- **Журнал обмена** — таблица `exchange_batches`: строка на каждый запрос (в том числе при ошибке), в отдельной
  транзакции: время, метод, путь, поток, HTTP-код, вход (`Basic user=<логин>` / `Bearer`, без пароля и токена),
  `full`, счётчики, код и текст ошибки, байты тела, длительность. Тело порции не хранится.

Код: `app/exchange/onec/` — `router.py` (роутер и `setup_onec_exchange`), `auth.py`, `errors.py`, `journal.py`,
`common.py` (тело, JSON, UPSERT, ответ), потоки — `catalog.py`, `prices.py`, `stock.py`, `images.py`,
`orders_status.py`. Тесты — `tests/exchange/` (фикстуры в `conftest.py`).

## Структура

- `app/main.py` — `create_app()`, CORS, подключение роутеров
- `app/config.py` — `Settings`, `get_settings()`
- `app/db.py` — `Base`, `engine`, `SessionLocal`, `get_db()`
- `app/api/` — API для фронтенда (`/api`)
- `app/exchange/onec/` — приём данных из 1С (`/exchange/1c`)
- `app/onec_client/` — клиент API 1С
- `app/models/`, `app/services/` — модели и бизнес-логика
