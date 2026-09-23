"""add follow-up fields to email AI understanding

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_ai_understanding",
        sa.Column("follow_up_needed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "email_ai_understanding",
        sa.Column("follow_up_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "email_ai_understanding",
        sa.Column("follow_up_reason", sa.Text(), nullable=True),
    )
    op.alter_column("email_ai_understanding", "follow_up_needed", server_default=None)


def downgrade() -> None:
    op.drop_column("email_ai_understanding", "follow_up_reason")
    op.drop_column("email_ai_understanding", "follow_up_date")
    op.drop_column("email_ai_understanding", "follow_up_needed")