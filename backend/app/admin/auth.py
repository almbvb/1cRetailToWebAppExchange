"""Временный вход в админпанель одним администратором из настроек (до этапа С6: пользователи и роли).

Логин и пароль — ADMIN_USERNAME / ADMIN_PASSWORD; если хотя бы один не задан, войти нельзя никому.
Сессия — подписанная SECRET_KEY cookie (Starlette SessionMiddleware), живёт SESSION_MAX_AGE секунд.
Неуспешные попытки пишутся в лог (логин и адрес клиента, без пароля); блокировки подбора нет.
"""

import logging
import secrets

from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.config import Settings

logger = logging.getLogger(__name__)

SESSION_COOKIE = "admin_session"
SESSION_MAX_AGE = 8 * 60 * 60
# Ключ сессии с логином вошедшего администратора (его же читает get_user_id в SQLAdmin).
SESSION_USER_KEY = "user_id"


def _same(given: str, expected: str) -> bool:
    # compare_digest для str принимает только ASCII, поэтому сравниваем байты UTF-8.
    return secrets.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


class AdminAuth(AuthenticationBackend):
    def __init__(self, settings: Settings, base_url: str) -> None:
        super().__init__(
            secret_key=settings.secret_key.get_secret_value(),
            session_cookie=SESSION_COOKIE,
            max_age=SESSION_MAX_AGE,
            path=base_url,
            same_site="lax",
            # В prod админка открывается только по HTTPS: cookie без HTTPS не отправляется.
            https_only=settings.app_env == "prod",
        )
        self._settings = settings
        if self._credentials() is None:
            logger.warning("Админпанель: ADMIN_USERNAME или ADMIN_PASSWORD не заданы, вход невозможен")

    def _credentials(self) -> tuple[str, str] | None:
        username = self._settings.admin_username
        password = self._settings.admin_password
        if not username or password is None or not password.get_secret_value():
            return None
        return username, password.get_secret_value()

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        client = request.client.host if request.client else "-"

        credentials = self._credentials()
        if credentials is None:
            logger.warning(
                "Админпанель: попытка входа (логин %r, адрес %s), но вход не настроен", username, client
            )
            return False

        # Сравниваем и логин, и пароль всегда, без раннего выхода.
        user_ok = _same(username, credentials[0])
        password_ok = _same(password, credentials[1])
        if not (user_ok and password_ok):
            logger.warning("Админпанель: неуспешный вход (логин %r, адрес %s)", username, client)
            return False

        request.session.clear()
        request.session[SESSION_USER_KEY] = credentials[0]
        logger.info("Админпанель: вход администратора %r (адрес %s)", credentials[0], client)
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        credentials = self._credentials()
        user = request.session.get(SESSION_USER_KEY)
        if credentials is None or not isinstance(user, str):
            return False
        return _same(user, credentials[0])
