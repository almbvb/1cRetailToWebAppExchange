"""Представления админпанели: журнал обмена и данные, принятые из 1С. Все — только для чтения.

Связей (FK) между таблицами нет, поэтому группы, единицы и товары показываются GUID-ами.
Числовые столбцы выводятся как есть: точные типы (numeric) не используются.
"""

import json
from datetime import datetime
from functools import cache
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from sqladmin import ModelView
from sqladmin.filters import AllUniqueStringValuesFilter, BooleanFilter
from sqladmin.formatters import BASE_FORMATTERS
from sqlalchemy import Select, select

from app.config import get_settings
from app.models import (
    CatalogGroup,
    CatalogImage,
    CatalogPrice,
    CatalogProduct,
    CatalogStock,
    CatalogUnit,
    ExchangeBatch,
    Order,
    OrderOnecItem,
)

ALL = ("__all", "Все")


@cache
def _local_zone() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def _format_datetime(value: datetime) -> str:
    """Время в часовом поясе магазина (TIMEZONE), с точностью до секунды."""
    if value.tzinfo is not None:
        value = value.astimezone(_local_zone())
    return value.strftime("%d.%m.%Y %H:%M:%S")


def _format_counts(model: Any, attribute: str) -> str:
    counts = getattr(model, attribute)
    if not counts:
        return ""
    return json.dumps(counts, ensure_ascii=False, sort_keys=True)


class YesNoFilter(BooleanFilter):
    """Фильтр «да/нет» с русскими подписями."""

    async def lookups(self, request, model, run_query) -> list[tuple[str, str]]:
        return [ALL, ("true", "Да"), ("false", "Нет")]


class DistinctValuesFilter(AllUniqueStringValuesFilter):
    """Выбор из встречающихся значений столбца; для целых столбцов значение приводится к int."""

    def __init__(self, column: Any, title: str, *, integer: bool = False) -> None:
        super().__init__(column, title=title)
        self.integer = integer

    async def lookups(self, request, model, run_query) -> list[tuple[str, str]]:
        values = await run_query(select(self.column).distinct().order_by(self.column))
        return [ALL] + [(str(value[0]), str(value[0])) for value in values if value[0] is not None]

    async def get_filtered_query(self, query: Select, value: Any, model: Any) -> Select:
        if value in ("", "__all") or value is None:
            return query
        if self.integer:
            try:
                value = int(value)
            except ValueError:
                return query
        return query.filter(self.column == value)


class ReadOnlyView(ModelView):
    """Общие настройки: только просмотр (и выгрузка CSV), 50 строк на странице."""

    can_create = False
    can_edit = False
    can_delete = False
    can_import = False
    can_view_details = True
    can_export = True
    export_types: ClassVar[list[str]] = ["csv"]
    page_size = 50
    page_size_options: ClassVar[list[int]] = [50, 100, 200]
    column_type_formatters: ClassVar[dict[type, Any]] = {**BASE_FORMATTERS, datetime: _format_datetime}
    column_type_formatters_detail: ClassVar[dict[type, Any]] = column_type_formatters

    def get_export_name(self, export_type: str) -> str:
        # Имя файла — по таблице: русское название SQLAdmin вырезал бы из заголовка целиком.
        return f"{self.model.__tablename__}_{datetime.now():%Y-%m-%d_%H-%M-%S}.{export_type}"


class ExchangeBatchAdmin(ReadOnlyView, model=ExchangeBatch):
    name = "Запрос обмена"
    name_plural = "Журнал обмена"
    icon = "fa-solid fa-right-left"
    column_list: ClassVar = [
        ExchangeBatch.received_at,
        ExchangeBatch.method,
        ExchangeBatch.path,
        ExchangeBatch.stream,
        ExchangeBatch.status_code,
        ExchangeBatch.auth,
        ExchangeBatch.full,
        ExchangeBatch.counts,
        ExchangeBatch.error_code,
        ExchangeBatch.error_message,
        ExchangeBatch.body_bytes,
        ExchangeBatch.duration_ms,
    ]
    column_labels: ClassVar = {
        ExchangeBatch.id: "№",
        ExchangeBatch.received_at: "Время",
        ExchangeBatch.method: "Метод",
        ExchangeBatch.path: "Путь",
        ExchangeBatch.stream: "Поток",
        ExchangeBatch.status_code: "Код",
        ExchangeBatch.auth: "Вход",
        ExchangeBatch.full: "Full",
        ExchangeBatch.counts: "Счётчики",
        ExchangeBatch.error_code: "Код ошибки",
        ExchangeBatch.error_message: "Ошибка",
        ExchangeBatch.body_bytes: "Байты",
        ExchangeBatch.duration_ms: "Мс",
    }
    column_formatters: ClassVar = {ExchangeBatch.counts: _format_counts}
    column_formatters_detail: ClassVar = {ExchangeBatch.counts: _format_counts}
    column_sortable_list: ClassVar = [
        ExchangeBatch.received_at,
        ExchangeBatch.status_code,
        ExchangeBatch.body_bytes,
        ExchangeBatch.duration_ms,
    ]
    column_default_sort: ClassVar = [(ExchangeBatch.received_at, True), (ExchangeBatch.id, True)]
    column_filters: ClassVar = [
        DistinctValuesFilter(ExchangeBatch.stream, "Поток"),
        DistinctValuesFilter(ExchangeBatch.status_code, "Код ответа", integer=True),
    ]


