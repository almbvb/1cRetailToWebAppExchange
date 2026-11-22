# 1cRetailToWebAppExchange

Шаблон сайта-PWA доставки продуктов с обменом с 1С:Розница 2.3.
Сайт принимает из 1С каталог, цены, остатки, картинки и статусы заказов, а сам вызывает API 1С
для проверки наличия и создания заказа. Оплата — при получении.

- **Backend:** Python 3.14, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 18 — `backend/`
- **Frontend:** Vite + React + TypeScript, PWA — `frontend/`
- **Тема клиента** (цвета, логотип, тексты): `frontend/src/theme/`, `frontend/public/brand/`

## Структура

```
backend/     API сайта, приём данных из 1С (/exchange/1c), клиент API 1С, модели, миграции, тесты
frontend/    витрина, корзина, личный кабинет (PWA)
scripts/     запуск стенда: db.ps1, dev_backend.ps1, dev_frontend.ps1
tools/       служебные утилиты (повтор порций обмена для тестов)
docs/        документация
journal.md   журнал решений сайта
state.md     текущее состояние, этапы, стенд
```

## Быстрый старт (Windows)

1. Скопировать `.env.example` в `.env` и заполнить. Секреты хранятся только в `.env`, он не коммитится.
2. PostgreSQL: `scripts\db.ps1 start`.
3. Backend: см. `backend/README.md`, запуск — `scripts\dev_backend.ps1` (http://127.0.0.1:8090).
4. Frontend: см. `frontend/README.md`, запуск — `scripts\dev_frontend.ps1` (http://localhost:3000).
5. В 1С («Настройки обмена с приложением») указать адрес API приложения `http://localhost:8090/exchange/1c`
   и логин и пароль из `.env` (`EXCHANGE_BASIC_USER`, `EXCHANGE_BASIC_PASSWORD`).

## Новый клиент из шаблона

```powershell
gh repo create almbvb/<клиент>-shop --template almbvb/1cRetailToWebAppExchange --private --clone
```

В клиентском репозитории менять только тему и `.env`. Обновить ядро из шаблона:

```powershell
git remote add template https://github.com/almbvb/1cRetailToWebAppExchange.git
git fetch template
git merge template/main
```

## Контракт с 1С

Контракт обмена ведёт сторона 1С (`api_spec.md`). Поддерживаемая версия — в `state.md`.
