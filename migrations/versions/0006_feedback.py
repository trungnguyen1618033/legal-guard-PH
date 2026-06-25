"""bảng feedback (phản hồi người dùng — vòng học golden set)

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("kind", sa.String()),
        sa.Column("ref", sa.String()),
        sa.Column("rating", sa.String()),
        sa.Column("note", sa.String()),
        sa.Column("created_at", sa.String()),
    )
    op.create_index("idx_feedback_org", "feedback", ["org_id"])
    op.create_index("idx_feedback_rating", "feedback", ["rating"])


def downgrade() -> None:
    op.drop_index("idx_feedback_rating", table_name="feedback")
    op.drop_index("idx_feedback_org", table_name="feedback")
    op.drop_table("feedback")
