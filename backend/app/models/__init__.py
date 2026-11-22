"""Модели SQLAlchemy; каждый модуль с моделями импортируется здесь, чтобы Alembic видел их в Base.metadata."""

from app.models.catalog import (
    CatalogGroup,
    CatalogImage,
    CatalogPrice,
    CatalogProduct,
    CatalogStock,
    CatalogUnit,
)
from app.models.exchange import ExchangeBatch
from app.models.orders import Order, OrderOnecItem

__all__ = [
    "CatalogGroup",
    "CatalogImage",
    "CatalogPrice",
    "CatalogProduct",
    "CatalogStock",
    "CatalogUnit",
    "ExchangeBatch",
    "Order",
    "OrderOnecItem",
]
