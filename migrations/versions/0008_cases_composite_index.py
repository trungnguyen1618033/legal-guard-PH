"""composite index cases(org_id, created_at) — tối ưu list_by_org

Truy vấn nóng nhất: list_by_org = WHERE org_id=? ORDER BY created_at DESC. Index ghép phục vụ cả lọc
lẫn sắp xếp trong 1 lần quét (tốt hơn 2 index rời). Khớp `CaseRow.__table_args__` (create_all dev).

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_cases_org_created", "cases", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_cases_org_created", table_name="cases")
