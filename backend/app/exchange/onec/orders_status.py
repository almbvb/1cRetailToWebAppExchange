"""ЗАГЛУШКА С1-Т1. Статусы заказов POST /exchange/1c/orders/status (api_spec.md 3.5) — реализует Т5.

Инструкция исполнителю Т5 (файл переписывается целиком; docs/c1_exchange.md — «Общие правила приёма»):

1. Маршрут: `router = APIRouter()` и `@router.post("/orders/status")`; префикс /exchange/1c и вход
   (Basic/Bearer) уже даёт router.py — сами не проверяйте. Обработчик — обычная `def` (синхронная БД).
2. Тело: модели порции наследуйте от `common.ExchangeModel`, типы `common.Guid`, `Money`, `Quantity`,
   `Timestamp`; параметр `body: Annotated[StatusIn, Depends(json_body(StatusIn))]` — предел 20 МБ, ошибки ->
   400 INVALID_FORMAT с details вида `orders[0].items[2].price`. Только то, что задаёт контракт (К-5).
3. БД: `db: Annotated[Session, Depends(get_db)]` (app.db). Порция — одна транзакция: все изменения, затем
   `db.commit()`, затем ответ.
4. Запись: заказ — `upsert(db, Order, rows,
   where=lambda excluded: Order.onec_changed_at <= excluded.onec_changed_at)`
   (более ранний changed_at игнорируется, skipped = len(rows) - результат); заказ, которого сайт не
   создавал, сохраняется; поле `number` (номер сайта) не трогать — передайте `update=[...]` без него.
   Состав order_onec_items принятых заказов заменяется целиком (delete + insert). Повторы order_id в
   порции — `dedupe_last`.
5. Журнал: параметр `journal: Journal` (journal.py); stream ("orders_status") выставляется сам, full у
   статусов нет; `return ok_response(journal, orders=…, skipped=…)` -> 200 {"ok": true, "counts": {...}}.
6. Ошибка порции: `raise ExchangeError(400, INVALID_FORMAT, "текст", details)` (errors.py).
7. Тесты: tests/exchange/conftest.py — `exchange_client.post_json("/orders/status", body)`, `db_fetch`,
   `journal_rows`.
"""

from fastapi import APIRouter

from app.exchange.onec.errors import NOT_IMPLEMENTED, ExchangeError

router = APIRouter()


@router.post("/orders/status", summary="Статусы и состав заказов (заглушка)")
def receive_orders_status() -> None:
    raise ExchangeError(501, NOT_IMPLEMENTED, "Поток orders/status ещё не реализован")
