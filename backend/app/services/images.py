"""Картинки товаров: проверка, оригинал и превью WebP в MEDIA_DIR (без HTTP и БД; docs/c1_exchange.md).

Раскладка файлов товара (папка MEDIA_DIR/products/<product_id>/):
- original.jpg или original.png — исходный файл байт в байт (как прислала 1С);
- <sha256[:12]>_400.webp и <sha256[:12]>_1000.webp — превью по длинной стороне (меньшие не увеличиваются).

Решения:
- Формат определяется по содержимому (Pillow, только плагины JPEG и PNG), заголовок Content-Type не важен.
  JPEG с несколькими кадрами (MPO, камеры телефонов) считается JPEG.
- Размер в пикселях проверяется по заголовку ДО декодирования: больше max_megapixels -> ImageTooLargeError
  (это и есть защита от decompression bomb; DecompressionBombError самого Pillow — тоже ImageTooLargeError).
- Превью учитывают EXIF-поворот (Orientation) и не содержат EXIF (нет GPS и прочих метаданных).
  width и height в результате — как картинку видит покупатель (после поворота).
- PNG с прозрачностью -> превью WebP с альфа-каналом (витрина сама выбирает фон); без прозрачности — RGB.
- Запись атомарная: временный файл в той же папке + os.replace (читатель видит старый или новый файл целиком).
- Тот же sha256 и все файлы на месте -> ничего не пересоздаётся (StoredImage.unchanged).
- Старые превью и оригинал другого расширения удаляет cleanup_product_images — вызывать ПОСЛЕ фиксации
  строки в БД, чтобы при сбое БД старая строка не указывала на удалённые файлы.
"""

import hashlib
import io
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

PREVIEW_SIZES = (400, 1000)
PRODUCTS_DIR = "products"
MEDIA_URL_PREFIX = "/media"
WEBP_QUALITY = 82
WEBP_METHOD = 4  # 0 (быстро) … 6 (медленно, чуть меньше файл)

# Формат Pillow -> (расширение оригинала, content_type).
_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "MPO": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
}
_ORIGINAL_NAMES = {f"original.{ext}" for ext, _ in _FORMATS.values()}
_PREVIEW_NAME = re.compile(r"^[0-9a-f]{12}_(\d+)\.webp$")
_TMP_PREFIX = ".tmp-"

# EXIF Orientation -> преобразование (как в PIL.ImageOps.exif_transpose).
_EXIF_ORIENTATION = 0x0112
_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


class ImageError(Exception):
    """Картинка не принята."""


class UnsupportedImageError(ImageError):
    """Не JPEG и не PNG по содержимому или файл битый."""


class ImageTooLargeError(ImageError):
    """Больше допустимого числа пикселей."""


@dataclass(frozen=True)
class StoredImage:
    product_id: uuid.UUID
    content_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    original_path: str  # относительно MEDIA_DIR, через «/»
    unchanged: bool  # тот же файл уже был сохранён — ничего не записано

    @property
    def keep_names(self) -> set[str]:
        """Имена файлов, которые относятся к этой картинке (остальные в папке товара — устаревшие)."""
        return {Path(self.original_path).name} | {preview_name(self.sha256, size) for size in PREVIEW_SIZES}


def product_dir(media_dir: Path, product_id: uuid.UUID) -> Path:
    # str(UUID) — только hex и «-»: путь не выходит за MEDIA_DIR.
    return Path(media_dir) / PRODUCTS_DIR / str(uuid.UUID(str(product_id)))


def preview_name(sha256: str, size: int) -> str:
    if size not in PREVIEW_SIZES:
        raise ValueError(f"Нет превью размера {size}; есть {PREVIEW_SIZES}")
    return f"{sha256[:12]}_{size}.webp"


def preview_url(product_id: uuid.UUID, sha256: str, size: int) -> str:
    """Относительный адрес превью для витрины: /media/products/<id>/<sha12>_<size>.webp."""
    return f"{MEDIA_URL_PREFIX}/{PRODUCTS_DIR}/{uuid.UUID(str(product_id))}/{preview_name(sha256, size)}"


def _open_checked(data: bytes, max_megapixels: float) -> Image.Image:
    """Открывает картинку (только заголовок) и проверяет формат и число пикселей."""
    if not data:
        raise UnsupportedImageError("Пустой файл")
    try:
        image = Image.open(io.BytesIO(data), formats=["JPEG", "PNG"])
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(str(exc)) from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise UnsupportedImageError(f"Не JPEG и не PNG или файл повреждён ({type(exc).__name__})") from None
    if image.format not in _FORMATS:
        raise UnsupportedImageError(f"Формат {image.format} не поддерживается")
    width, height = image.size
    if width <= 0 or height <= 0:
        raise UnsupportedImageError("Нулевой размер картинки")
    if width * height > max_megapixels * 1_000_000:
        raise ImageTooLargeError(f"Картинка {width}×{height} больше {max_megapixels} Мп")
    return image


