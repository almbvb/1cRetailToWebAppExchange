"""Общие средства обработчиков потоков 1С: тело запроса, разбор JSON, дедупликация, UPSERT, ответ 200.

Как писать обработчик потока — docstring любого из файлов catalog.py, prices.py, stock.py, images.py,
orders_status.py. Коротко:

    @router.post("/stock")
    def receive_stock(
        body: Annotated[StockIn, Depends(json_body(StockIn))],  # 20 МБ, JSON, pydantic -> 400/413
        db: Annotated[Session, Depends(get_db)],
        journal: Journal,
    ) -> dict:
        rows = dedupe_last([...], key=lambda r: (r["store_id"], r["product_id"]))
        newer = lambda excluded: CatalogStock.updated_at <= excluded.updated_at  # noqa: E731
        written = upsert(db, CatalogStock, rows, where=newer)
        db.commit()  # ответ 200 — только после фиксации
        return ok_response(journal, stock=written, skipped=len(rows) - written)
"""

import itertools
import json
import uuid
from collections.abc import Awaitable, Callable, Hashable, Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from fastapi import Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError
from sqlalchemy import ColumnElement, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.exchange.onec.errors import INVALID_FORMAT, PAYLOAD_TOO_LARGE, ExchangeError, validation_details
from app.exchange.onec.journal import ExchangeJournal, get_journal

# Предел тела JSON-порции (docs/c1_exchange.md). Читается при каждом запросе — тесты могут подменить.
JSON_MAX_BYTES = 20 * 1024 * 1024

# Лимит PostgreSQL — 65535 параметров на запрос; берём с запасом.
MAX_PARAMS_PER_STATEMENT = 30_000

# Типы полей для моделей порций (К-5: только тип и формат, без своих пределов).
Guid = uuid.UUID  # GUID 1С; в БД — uuid
Money = Decimal  # цена, сумма; в БД — numeric(12,2)
Quantity = Decimal  # количество, остаток; в БД — numeric(14,3)
Timestamp = AwareDatetime  # ISO 8601 с часовым поясом; в БД — timestamptz


class ExchangeModel(BaseModel):
    """База моделей порций: неизвестные поля игнорируются (api_spec.md, разд. 1)."""

    model_config = ConfigDict(extra="ignore")


# --- Тело запроса ---


async def read_body(
    request: Request,
    max_bytes: int,
    *,
    too_large_code: str = PAYLOAD_TOO_LARGE,
    status_code: int = 413,
) -> bytes:
    """Читает тело не больше max_bytes: заранее по Content-Length и при потоковом чтении.

    Больше предела -> ExchangeError(413, too_large_code). Для картинок: too_large_code="IMAGE_TOO_LARGE".
    """
    message = f"Тело запроса больше {max_bytes} байт"
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError:
            raise ExchangeError(400, INVALID_FORMAT, "Неверный заголовок Content-Length") from None
        if declared_bytes > max_bytes:
            raise ExchangeError(status_code, too_large_code, message)
    buffer = bytearray()
    async for chunk in request.stream():
        buffer += chunk
        if len(buffer) > max_bytes:
            raise ExchangeError(status_code, too_large_code, message)
    return bytes(buffer)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"Недопустимое значение {name}")


def parse_json[M: BaseModel](raw: bytes, model: type[M], journal: ExchangeJournal | None = None) -> M:
    """bytes -> модель. Неверный JSON или неверные поля -> ExchangeError(400 INVALID_FORMAT, details).

    Дробные числа разбираются в Decimal (без потерь для цен и количеств). Если в теле есть булево full,
    оно записывается в журнал даже при ошибке валидации.
    """
    try:
        # Контракт — UTF-8; BOM допускается.
        text = raw.decode("utf-8-sig")
        data = json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)
    except ValueError as exc:
        raise ExchangeError(
            400, INVALID_FORMAT, "Неверный JSON", [{"field": "body", "message": str(exc)}]
        ) from None
    if journal is not None and isinstance(data, dict) and isinstance(data.get("full"), bool):
        journal.full = data["full"]
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = validation_details(exc.errors(include_url=False))
        raise ExchangeError(400, INVALID_FORMAT, "Неверный формат порции", details) from None


