"""Ошибки приёма из 1С: всегда {"error": {"code", "message", "details": []}} (api_spec.md, разд. 1).

Внутри /exchange/1c в этот формат приводятся: ExchangeError, ошибки валидации FastAPI (400 INVALID_FORMAT),
404/405 маршрутизации. Непредвиденное исключение (500 INTERNAL_ERROR) обрабатывает журнал
(journal.ExchangeJournalMiddleware): он внешний по отношению к обработчикам исключений FastAPI.
Вне /exchange/1c поведение FastAPI не меняется.
"""

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

EXCHANGE_PREFIX = "/exchange/1c"

# Коды ошибок контракта и свои коды приложения.
INVALID_FORMAT = "INVALID_FORMAT"
UNAUTHORIZED = "UNAUTHORIZED"
NOT_FOUND = "NOT_FOUND"
METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
UNSUPPORTED_IMAGE = "UNSUPPORTED_IMAGE"
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
INTERNAL_ERROR = "INTERNAL_ERROR"

# Сколько записей details отдавать в ответе (неверная порция из 500 записей не должна давать огромный ответ).
MAX_DETAILS = 50

_HTTP_CODES = {
    400: (INVALID_FORMAT, "Неверный запрос"),
    401: (UNAUTHORIZED, "Требуется вход"),
    404: (NOT_FOUND, "Адрес не найден"),
    405: (METHOD_NOT_ALLOWED, "Метод не поддерживается"),
    413: (PAYLOAD_TOO_LARGE, "Тело запроса слишком большое"),
}

# Части loc ошибок FastAPI, которые не нужны в пути поля.
_LOC_SOURCES = {"body", "path", "query", "header", "cookie"}


class ExchangeJSONResponse(JSONResponse):
    """JSON-ответ обмена с явной кодировкой (api_spec.md, разд. 1: application/json; charset=utf-8)."""

    media_type = "application/json; charset=utf-8"


class ExchangeError(Exception):
    """Ошибка приёма порции: обработчик отдаёт её в формате контракта, порция откатывается.

    raise ExchangeError(400, "INVALID_FORMAT", "Ошибка", [{"field": "products[3].id", "message": ""}])
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = list(details or [])
        self.headers = headers


def is_exchange_path(path: str) -> bool:
    return path == EXCHANGE_PREFIX or path.startswith(EXCHANGE_PREFIX + "/")


def error_body(code: str, message: str, details: list[Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": list(details or [])[:MAX_DETAILS]}}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> ExchangeJSONResponse:
    return ExchangeJSONResponse(error_body(code, message, details), status_code=status_code, headers=headers)


def field_path(loc: tuple[Any, ...] | list[Any]) -> str:
    """('products', 3, 'id') -> 'products[3].id'; пустой путь — 'body' (всё тело)."""
    parts = list(loc)
    if parts and parts[0] in _LOC_SOURCES and len(parts) > 1:
        parts = parts[1:]
    elif parts and parts[0] in _LOC_SOURCES:
        parts = []
    result = ""
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}" if result else str(part)
    return result or "body"


def validation_details(errors: list[dict[str, Any]] | Any) -> list[dict[str, str]]:
    """Ошибки pydantic/FastAPI -> [{"field": "products[3].id", "message": "…"}]."""
    return [
        {"field": field_path(error.get("loc", ())), "message": str(error.get("msg", ""))} for error in errors
    ]


def _remember_error(request: Request, code: str, message: str, details: list[Any]) -> None:
    # Импорт здесь: journal импортирует errors.
    from app.exchange.onec.journal import find_journal

    entry = find_journal(request.scope)
    if entry is not None:
        entry.set_error(code, message, details)


async def _exchange_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ExchangeError)
    _remember_error(request, exc.code, exc.message, exc.details)
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    if not is_exchange_path(request.url.path):
        return await request_validation_exception_handler(request, exc)
    details = validation_details(exc.errors())
    message = "Неверный формат запроса"
    _remember_error(request, INVALID_FORMAT, message, details)
    return error_response(400, INVALID_FORMAT, message, details)


async def _http_error_handler(request: Request, exc: Exception) -> Any:
    assert isinstance(exc, StarletteHTTPException)
    if not is_exchange_path(request.url.path):
        return await http_exception_handler(request, exc)
    code, message = _HTTP_CODES.get(exc.status_code, (f"HTTP_{exc.status_code}", "Ошибка запроса"))
    _remember_error(request, code, message, [])
    return error_response(exc.status_code, code, message, [], exc.headers)


def register_exchange_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ExchangeError, _exchange_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)


def summarize_error(message: str, details: list[Any], limit: int = 2000) -> str:
    """Текст ошибки для журнала: сообщение и первые details (без тела порции)."""
    text = message
    if details:
        text += " " + json.dumps(details[:10], ensure_ascii=False, default=str)
    return text[:limit]
