"""memory_episodes: bi-temporal (valid_to + superseded_by) — invalidate-not-delete

Vị thế đối tác đổi qua deal → tình tiết cũ bị SUPERSEDE: set valid_to (thời điểm hết đúng) + superseded_by
(id tình tiết mới), GIỮ lại (provenance/point-in-time), KHÔNG xóa. Recall mặc định chỉ trả valid_to='' (HIỆN
TẠI). Cột String default '' (tương thích hàng cũ = đang-hiện-tại).

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IDEMPOTENT: SqlMemory.__init__ self-heal (ALTER ADD COLUMN IF NOT EXISTS valid_to/superseded_by) có thể
    # đã thêm 2 cột này lúc APP BOOT trên cluster còn ở 0017 → op.add_column TRẦN sẽ 'DuplicateColumn' → chain
    # KẸT ở 0017 (không lên được 0019/0020 = cases/conversations.counterparty). Kiểm cột tồn tại trước khi thêm
    # (inspector portable sqlite/postgres/CRDB) → chạy được dù app đã self-heal.
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("memory_episodes")}
    if "valid_to" not in existing:
        op.add_column("memory_episodes", sa.Column("valid_to", sa.String(), nullable=False, server_default=""))
    if "superseded_by" not in existing:
        op.add_column("memory_episodes",
                      sa.Column("superseded_by", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("memory_episodes", "superseded_by")
    op.drop_column("memory_episodes", "valid_to")
