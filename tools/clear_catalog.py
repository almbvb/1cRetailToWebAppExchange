"""Очистка каталога сайта перед новой полной выгрузкой из 1С (api_spec.md 0.10, 3.1; К-19).

Удаляет единицы, группы, товары, цены, остатки, записи о картинках и файлы картинок
(MEDIA_DIR/products). Заказы и журнал обмена не трогает.

Запуск (из корня репозитория):
  backend\\.venv\\Scripts\\python.exe tools\\clear_catalog.py          — только показать, что будет удалено
  backend\\.venv\\Scripts\\python.exe tools\\clear_catalog.py --yes    — удалить

База и папка картинок — из .env (DATABASE_URL, MEDIA_DIR). Значения секретов не выводятся.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.services.images import PRODUCTS_DIR  # noqa: E402

TABLES = (
    "catalog_units",
    "catalog_groups",
    "catalog_products",
    "catalog_prices",
    "catalog_stock",
    "catalog_images",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Очистка каталога сайта перед полной выгрузкой из 1С")
    parser.add_argument("--yes", action="store_true", help="выполнить удаление (без опции — только показать)")
    args = parser.parse_args()

    products_dir = Path(get_settings().media_dir) / PRODUCTS_DIR
    print(f"База: {engine.url.database}")
    with engine.connect() as conn:
        for table in TABLES:
            count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            print(f"  {table}: {count}")
    folders = sum(1 for p in products_dir.iterdir() if p.is_dir()) if products_dir.is_dir() else 0
    print(f"Папок картинок в {products_dir}: {folders}")

    if not args.yes:
        print("Ничего не удалено. Для удаления запустите с --yes.")
        return 0

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)}"))
    if products_dir.is_dir():
        shutil.rmtree(products_dir)
    print("Каталог очищен: таблицы пусты, файлы картинок удалены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
