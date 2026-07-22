"""cases.counterparty — trục NHỚ theo-đối-tác của deal (agentic memory flywheel)

Case = system-of-record của deal → gắn tên đối tác (set lúc analyze từ NegotiationPosition). record_outcome
suy counterparty TỪ case_id → gắn episode outcome ĐÚNG đối tác + auto-trigger consolidation gộp được CẢ
outcome (trước đây outcome lưu counterparty='' → consolidation theo-đối-tác không thấy). Bao mọi đường ghi
outcome (Slack/web/API). Cột String index default '' (tương thích hàng cũ).

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("counterparty", sa.String(), nullable=False, server_default=""))
    op.create_index("ix_cases_counterparty", "cases", ["counterparty"])


def downgrade() -> None:
    op.drop_index("ix_cases_counterparty", table_name="cases")
    op.drop_column("cases", "counterparty")
