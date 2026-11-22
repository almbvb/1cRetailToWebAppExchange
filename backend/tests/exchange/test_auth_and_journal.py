"""С1-Т1: вход, формат ошибок, разбор JSON, транзакция порции, журнал обмена, общие хелперы UPSERT."""

import base64
import io
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from PIL import Image
from sqlalchemy.orm import Session

from app.db import get_db
from app.exchange.onec import common, journal
from app.exchange.onec.auth import require_exchange_auth
from app.exchange.onec.common import (
    ExchangeModel,
    Guid,
    dedupe_last,
    json_body,
    ok_response,
    upsert,
)
from app.exchange.onec.errors import EXCHANGE_PREFIX, INVALID_FORMAT, ExchangeError
from app.exchange.onec.journal import Journal
from app.main import create_app
from app.models import CatalogStock, CatalogUnit
from tests.exchange import TEST_BASIC_PASSWORD, TEST_BASIC_USER, TEST_BEARER_TOKEN, TEST_STORE_ID
from tests.exchange.conftest import ExchangeClient

CRASH_TEXT = "текст исключения, которого не должно быть в ответе"

# --- Тестовые маршруты внутри /exchange/1c (как будущие обработчики потоков) ---


class ProbeUnit(ExchangeModel):
    id: Guid
    name: str


class ProbeIn(ExchangeModel):
    full: bool = False
    units: list[ProbeUnit]


probe_router = APIRouter(prefix=EXCHANGE_PREFIX, dependencies=[Depends(require_exchange_auth)])


@probe_router.post("/_probe/units")
def probe_units(
    body: Annotated[ProbeIn, Depends(json_body(ProbeIn))],
    db: Annotated[Session, Depends(get_db)],
    entry: Journal,
    fail: bool = False,
) -> dict[str, Any]:
    rows = [{"id": unit.id, "name": unit.name, "code": "796"} for unit in body.units]
    written = upsert(db, CatalogUnit, rows)
    if fail:
        raise ExchangeError(400, INVALID_FORMAT, "Проверка отката", [{"field": "units[0]", "message": "x"}])
    db.commit()
    return ok_response(entry, units=written)


@probe_router.post("/_probe/crash")
def probe_crash(db: Annotated[Session, Depends(get_db)]) -> None:
    upsert(db, CatalogUnit, [{"id": uuid.uuid4(), "name": "до сбоя", "code": "1"}])
    raise RuntimeError(CRASH_TEXT)


@pytest.fixture
def probe_client(make_exchange_client: Callable[[FastAPI], ExchangeClient]) -> ExchangeClient:
    probe_app = create_app()
    probe_app.include_router(probe_router)
    return make_exchange_client(probe_app)


def basic_header(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def assert_error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["details"], list)
    return body["error"]


def tiny_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


# Потоки с минимальными корректными телами: (метод, путь, тело, Content-Type, поток, full в журнале).
# full: у потоков с full в порции (catalog, prices, stock) отсутствующий full — false; у прочих — null.
STREAMS = [
    ("POST", "/catalog", b'{"full": false}', "application/json", "catalog", False),
    ("POST", "/prices", b'{"full": false, "prices": []}', "application/json", "prices", False),
    ("POST", "/stock", b'{"stock": []}', "application/json", "stock", False),
    ("PUT", f"/images/{uuid.uuid4()}", tiny_png(), "image/png", "images", None),
    ("DELETE", f"/images/{uuid.uuid4()}", None, None, "images", None),
    ("POST", "/orders/status", b'{"orders": []}', "application/json", "orders_status", None),
]


# --- Вход ---


def test_no_auth_401(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    response = exchange_client.post_json("/catalog", {"full": False}, auth=None)
    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["www-authenticate"] == 'Basic realm="exchange"'
    row = last_journal()
    assert (row["method"], row["path"], row["stream"], row["status_code"]) == (
        "POST",
        "/exchange/1c/catalog",
        "catalog",
        401,
    )
    assert row["auth"] == "none"
    assert row["error_code"] == "UNAUTHORIZED"


def test_wrong_password_401_and_no_secret_in_journal(
    exchange_client: ExchangeClient, journal_rows: Callable
) -> None:
    wrong = "неверный-пароль-xyz"
    response = exchange_client.post_json("/stock", {}, auth=(TEST_BASIC_USER, wrong))
    assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["www-authenticate"] == 'Basic realm="exchange"'
    response = exchange_client.post_json("/stock", {}, auth=("other_user", TEST_BASIC_PASSWORD))
    assert_error(response, 401, "UNAUTHORIZED")
    rows = journal_rows()
    assert [row["auth"] for row in rows] == ["Basic user=other_user", f"Basic user={TEST_BASIC_USER}"]
    dump = repr(rows)
    assert wrong not in dump
    assert TEST_BASIC_PASSWORD not in dump


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Basic not-base64!!"},
        {"Authorization": "Basic " + base64.b64encode(b"no-colon").decode()},
        {"Authorization": "Digest something"},
        {"Authorization": "Bearer "},
    ],
)
def test_malformed_auth_401(exchange_client: ExchangeClient, header: dict[str, str]) -> None:
    response = exchange_client.request("POST", "/catalog", headers=header, auth=None)
    assert_error(response, 401, "UNAUTHORIZED")


