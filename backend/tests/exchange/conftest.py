"""Фикстуры тестов приёма из 1С (/exchange/1c) для С1-Т1…Т5.

- Настройки обмена подменяются тестовыми (autouse): логин/пароль/токен — константы из
  tests/exchange/__init__.py (`from tests.exchange import TEST_STORE_ID, ...`), а не из .env;
  ONEC_STORE_ID = TEST_STORE_ID; MEDIA_DIR — временная папка теста.
- `exchange_client` — клиент с верным Basic: .post_json("/catalog", body), .put_bytes(...), .delete(...),
  .request(...); путь — от /exchange/1c; auth=None — без входа. `.http` — сам TestClient.
- БД: обработчик получает ту же `db_session` (внешняя транзакция теста, commit -> savepoint, после теста
  откат). Исключение в обработчике откатывает его savepoint, как закрытие сессии в рабочем режиме.
  Данные для теста готовьте через db_session и `db_session.commit()` (иначе откат порции их тоже снимет).
  Проверка: `db_fetch(CatalogProduct, CatalogProduct.deleted.is_(False))` — свежие данные из БД.
- Журнал обмена пишется отдельной сессией (SessionLocal -> тестовая база) и ФИКСИРУЕТСЯ по-настоящему,
  как в рабочем режиме; поэтому exchange_batches очищается до и после каждого теста (autouse).
  `journal_rows()` — строки журнала, новые первыми (словари); `last_journal()` — последняя строка.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.exchange.onec.errors import EXCHANGE_PREFIX
from app.main import app
from app.models import ExchangeBatch
from tests.exchange import (
    TEST_BASIC,
    TEST_BASIC_PASSWORD,
    TEST_BASIC_USER,
    TEST_BEARER_TOKEN,
    TEST_STORE_ID,
)


@pytest.fixture(autouse=True)
def exchange_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    """Тестовые настройки обмена на объекте get_settings() (восстанавливаются после теста)."""
    monkeypatch.setattr(settings, "exchange_basic_user", TEST_BASIC_USER)
    monkeypatch.setattr(settings, "exchange_basic_password", SecretStr(TEST_BASIC_PASSWORD))
    monkeypatch.setattr(settings, "exchange_bearer_tokens", [SecretStr(TEST_BEARER_TOKEN)])
    monkeypatch.setattr(settings, "onec_store_id", str(TEST_STORE_ID))
    monkeypatch.setattr(settings, "media_dir", tmp_path / "media")
    return settings


def _clear_journal(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(delete(ExchangeBatch))


@pytest.fixture(autouse=True)
def _clean_exchange_journal(db_engine: Engine) -> Iterator[None]:
    _clear_journal(db_engine)
    yield
    _clear_journal(db_engine)


class ExchangeClient:
    """Клиент /exchange/1c; по умолчанию с верным Basic, auth=None — без заголовка входа."""

    def __init__(self, http: TestClient) -> None:
        self.http = http

    def request(
        self,
        method: str,
        path: str,
        *,
        content: Any = None,
        headers: dict[str, str] | None = None,
        auth: Any = TEST_BASIC,
    ) -> httpx.Response:
        return self.http.request(method, EXCHANGE_PREFIX + path, content=content, headers=headers, auth=auth)

    def post_json(
        self, path: str, body: Any, *, auth: Any = TEST_BASIC, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """body — dict/list (в JSON; Decimal, UUID, datetime -> строки) или готовые bytes/str."""
        if isinstance(body, bytes | str):
            content = body.encode("utf-8") if isinstance(body, str) else body
        else:
            content = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        all_headers = {"Content-Type": "application/json; charset=utf-8"} | (headers or {})
        return self.request("POST", path, content=content, headers=all_headers, auth=auth)

    def put_bytes(
        self, path: str, data: bytes, content_type: str = "image/jpeg", *, auth: Any = TEST_BASIC
    ) -> httpx.Response:
        return self.request("PUT", path, content=data, headers={"Content-Type": content_type}, auth=auth)

    def delete(self, path: str, *, auth: Any = TEST_BASIC) -> httpx.Response:
        return self.request("DELETE", path, auth=auth)


@pytest.fixture
def make_exchange_client(db_session: Session) -> Iterator[Callable[[FastAPI], ExchangeClient]]:
    """Фабрика клиента для любого приложения (например create_app() с тестовыми маршрутами)."""
    opened: list[tuple[FastAPI, TestClient]] = []

    def override_db() -> Iterator[Session]:
        try:
            yield db_session
        except Exception:
            db_session.rollback()  # откат savepoint порции, внешняя транзакция теста остаётся
            raise

    def make(target_app: FastAPI) -> ExchangeClient:
        target_app.dependency_overrides[get_db] = override_db
        http = TestClient(target_app)
        http.__enter__()
        opened.append((target_app, http))
        return ExchangeClient(http)

    yield make
    for target_app, http in opened:
        http.__exit__(None, None, None)
        target_app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def exchange_client(make_exchange_client: Callable[[FastAPI], ExchangeClient]) -> ExchangeClient:
    return make_exchange_client(app)


@pytest.fixture
def db_fetch(db_session: Session) -> Callable[..., list[Any]]:
    """db_fetch(Model, *условия, order_by=...) -> список объектов, прочитанных из БД заново."""

    def fetch(model: type, *where: Any, order_by: Any = None) -> list[Any]:
        db_session.expire_all()
        statement = select(model).where(*where)
        if order_by is not None:
            statement = statement.order_by(order_by)
        return list(db_session.scalars(statement))

    return fetch


@pytest.fixture
def journal_rows(db_engine: Engine) -> Callable[[int], list[dict[str, Any]]]:
    """journal_rows(limit=20) -> строки exchange_batches как словари, новые первыми."""

    def rows(limit: int = 20) -> list[dict[str, Any]]:
        table = ExchangeBatch.__table__
        with db_engine.connect() as connection:
            result = connection.execute(select(table).order_by(table.c.id.desc()).limit(limit))
            return [dict(row._mapping) for row in result]

    return rows


@pytest.fixture
def last_journal(journal_rows: Callable[[int], list[dict[str, Any]]]) -> Callable[[], dict[str, Any]]:
    def last() -> dict[str, Any]:
        found = journal_rows(1)
        assert found, "журнал обмена пуст"
        return found[0]

    return last
