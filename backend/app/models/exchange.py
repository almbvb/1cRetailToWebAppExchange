"""Журнал обмена с 1С: строка на каждый запрос к /exchange/1c (app/exchange/onec/journal.py).

Тело порции не хранится; пароль и токен не пишутся (в auth — только схема и логин).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ExchangeBatch(Base):
    __tablename__ = "exchange_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Момент поступления запроса.
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    method: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    # catalog | prices | stock | images | orders_status; null — путь вне известных потоков.
    stream: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    # "none", "Basic user=<логин>", "Bearer" — без пароля и токена.
    auth: Mapped[str] = mapped_column(Text)
    full: Mapped[bool | None] = mapped_column(Boolean)
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    body_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_ms: Mapped[int] = mapped_column(Integer)