def test_basic_not_configured_401(
    exchange_client: ExchangeClient, exchange_settings: Any, monkeypatch
) -> None:
    monkeypatch.setattr(exchange_settings, "exchange_basic_password", None)
    response = exchange_client.post_json("/catalog", {})
    assert_error(response, 401, "UNAUTHORIZED")


def assert_ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    body = response.json()
    assert body["ok"] is True
    return body["counts"]


@pytest.mark.parametrize(
    ("method", "path", "content", "content_type", "stream", "full"),
    STREAMS,
    ids=[f"{method}-{stream}" for method, _, _, _, stream, _ in STREAMS],
)
def test_valid_basic_reaches_stream(
    exchange_client: ExchangeClient,
    last_journal: Callable,
    method: str,
    path: str,
    content: bytes | None,
    content_type: str | None,
    stream: str,
    full: bool | None,
) -> None:
    headers = {"Content-Type": content_type} if content_type else None
    counts = assert_ok(exchange_client.request(method, path, content=content, headers=headers))
    row = last_journal()
    assert (row["method"], row["path"], row["stream"]) == (method, EXCHANGE_PREFIX + path, stream)
    assert row["status_code"] == 200
    assert row["auth"] == f"Basic user={TEST_BASIC_USER}"
    assert row["full"] is full
    assert row["counts"] == counts
    assert (row["error_code"], row["error_message"]) == (None, None)


def test_bearer(exchange_client: ExchangeClient, journal_rows: Callable) -> None:
    body = b'{"full": false, "prices": []}'
    good = {"Authorization": f"Bearer {TEST_BEARER_TOKEN}", "Content-Type": "application/json"}
    assert_ok(exchange_client.request("POST", "/prices", content=body, headers=good, auth=None))
    bad = {"Authorization": "Bearer wrong-token", "Content-Type": "application/json"}
    response = exchange_client.request("POST", "/prices", content=body, headers=bad, auth=None)
    assert_error(response, 401, "UNAUTHORIZED")
    rows = journal_rows()
    assert [(row["auth"], row["status_code"]) for row in rows] == [("Bearer", 401), ("Bearer", 200)]
    assert TEST_BEARER_TOKEN not in repr(rows)


# --- Формат ошибок вне потоков ---


