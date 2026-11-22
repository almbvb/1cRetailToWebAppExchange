"""ЗАГЛУШКА С1-Т1. Поток цен POST /exchange/1c/prices (api_spec.md 3.2) — реализует Т2.

Инструкция исполнителю Т2 (файл переписывается целиком; docs/c1_exchange.md — «Общие правила приёма»):

1. Маршрут: `router = APIRouter()` и `@router.post("/prices")`; префикс /exchange/1c и вход (Basic/Bearer)
   уже даёт router.py — сами не проверяйте. Обработчик — обычная `def` (синхронная БД).
2. Тело: модели порции наследуйте от `common.ExchangeModel`, типы `common.Guid`, `Money`; параметр
   `body: Annotated[PricesIn, Depends(json_body(PricesIn))]` — предел 20 МБ, ошибки -> 400 INVALID_FORMAT
   с details вида `prices[3].product_id`. Проверяйте только то, что задаёт контракт (К-5).
3. БД: `db: Annotated[Session, Depends(get_db)]` (app.db). Порция — одна транзакция: upsert, затем
   `db.commit()`, затем ответ.
4. Запись: `upsert(db, CatalogPrice, rows)` из common (ключ store_id+product_id, повторы — последняя).
   Цена может прийти раньше карточки товара — сохраняется (внешних ключей нет).
   store_id != ONEC_STORE_ID (`common.own_store_id()`) — сохранить и посчитать в counts.other_store.
5. Журнал: параметр `journal: Journal` (journal.py); stream и full выставляются сами;
   `return ok_response(journal, prices=…, other_store=…)` -> 200 {"ok": true, "counts": {...}}.
6. Ошибка порции: `raise ExchangeError(400, INVALID_FORMAT, "текст", details)` (errors.py).
7. Тесты: tests/exchange/conftest.py — `exchange_client.post_json("/prices", body)`, `db_fetch`,
   `journal_rows`.
"""

from fastapi import APIRouter

from app.exchange.onec.errors import NOT_IMPLEMENTED, ExchangeError

router = APIRouter()


@router.post("/prices", summary="Цены (заглушка)")
def receive_prices() -> None:
    raise ExchangeError(501, NOT_IMPLEMENTED, "Поток prices ещё не реализован")
