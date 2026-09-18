"""create user-owned compose drafts

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compose_drafts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("recipients", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("cc", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("bcc", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_compose_drafts"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_compose_drafts_user_id_users", ondelete="CASCADE"),
    )
    op.create_index("ix_compose_drafts_user_id", "compose_drafts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_compose_drafts_user_id", table_name="compose_drafts")
    op.drop_table("compose_drafts")