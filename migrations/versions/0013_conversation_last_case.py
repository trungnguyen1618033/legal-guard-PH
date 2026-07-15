"""conversations.last_case_id — case rà soát GẦN NHẤT của phiên

Cho phép xuất file (Word có comment / bản đối chiếu) theo LỆNH CHAT ("thêm comment vào file",
"xuất file"…) ở lượt sau: nhớ case_id rà soát gần nhất của phiên để dựng lại file từ dữ liệu case.
Cột String, default "".

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("last_case_id", sa.String(), nullable=False,
                                             server_default=""))


def downgrade() -> None:
    op.drop_column("conversations", "last_case_id")
