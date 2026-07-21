"""memory_episodes — bộ nhớ agent theo ĐỐI TÁC (agentic memory, anchor CockroachDB)

Tình tiết đã rà/nhượng/chốt với một counterparty → recall (semantic/lexical) inject vào prompt analyze/
negotiate. Cô lập org_id; cascade erasure theo case_id. `embedding` = JSON vector (nullable, offline→NULL).
Index (org_id, created_at) cho truy vấn nóng recall; index counterparty/case_id cho boost + erasure.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_episodes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("counterparty", sa.String(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(), nullable=False, server_default="note"),
        sa.Column("clause", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False, server_default=""),
        sa.Column("case_id", sa.String(), nullable=False, server_default=""),
        sa.Column("embedding", sa.Text(), nullable=True),
    )
    op.create_index("idx_mem_org_created", "memory_episodes", ["org_id", "created_at"])
    op.create_index("ix_memory_episodes_counterparty", "memory_episodes", ["counterparty"])
    op.create_index("ix_memory_episodes_case_id", "memory_episodes", ["case_id"])
    op.create_index("ix_memory_episodes_org_id", "memory_episodes", ["org_id"])
    op.create_index("ix_memory_episodes_created_at", "memory_episodes", ["created_at"])


def downgrade() -> None:
    op.drop_table("memory_episodes")
