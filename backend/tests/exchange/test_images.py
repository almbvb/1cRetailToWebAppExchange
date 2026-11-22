"""Поток картинок PUT/DELETE /exchange/1c/images/{product_id} (С1-Т4) и app.services.images.

Картинки генерируются Pillow в памяти; MEDIA_DIR — временная папка теста (фикстура media_dir).
"""

import io
import uuid
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.config import Settings
from app.models import CatalogImage
from app.services import images as image_files
from tests.exchange.conftest import ExchangeClient

PRODUCT_ID = uuid.UUID("7c1e0a50-3333-4a2b-9c3d-000000000001")


@pytest.fixture(autouse=True)
def media_dir(exchange_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """MEDIA_DIR — только временная папка (не var/media)."""
    folder = tmp_path / "media"
    monkeypatch.setattr(exchange_settings, "media_dir", folder)
    return folder


def make_image(
    fmt: str,
    size: tuple[int, int],
    color: Any = (200, 30, 30),
    *,
    mode: str = "RGB",
    orientation: int | None = None,
) -> bytes:
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    params: dict[str, Any] = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        params["exif"] = exif
    image.save(buffer, fmt, **params)
    return buffer.getvalue()


def product_dir(media_dir: Path, product_id: uuid.UUID = PRODUCT_ID) -> Path:
    return media_dir / "products" / str(product_id)


def file_names(media_dir: Path, product_id: uuid.UUID = PRODUCT_ID) -> set[str]:
    folder = product_dir(media_dir, product_id)
    return {path.name for path in folder.iterdir()} if folder.exists() else set()


def preview_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        assert image.format == "WEBP"
        return image.size


def put(client: ExchangeClient, data: bytes, content_type: str = "image/jpeg", **kwargs: Any) -> Any:
    return client.put_bytes(f"/images/{PRODUCT_ID}", data, content_type, **kwargs)


def sha12(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()[:12]


def assert_error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


# --- Приём картинки ---


def test_put_jpeg_saves_original_previews_and_row(
    exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any, last_journal: Any
) -> None:
    data = make_image("JPEG", (1600, 1200))
    response = put(exchange_client, data)

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "counts": {"image_bytes": len(data), "unchanged": 0}}
    folder = product_dir(media_dir)
    prefix = sha12(data)
    assert file_names(media_dir) == {"original.jpg", f"{prefix}_400.webp", f"{prefix}_1000.webp"}
    assert (folder / "original.jpg").read_bytes() == data  # оригинал байт в байт
    assert preview_size(folder / f"{prefix}_1000.webp") == (1000, 750)
    assert preview_size(folder / f"{prefix}_400.webp") == (400, 300)

    # Картинка раньше карточки товара — сохраняется (товара в catalog_products нет).
    [row] = db_fetch(CatalogImage, CatalogImage.product_id == PRODUCT_ID)
    assert row.content_type == "image/jpeg"
    assert row.size_bytes == len(data)
    assert row.sha256.startswith(prefix) and len(row.sha256) == 64
    assert (row.width, row.height) == (1600, 1200)
    assert row.original_path == f"products/{PRODUCT_ID}/original.jpg"
    assert (media_dir / row.original_path).is_file()

    journal = last_journal()
    assert journal["stream"] == "images"
    assert journal["status_code"] == 200
    assert journal["counts"] == {"image_bytes": len(data), "unchanged": 0}
    assert journal["error_code"] is None


def test_put_png_portrait(exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any) -> None:
    data = make_image("PNG", (1200, 2400), (10, 120, 10))
    response = put(exchange_client, data, "image/png")

    assert response.status_code == 200, response.text
    prefix = sha12(data)
    assert file_names(media_dir) == {"original.png", f"{prefix}_400.webp", f"{prefix}_1000.webp"}
    assert preview_size(product_dir(media_dir) / f"{prefix}_1000.webp") == (500, 1000)
    assert preview_size(product_dir(media_dir) / f"{prefix}_400.webp") == (200, 400)
    [row] = db_fetch(CatalogImage, CatalogImage.product_id == PRODUCT_ID)
    assert (row.content_type, row.width, row.height) == ("image/png", 1200, 2400)


def test_png_transparency_kept_in_preview(exchange_client: ExchangeClient, media_dir: Path) -> None:
    data = make_image("PNG", (600, 300), (0, 0, 255, 0), mode="RGBA")
    assert put(exchange_client, data, "image/png").status_code == 200

    with Image.open(product_dir(media_dir) / f"{sha12(data)}_400.webp") as preview:
        assert preview.mode == "RGBA"
        assert preview.getpixel((10, 10))[3] == 0  # прозрачный пиксель остался прозрачным


def test_small_image_not_upscaled(exchange_client: ExchangeClient, media_dir: Path) -> None:
    data = make_image("JPEG", (300, 200))
    assert put(exchange_client, data).status_code == 200

    prefix = sha12(data)
    assert preview_size(product_dir(media_dir) / f"{prefix}_400.webp") == (300, 200)
    assert preview_size(product_dir(media_dir) / f"{prefix}_1000.webp") == (300, 200)


def test_exif_orientation_applied_to_previews(
    exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any
) -> None:
    # Хранится 200×100: левая половина красная, правая синяя; Orientation=6 — показать с поворотом на 90°
    # по часовой: картинка 100×200, красная половина сверху.
    image = Image.new("RGB", (200, 100), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, 100, 100))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif, quality=95)
    data = buffer.getvalue()

    assert put(exchange_client, data).status_code == 200

    with Image.open(product_dir(media_dir) / f"{sha12(data)}_400.webp") as preview:
        assert preview.size == (100, 200)
        assert not preview.getexif()  # EXIF в превью не переносится
        rgb = preview.convert("RGB")
        top, bottom = rgb.getpixel((50, 20)), rgb.getpixel((50, 180))
    assert top[0] > 200 and top[2] < 60, top
    assert bottom[2] > 200 and bottom[0] < 60, bottom
    [row] = db_fetch(CatalogImage, CatalogImage.product_id == PRODUCT_ID)
    assert (row.width, row.height) == (100, 200)  # как видит покупатель


