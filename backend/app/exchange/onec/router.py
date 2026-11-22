"""Роутер приёма данных из 1С (/exchange/1c).

Маршруты по api_spec.md, разд. 3, добавляются на этапе С1; сейчас роутер пустой.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/exchange/1c", tags=["Обмен с 1С"])
