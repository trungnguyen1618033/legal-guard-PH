"""bảng kb_vectors — embedding bền (corpus lớn không re-embed mỗi boot)

id = sha256(text) → khử trùng + phát hiện chunk đổi. vector = JSON list[float] (portable SQLite/Postgres).
Quy mô RẤT lớn: nâng cột sang pgvector `Vector(dim)` + index ivfflat/hnsw, query ORDER BY emb <=> q.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kb_vectors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("vector", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("kb_vectors")
