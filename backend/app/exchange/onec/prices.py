"""Поток цен POST /exchange/1c/prices (api_spec.md 3.2; docs/c1_exchange.md — «Общие правила приёма»).

Порция: `{full, prices: [{store_id, product_id, price}]}`; все три поля записи обязательны.
Запись — UPSERT по (store_id, product_id), повтор ключа в порции — остаётся последняя; вся порция —
одна транзакция. `full: true` ничего не удаляет. Цена может прийти раньше карточки товара — сохраняется.
Цена 0 сохраняется как есть (товар не продаётся — решает витрина). Своих пределов нет (К-5): цена пишется
как пришла (Decimal, столбец numeric без разрядности, без округления — округляет витрина); проверяется
только, что это конечное число в пределах типа numeric PostgreSQL (common.Money; иначе — 400 с полем).
`store_id` не равный ONEC_STORE_ID сохраняется и считается в `counts.other_store`.

Ответ: `counts` — prices (записано строк после удаления повторов ключа), other_store (из них чужой магазин).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.exchange.onec.common import (
    ExchangeModel,
    Guid,
    Money,
    dedupe_last,
    json_body,
    ok_response,
    own_store_id,
    upsert,
)
from app.exchange.onec.journal import Journal
from app.models import CatalogPrice

router = APIRouter()


class PriceIn(ExchangeModel):
    store_id: Guid
    product_id: Guid
    price: Money


class PricesIn(ExchangeModel):
    full: bool = False
    prices: list[PriceIn] = []


@router.post("/prices", summary="Цены")
def receive_prices(
    body: Annotated[PricesIn, Depends(json_body(PricesIn))],
    db: Annotated[Session, Depends(get_db)],
    journal: Journal,
) -> dict[str, Any]:
    items = dedupe_last(body.prices, key=lambda item: (item.store_id, item.product_id))
    rows = [{"store_id": i.store_id, "product_id": i.product_id, "price": i.price} for i in items]
    written = upsert(db, CatalogPrice, rows)
    db.commit()  # ответ 200 — только после фиксации всей порции

    own = own_store_id()
    other_store = sum(item.store_id != own for item in items)
    return ok_response(journal, prices=written, other_store=other_store)
