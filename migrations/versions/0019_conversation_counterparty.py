"""conversations.counterparty — trục NHỚ theo-đối-tác của phiên chat (agentic memory)

Ghi tên đối tác của deal đang bàn (nêu 1 lần ở caption/tin → nhớ qua các lượt) → rà HĐ mới + đàm phán
trong phiên gắn ĐÚNG counterparty → recall bộ nhớ theo-đối-tác (mục 'Về đối tác này'). Trước đây field
`Conversation.counterparty` có trong model nhưng KHÔNG được persist (SQL store bỏ sót) → axis nhớ chết ở
prod. Cột String default '' (tương thích hàng cũ = chưa gắn đối tác).

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("counterparty", sa.String(), nullable=False,
                                             server_default=""))


def downgrade() -> None:
    op.drop_column("conversations", "counterparty")
