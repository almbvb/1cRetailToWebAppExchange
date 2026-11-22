"""Окружение Alembic: адрес базы берётся из app.config.Settings, а не из alembic.ini.

По умолчанию — DATABASE_URL; с ключом `-x db=test` — TEST_DATABASE_URL.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401 — регистрирует модели в Base.metadata
from app.config import get_settings
from app.db import Base

config = context.config

# При вызове из кода (тесты) логирование не перенастраиваем: attributes["configure_logger"] = False.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    settings = get_settings()
    if context.get_x_argument(as_dictionary=True).get("db") == "test":
        if settings.test_database_url is None:
            raise RuntimeError("TEST_DATABASE_URL не задан")
        return settings.test_database_url.get_secret_value()
    return settings.database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к базе (alembic upgrade head --sql)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
