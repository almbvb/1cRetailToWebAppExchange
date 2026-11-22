"""Админпанель SQLAdmin на /admin: журнал обмена с 1С и принятые данные, только чтение.

Вход — временный, одним администратором из настроек (app/admin/auth.py); пользователи и роли — этап С6.
"""

from fastapi import FastAPI
from sqladmin import Admin
from sqladmin.authentication import login_required
from sqladmin.i18n import BABEL_INSTALLED, I18nConfig
from starlette import status
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.admin.auth import AdminAuth
from app.admin.views import VIEWS, ExchangeBatchAdmin
from app.config import Settings
from app.db import SessionLocal

BASE_URL = "/admin"
TITLE = "Админпанель — доставка"


class DeliveryAdmin(Admin):
    @login_required
    async def index(self, request: Request) -> Response:
        """Главная страница — журнал обмена."""
        return RedirectResponse(
            request.url_for("admin:list", identity=ExchangeBatchAdmin.identity),
            status_code=status.HTTP_302_FOUND,
        )


def setup_admin(app: FastAPI, settings: Settings) -> Admin:
    """Монтирует админпанель в приложение; сессии БД — из общего SessionLocal."""
    # Русский интерфейс SQLAdmin требует пакета babel; без него — английские надписи самого SQLAdmin.
    i18n = (
        I18nConfig(default_locale="ru", language_cookie_name=None, language_header_name=None)
        if BABEL_INSTALLED
        else None
    )
    admin = DeliveryAdmin(
        app,
        session_maker=SessionLocal,
        base_url=BASE_URL,
        title=TITLE,
        authentication_backend=AdminAuth(settings, BASE_URL),
        i18n_config=i18n,
    )
    for view in VIEWS:
        admin.add_view(view)
    app.state.admin = admin
    return admin
