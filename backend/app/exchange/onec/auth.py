"""Вход 1С на /exchange/1c (api_spec.md, разд. 3): HTTP Basic или Bearer.

Basic — EXCHANGE_BASIC_USER / EXCHANGE_BASIC_PASSWORD; Bearer — любой из EXCHANGE_BEARER_TOKENS.
Сравнение — secrets.compare_digest. Без верных данных — 401 UNAUTHORIZED и WWW-Authenticate: Basic.
Пароль и токен никуда не пишутся: describe_authorization() отдаёт только схему и логин.
"""

import base64
import binascii
import secrets

from fastapi import Request

from app.config import Settings, get_settings
from app.exchange.onec.errors import UNAUTHORIZED, ExchangeError

WWW_AUTHENTICATE = 'Basic realm="exchange"'
_MAX_DESCRIPTION = 200


def _split_header(header: str | None) -> tuple[str, str]:
    scheme, _, value = (header or "").strip().partition(" ")
    return scheme.lower(), value.strip()


def _decode_basic(value: str) -> tuple[str, str] | None:
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except binascii.Error, ValueError, UnicodeDecodeError:
        return None
    user, sep, password = decoded.partition(":")
    return (user, password) if sep else None


def describe_authorization(header: str | None) -> str:
    """Описание входа для журнала, без секрета: 'none', 'Basic user=<логин>', 'Bearer', '<схема>'."""
    scheme, value = _split_header(header)
    if not scheme:
        return "none"
    if scheme == "basic":
        credentials = _decode_basic(value)
        user = credentials[0] if credentials else "?"
        return f"Basic user={user}"[:_MAX_DESCRIPTION]
    if scheme == "bearer":
        return "Bearer"
    return scheme[:20]


def _equal(given: str, expected: str) -> bool:
    # compare_digest для str принимает только ASCII, поэтому сравниваем байты UTF-8.
    return secrets.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def check_authorization(header: str | None, settings: Settings) -> str | None:
    """Описание входа, если данные верны, иначе None."""
    scheme, value = _split_header(header)
    if scheme == "basic":
        credentials = _decode_basic(value)
        expected_user = settings.exchange_basic_user
        expected_password = settings.exchange_basic_password
        if credentials is None or not expected_user or expected_password is None:
            return None
        password_secret = expected_password.get_secret_value()
        if not password_secret:
            return None
        # Оба сравнения выполняются всегда (без раннего выхода по логину).
        user_ok = _equal(credentials[0], expected_user)
        password_ok = _equal(credentials[1], password_secret)
        return describe_authorization(header) if user_ok and password_ok else None
    if scheme == "bearer" and value:
        matched = False
        for token in settings.exchange_bearer_tokens:
            secret = token.get_secret_value()
            if secret and _equal(value, secret):
                matched = True
        return "Bearer" if matched else None
    return None


def require_exchange_auth(request: Request) -> str:
    """Зависимость FastAPI на весь роутер обмена. Возвращает описание входа ('Basic user=…' или 'Bearer')."""
    description = check_authorization(request.headers.get("authorization"), get_settings())
    if description is None:
        raise ExchangeError(
            401, UNAUTHORIZED, "Требуется вход", headers={"WWW-Authenticate": WWW_AUTHENTICATE}
        )
    return description
