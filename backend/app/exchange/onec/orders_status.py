"""Статусы и состав заказов POST /exchange/1c/orders/status (api_spec.md 3.5; docs/c1_exchange.md).

- Заказ по order_id заменяется целиком: шапка (orders) и состав (order_onec_items, delete + insert).
- Заказ с changed_at строго раньше сохранённого игнорируется целиком (шапка и состав), считается в skipped;
  равный или более поздний — принимается (повтор той же порции идемпотентен).
- Поле orders.number (номер сайта, С4) не перезаписывается. Заказ, которого сайт не создавал, сохраняется.
- Неизвестный status не останавливает поток (К-5): сохраняется как есть, считается в unknown_status,
  в лог пишется предупреждение.
- Порция — одна транзакция; ответ 200 только после фиксации. full у статусов нет.

Счётчики: orders (принято заказов), items (записано строк состава), skipped, unknown_status.
"""

import itertools
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import delete, func, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import get_db
from app.exchange.onec.common import (
    MAX_PARAMS_PER_STATEMENT,
    ExchangeModel,
    Guid,
    Money,
    Quantity,
    Timestamp,
    dedupe_last,
    json_body,
    ok_response,
)
from app.exchange.onec.journal import Journal
from app.models import Order, OrderOnecItem

logger = logging.getLogger(__name__)

router = APIRouter()

# Статусы по api_spec.md 2.3; прочие сохраняются как есть и считаются в unknown_status.
KNOWN_STATUSES = frozenset({"new", "confirmed", "completed", "cancelled"})

# Сколько заказов с неизвестным статусом перечислять в одном предупреждении лога.
MAX_LOGGED_UNKNOWN = 20

# Колонки шапки, которые заменяет статус (number — номер сайта — не трогаем).
_HEADER_UPDATE = ("onec_number", "status", "onec_created_at", "onec_changed_at", "total")


# --- Модели порции (К-5: только обязательные поля, типы, формат GUID; order_id — до 36 символов, 2.2) ---


class OrderItemIn(ExchangeModel):
    product_id: Guid
    quantity: Quantity
    price: Money
    amount: Money
    cancelled: bool


class OrderStatusIn(ExchangeModel):
    order_id: Annotated[str, Field(max_length=36)]
    number: str
    status: str
    created_at: Timestamp
    changed_at: Timestamp
    items: list[OrderItemIn]
    total: Money


class StatusIn(ExchangeModel):
    orders: list[OrderStatusIn] = Field(default_factory=list)


# --- Запись ---


def _upsert_headers(db: Session, orders: list[OrderStatusIn]) -> set[str]:
    """UPSERT шапок «не раньше сохранённого»; возвращает order_id, которые вставлены или обновлены.

    Проверка changed_at — в самом ON CONFLICT ... WHERE, а принятые заказы берутся из RETURNING: это
    атомарно (конфликтующая строка блокируется до конца транзакции), и состав заменяется ровно у тех
    заказов, чья шапка принята, даже при параллельной порции с тем же заказом.
    """
    rows = [
        {
            "order_id": order.order_id,
            "onec_number": order.number,
            "status": order.status,
            "onec_created_at": order.created_at,
            "onec_changed_at": order.changed_at,
            "total": order.total,
        }
        for order in orders
    ]
    accepted: set[str] = set()
    size = max(1, MAX_PARAMS_PER_STATEMENT // len(rows[0]))
    for chunk in itertools.batched(rows, size, strict=False):
        statement = pg_insert(Order).values(list(chunk))
        set_: dict[str, Any] = {name: statement.excluded[name] for name in _HEADER_UPDATE}
        set_["received_at"] = func.now()
        statement = statement.on_conflict_do_update(
            index_elements=[Order.order_id],
            set_=set_,
            where=Order.onec_changed_at <= statement.excluded.onec_changed_at,
        ).returning(Order.order_id)
        accepted.update(db.scalars(statement))
    return accepted


def _replace_items(db: Session, orders: list[OrderStatusIn]) -> int:
    """Состав принятых заказов заменяется целиком: delete + insert; line_no — номер строки с 1."""
    order_ids = [order.order_id for order in orders]
    for chunk in itertools.batched(order_ids, MAX_PARAMS_PER_STATEMENT, strict=False):
        db.execute(delete(OrderOnecItem).where(OrderOnecItem.order_id.in_(chunk)))
    rows = [
        {
            "order_id": order.order_id,
            "line_no": line_no,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "price": item.price,
            "amount": item.amount,
            "cancelled": item.cancelled,
        }
        for order in orders
        for line_no, item in enumerate(order.items, start=1)
    ]
    if rows:
        db.execute(insert(OrderOnecItem), rows)
    return len(rows)


def _warn_unknown_statuses(orders: list[OrderStatusIn]) -> None:
    sample = ", ".join(f"{order.order_id}={order.status!r}" for order in orders[:MAX_LOGGED_UNKNOWN])
    more = f" и ещё {len(orders) - MAX_LOGGED_UNKNOWN}" if len(orders) > MAX_LOGGED_UNKNOWN else ""
    logger.warning("orders/status: неизвестный статус заказа (сохранён как есть): %s%s", sample, more)


@router.post("/orders/status", summary="Статусы и состав заказов")
def receive_orders_status(
    body: Annotated[StatusIn, Depends(json_body(StatusIn))],
    db: Annotated[Session, Depends(get_db)],
    journal: Journal,
) -> dict[str, Any]:
    # Повторы order_id в порции — остаётся последний; сортировка — единый порядок блокировок строк.
    orders = sorted(dedupe_last(body.orders, key=lambda order: order.order_id), key=lambda o: o.order_id)

    accepted_orders: list[OrderStatusIn] = []
    items_written = 0
    if orders:
        accepted_ids = _upsert_headers(db, orders)
        accepted_orders = [order for order in orders if order.order_id in accepted_ids]
        items_written = _replace_items(db, accepted_orders)
    db.commit()

    unknown = [order for order in accepted_orders if order.status not in KNOWN_STATUSES]
    if unknown:
        _warn_unknown_statuses(unknown)
    return ok_response(
        journal,
        orders=len(accepted_orders),
        items=items_written,
        skipped=len(orders) - len(accepted_orders),
        unknown_status=len(unknown),
    )
