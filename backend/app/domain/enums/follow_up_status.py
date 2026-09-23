from enum import StrEnum


class FollowUpStatus(StrEnum):
    PENDING = "pending"
    NOTIFIED = "notified"
    COMPLETED = "completed"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"


ACTIVE_FOLLOW_UP_STATUSES = (
    FollowUpStatus.PENDING,
    FollowUpStatus.NOTIFIED,
    FollowUpStatus.SNOOZED,
)