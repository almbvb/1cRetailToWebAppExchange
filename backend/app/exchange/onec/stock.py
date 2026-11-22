"""ЗАГЛУШКА С1-Т1. Поток остатков POST /exchange/1c/stock (api_spec.md 3.3) — реализует Т3.

Инструкция исполнителю Т3 (файл переписывается целиком; docs/c1_exchange.md — «Общие правила приёма»):

1. Маршрут: `router = APIRouter()` и `@router.post("/stock")`; префикс /exchange/1c и вход (Basic/Bearer)
   уже даёт router.py — сами не проверяйте. Обработчик — обычная `def` (синхронная БД).
2. Тело: модели порции наследуйте от `common.ExchangeModel`, типы `common.Guid`, `Quantity`, `Timestamp`;
   параметр `body: Annotated[StockIn, Depends(json_body(StockIn))]` — предел 20 МБ, ошибки -> 400
   INVALID_FORMAT с details вида `stock[3].updated_at`. Проверяйте только то, что задаёт контракт (К-5).
3. БД: `db: Annotated[Session, Depends(get_db)]` (app.db). Порция — одна транзакция: upsert, затем
   `db.commit()`, затем ответ.
4. Запись «не раньше сохранённого»:
   `written = upsert(db, CatalogStock, rows,
   where=lambda excluded: CatalogStock.updated_at <= excluded.updated_at)`
   — запись со строго более ранним updated_at не меняет строку и не входит в written;
   `skipped = len(rows) - written` (rows уже без повторов: `dedupe_last`). Остаток может прийти раньше
   карточки — сохраняется. store_id != `common.own_store_id()` — сохранить, считать в other_store.
5. Журнал: параметр `journal: Journal` (journal.py); stream и full выставляются сами;
   `return ok_response(journal, stock=…, skipped=…, other_store=…)` -> 200 {"ok": true, "counts": {...}}.
6. Ошибка порции: `raise ExchangeError(400, INVALID_FORMAT, "текст", details)` (errors.py).
7. Тесты: tests/exchange/conftest.py — `exchange_client.post_json("/stock", body)`, `db_fetch`,
   `journal_rows`.
"""

from fastapi import APIRouter

from app.exchange.onec.errors import NOT_IMPLEMENTED, ExchangeError

router = APIRouter()


@router.post("/stock", summary="Доступные остатки (заглушка)")
def receive_stock() -> None:
    raise ExchangeError(501, NOT_IMPLEMENTED, "Поток stock ещё не реализован")
