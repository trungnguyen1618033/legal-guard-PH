"""bổ sung index khớp model (drift): cases.created_at, outcomes.case_id

Model (create_all, dùng dev/test) khai index trên cases.created_at + outcomes.case_id, nhưng các migration
trước KHÔNG tạo → prod (alembic) thiếu 2 index này. Migration này đồng bộ prod với model.
- cases.created_at: tăng tốc list_by_org (ORDER BY created_at DESC)
- outcomes.case_id: tăng tốc cascade-erasure (xóa outcomes theo case_id) + tra theo case

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_cases_created_at", "cases", ["created_at"])
    op.create_index("ix_outcomes_case_id", "outcomes", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_outcomes_case_id", table_name="outcomes")
    op.drop_index("ix_cases_created_at", table_name="cases")