def test_unknown_path_404_in_error_format(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    assert_error(exchange_client.post_json("/nothing", {}), 404, "NOT_FOUND")
    row = last_journal()
    assert (row["status_code"], row["stream"], row["error_code"]) == (404, None, "NOT_FOUND")


def test_wrong_method_405_in_error_format(exchange_client: ExchangeClient, last_journal: Callable) -> None:
    response = exchange_client.request("GET", "/catalog")
    assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert "POST" in response.headers["allow"]
    assert last_journal()["status_code"] == 405


def test_invalid_guid_in_path_400(exchange_client: ExchangeClient) -> None:
    error = assert_error(exchange_client.put_bytes("/images/not-a-guid", b"x"), 400, INVALID_FORMAT)
    assert error["details"][0]["field"] == "product_id"


def test_errors_outside_exchange_unchanged(exchange_client: ExchangeClient, journal_rows: Callable) -> None:
    response = exchange_client.http.get("/api/nothing")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert journal_rows() == []


# --- Разбор JSON ---


@pytest.mark.parametrize(
    "raw",
    [b"", b"{not json", b'{"units": [}', "{}".encode("utf-16"), b"NaN", bytes([0xFF]) + b"{}"],
    ids=["empty", "syntax", "unclosed", "utf16", "nan", "not-utf8"],
)
def test_invalid_json_400(probe_client: ExchangeClient, last_journal: Callable, raw: bytes) -> None:
    error = assert_error(probe_client.post_json("/_probe/units", raw), 400, INVALID_FORMAT)
    assert error["details"][0]["field"] == "body"
    row = last_journal()
    assert (row["status_code"], row["error_code"]) == (400, INVALID_FORMAT)


def test_validation_details_have_field_paths(probe_client: ExchangeClient, last_journal: Callable) -> None:
    body = {"full": True, "units": [{"id": str(uuid.uuid4()), "name": "шт"}, {"id": "bad", "name": "кг"}]}
    error = assert_error(probe_client.post_json("/_probe/units", body), 400, INVALID_FORMAT)
    assert [detail["field"] for detail in error["details"]] == ["units[1].id"]
    row = last_journal()
    assert row["full"] is True  # full попадает в журнал даже при ошибке порции
    assert "units[1].id" in row["error_message"]

    error = assert_error(probe_client.post_json("/_probe/units", {"full": False}), 400, INVALID_FORMAT)
    assert [detail["field"] for detail in error["details"]] == ["units"]
    error = assert_error(probe_client.post_json("/_probe/units", [1, 2]), 400, INVALID_FORMAT)
    assert [detail["field"] for detail in error["details"]] == ["body"]


def test_full_in_journal(
    probe_client: ExchangeClient, exchange_client: ExchangeClient, last_journal: Callable
) -> None:
    """full: как пришло; нет поля у порции с full — false; у порции без full (orders/status) — null."""
    units = {"units": []}
    for body, expected in [(units | {"full": True}, True), (units | {"full": False}, False), (units, False)]:
        response = probe_client.post_json("/_probe/units", body)
        assert response.status_code == 200, response.text
        assert last_journal()["full"] is expected
    # Неверный JSON — full неизвестен; неверный тип full — тоже не отмечается.
    assert_error(probe_client.post_json("/_probe/units", b"{"), 400, INVALID_FORMAT)
    assert last_journal()["full"] is None
    assert_error(probe_client.post_json("/_probe/units", units | {"full": "да"}), 400, INVALID_FORMAT)
    assert last_journal()["full"] is None
    assert_ok(exchange_client.post_json("/orders/status", {"orders": []}))
    assert last_journal()["full"] is None
    assert_ok(exchange_client.post_json("/orders/status", {"full": True, "orders": []}))
    assert last_journal()["full"] is True  # булево full из тела пишется всегда


def test_unknown_fields_ignored_and_ok_response(
    probe_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    unit_id = uuid.uuid4()
    body = {"full": True, "extra": {"a": 1}, "units": [{"id": str(unit_id), "name": "кг", "zzz": 5}]}
    response = probe_client.post_json("/_probe/units", body)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "counts": {"units": 1}}
    assert [unit.name for unit in db_fetch(CatalogUnit, CatalogUnit.id == unit_id)] == ["кг"]
    row = last_journal()
    assert (row["status_code"], row["full"], row["counts"], row["error_code"]) == (
        200,
        True,
        {"units": 1},
        None,
    )
    assert row["stream"] is None
    assert row["body_bytes"] == len(response.request.content)
    assert row["duration_ms"] >= 0


# --- Транзакция порции и 500 ---


def test_batch_rolled_back_on_error_but_journal_kept(
    probe_client: ExchangeClient, db_fetch: Callable, last_journal: Callable
) -> None:
    unit_id = uuid.uuid4()
    body = {"units": [{"id": str(unit_id), "name": "шт"}]}
    response = probe_client.post_json("/_probe/units?fail=true", body)
    assert_error(response, 400, INVALID_FORMAT)
    assert db_fetch(CatalogUnit, CatalogUnit.id == unit_id) == []
    row = last_journal()
    assert (row["status_code"], row["error_code"]) == (400, INVALID_FORMAT)
    assert row["error_message"].startswith("Проверка отката")


def test_unexpected_exception_500_without_leak(
    probe_client: ExchangeClient, db_fetch: Callable, last_journal: Callable, caplog
) -> None:
    caplog.set_level(logging.ERROR, logger="app.exchange.onec.journal")
    response = probe_client.post_json("/_probe/crash", {})
    error = assert_error(response, 500, "INTERNAL_ERROR")
    assert CRASH_TEXT not in response.text
    assert error["details"] == []
    assert db_fetch(CatalogUnit, CatalogUnit.name == "до сбоя") == []
    row = last_journal()
    assert (row["status_code"], row["error_code"]) == (500, "INTERNAL_ERROR")
    assert CRASH_TEXT not in (row["error_message"] or "")
    assert "RuntimeError" in row["error_message"]
    assert CRASH_TEXT in caplog.text  # в лог — с текстом и трассировкой


def test_journal_failure_does_not_break_response(
    exchange_client: ExchangeClient, journal_rows: Callable, monkeypatch, caplog
) -> None:
    def broken_session() -> Session:
        raise RuntimeError("журнал недоступен")

    monkeypatch.setattr(journal, "journal_session_factory", broken_session)
    caplog.set_level(logging.ERROR, logger="app.exchange.onec.journal")
    assert_ok(exchange_client.post_json("/prices", {"full": False, "prices": []}))
    assert journal_rows() == []
    assert "Сбой записи журнала обмена" in caplog.text


# --- Предел тела ---


def test_body_over_limit_by_content_length_413(
    probe_client: ExchangeClient, last_journal: Callable, monkeypatch
) -> None:
    monkeypatch.setattr(common, "JSON_MAX_BYTES", 64)
    body = {"units": [{"id": str(uuid.uuid4()), "name": "x" * 100}]}
    response = probe_client.post_json("/_probe/units", body)
    assert_error(response, 413, "PAYLOAD_TOO_LARGE")
    row = last_journal()
    assert (row["status_code"], row["error_code"]) == (413, "PAYLOAD_TOO_LARGE")
    assert row["body_bytes"] == len(response.request.content)


def test_body_over_limit_while_streaming_413(probe_client: ExchangeClient, monkeypatch) -> None:
    monkeypatch.setattr(common, "JSON_MAX_BYTES", 64)
    chunks = iter([b'{"units": [', b" " * 60, b" " * 60, b"]}"])  # без Content-Length (chunked)
    response = probe_client.request("POST", "/_probe/units", content=chunks)
    assert "content-length" not in response.request.headers
    assert_error(response, 413, "PAYLOAD_TOO_LARGE")


def test_default_json_limit_is_20_mb() -> None:
    assert common.JSON_MAX_BYTES == 20 * 1024 * 1024


# --- Хелперы дедупликации и UPSERT ---


def test_dedupe_last_keeps_last() -> None:
    items = [("a", 1), ("b", 2), ("a", 3)]
    assert dedupe_last(items, key=lambda item: item[0]) == [("a", 3), ("b", 2)]


def test_upsert_batches_and_duplicates(db_session: Session, db_fetch: Callable) -> None:
    ids = [uuid.uuid4() for _ in range(4)]
    rows = [{"id": unit_id, "name": f"u{n}", "code": str(n)} for n, unit_id in enumerate(ids)]
    rows.append({"id": ids[0], "name": "последняя", "code": "0"})  # повтор ключа в порции
    assert upsert(db_session, CatalogUnit, rows, batch_size=2) == 4
    db_session.commit()
    names = {unit.id: unit.name for unit in db_fetch(CatalogUnit, CatalogUnit.id.in_(ids))}
    assert names[ids[0]] == "последняя" and len(names) == 4
    # Повтор порции идемпотентен: запись по ключу заменяется целиком.
    assert upsert(db_session, CatalogUnit, [{"id": ids[1], "name": "новое", "code": "9"}]) == 1
    db_session.commit()
    unit = db_fetch(CatalogUnit, CatalogUnit.id == ids[1])[0]
    assert (unit.name, unit.code) == ("новое", "9")


def test_upsert_where_not_earlier(db_session: Session, db_fetch: Callable) -> None:
    product_id = uuid.uuid4()
    moment = datetime(2026, 11, 17, 15, 31, tzinfo=UTC)

    def put(available: str, updated_at: datetime) -> int:
        row = {
            "store_id": TEST_STORE_ID,
            "product_id": product_id,
            "available": Decimal(available),
            "updated_at": updated_at,
        }
        return upsert(
            db_session,
            CatalogStock,
            [row],
            where=lambda excluded: CatalogStock.updated_at <= excluded.updated_at,
        )

    def current() -> Decimal:
        return db_fetch(CatalogStock, CatalogStock.product_id == product_id)[0].available

    assert put("5", moment) == 1
    assert put("7", moment - timedelta(seconds=1)) == 0  # строго раньше — пропуск
    assert current() == Decimal("5.000")
    assert put("8", moment) == 1  # то же время — принимается
    assert put("0.199", moment + timedelta(minutes=1)) == 1
    assert current() == Decimal("0.199")
