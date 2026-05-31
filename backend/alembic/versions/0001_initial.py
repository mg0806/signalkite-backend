"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kite_user_id", sa.String(length=64), nullable=False),
        sa.Column("access_token", sa.String(length=512), nullable=False),
        sa.Column("token_expiry", sa.DateTime(), nullable=True),
        sa.Column("fcm_token", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_kite_user_id"), "users", ["kite_user_id"], unique=True)

    op.create_table(
        "holdings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tradingsymbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("average_price", sa.Float(), nullable=False),
        sa.Column("last_price", sa.Float(), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "tradingsymbol", name="uq_user_holding_symbol"),
    )
    op.create_index(op.f("ix_holdings_tradingsymbol"), "holdings", ["tradingsymbol"], unique=False)
    op.create_index(op.f("ix_holdings_user_id"), "holdings", ["user_id"], unique=False)

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tradingsymbol", sa.String(length=32), nullable=False),
        sa.Column("signal_type", sa.String(length=8), nullable=False),
        sa.Column("confidence", sa.String(length=8), nullable=False),
        sa.Column("rsi", sa.Float(), nullable=True),
        sa.Column("macd_hist", sa.Float(), nullable=True),
        sa.Column("bb_position", sa.String(length=32), nullable=True),
        sa.Column("ema_cross", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_signals_computed_at"), "signals", ["computed_at"], unique=False)
    op.create_index(op.f("ix_signals_confidence"), "signals", ["confidence"], unique=False)
    op.create_index(op.f("ix_signals_signal_type"), "signals", ["signal_type"], unique=False)
    op.create_index(op.f("ix_signals_tradingsymbol"), "signals", ["tradingsymbol"], unique=False)
    op.create_index(op.f("ix_signals_user_id"), "signals", ["user_id"], unique=False)

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tradingsymbol", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=256), nullable=False),
        sa.Column("signal_type", sa.String(length=8), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alerts_tradingsymbol"), "alerts", ["tradingsymbol"], unique=False)
    op.create_index(op.f("ix_alerts_user_id"), "alerts", ["user_id"], unique=False)

    op.create_table(
        "ohlcv_cache",
        sa.Column("tradingsymbol", sa.String(length=32), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tradingsymbol", "date"),
        sa.UniqueConstraint("tradingsymbol", "date", name="uq_ohlcv_symbol_date"),
    )


def downgrade() -> None:
    op.drop_table("ohlcv_cache")
    op.drop_index(op.f("ix_alerts_user_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_tradingsymbol"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_index(op.f("ix_signals_user_id"), table_name="signals")
    op.drop_index(op.f("ix_signals_tradingsymbol"), table_name="signals")
    op.drop_index(op.f("ix_signals_signal_type"), table_name="signals")
    op.drop_index(op.f("ix_signals_confidence"), table_name="signals")
    op.drop_index(op.f("ix_signals_computed_at"), table_name="signals")
    op.drop_table("signals")
    op.drop_index(op.f("ix_holdings_user_id"), table_name="holdings")
    op.drop_index(op.f("ix_holdings_tradingsymbol"), table_name="holdings")
    op.drop_table("holdings")
    op.drop_index(op.f("ix_users_kite_user_id"), table_name="users")
    op.drop_table("users")
