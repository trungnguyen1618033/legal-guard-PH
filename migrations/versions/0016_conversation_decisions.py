"""conversations.decisions — nhật ký quyết định (đồng ý/sửa) để TỔNG HỢP khi Chốt

Mỗi lần bấm 'Đồng ý sửa' / trả lời 'Sửa lại' → ghi {clause, action, text} vào đây (JSON). Khi 'Chốt' →
dựng BẢN TỔNG HỢP: đã đồng ý · đã sửa · chưa xử lý. Cột String (JSON), default "".

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("decisions", sa.String(), nullable=False,
                                             server_default=""))


def downgrade() -> None:
    op.drop_column("conversations", "decisions")
