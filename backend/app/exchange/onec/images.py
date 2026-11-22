"""ЗАГЛУШКА С1-Т1. Картинки PUT и DELETE /exchange/1c/images/{product_id} (api_spec.md 3.4) — реализует Т4.

Инструкция исполнителю Т4 (файл переписывается целиком; docs/c1_exchange.md — «Картинки»):

1. Маршруты: `router = APIRouter()`, `@router.put("/images/{product_id}")` и
   `@router.delete("/images/{product_id}")`; префикс /exchange/1c и вход (Basic/Bearer) уже даёт router.py.
   `product_id: uuid.UUID` в сигнатуре — не GUID -> 400 INVALID_FORMAT (details: field "product_id") само.
2. Тело — не JSON: `raw = await read_body(request, get_settings().image_max_bytes,
   too_large_code=IMAGE_TOO_LARGE)` (common) — Content-Length до чтения и счёт при чтении, больше -> 413.
   Обработчик с await — `async def`; работу с Pillow, файлами и БД выносите в синхронную функцию и
   вызывайте через `await run_in_threadpool(...)` (starlette.concurrency), чтобы не держать цикл событий.
   Не JPEG/PNG -> `ExchangeError(415, UNSUPPORTED_IMAGE, ...)`, больше IMAGE_MAX_MEGAPIXELS -> 413.
3. БД: `db: Annotated[Session, Depends(get_db)]` (app.db); `upsert(db, CatalogImage, [row])` из common,
   затем `db.commit()`, затем ответ. Файлы — в `get_settings().media_dir` (в тестах — временная папка).
4. Журнал: параметр `journal: Journal` (journal.py); stream ("images") выставляется сам;
   `return ok_response(journal, image_bytes=len(raw))` / `ok_response(journal, image_deleted=1)`.
5. Ошибка: `raise ExchangeError(код, CODE, "текст", details)` (errors.py) — формат контракта, журнал.
6. Тесты: tests/exchange/conftest.py — `exchange_client.put_bytes("/images/<id>", data, "image/jpeg")`,
   `exchange_client.delete("/images/<id>")`, `db_fetch`, `journal_rows`; media_dir подменён на tmp_path.
"""

import uuid

from fastapi import APIRouter

from app.exchange.onec.errors import NOT_IMPLEMENTED, ExchangeError

router = APIRouter()


@router.put("/images/{product_id}", summary="Картинка товара (заглушка)")
def put_image(product_id: uuid.UUID) -> None:
    raise ExchangeError(501, NOT_IMPLEMENTED, "Поток images ещё не реализован")


@router.delete("/images/{product_id}", summary="Удаление картинки товара (заглушка)")
def delete_image(product_id: uuid.UUID) -> None:
    raise ExchangeError(501, NOT_IMPLEMENTED, "Поток images ещё не реализован")
