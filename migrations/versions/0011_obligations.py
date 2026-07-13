"""bảng obligations (nghĩa vụ & hạn chót — giai đoạn SAU KÝ, autopilot nhắc hạn)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "obligations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("case_id", sa.String()),
        sa.Column("kind", sa.String(), server_default="other"),
        sa.Column("description", sa.String()),
        sa.Column("due_date", sa.String(), server_default=""),
        sa.Column("rule", sa.String(), server_default=""),
        sa.Column("party", sa.String(), server_default=""),
        sa.Column("consequence", sa.String(), server_default=""),
        sa.Column("source_clause", sa.String(), server_default=""),
        sa.Column("status", sa.String(), server_default="pending"),
        sa.Column("created_at", sa.String()),
    )
    op.create_index("idx_obligations_org", "obligations", ["org_id"])
    op.create_index("idx_obligations_case", "obligations", ["case_id"])
    op.create_index("idx_obligations_due", "obligations", ["due_date"])


def downgrade() -> None:
    op.drop_index("idx_obligations_due", table_name="obligations")
    op.drop_index("idx_obligations_case", table_name="obligations")
    op.drop_index("idx_obligations_org", table_name="obligations")
    op.drop_table("obligations")
