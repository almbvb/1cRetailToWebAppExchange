"""ЗАГЛУШКА С1-Т1. Поток каталога POST /exchange/1c/catalog (api_spec.md 3.1) — реализует Т2.

Инструкция исполнителю Т2 (файл переписывается целиком; docs/c1_exchange.md — «Общие правила приёма»):

1. Маршрут: `router = APIRouter()` и `@router.post("/catalog")`; префикс /exchange/1c и вход (Basic/Bearer)
   уже даёт router.py — сами не проверяйте. Обработчик — обычная `def` (синхронная БД).
2. Тело: модели порции наследуйте от `common.ExchangeModel` (неизвестные поля игнорируются), типы —
   `common.Guid`, `Money`, `Quantity`, `Timestamp`; параметр
   `body: Annotated[CatalogIn, Depends(json_body(CatalogIn))]` — предел 20 МБ, неверный JSON и ошибки
   полей -> 400 INVALID_FORMAT c details вида `products[3].id`.
   Проверяйте только то, что задаёт контракт (К-5).
3. БД: `db: Annotated[Session, Depends(get_db)]` (app.db). Вся порция — одна транзакция: сначала все
   upsert, затем `db.commit()`, затем ответ. Исключение до commit -> откат порции (сессия закрывается).
4. Запись: `upsert(db, CatalogProduct, rows)` из common — INSERT ... ON CONFLICT по первичному ключу,
   пакетами, повторы ключа в порции убираются (остаётся последняя), received_at обновляется сам.
   Явная дедупликация списка: `dedupe_last(items, key=...)`. rows — словари с именами колонок таблицы.
5. Журнал: параметр `journal: Journal` (journal.py). Поток (`stream`) определяется по пути сам; `full`
   из тела json_body записывает сам; счётчики — через ответ: `return ok_response(journal, groups=…, units=…,
   products=…)` -> 200 {"ok": true, "counts": {...}} и counts в журнал.
6. Ошибка порции: `raise ExchangeError(400, INVALID_FORMAT, "текст", [{"field": "...", "message": "..."}])`
   (errors.py) — ответ в формате контракта, порция откатывается, строка журнала пишется.
7. Тесты: tests/exchange/conftest.py — фикстуры `exchange_client` (.post_json("/catalog", body)),
   `db_session`, `db_fetch`, `journal_rows`, константы TEST_STORE_ID и др.
"""

from fastapi import APIRouter

from app.exchange.onec.errors import NOT_IMPLEMENTED, ExchangeError

router = APIRouter()


@router.post("/catalog", summary="Каталог: группы, единицы, товары (заглушка)")
def receive_catalog() -> None:
    raise ExchangeError(501, NOT_IMPLEMENTED, "Поток catalog ещё не реализован")
