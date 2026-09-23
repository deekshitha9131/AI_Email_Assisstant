"""associate notifications with follow-ups

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("follow_up_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_notifications_follow_up_id_follow_ups",
        "notifications",
        "follow_ups",
        ["follow_up_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_notifications_follow_up_id", "notifications", ["follow_up_id"])
    op.drop_constraint(
        "uq_notifications_user_id_email_id_notification_type",
        "notifications",
        type_="unique",
    )
    op.create_index(
        "uq_notifications_email_type_without_follow_up",
        "notifications",
        ["user_id", "email_id", "notification_type"],
        unique=True,
        postgresql_where=sa.text("follow_up_id IS NULL"),
    )
    op.create_index(
        "uq_notifications_follow_up_type",
        "notifications",
        ["user_id", "follow_up_id", "notification_type"],
        unique=True,
        postgresql_where=sa.text("follow_up_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_notifications_follow_up_type", table_name="notifications")
    op.drop_index("uq_notifications_email_type_without_follow_up", table_name="notifications")
    op.create_unique_constraint(
        "uq_notifications_user_id_email_id_notification_type",
        "notifications",
        ["user_id", "email_id", "notification_type"],
    )
    op.drop_index("ix_notifications_follow_up_id", table_name="notifications")
    op.drop_constraint(
        "fk_notifications_follow_up_id_follow_ups",
        "notifications",
        type_="foreignkey",
    )
    op.drop_column("notifications", "follow_up_id")