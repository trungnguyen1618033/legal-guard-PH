"""bảng outcomes (flywheel kết quả đàm phán)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outcomes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("clause", sa.String(), nullable=False),
        sa.Column("tactic", sa.String()),
        sa.Column("result", sa.String()),
        sa.Column("created_at", sa.String()),
    )
    op.create_index("idx_outcomes_org", "outcomes", ["org_id"])
    op.create_index("idx_outcomes_clause", "outcomes", ["clause"])


def downgrade() -> None:
    op.drop_index("idx_outcomes_clause", table_name="outcomes")
    op.drop_index("idx_outcomes_org", table_name="outcomes")
    op.drop_table("outcomes")
