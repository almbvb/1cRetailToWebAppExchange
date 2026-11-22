"""Каталог, принятый из 1С (api_spec.md, разд. 3.1–3.4; docs/c1_exchange.md, «Модель данных»).

Внешних ключей между таблицами нет: потоки 1С независимы, остаток, цена или картинка могут прийти
раньше карточки товара. Строки — text без пределов длины (К-5). received_at — момент последнего приёма записи.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _received_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogGroup(Base):
    """Группа товаров (3.1 groups)."""

    __tablename__ = "catalog_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
    deleted: Mapped[bool] = mapped_column(Boolean, server_default=false())
    received_at: Mapped[datetime] = _received_at()


class CatalogUnit(Base):
    """Единица измерения (3.1 units)."""

    __tablename__ = "catalog_units"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = _received_at()


class CatalogProduct(Base):
    """Товар (3.1 products). deleted: пометка удаления в 1С или позиция не товар — витрина скрывает."""

    __tablename__ = "catalog_products"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(Text)
    article: Mapped[str | None] = mapped_column(Text)
    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    weighted: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str | None] = mapped_column(Text)
    deleted: Mapped[bool] = mapped_column(Boolean, server_default=false(), index=True)
    received_at: Mapped[datetime] = _received_at()


class CatalogPrice(Base):
    """Розничная цена товара в магазине (3.2). Цена 0 — товар не продаётся."""

    __tablename__ = "catalog_prices"

    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    received_at: Mapped[datetime] = _received_at()


class CatalogStock(Base):
    """Доступный остаток (3.3). updated_at — момент расчёта в 1С; более ранняя запись не заменяет позднюю."""

    __tablename__ = "catalog_stock"

    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, index=True)
    available: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = _received_at()


class CatalogImage(Base):
    """Основная картинка товара (3.4); файлы — в MEDIA_DIR/products/<product_id>/."""

    __tablename__ = "catalog_images"

    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    original_path: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = _received_at()