class CatalogGroupAdmin(ReadOnlyView, model=CatalogGroup):
    name = "Группа"
    name_plural = "Группы"
    icon = "fa-solid fa-folder-tree"
    category = "Каталог"
    column_list: ClassVar = [
        CatalogGroup.name,
        CatalogGroup.id,
        CatalogGroup.parent_id,
        CatalogGroup.sort,
        CatalogGroup.deleted,
        CatalogGroup.received_at,
    ]
    column_labels: ClassVar = {
        CatalogGroup.id: "GUID",
        CatalogGroup.parent_id: "Родитель (GUID)",
        CatalogGroup.name: "Название",
        CatalogGroup.sort: "Порядок",
        CatalogGroup.deleted: "Удалена",
        CatalogGroup.received_at: "Получена",
    }
    column_searchable_list: ClassVar = [CatalogGroup.name]
    column_sortable_list: ClassVar = [CatalogGroup.name, CatalogGroup.sort, CatalogGroup.received_at]
    column_default_sort: ClassVar = [(CatalogGroup.sort, False), (CatalogGroup.name, False)]
    column_filters: ClassVar = [YesNoFilter(CatalogGroup.deleted, title="Удалена")]


class CatalogUnitAdmin(ReadOnlyView, model=CatalogUnit):
    name = "Единица"
    name_plural = "Единицы"
    icon = "fa-solid fa-ruler"
    category = "Каталог"
    column_list: ClassVar = [CatalogUnit.name, CatalogUnit.code, CatalogUnit.id, CatalogUnit.received_at]
    column_labels: ClassVar = {
        CatalogUnit.id: "GUID",
        CatalogUnit.name: "Название",
        CatalogUnit.code: "Код",
        CatalogUnit.received_at: "Получена",
    }
    column_sortable_list: ClassVar = [CatalogUnit.name, CatalogUnit.code]
    column_default_sort: ClassVar = [(CatalogUnit.name, False)]


class CatalogProductAdmin(ReadOnlyView, model=CatalogProduct):
    name = "Товар"
    name_plural = "Товары"
    icon = "fa-solid fa-box"
    category = "Каталог"
    column_list: ClassVar = [
        CatalogProduct.name,
        CatalogProduct.article,
        CatalogProduct.id,
        CatalogProduct.group_id,
        CatalogProduct.unit_id,
        CatalogProduct.weighted,
        CatalogProduct.deleted,
        CatalogProduct.received_at,
    ]
    column_labels: ClassVar = {
        CatalogProduct.id: "GUID",
        CatalogProduct.group_id: "Группа (GUID)",
        CatalogProduct.name: "Название",
        CatalogProduct.article: "Артикул",
        CatalogProduct.unit_id: "Единица (GUID)",
        CatalogProduct.weighted: "Весовой",
        CatalogProduct.description: "Описание",
        CatalogProduct.deleted: "Удалён",
        CatalogProduct.received_at: "Получен",
    }
    column_searchable_list: ClassVar = [CatalogProduct.name, CatalogProduct.article]
    column_sortable_list: ClassVar = [CatalogProduct.name, CatalogProduct.article, CatalogProduct.received_at]
    column_default_sort: ClassVar = [(CatalogProduct.name, False)]
    column_filters: ClassVar = [
        YesNoFilter(CatalogProduct.deleted, title="Удалён"),
        YesNoFilter(CatalogProduct.weighted, title="Весовой"),
    ]


class CatalogPriceAdmin(ReadOnlyView, model=CatalogPrice):
    name = "Цена"
    name_plural = "Цены"
    icon = "fa-solid fa-tag"
    category = "Каталог"
    column_list: ClassVar = [
        CatalogPrice.product_id,
        CatalogPrice.store_id,
        CatalogPrice.price,
        CatalogPrice.received_at,
    ]
    column_labels: ClassVar = {
        CatalogPrice.product_id: "Товар (GUID)",
        CatalogPrice.store_id: "Магазин (GUID)",
        CatalogPrice.price: "Цена",
        CatalogPrice.received_at: "Получена",
    }
    column_sortable_list: ClassVar = [CatalogPrice.price, CatalogPrice.received_at]
    column_default_sort: ClassVar = [(CatalogPrice.received_at, True)]


