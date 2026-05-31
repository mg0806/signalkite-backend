"""security fields and market scan jobs

Revision ID: 0003_security_and_scan_jobs
Revises: 0002_ohlcv_exchange_cache
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_security_and_scan_jobs"
down_revision: str | None = "0002_ohlcv_exchange_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "market_scan_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("limit_per_category", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_market_scan_jobs_created_at"), "market_scan_jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_market_scan_jobs_status"), "market_scan_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_market_scan_jobs_status"), table_name="market_scan_jobs")
    op.drop_index(op.f("ix_market_scan_jobs_created_at"), table_name="market_scan_jobs")
    op.drop_table("market_scan_jobs")
    op.drop_column("users", "token_version")
