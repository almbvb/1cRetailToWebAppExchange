"""Заказы и их состав по данным 1С (api_spec.md, разд. 3.5).

Заказ создаётся уже в С1: статус может прийти по заказу, которого сайт не создавал, — он сохраняется.
Поля покупателя и состав, который видел покупатель, добавит С4. Внешних ключей нет.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Order(Base):
    """Заказ приложения. order_id — UUID приложения (строка до 36 символов, api_spec.md 2.2)."""

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Номер сайта (D-000001); заполняется с С4.
    number: Mapped[str | None] = mapped_column(Text)
    onec_number: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    onec_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # changed_at из 1С: статус с более ранним changed_at не заменяет более поздний.
    onec_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderOnecItem(Base):
    """Строка актуального состава заказа в 1С; заменяется целиком при каждом принятом статусе."""

    __tablename__ = "order_onec_items"

    order_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    cancelled: Mapped[bool] = mapped_column(Boolean)
