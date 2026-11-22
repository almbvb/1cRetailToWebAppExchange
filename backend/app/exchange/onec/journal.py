"""Журнал обмена: строка в exchange_batches на КАЖДЫЙ запрос к /exchange/1c (401, 400, 404, 413, 500 — тоже).

ExchangeJournalMiddleware (чистый ASGI) оборачивает запросы к /exchange/1c:
- до обработки создаёт ExchangeJournal (метод, путь, поток по пути, вход без секрета) и кладёт его в
  scope["state"]; обработчик потока получает его зависимостью `journal: Journal` и выставляет full и counts
  (common.ok_response и common.json_body делают это сами);
- обработчики ошибок (errors.py) записывают туда код и текст ошибки;
- непредвиденное исключение -> лог с трассировкой и ответ 500 INTERNAL_ERROR без текста исключения;
- после отправки ответа пишет строку журнала в ОТДЕЛЬНОЙ сессии и транзакции (journal_session_factory),
  поэтому запись остаётся, даже если порция откатилась. Сбой записи журнала только логируется.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

import anyio.to_thread
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import db
from app.exchange.onec.auth import describe_authorization
from app.exchange.onec.errors import (
    EXCHANGE_PREFIX,
    INTERNAL_ERROR,
    error_response,
    is_exchange_path,
    summarize_error,
)
from app.models import ExchangeBatch

logger = logging.getLogger(__name__)

STATE_KEY = "onec_exchange_journal"

# Первый сегмент пути после /exchange/1c -> поток журнала.
_STREAMS = {
    "catalog": "catalog",
    "prices": "prices",
    "stock": "stock",
    "images": "images",
    "orders": "orders_status",
}


def stream_from_path(path: str) -> str | None:
    rest = path[len(EXCHANGE_PREFIX) :].strip("/")
    return _STREAMS.get(rest.split("/", 1)[0]) if rest else None


@dataclass
class ExchangeJournal:
    """Данные строки журнала текущего запроса. Обработчик потока меняет full и counts."""

    method: str
    path: str
    auth: str
    stream: str | None = None
    full: bool | None = None
    counts: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def set_error(self, code: str, message: str, details: list[Any] | None = None) -> None:
        self.error_code = code
        self.error_message = summarize_error(message, list(details or []))


def find_journal(scope: Scope) -> ExchangeJournal | None:
    state = scope.get("state")
    return state.get(STATE_KEY) if isinstance(state, dict) else None


def get_journal(request: Request) -> ExchangeJournal:
    """Зависимость FastAPI: журнал текущего запроса (без middleware — пустой, никуда не пишется)."""
    entry = find_journal(request.scope)
    if entry is None:
        entry = ExchangeJournal(method=request.method, path=request.url.path, auth="none")
        request.scope.setdefault("state", {})[STATE_KEY] = entry
    return entry


Journal = Annotated[ExchangeJournal, Depends(get_journal)]


def journal_session_factory() -> Session:
    """Отдельная сессия журнала. SessionLocal берётся при вызове: в тестах он привязан к тестовой базе."""
    return db.SessionLocal()


def write_journal(entry: ExchangeJournal, status_code: int, body_bytes: int, duration_ms: int) -> None:
    """Пишет строку журнала в своей транзакции; ошибка записи логируется и не пробрасывается."""
    try:
        with journal_session_factory() as session:
            session.add(
                ExchangeBatch(
                    received_at=entry.received_at,
                    method=entry.method,
                    path=entry.path,
                    stream=entry.stream,
                    status_code=status_code,
                    auth=entry.auth,
                    full=entry.full,
                    counts=entry.counts,
                    error_code=entry.error_code,
                    error_message=entry.error_message,
                    body_bytes=body_bytes,
                    duration_ms=duration_ms,
                )
            )
            session.commit()
    except Exception:
        logger.exception("Сбой записи журнала обмена: %s %s -> %s", entry.method, entry.path, status_code)


class ExchangeJournalMiddleware:
    """ASGI-middleware журнала и 500 INTERNAL_ERROR для /exchange/1c; остальные пути проходят как есть."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_exchange_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        headers = Headers(scope=scope)
        entry = ExchangeJournal(
            method=scope["method"],
            path=scope["path"],
            auth=describe_authorization(headers.get("authorization")),
            stream=stream_from_path(scope["path"]),
        )
        scope.setdefault("state", {})[STATE_KEY] = entry

        received = 0
        status_code: int | None = None

        async def receive_counting() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
            return message

        async def send_tracking(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        error: Exception | None = None
        try:
            await self.app(scope, receive_counting, send_tracking)
        except Exception as exc:
            logger.exception("Ошибка обработки запроса обмена %s %s", scope["method"], scope["path"])
            # Текст исключения наружу и в журнал не идёт (может содержать данные); только тип — в журнал.
            entry.set_error(INTERNAL_ERROR, f"Внутренняя ошибка ({type(exc).__name__})")
            if status_code is None:
                response = error_response(500, INTERNAL_ERROR, "Внутренняя ошибка сервера")
                await response(scope, receive, send_tracking)
            else:
                error = exc  # ответ уже начат — заменить нельзя
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            declared = _content_length(headers)
            body_bytes = max(received, declared or 0)
            await anyio.to_thread.run_sync(write_journal, entry, status_code or 500, body_bytes, duration_ms)
        if error is not None:
            raise error


def _content_length(headers: Headers) -> int | None:
    try:
        value = int(headers["content-length"])
    except KeyError, ValueError:
        return None
    return value if 0 <= value < 2**62 else None
