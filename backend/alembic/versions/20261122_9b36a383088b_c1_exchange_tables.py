"""С1: таблицы приёма данных из 1С (каталог, цены, остатки, картинки, заказы, журнал обмена).

Внешних ключей между таблицами нет: потоки 1С независимы (docs/c1_exchange.md).

Revision ID: 9b36a383088b
Revises:
Create Date: 2026-11-22 19:22:13.396639
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9b36a383088b"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_groups")),
    )
    op.create_table(
        "catalog_images",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("original_path", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("product_id", name=op.f("pk_catalog_images")),
    )
    op.create_table(
        "catalog_prices",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("store_id", "product_id", name=op.f("pk_catalog_prices")),
    )
    op.create_index(op.f("ix_catalog_prices_product_id"), "catalog_prices", ["product_id"], unique=False)
    op.create_table(
        "catalog_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("article", sa.Text(), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("weighted", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_products")),
    )
    op.create_index(op.f("ix_catalog_products_deleted"), "catalog_products", ["deleted"], unique=False)
    op.create_index(op.f("ix_catalog_products_group_id"), "catalog_products", ["group_id"], unique=False)
    op.create_table(
        "catalog_stock",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("available", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("store_id", "product_id", name=op.f("pk_catalog_stock")),
    )
    op.create_index(op.f("ix_catalog_stock_product_id"), "catalog_stock", ["product_id"], unique=False)
    op.create_table(
        "catalog_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_units")),
    )
    op.create_table(
        "exchange_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("stream", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("full", sa.Boolean(), nullable=True),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("body_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exchange_batches")),
    )
    op.create_index(
        op.f("ix_exchange_batches_received_at"), "exchange_batches", ["received_at"], unique=False
    )
    op.create_table(
        "order_onec_items",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("order_id", "line_no", name=op.f("pk_order_onec_items")),
    )
    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("onec_number", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("onec_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("onec_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_orders")),
    )


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("order_onec_items")
    op.drop_index(op.f("ix_exchange_batches_received_at"), table_name="exchange_batches")
    op.drop_table("exchange_batches")
    op.drop_table("catalog_units")
    op.drop_index(op.f("ix_catalog_stock_product_id"), table_name="catalog_stock")
    op.drop_table("catalog_stock")
    op.drop_index(op.f("ix_catalog_products_group_id"), table_name="catalog_products")
    op.drop_index(op.f("ix_catalog_products_deleted"), table_name="catalog_products")
    op.drop_table("catalog_products")
    op.drop_index(op.f("ix_catalog_prices_product_id"), table_name="catalog_prices")
    op.drop_table("catalog_prices")
    op.drop_table("catalog_images")
    op.drop_table("catalog_groups")
