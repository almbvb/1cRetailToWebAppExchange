"""Поток остатков POST /exchange/1c/stock (api_spec.md 3.3; docs/c1_exchange.md — «Общие правила приёма»).

Тело: {"full": false, "stock": [{"store_id", "product_id", "available", "updated_at"}]}.
- `available` — абсолютное значение доступного остатка (не разница), весовые — дробные;
  0 сохраняется как 0 (не удаление). Значения не проверяются сверх типа (К-5): пишутся как пришли
  (столбец numeric без разрядности, без округления); только конечное число в пределах numeric PostgreSQL.
- `updated_at` — ISO 8601 со смещением (common.Timestamp); без смещения — 400 INVALID_FORMAT.
- Запись по (store_id, product_id) «не раньше сохранённого»: строго более ранний updated_at не меняет
  строку и считается в counts.skipped; равный — заменяет (повтор порции идемпотентен).
- Остаток может прийти раньше карточки товара — сохраняется (внешних ключей нет).
- store_id != ONEC_STORE_ID — сохраняется, считается в counts.other_store (витрина показывает свой магазин).
- `full: true` ничего не удаляет и не обнуляет; только отмечается в журнале (это делает common.json_body).
Порция — одна транзакция; ответ 200 только после commit.

Счётчики ответа и журнала:
- stock — записей вставлено или заменено;
- skipped — записей проигнорировано как более ранние (после удаления повторов ключа в порции);
- other_store — записей порции (после удаления повторов) с чужим store_id, записанных или пропущенных.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.exchange.onec.common import (
    ExchangeModel,
    Guid,
    Quantity,
    Timestamp,
    dedupe_last,
    json_body,
    ok_response,
    own_store_id,
    upsert,
)
from app.exchange.onec.journal import Journal
from app.models import CatalogStock

router = APIRouter()


class StockItemIn(ExchangeModel):
    """Остаток товара в магазине (3.3 stock[])."""

    store_id: Guid
    product_id: Guid
    available: Quantity
    updated_at: Timestamp


class StockIn(ExchangeModel):
    """Порция остатков (3.3). Список может отсутствовать — пустая порция."""

    full: bool = False
    stock: list[StockItemIn] = Field(default_factory=list)


def _not_earlier(excluded: Any) -> Any:
    """Условие обновления: сохранённый updated_at не позже пришедшего (равный — заменяет)."""
    return CatalogStock.updated_at <= excluded.updated_at


@router.post("/stock", summary="Доступные остатки")
def receive_stock(
    body: Annotated[StockIn, Depends(json_body(StockIn))],
    db: Annotated[Session, Depends(get_db)],
    journal: Journal,
) -> dict[str, Any]:
    # Повторы ключа в порции — остаётся последняя запись.
    rows = dedupe_last(
        (
            {
                "store_id": item.store_id,
                "product_id": item.product_id,
                "available": item.available,
                "updated_at": item.updated_at,
            }
            for item in body.stock
        ),
        key=lambda row: (row["store_id"], row["product_id"]),
    )
    own_store = own_store_id()
    other_store = sum(1 for row in rows if row["store_id"] != own_store)

    written = upsert(db, CatalogStock, rows, where=_not_earlier)
    db.commit()  # ответ 200 — только после фиксации
    return ok_response(journal, stock=written, skipped=len(rows) - written, other_store=other_store)
