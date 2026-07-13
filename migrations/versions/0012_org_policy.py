"""bảng org_policies (playbook công ty — chính sách pháp lý cấp org)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_policies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("rule_text", sa.String()),
        sa.Column("kind", sa.String(), server_default="mandatory"),
        sa.Column("severity", sa.String(), server_default="must_fix"),
        sa.Column("active", sa.Boolean(), server_default=sa.true()),
    )
    op.create_index("idx_org_policies_org", "org_policies", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_org_policies_org", table_name="org_policies")
    op.drop_table("org_policies")
