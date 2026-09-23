"""create follow-ups table

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

follow_up_status_enum = sa.Enum(
    "pending", "notified", "completed", "dismissed", "snoozed", name="follow_up_status"
)
follow_up_source_enum = sa.Enum("ai", "user", name="follow_up_source")
active_statuses = "'pending', 'notified', 'snoozed'"


def upgrade() -> None:
    op.create_table(
        "follow_ups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", follow_up_status_enum, nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", follow_up_source_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_follow_ups"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_follow_ups_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], name="fk_follow_ups_email_id_emails", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_follow_ups_thread_id_threads", ondelete="CASCADE"),
    )
    op.create_index("ix_follow_ups_user_id", "follow_ups", ["user_id"])
    op.create_index("ix_follow_ups_email_id", "follow_ups", ["email_id"])
    op.create_index("ix_follow_ups_thread_id", "follow_ups", ["thread_id"])
    op.create_index(
        "uq_follow_ups_active_email",
        "follow_ups",
        ["email_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({active_statuses})"),
    )
    op.create_index(
        "uq_follow_ups_active_thread",
        "follow_ups",
        ["thread_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({active_statuses})"),
    )


def downgrade() -> None:
    op.drop_index("uq_follow_ups_active_thread", table_name="follow_ups")
    op.drop_index("uq_follow_ups_active_email", table_name="follow_ups")
    op.drop_index("ix_follow_ups_thread_id", table_name="follow_ups")
    op.drop_index("ix_follow_ups_email_id", table_name="follow_ups")
    op.drop_index("ix_follow_ups_user_id", table_name="follow_ups")
    op.drop_table("follow_ups")
    follow_up_source_enum.drop(op.get_bind(), checkfirst=True)
    follow_up_status_enum.drop(op.get_bind(), checkfirst=True)