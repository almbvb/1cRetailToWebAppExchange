"""Админпанель /admin: вход одним администратором и представления только для чтения.

Логин и пароль подменяются в настройках бэкенда входа (значения из .env не используются).
Данные для страниц пишутся в транзакцию теста: SessionLocal админки привязывается к её соединению.
"""

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.views import VIEWS
from app.db import SessionLocal
from app.main import app
from app.models import CatalogProduct, CatalogStock, ExchangeBatch, Order

USERNAME = "test-admin"
PASSWORD = "test-admin-password"


def _set_credentials(monkeypatch: pytest.MonkeyPatch, username: str | None, password: str | None) -> None:
    auth = app.state.admin.authentication_backend
    settings = auth._settings.model_copy(
        update={
            "admin_username": username,
            "admin_password": SecretStr(password) if password is not None else None,
        }
    )
    monkeypatch.setattr(auth, "_settings", settings)


@pytest.fixture
def admin_client(client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _set_credentials(monkeypatch, USERNAME, PASSWORD)
    # Админка открывает сессии через SessionLocal: пусть они идут в транзакцию теста (откатится).
    monkeypatch.setitem(SessionLocal.kw, "bind", db_session.connection())
    monkeypatch.setitem(SessionLocal.kw, "join_transaction_mode", "create_savepoint")
    return client


@pytest.fixture
def logged_in(admin_client: TestClient) -> Iterator[TestClient]:
    response = admin_client.post(
        "/admin/login", data={"username": USERNAME, "password": PASSWORD}, follow_redirects=False
    )
    assert response.status_code == 302
    yield admin_client


def _batch(db_session: Session, **values) -> ExchangeBatch:
    batch = ExchangeBatch(
        method="POST",
        path="/exchange/1c/prices",
        stream="prices",
        status_code=200,
        auth="Basic user=onec",
        full=False,
        counts={"prices": 3},
        body_bytes=120,
        duration_ms=7,
    )
    for key, value in values.items():
        setattr(batch, key, value)
    db_session.add(batch)
    db_session.flush()
    return batch


def test_admin_redirects_to_login_without_session(admin_client: TestClient) -> None:
    for path in ("/admin/", "/admin/exchange-batch/list"):
        response = admin_client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"].endswith("/admin/login")
    assert admin_client.get("/admin/login").status_code == 200


def test_wrong_password_rejected_and_logged(
    admin_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.admin.auth"):
        response = admin_client.post(
            "/admin/login", data={"username": USERNAME, "password": "wrong-password"}, follow_redirects=False
        )
    assert response.status_code == 400
    assert "неуспешный вход" in caplog.text
    assert "wrong-password" not in caplog.text
    assert admin_client.get("/admin/", follow_redirects=False).status_code == 302


@pytest.mark.parametrize(("username", "password"), [(None, None), (USERNAME, None), (None, PASSWORD)])
def test_login_impossible_when_not_configured(
    admin_client: TestClient, monkeypatch: pytest.MonkeyPatch, username: str | None, password: str | None
) -> None:
    _set_credentials(monkeypatch, username, password)
    for given_username, given_password in ((USERNAME, PASSWORD), ("", "")):
        response = admin_client.post(
            "/admin/login",
            data={"username": given_username, "password": given_password},
            follow_redirects=False,
        )
        assert response.status_code == 400
    assert admin_client.get("/admin/", follow_redirects=False).status_code == 302


def test_session_invalid_after_credentials_removed(logged_in: TestClient, monkeypatch) -> None:
    assert logged_in.get("/admin/exchange-batch/list").status_code == 200
    _set_credentials(monkeypatch, None, None)
    assert logged_in.get("/admin/exchange-batch/list", follow_redirects=False).status_code == 302


def test_login_opens_exchange_journal(logged_in: TestClient, db_session: Session) -> None:
    _batch(db_session, status_code=400, error_code="INVALID_FORMAT", error_message="prices[0].price")
    response = logged_in.get("/admin/")
    assert response.status_code == 200
    assert response.url.path == "/admin/exchange-batch/list"
    assert "Журнал обмена" in response.text
    assert "Админпанель — доставка" in response.text
    assert "INVALID_FORMAT" in response.text
    assert "Счётчики" in response.text


def test_exchange_journal_newest_first_and_filters(logged_in: TestClient, db_session: Session) -> None:
    _batch(db_session, received_at=datetime(2026, 1, 1, tzinfo=UTC), error_code="OLD_ROW")
    _batch(db_session, received_at=datetime(2026, 2, 1, tzinfo=UTC), error_code="NEW_ROW")
    _batch(db_session, stream="stock", path="/exchange/1c/stock", status_code=401, error_code="UNAUTHORIZED")

    text = logged_in.get("/admin/exchange-batch/list").text
    assert text.index("NEW_ROW") < text.index("OLD_ROW")

    by_stream = logged_in.get("/admin/exchange-batch/list", params={"stream": "stock"}).text
    assert "UNAUTHORIZED" in by_stream
    assert "NEW_ROW" not in by_stream

    by_code = logged_in.get("/admin/exchange-batch/list", params={"status_code": "401"}).text
    assert "UNAUTHORIZED" in by_code
    assert "OLD_ROW" not in by_code


@pytest.mark.parametrize("view", VIEWS, ids=lambda view: view.identity)
def test_all_views_open(logged_in: TestClient, view) -> None:
    response = logged_in.get(f"/admin/{view.identity}/list")
    assert response.status_code == 200
    assert view.name_plural in response.text


def test_views_show_data(logged_in: TestClient, db_session: Session) -> None:
    product_id = uuid.uuid4()
    db_session.add(
        CatalogProduct(
            id=product_id,
            name="Молоко 3,2%",
            article="ART-777",
            unit_id=uuid.uuid4(),
            weighted=False,
        )
    )
    db_session.add(
        CatalogStock(
            store_id=uuid.uuid4(),
            product_id=product_id,
            available=Decimal("5"),
            updated_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
    )
    db_session.add(
        Order(
            order_id="order-admin-1",
            onec_number="RT-000123",
            status="assembling",
            onec_created_at=datetime(2026, 3, 1, tzinfo=UTC),
            onec_changed_at=datetime(2026, 3, 1, tzinfo=UTC),
            total=Decimal("100.50"),
        )
    )
    db_session.flush()

    products = logged_in.get("/admin/catalog-product/list", params={"search": "ART-777"}).text
    assert "Молоко 3,2%" in products
    assert "Артикул" in products
    assert "Молоко" not in logged_in.get("/admin/catalog-product/list", params={"deleted": "true"}).text

    assert str(product_id) in logged_in.get("/admin/catalog-stock/list").text
    orders = logged_in.get("/admin/order/list", params={"status": "assembling"}).text
    assert "RT-000123" in orders


def test_details_and_csv_export(logged_in: TestClient, db_session: Session) -> None:
    batch = _batch(db_session, error_code="DETAILS_ROW")
    details = logged_in.get(f"/admin/exchange-batch/details/{batch.id}")
    assert details.status_code == 200
    assert "DETAILS_ROW" in details.text

    export = logged_in.get("/admin/exchange-batch/export/csv")
    assert export.status_code == 200
    assert "exchange_batches_" in export.headers["content-disposition"]
    assert "DETAILS_ROW" in export.text


def test_write_actions_unavailable(logged_in: TestClient, db_session: Session) -> None:
    batch = _batch(db_session)
    for view in VIEWS:
        identity = view.identity
        assert logged_in.get(f"/admin/{identity}/create").status_code == 403
        assert logged_in.post(f"/admin/{identity}/create", data={}).status_code == 403
    assert logged_in.get(f"/admin/exchange-batch/edit/{batch.id}").status_code == 403
    assert logged_in.post(f"/admin/exchange-batch/edit/{batch.id}", data={"path": "x"}).status_code == 403
    assert logged_in.delete("/admin/exchange-batch/delete", params={"pks": str(batch.id)}).status_code == 403
    assert logged_in.post("/admin/exchange-batch/import").status_code in (403, 404, 405)

    page = logged_in.get("/admin/exchange-batch/list").text
    assert "/admin/exchange-batch/create" not in page
    assert db_session.scalar(select(func.count()).select_from(ExchangeBatch)) >= 1
    db_session.refresh(batch)
    assert batch.path == "/exchange/1c/prices"


def test_logout(logged_in: TestClient) -> None:
    assert logged_in.get("/admin/logout", follow_redirects=False).status_code == 302
    assert logged_in.get("/admin/", follow_redirects=False).status_code == 302


def test_admin_does_not_affect_api(admin_client: TestClient) -> None:
    assert admin_client.get("/api/health").status_code in (200, 503)
    response = admin_client.post("/exchange/1c/prices", content=b"{}")
    assert response.status_code == 401
    assert "error" in response.json()
