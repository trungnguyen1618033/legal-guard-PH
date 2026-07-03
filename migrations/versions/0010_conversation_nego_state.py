"""conversations.nego_state — sổ nhượng-bộ đàm phán (JSON string) mang qua các vòng

Bộ nhớ CÓ CẤU TRÚC của thế trận (red_lines/secured/conceded/open_items) — chống agent 'quên' đã
nhượng/chốt gì khi context free-text bị cắt cụt. Cột String (JSON portable), default "".

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("nego_state", sa.String(), nullable=False,
                                             server_default=""))


def downgrade() -> None:
    op.drop_column("conversations", "nego_state")
