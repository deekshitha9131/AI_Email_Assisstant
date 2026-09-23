from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.services.follow_up_service import FollowUpService
from app.domain.enums.follow_up_source import FollowUpSource
from app.domain.enums.follow_up_status import FollowUpStatus
from app.domain.exceptions.follow_up import ActiveFollowUpExistsError, FollowUpStatusError


async def test_create_follow_up_uses_owned_email_thread() -> None:
    user = SimpleNamespace(id=uuid4())
    email = SimpleNamespace(id=uuid4(), thread_id=uuid4())
    thread = SimpleNamespace(id=email.thread_id)
    expected = SimpleNamespace(id=uuid4(), status=FollowUpStatus.PENDING)

    email_service = SimpleNamespace(get_email=AsyncMock(return_value=email))
    thread_service = SimpleNamespace(get_thread=AsyncMock(return_value=(thread, [])))
    repository = SimpleNamespace(create=AsyncMock(return_value=expected))
    service = FollowUpService(
        email_service=email_service,
        thread_service=thread_service,
        repository=repository,
    )

    result = await service.create(
        user,
        email.id,
        due_at=datetime(2026, 9, 20, 14, 30, tzinfo=UTC),
        reason="Check the request.",
        source=FollowUpSource.AI,
    )

    assert result is expected
    email_service.get_email.assert_awaited_once_with(user, email.id)
    thread_service.get_thread.assert_awaited_once_with(user, email.thread_id)
    repository.create.assert_awaited_once_with(
        user_id=user.id,
        email_id=email.id,
        thread_id=email.thread_id,
        due_at=datetime(2026, 9, 20, 14, 30, tzinfo=UTC),
        reason="Check the request.",
        source=FollowUpSource.AI,
    )


async def test_create_from_ai_skips_when_follow_up_is_not_needed() -> None:
    repository = SimpleNamespace(create=AsyncMock())
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )

    result = await service.create_from_ai(
        SimpleNamespace(id=uuid4()),
        uuid4(),
        follow_up_needed=False,
        due_at=None,
        reason=None,
    )

    assert result is None
    repository.create.assert_not_awaited()


async def test_create_from_ai_skips_when_required_date_is_missing() -> None:
    repository = SimpleNamespace(create=AsyncMock())
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )

    result = await service.create_from_ai(
        SimpleNamespace(id=uuid4()),
        uuid4(),
        follow_up_needed=True,
        due_at=None,
        reason="Check the request.",
    )

    assert result is None
    repository.create.assert_not_awaited()


async def test_create_from_ai_ignores_existing_active_follow_up() -> None:
    repository = SimpleNamespace(
        create=AsyncMock(side_effect=ActiveFollowUpExistsError("already exists"))
    )
    email = SimpleNamespace(id=uuid4(), thread_id=uuid4())
    service = FollowUpService(
        email_service=SimpleNamespace(get_email=AsyncMock(return_value=email)),
        thread_service=SimpleNamespace(get_thread=AsyncMock(return_value=(object(), []))),
        repository=repository,
    )

    result = await service.create_from_ai(
        SimpleNamespace(id=uuid4()),
        email.id,
        follow_up_needed=True,
        due_at=datetime(2026, 9, 20, 14, 30, tzinfo=UTC),
        reason="Check the request.",
    )

    assert result is None
    repository.create.assert_awaited_once()


async def test_completed_follow_up_cannot_be_modified() -> None:
    follow_up = SimpleNamespace(id=uuid4(), status=FollowUpStatus.COMPLETED)
    repository = SimpleNamespace(get_by_id_for_user=AsyncMock(return_value=follow_up))
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )

    with pytest.raises(FollowUpStatusError):
        await service.complete(SimpleNamespace(id=uuid4()), follow_up.id)


