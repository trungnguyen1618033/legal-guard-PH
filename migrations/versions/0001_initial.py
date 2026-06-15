"""initial — bảng cases

Revision ID: 0001
Revises:
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("lang", sa.String()),
        sa.Column("contract_excerpt", sa.String()),
        sa.Column("summary", sa.String()),
        sa.Column("needs_human_review", sa.Boolean()),
        sa.Column("risks", sa.JSON()),
        sa.Column("fallbacks", sa.JSON()),
        sa.Column("trace", sa.JSON()),
    )
    op.create_index("idx_cases_tenant", "cases", ["tenant", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_cases_tenant", table_name="cases")
    op.drop_table("cases")
