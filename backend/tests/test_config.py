import pytest
from pydantic import ValidationError

from app.config import REPO_ROOT, Settings

REQUIRED = {"secret_key": "x" * 32, "database_url": "postgresql+psycopg://u:p@127.0.0.1:5433/db"}


def make_settings(**overrides) -> Settings:
    # _env_file=None: не читать .env, проверяем только значения по умолчанию и разбор.
    return Settings(_env_file=None, **(REQUIRED | overrides))


def test_defaults() -> None:
    settings = make_settings()
    assert settings.app_port == 8090
    assert settings.timezone == "Europe/Moscow"
    assert settings.frontend_origin == "http://localhost:3000"
    assert settings.image_max_bytes == 4_194_304
    assert settings.image_max_megapixels == 40
    assert settings.onec_api_timeout == 30
    assert settings.order_number_prefix == "D-"
    assert settings.mail_mode == "console"
    assert settings.media_dir == (REPO_ROOT / "var" / "media").resolve()
    assert settings.exchange_bearer_tokens == []


def test_bearer_tokens_split_by_comma() -> None:
    settings = make_settings(exchange_bearer_tokens=" a, b,,c ")
    assert [token.get_secret_value() for token in settings.exchange_bearer_tokens] == ["a", "b", "c"]


def test_short_secret_key_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(secret_key="short")