async def test_dismissed_follow_up_cannot_be_modified() -> None:
    follow_up = SimpleNamespace(id=uuid4(), status=FollowUpStatus.DISMISSED)
    repository = SimpleNamespace(get_by_id_for_user=AsyncMock(return_value=follow_up))
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )

    with pytest.raises(FollowUpStatusError):
        await service.snooze(
            SimpleNamespace(id=uuid4()),
            follow_up.id,
            due_at=datetime(2026, 9, 21, 14, 30, tzinfo=UTC),
        )


async def test_notify_pending_follow_up_creates_notification_and_marks_notified() -> None:
    follow_up = SimpleNamespace(id=uuid4(), status=FollowUpStatus.PENDING)
    notified = SimpleNamespace(id=follow_up.id, status=FollowUpStatus.NOTIFIED)
    repository = SimpleNamespace(
        get_by_id_for_user=AsyncMock(return_value=follow_up),
        mark_notified_for_user=AsyncMock(return_value=notified),
    )
    notification_service = SimpleNamespace(create_follow_up_due=AsyncMock())
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )
    user = SimpleNamespace(id=uuid4())

    result, created = await service.notify(
        user,
        follow_up.id,
        notification_service=notification_service,
    )

    assert result is notified
    assert created is True
    notification_service.create_follow_up_due.assert_awaited_once_with(user, follow_up)
    repository.mark_notified_for_user.assert_awaited_once_with(follow_up.id, user.id)


async def test_notify_snoozed_follow_up_creates_notification_and_marks_notified() -> None:
    follow_up = SimpleNamespace(id=uuid4(), status=FollowUpStatus.SNOOZED)
    notified = SimpleNamespace(id=follow_up.id, status=FollowUpStatus.NOTIFIED)
    repository = SimpleNamespace(
        get_by_id_for_user=AsyncMock(return_value=follow_up),
        mark_notified_for_user=AsyncMock(return_value=notified),
    )
    notification_service = SimpleNamespace(create_follow_up_due=AsyncMock())
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )

    result, created = await service.notify(
        SimpleNamespace(id=uuid4()),
        follow_up.id,
        notification_service=notification_service,
    )

    assert result is notified
    assert created is True


async def test_notify_already_notified_follow_up_is_idempotent() -> None:
    follow_up = SimpleNamespace(id=uuid4(), status=FollowUpStatus.NOTIFIED)
    repository = SimpleNamespace(get_by_id_for_user=AsyncMock(return_value=follow_up))
    notification_service = SimpleNamespace(create_follow_up_due=AsyncMock())
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )

    result, created = await service.notify(
        SimpleNamespace(id=uuid4()),
        follow_up.id,
        notification_service=notification_service,
    )

    assert result is follow_up
    assert created is False
    notification_service.create_follow_up_due.assert_not_awaited()


async def test_notify_completed_follow_up_is_rejected() -> None:
    follow_up = SimpleNamespace(id=uuid4(), status=FollowUpStatus.COMPLETED)
    repository = SimpleNamespace(get_by_id_for_user=AsyncMock(return_value=follow_up))
    notification_service = SimpleNamespace(create_follow_up_due=AsyncMock())
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )

    with pytest.raises(FollowUpStatusError):
        await service.notify(
            SimpleNamespace(id=uuid4()),
            follow_up.id,
            notification_service=notification_service,
        )

    notification_service.create_follow_up_due.assert_not_awaited()


async def test_notify_failure_does_not_mark_follow_up_notified() -> None:
    follow_up = SimpleNamespace(id=uuid4(), status=FollowUpStatus.SNOOZED)
    repository = SimpleNamespace(
        get_by_id_for_user=AsyncMock(return_value=follow_up),
        mark_notified_for_user=AsyncMock(),
    )
    notification_service = SimpleNamespace(
        create_follow_up_due=AsyncMock(side_effect=RuntimeError("notification failed"))
    )
    service = FollowUpService(
        email_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="notification failed"):
        await service.notify(
            SimpleNamespace(id=uuid4()),
            follow_up.id,
            notification_service=notification_service,
        )

    repository.mark_notified_for_user.assert_not_awaited()