def test_repeat_same_image_is_unchanged(
    exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any, last_journal: Any
) -> None:
    data = make_image("JPEG", (1200, 800))
    assert put(exchange_client, data).status_code == 200
    folder = product_dir(media_dir)
    before = {path.name: path.stat().st_mtime_ns for path in folder.iterdir()}

    response = put(exchange_client, data)

    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {"image_bytes": len(data), "unchanged": 1}
    assert {path.name: path.stat().st_mtime_ns for path in folder.iterdir()} == before
    assert len(db_fetch(CatalogImage)) == 1
    assert last_journal()["counts"] == {"image_bytes": len(data), "unchanged": 1}


def test_repeat_recreates_missing_preview(exchange_client: ExchangeClient, media_dir: Path) -> None:
    data = make_image("JPEG", (1200, 800))
    assert put(exchange_client, data).status_code == 200
    missing = product_dir(media_dir) / f"{sha12(data)}_400.webp"
    missing.unlink()

    response = put(exchange_client, data)

    assert response.json()["counts"]["unchanged"] == 0
    assert missing.is_file()


def test_replace_removes_old_previews(
    exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any
) -> None:
    first = make_image("JPEG", (1200, 800), (255, 0, 0))
    second = make_image("JPEG", (800, 1200), (0, 255, 0))
    assert put(exchange_client, first).status_code == 200

    response = put(exchange_client, second)

    assert response.status_code == 200, response.text
    assert response.json()["counts"]["unchanged"] == 0
    prefix = sha12(second)
    assert file_names(media_dir) == {"original.jpg", f"{prefix}_400.webp", f"{prefix}_1000.webp"}
    assert (product_dir(media_dir) / "original.jpg").read_bytes() == second
    [row] = db_fetch(CatalogImage, CatalogImage.product_id == PRODUCT_ID)
    assert row.sha256.startswith(prefix)
    assert (row.width, row.height) == (800, 1200)


def test_png_replaced_by_jpeg_removes_old_original(
    exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any
) -> None:
    png = make_image("PNG", (500, 500))
    jpeg = make_image("JPEG", (500, 500))
    assert put(exchange_client, png, "image/png").status_code == 200
    assert "original.png" in file_names(media_dir)

    assert put(exchange_client, jpeg).status_code == 200

    prefix = sha12(jpeg)
    assert file_names(media_dir) == {"original.jpg", f"{prefix}_400.webp", f"{prefix}_1000.webp"}
    [row] = db_fetch(CatalogImage, CatalogImage.product_id == PRODUCT_ID)
    assert (row.content_type, row.original_path) == ("image/jpeg", f"products/{PRODUCT_ID}/original.jpg")


