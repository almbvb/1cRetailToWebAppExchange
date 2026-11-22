"""Общие фикстуры: приложение работает с тестовой базой TEST_DATABASE_URL, а не с основной.

Схема тестовой базы приводится к head миграциями Alembic один раз за запуск.
Каждый тест идёт в своей транзакции, которая откатывается после теста.
"""

from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import SessionLocal, get_db, make_engine
from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def db_engine(settings: Settings) -> Iterator[Engine]:
    if settings.test_database_url is None:
        pytest.exit("TEST_DATABASE_URL не задан: тесты не запускаются на основной базе", returncode=2)
    test_url = settings.test_database_url.get_secret_value()
    if test_url == settings.database_url.get_secret_value():
        pytest.exit("TEST_DATABASE_URL совпадает с DATABASE_URL", returncode=2)

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.cmd_opts = Namespace(x=["db=test"])
    alembic_cfg.attributes["configure_logger"] = False
    command.upgrade(alembic_cfg, "head")

    engine = make_engine(test_url)
    # Код, создающий сессии напрямую через SessionLocal, тоже попадёт в тестовую базу.
    previous_bind = SessionLocal.kw.get("bind")
    SessionLocal.configure(bind=engine)
    yield engine
    SessionLocal.configure(bind=previous_bind)
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Сессия внутри внешней транзакции; commit в коде приложения превращается в savepoint."""
    with db_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