def json_body[M: BaseModel](
    model: type[M], max_bytes: int | None = None
) -> Callable[[Request], Awaitable[M]]:
    """Зависимость FastAPI: тело запроса как модель `model` (предел JSON_MAX_BYTES, ошибки — 400/413).

    body: Annotated[CatalogIn, Depends(json_body(CatalogIn))]
    """

    async def dependency(request: Request) -> M:
        limit = JSON_MAX_BYTES if max_bytes is None else max_bytes
        raw = await read_body(request, limit)
        # Разбор большой порции — в пуле потоков, чтобы не держать цикл событий.
        return await run_in_threadpool(parse_json, raw, model, get_journal(request))

    return dependency


# --- Запись в БД ---


def dedupe_last[T, K: Hashable](items: Iterable[T], key: Callable[[T], K]) -> list[T]:
    """Убирает повторы ключа в порции: остаётся ПОСЛЕДНЯЯ запись (иначе ON CONFLICT падает на повторе)."""
    result: dict[K, T] = {}
    for item in items:
        result[key(item)] = item
    return list(result.values())


def upsert(
    session: Session,
    model: type,
    rows: Sequence[Mapping[str, Any]],
    *,
    key: Sequence[str] | None = None,
    update: Sequence[str] | None = None,
    where: Callable[[Any], ColumnElement[bool]] | None = None,
    batch_size: int | None = None,
) -> int:
    """INSERT ... ON CONFLICT (key) DO UPDATE пакетами; возвращает число вставленных и обновлённых строк.

    - rows — словари с одинаковым набором колонок (имена колонок таблицы);
    - key — колонки конфликта, по умолчанию первичный ключ; повторы ключа
      в rows убираются (остаётся последний);
    - update — какие колонки обновлять, по умолчанию все из rows, кроме key;
    - received_at, если он есть в таблице и не передан, при обновлении ставится
      в now() (при вставке — default);
    - where — условие обновления от excluded (новые значения), например «не раньше сохранённого»:
      where=lambda excluded: CatalogStock.updated_at <= excluded.updated_at
      Строки, не прошедшие условие, не меняются и не входят в результат: skipped = len(rows) - результат.
    Фиксацию (commit) делает обработчик потока.
    """
    table = model.__table__  # type: ignore[attr-defined]
    key_columns = list(key) if key is not None else [column.name for column in table.primary_key.columns]
    unique_rows = dedupe_last(rows, key=lambda row: tuple(row[name] for name in key_columns))
    if not unique_rows:
        return 0
    columns = list(unique_rows[0].keys())
    if any(set(row.keys()) != set(columns) for row in unique_rows):
        raise ValueError("upsert: у всех строк должен быть одинаковый набор колонок")
    if update is not None:
        update_columns = list(update)
    else:
        update_columns = [name for name in columns if name not in key_columns]
    touch_received_at = "received_at" in table.c and "received_at" not in columns
    size = batch_size or max(1, MAX_PARAMS_PER_STATEMENT // len(columns))

    affected = 0
    for chunk in itertools.batched(unique_rows, size, strict=False):
        statement = pg_insert(table).values([dict(row) for row in chunk])
        set_: dict[str, Any] = {name: statement.excluded[name] for name in update_columns}
        if touch_received_at:
            set_["received_at"] = func.now()
        if set_:
            statement = statement.on_conflict_do_update(
                index_elements=key_columns,
                set_=set_,
                where=where(statement.excluded) if where is not None else None,
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=key_columns)
        # rowcount для INSERT в SQLAlchemy 2 доступен только с preserve_rowcount.
        result = session.execute(statement.execution_options(preserve_rowcount=True))
        affected += result.rowcount  # type: ignore[attr-defined]
    return affected


# --- Ответ и настройки ---


def ok_response(journal: ExchangeJournal, **counts: int) -> dict[str, Any]:
    """Ответ 200 {"ok": true, "counts": {...}}; счётчики попадают и в журнал. Вызывать после commit."""
    journal.counts = dict(counts)
    return {"ok": True, "counts": dict(counts)}


def own_store_id() -> uuid.UUID | None:
    """ONEC_STORE_ID как UUID (None — не задан или не GUID). Чужой магазин -> counts.other_store."""
    value = get_settings().onec_store_id
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