class CatalogStockAdmin(ReadOnlyView, model=CatalogStock):
    name = "Остаток"
    name_plural = "Остатки"
    icon = "fa-solid fa-warehouse"
    category = "Каталог"
    column_list: ClassVar = [
        CatalogStock.product_id,
        CatalogStock.store_id,
        CatalogStock.available,
        CatalogStock.updated_at,
        CatalogStock.received_at,
    ]
    column_labels: ClassVar = {
        CatalogStock.product_id: "Товар (GUID)",
        CatalogStock.store_id: "Магазин (GUID)",
        CatalogStock.available: "Доступно",
        CatalogStock.updated_at: "Расчёт в 1С",
        CatalogStock.received_at: "Получен",
    }
    column_sortable_list: ClassVar = [
        CatalogStock.available,
        CatalogStock.updated_at,
        CatalogStock.received_at,
    ]
    column_default_sort: ClassVar = [(CatalogStock.updated_at, True)]


class CatalogImageAdmin(ReadOnlyView, model=CatalogImage):
    name = "Картинка"
    name_plural = "Картинки"
    icon = "fa-solid fa-image"
    category = "Каталог"
    column_list: ClassVar = [
        CatalogImage.product_id,
        CatalogImage.width,
        CatalogImage.height,
        CatalogImage.size_bytes,
        CatalogImage.content_type,
        CatalogImage.sha256,
        CatalogImage.received_at,
    ]
    column_labels: ClassVar = {
        CatalogImage.product_id: "Товар (GUID)",
        CatalogImage.width: "Ширина",
        CatalogImage.height: "Высота",
        CatalogImage.size_bytes: "Байты",
        CatalogImage.content_type: "Тип",
        CatalogImage.sha256: "SHA-256",
        CatalogImage.original_path: "Файл",
        CatalogImage.received_at: "Получена",
    }
    column_sortable_list: ClassVar = [CatalogImage.size_bytes, CatalogImage.received_at]
    column_default_sort: ClassVar = [(CatalogImage.received_at, True)]


class OrderAdmin(ReadOnlyView, model=Order):
    name = "Заказ"
    name_plural = "Заказы"
    icon = "fa-solid fa-receipt"
    category = "Заказы"
    column_list: ClassVar = [
        Order.onec_number,
        Order.number,
        Order.status,
        Order.total,
        Order.onec_changed_at,
        Order.order_id,
        Order.received_at,
    ]
    column_labels: ClassVar = {
        Order.order_id: "ID заказа",
        Order.number: "Номер сайта",
        Order.onec_number: "Номер 1С",
        Order.status: "Статус",
        Order.onec_created_at: "Создан в 1С",
        Order.onec_changed_at: "Изменён в 1С",
        Order.total: "Сумма",
        Order.received_at: "Получен",
    }
    column_searchable_list: ClassVar = [Order.onec_number, Order.number, Order.order_id]
    column_sortable_list: ClassVar = [Order.onec_number, Order.status, Order.total, Order.onec_changed_at]
    column_default_sort: ClassVar = [(Order.onec_changed_at, True)]
    column_filters: ClassVar = [DistinctValuesFilter(Order.status, "Статус")]


class OrderOnecItemAdmin(ReadOnlyView, model=OrderOnecItem):
    name = "Строка заказа"
    name_plural = "Состав заказов"
    icon = "fa-solid fa-list"
    category = "Заказы"
    column_list: ClassVar = [
        OrderOnecItem.order_id,
        OrderOnecItem.line_no,
        OrderOnecItem.product_id,
        OrderOnecItem.quantity,
        OrderOnecItem.price,
        OrderOnecItem.amount,
        OrderOnecItem.cancelled,
    ]
    column_labels: ClassVar = {
        OrderOnecItem.order_id: "ID заказа",
        OrderOnecItem.line_no: "Строка",
        OrderOnecItem.product_id: "Товар (GUID)",
        OrderOnecItem.quantity: "Количество",
        OrderOnecItem.price: "Цена",
        OrderOnecItem.amount: "Сумма",
        OrderOnecItem.cancelled: "Отменена",
    }
    column_searchable_list: ClassVar = [OrderOnecItem.order_id]
    column_sortable_list: ClassVar = [OrderOnecItem.order_id, OrderOnecItem.line_no]
    column_default_sort: ClassVar = [(OrderOnecItem.order_id, False), (OrderOnecItem.line_no, False)]
    column_filters: ClassVar = [YesNoFilter(OrderOnecItem.cancelled, title="Отменена")]


# Порядок меню; первым — журнал обмена (на него ведёт главная страница /admin/).
VIEWS: list[type[ModelView]] = [
    ExchangeBatchAdmin,
    CatalogGroupAdmin,
    CatalogUnitAdmin,
    CatalogProductAdmin,
    CatalogPriceAdmin,
    CatalogStockAdmin,
    CatalogImageAdmin,
    OrderAdmin,
    OrderOnecItemAdmin,
]
