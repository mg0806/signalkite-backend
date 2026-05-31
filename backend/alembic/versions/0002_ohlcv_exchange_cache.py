"""add exchange to ohlcv cache

Revision ID: 0002_ohlcv_exchange_cache
Revises: 0001_initial
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ohlcv_exchange_cache"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ohlcv_cache") as batch_op:
        batch_op.add_column(sa.Column("exchange", sa.String(length=16), nullable=False, server_default="NSE"))
        batch_op.drop_constraint("uq_ohlcv_symbol_date", type_="unique")
        batch_op.create_unique_constraint("uq_ohlcv_symbol_exchange_date", ["tradingsymbol", "exchange", "date"])


def downgrade() -> None:
    with op.batch_alter_table("ohlcv_cache") as batch_op:
        batch_op.drop_constraint("uq_ohlcv_symbol_exchange_date", type_="unique")
        batch_op.create_unique_constraint("uq_ohlcv_symbol_date", ["tradingsymbol", "date"])
        batch_op.drop_column("exchange")