def test_content_type_header_is_not_trusted(
    exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any
) -> None:
    data = make_image("PNG", (100, 100))
    response = put(exchange_client, data, "image/jpeg")

    assert response.status_code == 200, response.text
    assert "original.png" in file_names(media_dir)
    [row] = db_fetch(CatalogImage, CatalogImage.product_id == PRODUCT_ID)
    assert row.content_type == "image/png"


# --- Ошибки ---


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(make_image("GIF", (50, 50)), id="gif"),
        pytest.param(make_image("BMP", (50, 50)), id="bmp"),
        pytest.param("просто текст".encode(), id="text"),
        pytest.param(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, id="broken-png-header"),
        pytest.param(make_image("JPEG", (400, 400))[:300], id="truncated-jpeg"),
        pytest.param(make_image("PNG", (400, 400))[:-40], id="truncated-png"),
    ],
)
def test_unsupported_content_415(
    exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any, last_journal: Any, data: bytes
) -> None:
    response = put(exchange_client, data)

    assert_error(response, 415, "UNSUPPORTED_IMAGE")
    assert file_names(media_dir) == set()
    assert db_fetch(CatalogImage) == []
    journal = last_journal()
    assert (journal["stream"], journal["status_code"], journal["error_code"]) == (
        "images",
        415,
        "UNSUPPORTED_IMAGE",
    )


def test_unsupported_keeps_previous_image(exchange_client: ExchangeClient, media_dir: Path) -> None:
    data = make_image("JPEG", (600, 600))
    assert put(exchange_client, data).status_code == 200
    before = file_names(media_dir)

    assert_error(put(exchange_client, b"not an image"), 415, "UNSUPPORTED_IMAGE")

    assert file_names(media_dir) == before


def test_body_over_limit_413(
    exchange_client: ExchangeClient,
    exchange_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    media_dir: Path,
    last_journal: Any,
) -> None:
    data = make_image("PNG", (300, 300), (1, 2, 3))
    monkeypatch.setattr(exchange_settings, "image_max_bytes", len(data) - 1)

    response = put(exchange_client, data, "image/png")

    assert_error(response, 413, "IMAGE_TOO_LARGE")
    assert file_names(media_dir) == set()
    assert last_journal()["error_code"] == "IMAGE_TOO_LARGE"


def test_body_over_limit_without_content_length_413(
    exchange_client: ExchangeClient, exchange_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = make_image("PNG", (300, 300), (1, 2, 3))
    monkeypatch.setattr(exchange_settings, "image_max_bytes", len(data) - 1)

    def chunks() -> Any:  # потоковое тело без Content-Length
        yield data[:100]
        yield data[100:]

    response = exchange_client.request("PUT", f"/images/{PRODUCT_ID}", content=chunks())

    assert_error(response, 413, "IMAGE_TOO_LARGE")


def test_body_at_limit_accepted(
    exchange_client: ExchangeClient, exchange_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = make_image("PNG", (300, 300))
    monkeypatch.setattr(exchange_settings, "image_max_bytes", len(data))

    assert put(exchange_client, data, "image/png").status_code == 200


def test_megapixels_over_limit_413(
    exchange_client: ExchangeClient,
    exchange_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    media_dir: Path,
    db_fetch: Any,
) -> None:
    monkeypatch.setattr(exchange_settings, "image_max_megapixels", 1)

    response = put(exchange_client, make_image("JPEG", (1001, 1000)))

    assert_error(response, 413, "IMAGE_TOO_LARGE")
    assert file_names(media_dir) == set()
    assert db_fetch(CatalogImage) == []
    # Ровно 1 Мп — проходит.
    assert put(exchange_client, make_image("JPEG", (1000, 1000))).status_code == 200


def test_empty_body_400(exchange_client: ExchangeClient, last_journal: Any) -> None:
    response = put(exchange_client, b"")

    assert_error(response, 400, "INVALID_FORMAT")
    assert last_journal()["error_code"] == "INVALID_FORMAT"


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_invalid_guid_400(exchange_client: ExchangeClient, method: str) -> None:
    content = make_image("JPEG", (10, 10)) if method == "PUT" else None
    response = exchange_client.request(method, "/images/not-a-guid", content=content)

    assert_error(response, 400, "INVALID_FORMAT")
    assert response.json()["error"]["details"][0]["field"] == "product_id"


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_without_auth_401(exchange_client: ExchangeClient, media_dir: Path, method: str) -> None:
    content = make_image("JPEG", (10, 10)) if method == "PUT" else None
    response = exchange_client.request(method, f"/images/{PRODUCT_ID}", content=content, auth=None)

    assert_error(response, 401, "UNAUTHORIZED")
    assert file_names(media_dir) == set()


# --- Удаление ---


def test_delete_existing_image(
    exchange_client: ExchangeClient, media_dir: Path, db_fetch: Any, last_journal: Any
) -> None:
    assert put(exchange_client, make_image("JPEG", (600, 400))).status_code == 200
    other = uuid.UUID("7c1e0a50-3333-4a2b-9c3d-000000000002")
    assert exchange_client.put_bytes(f"/images/{other}", make_image("PNG", (50, 50))).status_code == 200

    response = exchange_client.delete(f"/images/{PRODUCT_ID}")

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "counts": {"deleted": 1}}
    assert not product_dir(media_dir).exists()
    assert [row.product_id for row in db_fetch(CatalogImage)] == [other]  # чужая картинка на месте
    assert file_names(media_dir, other)
    journal = last_journal()
    assert (journal["stream"], journal["method"], journal["counts"]) == ("images", "DELETE", {"deleted": 1})


def test_delete_missing_image_ok(exchange_client: ExchangeClient) -> None:
    response = exchange_client.delete(f"/images/{PRODUCT_ID}")

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "counts": {"deleted": 0}}
    # Повтор DELETE — тоже 200.
    assert exchange_client.delete(f"/images/{PRODUCT_ID}").json()["counts"] == {"deleted": 0}


