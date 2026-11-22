"""numeric без разрядности, catalog_products.unit_id nullable (К-5)

Переполнение numeric(12,2)/(14,3) давало 500 и бесконечный повтор порции 1С; теперь числа хранятся
как пришли (numeric), округление — дело витрины. unit_id: у позиции-услуги в 1С единицы нет.
ALTER TYPE сохраняет данные (numeric(p,s) -> numeric без потерь).

Revision ID: 5c7e1a9d3f20
Revises: 2122785be2c9
Create Date: 2026-11-22 22:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5c7e1a9d3f20"
down_revision: Union[str, Sequence[str], None] = "2122785be2c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (таблица, колонка, прежний тип)
_COLUMNS = [
    ("catalog_prices", "price", sa.Numeric(12, 2)),
    ("catalog_stock", "available", sa.Numeric(14, 3)),
    ("orders", "total", sa.Numeric(12, 2)),
    ("order_onec_items", "quantity", sa.Numeric(14, 3)),
    ("order_onec_items", "price", sa.Numeric(12, 2)),
    ("order_onec_items", "amount", sa.Numeric(12, 2)),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, old_type in _COLUMNS:
        op.alter_column(table, column, existing_type=old_type, type_=sa.Numeric(), existing_nullable=False)
    op.alter_column("catalog_products", "unit_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    """Downgrade schema.

    Обратно возможно не всегда: строки с unit_id null или значения вне прежней разрядности
    не дадут выполнить откат (PostgreSQL сообщит ошибку) — их нужно исправить вручную.
    """
    op.alter_column("catalog_products", "unit_id", existing_type=sa.Uuid(), nullable=False)
    for table, column, old_type in _COLUMNS:
        op.alter_column(table, column, existing_type=sa.Numeric(), type_=old_type, existing_nullable=False)
