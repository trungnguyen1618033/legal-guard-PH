"""cases.drafting_issues — lỗi soạn thảo CÓ CẤU TRÚC (đưa vào file .docx có comment)

Cho phép file Word có comment (và các export khác) gồm CẢ lỗi soạn thảo / khác biệt Việt–Anh
({location, issue, fix_vi, fix_en}), không chỉ rủi ro pháp lý. Cột JSON, default [].

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("drafting_issues", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "drafting_issues")
