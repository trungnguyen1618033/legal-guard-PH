"""audit trail: vân tay văn bản gốc trên cases (SHA-256 + metadata, không lưu nội dung)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("source_sha256", sa.String(), server_default=""))
    op.add_column("cases", sa.Column("source_name", sa.String(), server_default=""))
    op.add_column("cases", sa.Column("source_bytes", sa.Integer(), server_default="0"))
    op.add_column("cases", sa.Column("text_chars", sa.Integer(), server_default="0"))
    op.create_index("ix_cases_source_sha256", "cases", ["source_sha256"])


def downgrade() -> None:
    op.drop_index("ix_cases_source_sha256", table_name="cases")
    op.drop_column("cases", "text_chars")
    op.drop_column("cases", "source_bytes")
    op.drop_column("cases", "source_name")
    op.drop_column("cases", "source_sha256")
