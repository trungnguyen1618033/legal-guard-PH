"""thêm org_id (cô lập theo công ty)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cases") as b:
        b.add_column(sa.Column("org_id", sa.String(), nullable=False, server_default="default"))
    op.create_index("idx_cases_org", "cases", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_cases_org", table_name="cases")
    with op.batch_alter_table("cases") as b:
        b.drop_column("org_id")