def test_put_after_delete(exchange_client: ExchangeClient, media_dir: Path) -> None:
    data = make_image("JPEG", (600, 400))
    assert put(exchange_client, data).status_code == 200
    assert exchange_client.delete(f"/images/{PRODUCT_ID}").status_code == 200

    response = put(exchange_client, data)

    assert response.json()["counts"]["unchanged"] == 0
    assert "original.jpg" in file_names(media_dir)


# --- Сервис без HTTP ---


def test_service_store_and_cleanup(tmp_path: Path) -> None:
    media = tmp_path / "svc"
    data = make_image("JPEG", (2000, 1000))

    stored = image_files.store_product_image(media, PRODUCT_ID, data, max_megapixels=40)

    assert not stored.unchanged
    assert stored.keep_names == file_names(media)
    assert not any(name.startswith(".tmp") for name in file_names(media))  # временных файлов не осталось
    again = image_files.store_product_image(media, PRODUCT_ID, data, max_megapixels=40)
    assert again.unchanged and again == stored.__class__(**{**stored.__dict__, "unchanged": True})
    # Посторонний файл в папке товара cleanup не трогает.
    (product_dir(media) / "note.txt").write_text("x")
    assert image_files.cleanup_product_images(media, stored) == []
    assert image_files.delete_product_images(media, PRODUCT_ID) is True
    assert image_files.delete_product_images(media, PRODUCT_ID) is False


def test_service_decompression_bomb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Предел Pillow ниже нашего: DecompressionBombError тоже считается «too large».
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(image_files.ImageTooLargeError):
        image_files.store_product_image(
            tmp_path, PRODUCT_ID, make_image("PNG", (100, 100)), max_megapixels=40
        )


def test_service_errors(tmp_path: Path) -> None:
    with pytest.raises(image_files.UnsupportedImageError):
        image_files.store_product_image(tmp_path, PRODUCT_ID, b"", max_megapixels=40)
    with pytest.raises(image_files.UnsupportedImageError):
        image_files.store_product_image(tmp_path, PRODUCT_ID, make_image("GIF", (5, 5)), max_megapixels=40)
    with pytest.raises(image_files.ImageTooLargeError):
        image_files.store_product_image(
            tmp_path, PRODUCT_ID, make_image("PNG", (200, 200)), max_megapixels=0.01
        )


def test_preview_url() -> None:
    sha = "abcdef0123456789" + "0" * 48

    assert (
        image_files.preview_url(PRODUCT_ID, sha, 400) == f"/media/products/{PRODUCT_ID}/abcdef012345_400.webp"
    )
    assert image_files.preview_url(str(PRODUCT_ID), sha, 1000).endswith("/abcdef012345_1000.webp")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        image_files.preview_url(PRODUCT_ID, sha, 500)
