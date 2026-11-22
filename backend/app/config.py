"""Настройки приложения из переменных окружения и файла .env в корне репозитория.

Список ключей и значения по умолчанию описаны в .env.example. Переменные окружения процесса
имеют приоритет над .env. Пустое значение в .env считается «не задано» (берётся значение по умолчанию).
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/config.py -> корень репозитория (на два уровня выше папки app).
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    # --- Приложение ---
    app_env: Literal["dev", "prod"] = "dev"
    app_port: int = 8090
    # Подпись сессий и кодов входа; длина не короче 32 символов.
    secret_key: SecretStr
    timezone: str = "Europe/Moscow"
    frontend_origin: str = "http://localhost:3000"

    # --- База данных PostgreSQL (адрес содержит пароль, поэтому SecretStr) ---
    database_url: SecretStr
    # Отдельная база для pytest; основная база в тестах не используется.
    test_database_url: SecretStr | None = None

    # --- Приём данных из 1С (api_spec.md, разд. 3) ---
    exchange_basic_user: str | None = None
    exchange_basic_password: SecretStr | None = None
    # В .env — строка токенов через запятую.
    exchange_bearer_tokens: Annotated[list[SecretStr], NoDecode] = Field(default_factory=list)
    image_max_bytes: int = 4_194_304
    image_max_megapixels: int = 40

    # --- API 1С, который вызывает сайт (api_spec.md, разд. 2) ---
    onec_api_base_url: str | None = None
    onec_api_user: str | None = None
    onec_api_password: SecretStr | None = None
    onec_store_id: str | None = None
    onec_api_timeout: float = 30

    # --- Заказы ---
    order_number_prefix: str = "D-"

    # --- Почта (коды входа) ---
    mail_mode: Literal["console", "smtp"] = "console"
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None

    # --- Файлы ---
    # Относительный путь считается от корня репозитория.
    media_dir: Path = Path("var/media")

    @field_validator("secret_key")
    @classmethod
    def _check_secret_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("SECRET_KEY должен быть не короче 32 символов")
        return value

    @field_validator("exchange_bearer_tokens", mode="before")
    @classmethod
    def _split_tokens(cls, value: object) -> object:
        if isinstance(value, str):
            return [token.strip() for token in value.split(",") if token.strip()]
        return value

    @field_validator("media_dir")
    @classmethod
    def _resolve_media_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()


@lru_cache
def get_settings() -> Settings:
    """Настройки процесса (читаются один раз). В тестах кэш сбрасывается через get_settings.cache_clear()."""
    return Settings()
