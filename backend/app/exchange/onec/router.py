"""Роутер приёма данных из 1С (/exchange/1c, api_spec.md разд. 3).

Вход (Basic/Bearer) — зависимость на весь роутер; маршруты потоков — в catalog.py, prices.py, stock.py,
images.py, orders_status.py. setup_onec_exchange(app) подключает формат ошибок и журнал обмена.
"""

from fastapi import APIRouter, Depends, FastAPI

from app.exchange.onec import catalog, images, orders_status, prices, stock
from app.exchange.onec.auth import require_exchange_auth
from app.exchange.onec.errors import (
    EXCHANGE_PREFIX,
    ExchangeJSONResponse,
    register_exchange_error_handlers,
)
from app.exchange.onec.journal import ExchangeJournalMiddleware

router = APIRouter(
    prefix=EXCHANGE_PREFIX,
    tags=["Обмен с 1С"],
    dependencies=[Depends(require_exchange_auth)],
    # Ответы 200 потоков — тоже с charset=utf-8.
    default_response_class=ExchangeJSONResponse,
)
for _module in (catalog, prices, stock, images, orders_status):
    router.include_router(_module.router)


def setup_onec_exchange(app: FastAPI) -> None:
    """Обработчики ошибок обмена и middleware журнала (вызывается в create_app)."""
    register_exchange_error_handlers(app)
    app.add_middleware(ExchangeJournalMiddleware)
