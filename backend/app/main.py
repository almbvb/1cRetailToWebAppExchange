"""Точка входа FastAPI: uvicorn app.main:app."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router as api_router
from app.config import Settings, get_settings
from app.exchange.onec.router import router as onec_exchange_router
from app.exchange.onec.router import setup_onec_exchange


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Сайт доставки — backend", version="0.1.0")

    # CORS нужен фронтенду в разработке (отдельный dev-сервер на FRONTEND_ORIGIN).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    app.include_router(onec_exchange_router)
    # Формат ошибок {"error": ...} и журнал обмена для /exchange/1c.
    setup_onec_exchange(app)
    return app


app = create_app()
