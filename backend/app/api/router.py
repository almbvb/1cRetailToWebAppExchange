"""Корневой роутер API сайта (/api)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/api")


class HealthOut(BaseModel):
    status: str
    db: bool


@router.get("/health", response_model=HealthOut, tags=["Служебное"], summary="Проверка работоспособности")
def health(response: Response, db: Annotated[Session, Depends(get_db)]) -> HealthOut:
    """Приложение отвечает; db — доступна ли база (SELECT 1). Если база недоступна — HTTP 503."""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        db_ok = False
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(status="ok", db=db_ok)