def _orientation(image: Image.Image) -> int:
    try:
        value = image.getexif().get(_EXIF_ORIENTATION, 1)
    except Exception:  # битый EXIF не должен мешать картинке
        return 1
    return value if isinstance(value, int) and value in _TRANSPOSE else 1


def _make_previews(image: Image.Image, orientation: int) -> dict[int, bytes]:
    """Декодирует картинку и делает превью WebP всех размеров (от большего к меньшему)."""
    try:
        image.load()
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(str(exc)) from None
    except (OSError, SyntaxError, ValueError, EOFError) as exc:
        raise UnsupportedImageError(f"Файл повреждён ({type(exc).__name__})") from None

    has_alpha = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
    try:
        source = image.convert("RGBA" if has_alpha else "RGB")
    except (OSError, ValueError) as exc:
        raise UnsupportedImageError(f"Цветовой режим {image.mode} не поддерживается ({exc})") from None

    previews: dict[int, bytes] = {}
    for size in sorted(PREVIEW_SIZES, reverse=True):
        width, height = source.size
        scale = size / max(width, height)
        if scale < 1:
            target = (max(1, round(width * scale)), max(1, round(height * scale)))
            # Следующий (меньший) размер делается из этого превью — быстрее, качество то же.
            source = source.resize(target, Image.Resampling.LANCZOS, reducing_gap=3.0)
        # Поворот после уменьшения: длинная сторона от поворота не меняется, а поворачивать меньше пикселей.
        oriented = source.transpose(_TRANSPOSE[orientation]) if orientation != 1 else source
        buffer = io.BytesIO()
        oriented.save(buffer, "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
        previews[size] = buffer.getvalue()
    return previews


def _write_atomic(path: Path, data: bytes) -> None:
    """Пишет файл целиком во временный в той же папке и подменяет os.replace."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=_TMP_PREFIX, suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _same_file(path: Path, sha256: str) -> bool:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == sha256
    except OSError:
        return False


def store_product_image(
    media_dir: Path, product_id: uuid.UUID, data: bytes, *, max_megapixels: float
) -> StoredImage:
    """Проверяет картинку, сохраняет оригинал и превью. Устаревшие файлы не трогает (см. cleanup_…).

    Ошибки: UnsupportedImageError (не JPEG/PNG, битый файл), ImageTooLargeError (больше max_megapixels).
    """
    folder = product_dir(media_dir, product_id)
    sha256 = hashlib.sha256(data).hexdigest()
    # Защита от decompression bomb — своя проверка числа пикселей по заголовку до декодирования
    # (_open_checked); Image.DecompressionBombError Pillow (больше 2×MAX_IMAGE_PIXELS) -> тоже «too large».
    # warnings.catch_warnings не используется: он меняет общее состояние и не потокобезопасен.
    image = _open_checked(data, max_megapixels)
    with image:
        ext, content_type = _FORMATS[image.format or ""]
        orientation = _orientation(image)
        width, height = image.size
        if orientation in (5, 6, 7, 8):  # поворот на 90° — стороны меняются местами
            width, height = height, width
        original = folder / f"original.{ext}"
        previews = {size: folder / preview_name(sha256, size) for size in PREVIEW_SIZES}

        unchanged = _same_file(original, sha256) and all(path.is_file() for path in previews.values())
        if not unchanged:
            preview_bytes = _make_previews(image, orientation)
            folder.mkdir(parents=True, exist_ok=True)
            # Сначала превью (новые имена), оригинал — последним: по нему проверяется «уже сохранено».
            for size, path in previews.items():
                _write_atomic(path, preview_bytes[size])
            _write_atomic(original, data)

    return StoredImage(
        product_id=product_id,
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha256,
        width=width,
        height=height,
        original_path=original.relative_to(Path(media_dir)).as_posix(),
        unchanged=unchanged,
    )


def cleanup_product_images(media_dir: Path, stored: StoredImage) -> list[str]:
    """Удаляет из папки товара превью других sha256 и оригинал другого расширения; возвращает имена."""
    folder = product_dir(media_dir, stored.product_id)
    keep = stored.keep_names
    removed: list[str] = []
    if not folder.is_dir():
        return removed
    for path in folder.iterdir():
        name = path.name
        stale = name in _ORIGINAL_NAMES or _PREVIEW_NAME.match(name) is not None
        if stale and name not in keep and path.is_file():
            path.unlink(missing_ok=True)
            removed.append(name)
    return removed


def delete_product_images(media_dir: Path, product_id: uuid.UUID) -> bool:
    """Удаляет папку товара со всеми файлами; True — папка была."""
    folder = product_dir(media_dir, product_id)
    if not folder.exists():
        return False
    shutil.rmtree(folder)
    return True
