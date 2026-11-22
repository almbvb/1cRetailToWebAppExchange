"""Картинки товара PUT и DELETE /exchange/1c/images/{product_id} (api_spec.md 3.4; docs/c1_exchange.md).

PUT — тело: файл картинки (не JSON).
- product_id не GUID -> 400 INVALID_FORMAT (проверка пути FastAPI);
- тело больше IMAGE_MAX_BYTES -> 413 IMAGE_TOO_LARGE (Content-Length до чтения и счёт при чтении);
- пустое тело -> 400 INVALID_FORMAT;
- формат — по содержимому: не JPEG и не PNG или битый файл -> 415 UNSUPPORTED_IMAGE;
  Content-Type запроса не главный, несовпадение только пишется в лог;
- больше IMAGE_MAX_MEGAPIXELS -> 413 IMAGE_TOO_LARGE.
Порядок: файлы (оригинал и превью, app.services.images) -> UPSERT catalog_images -> commit -> удаление
устаревших файлов (старые превью, оригинал другого расширения) -> ответ 200.
Сбой БД после записи файлов: ответ 500, 1С повторит; новые файлы уже лежат (повтор будет unchanged),
старые превью не удалены, строка БД — прежняя. Оригинал того же расширения уже заменён новым.
Картинка раньше карточки товара сохраняется (внешних ключей нет).

Счётчики: image_bytes — байт тела; unchanged — 1, если тот же файл уже был сохранён (ничего не пересоздано).

DELETE — удаляет строку catalog_images (commit), затем папку товара с файлами; картинки не было — тоже 200.
Счётчик deleted — 1, если была строка или файлы, иначе 0.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import get_db
from app.exchange.onec.common import ok_response, read_body, upsert
from app.exchange.onec.errors import (
    IMAGE_TOO_LARGE,
    INVALID_FORMAT,
    UNSUPPORTED_IMAGE,
    ExchangeError,
)
from app.exchange.onec.journal import ExchangeJournal, Journal
from app.models import CatalogImage
from app.services import images as image_files

logger = logging.getLogger(__name__)

router = APIRouter()


def _declared_type(header: str | None) -> str | None:
    return header.split(";", 1)[0].strip().lower() if header else None


def _details(exc: Exception) -> list[dict[str, str]]:
    return [{"field": "body", "message": str(exc)}]


def _store_image(
    product_id: uuid.UUID,
    raw: bytes,
    declared_type: str | None,
    db: Session,
    journal: ExchangeJournal,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        stored = image_files.store_product_image(
            settings.media_dir, product_id, raw, max_megapixels=settings.image_max_megapixels
        )
    except image_files.ImageTooLargeError as exc:
        raise ExchangeError(
            413, IMAGE_TOO_LARGE, f"Картинка больше {settings.image_max_megapixels} Мп", _details(exc)
        ) from None
    except image_files.UnsupportedImageError as exc:
        raise ExchangeError(415, UNSUPPORTED_IMAGE, "Содержимое не JPEG и не PNG", _details(exc)) from None

    if declared_type != stored.content_type:
        logger.warning(
            "Картинка %s: Content-Type %r, по содержимому %s", product_id, declared_type, stored.content_type
        )

    row = {
        "product_id": product_id,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "sha256": stored.sha256,
        "width": stored.width,
        "height": stored.height,
        "original_path": stored.original_path,
    }
    upsert(db, CatalogImage, [row])
    db.commit()

    # Устаревшие файлы — только после фиксации: до неё старая строка БД ссылается на них.
    try:
        image_files.cleanup_product_images(settings.media_dir, stored)
    except OSError:
        logger.exception("Картинка %s: не удалось удалить устаревшие файлы", product_id)

    return ok_response(journal, image_bytes=len(raw), unchanged=int(stored.unchanged))


@router.put("/images/{product_id}", summary="Картинка товара (JPEG или PNG)")
async def put_image(
    product_id: uuid.UUID,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    journal: Journal,
) -> dict[str, Any]:
    raw = await read_body(request, get_settings().image_max_bytes, too_large_code=IMAGE_TOO_LARGE)
    if not raw:
        raise ExchangeError(
            400, INVALID_FORMAT, "Пустое тело запроса", [{"field": "body", "message": "Нет файла картинки"}]
        )
    declared_type = _declared_type(request.headers.get("content-type"))
    # Pillow, файлы и БД — в пуле потоков, чтобы не держать цикл событий.
    return await run_in_threadpool(_store_image, product_id, raw, declared_type, db, journal)


@router.delete("/images/{product_id}", summary="Удаление картинки товара")
def delete_image(
    product_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    journal: Journal,
) -> dict[str, Any]:
    result = db.execute(delete(CatalogImage).where(CatalogImage.product_id == product_id))
    db.commit()
    # Сбой удаления файлов (например, файл занят) -> 500, 1С повторит DELETE; строка уже удалена.
    had_files = image_files.delete_product_images(get_settings().media_dir, product_id)
    deleted = int(bool(result.rowcount) or had_files)  # type: ignore[attr-defined]
    return ok_response(journal, deleted=deleted)
