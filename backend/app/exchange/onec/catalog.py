"""Поток каталога POST /exchange/1c/catalog (api_spec.md 3.1; docs/c1_exchange.md — «Общие правила приёма»).

Порция: `{full, groups[], units[], products[]}`; отсутствующий список — пустой, `full` по умолчанию false.
Запись — UPSERT по `id` (запись заменяется целиком), вся порция в одной транзакции. `full: true` ничего
не удаляет (только отмечается в журнале), `deleted: true` сохраняется флагом — витрина скрывает запись.

Проверяется только то, что задаёт контракт (К-5): обязательные поля, типы, формат GUID.
- Обязательные: `id` у всех записей и `products[].weighted`; ключи `name` (и `units[].code`) должны
  быть в записи, но `null` допускается.
- `products[].unit_id` — GUID или `null`, может отсутствовать (-> `null`): у позиции-услуги в 1С единицы
  нет (приходит с `deleted: true`); неверный GUID — 400.
- Строки, которые в БД NOT NULL (`name` групп, единиц и товаров, `units[].code`): `null` -> `''`.
- `article`, `description` — `null` остаётся `null`, пустая строка — пустой строкой; поле может отсутствовать.
- `parent_id`, `group_id` — GUID или `null`, могут отсутствовать; `deleted` отсутствует -> `false`.
- `groups[].sort` (с 0.9, «Отбор групп»): целое, необязательное — отсутствует или `null` -> `0`; значение
  вне integer PostgreSQL -> 400 (иначе 500). Запись, вышедшая из отбора, приходит с `deleted: true` —
  обычный флаг.
- Символ U+0000 из строк убирается: PostgreSQL не хранит его в `text` (иначе 500 и бесконечный повтор).

Ответ: `counts` — groups, units, products (записано строк после удаления повторов `id` в порции)
и deleted (сколько групп и товаров порции пришли с `deleted: true`).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import AfterValidator
from sqlalchemy.orm import Session

from app.db import get_db
from app.exchange.onec.common import ExchangeModel, Guid, dedupe_last, json_body, ok_response, upsert
from app.exchange.onec.journal import Journal
from app.models import CatalogGroup, CatalogProduct, CatalogUnit

router = APIRouter()

# Столбец catalog_groups.sort — integer (int4).
INT4_MIN, INT4_MAX = -(2**31), 2**31 - 1


def fits_int4(value: int | None) -> int | None:
    if value is not None and not INT4_MIN <= value <= INT4_MAX:
        raise ValueError("Значение не помещается в integer")
    return value


class GroupIn(ExchangeModel):
    id: Guid
    parent_id: Guid | None = None
    name: str | None
    sort: Annotated[int | None, AfterValidator(fits_int4)] = None
    deleted: bool = False


class UnitIn(ExchangeModel):
    id: Guid
    name: str | None
    code: str | None


class ProductIn(ExchangeModel):
    id: Guid
    group_id: Guid | None = None
    name: str | None
    article: str | None = None
    unit_id: Guid | None = None
    weighted: bool
    description: str | None = None
    deleted: bool = False


class CatalogIn(ExchangeModel):
    full: bool = False
    groups: list[GroupIn] = []
    units: list[UnitIn] = []
    products: list[ProductIn] = []


def clean_text(value: str | None) -> str | None:
    """Строка для text-колонки: без U+0000 (PostgreSQL его не принимает); None остаётся None."""
    if value is None or "\x00" not in value:
        return value
    return value.replace("\x00", "")


def required_text(value: str | None) -> str:
    """Строка для NOT NULL-колонки: null -> ''."""
    return clean_text(value) or ""


@router.post("/catalog", summary="Каталог: группы, единицы, товары")
def receive_catalog(
    body: Annotated[CatalogIn, Depends(json_body(CatalogIn))],
    db: Annotated[Session, Depends(get_db)],
    journal: Journal,
) -> dict[str, Any]:
    groups = dedupe_last(body.groups, key=lambda item: item.id)
    units = dedupe_last(body.units, key=lambda item: item.id)
    products = dedupe_last(body.products, key=lambda item: item.id)

    group_rows = [
        {
            "id": g.id,
            "parent_id": g.parent_id,
            "name": required_text(g.name),
            "sort": g.sort or 0,
            "deleted": g.deleted,
        }
        for g in groups
    ]
    unit_rows = [{"id": u.id, "name": required_text(u.name), "code": required_text(u.code)} for u in units]
    product_rows = [
        {
            "id": p.id,
            "group_id": p.group_id,
            "name": required_text(p.name),
            "article": clean_text(p.article),
            "unit_id": p.unit_id,
            "weighted": p.weighted,
            "description": clean_text(p.description),
            "deleted": p.deleted,
        }
        for p in products
    ]

    written_groups = upsert(db, CatalogGroup, group_rows)
    written_units = upsert(db, CatalogUnit, unit_rows)
    written_products = upsert(db, CatalogProduct, product_rows)
    db.commit()  # ответ 200 — только после фиксации всей порции

    deleted = sum(g.deleted for g in groups) + sum(p.deleted for p in products)
    return ok_response(
        journal,
        groups=written_groups,
        units=written_units,
        products=written_products,
        deleted=deleted,
    )
