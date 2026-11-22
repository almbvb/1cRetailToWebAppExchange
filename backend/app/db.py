"""Подключение к PostgreSQL: декларативная база моделей, engine, фабрика сессий и зависимость FastAPI."""

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Единые имена ограничений и индексов: Alembic генерирует предсказуемые миграции.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def make_engine(url: str) -> Engine:
    """Engine с проверкой соединения перед выдачей из пула и ограниченным временем подключения."""
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


# Соединение не открывается при импорте: create_engine ленивый.
engine = make_engine(get_settings().database_url.get_secret_value())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Зависимость FastAPI: сессия на время запроса, закрывается после ответа."""
    with SessionLocal() as session:
        yield session
