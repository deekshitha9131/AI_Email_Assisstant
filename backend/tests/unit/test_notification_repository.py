from unittest.mock import AsyncMock, MagicMock
import pytest
from uuid import UUID, uuid4
from datetime import datetime, timezone

from app.infrastructure.database.repositories.notification_repository import NotificationRepository
from app.infrastructure.database.models.notification import NotificationModel
from app.domain.entities.notification import Notification


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


@pytest.fixture
def repository(mock_session):
    return NotificationRepository(mock_session)


async def test_get_or_create_creates_new_email_based(repository, mock_session):
    # Arrange
    user_id = uuid4()
    email_id = uuid4()
    notification_type = "test_type"
    title = "Test Title"
    message = "Test Message"
    follow_up_id = None

    mock_result = MagicMock()
    mock_row = MagicMock()
    mock_row.__getitem__.return_value = NotificationModel(
        id=uuid4(),
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=follow_up_id,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    mock_result.first.return_value = mock_row
    mock_session.execute.return_value = mock_result

    # Act
    notification, created = await repository.get_or_create(
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=follow_up_id,
    )

    # Assert
    assert created is True
    assert notification.user_id == user_id
    assert notification.email_id == email_id
    assert notification.notification_type == notification_type
    assert notification.title == title
    assert notification.message == message
    # Verify that insert was called
    assert mock_session.execute.call_count == 1
    # Verify that commit was called
    mock_session.commit.assert_awaited_once()


async def test_get_or_create_returns_existing_email_based(repository, mock_session):
    # Arrange
    user_id = uuid4()
    email_id = uuid4()
    notification_type = "test_type"
    title = "Test Title"
    message = "Test Message"
    follow_up_id = None
    existing_id = uuid4()

    mock_result_insert = MagicMock()
    mock_result_insert.first.return_value = None
    mock_result_select = MagicMock()
    existing_model = NotificationModel(
        id=existing_id,
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=follow_up_id,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    mock_result_select.scalar_one_or_none.return_value = existing_model

    # We need to differentiate between the two calls to execute
    mock_session.execute.side_effect = [mock_result_insert, mock_result_select]

    # Act
    notification, created = await repository.get_or_create(
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=follow_up_id,
    )

    # Assert
    assert created is False
    assert notification.id == existing_id
    assert notification.user_id == user_id
    assert notification.email_id == email_id
    assert notification.notification_type == notification_type
    assert notification.title == title
    assert notification.message == message
    # Verify that insert then select were called
    assert mock_session.execute.call_count == 2
    # Verify that commit was NOT called (since no insert)
    mock_session.commit.assert_not_awaited()


async def test_get_or_create_handles_insert_conflict_without_raising_on_empty_result(
    repository, mock_session
):
    user_id = uuid4()
    email_id = uuid4()
    notification_type = "test_type"
    title = "Test Title"
    message = "Test Message"

    existing_id = uuid4()
    mock_result_insert = MagicMock()
    mock_result_insert.first.return_value = None

    mock_result_select = MagicMock()
    existing = NotificationModel(
        id=existing_id,
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=None,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    mock_result_select.scalar_one_or_none.return_value = existing
    mock_session.execute.side_effect = [mock_result_insert, mock_result_select]

    notification, created = await repository.get_or_create(
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=None,
    )

    assert created is False
    assert notification.id == existing_id
    assert notification.user_id == user_id
    mock_result_insert.scalar_one_or_none.assert_not_called()
    assert mock_session.execute.call_count == 2
    mock_session.commit.assert_not_awaited()


async def test_get_or_create_creates_new_follow_up_based(repository, mock_session):
    # Arrange
    user_id = uuid4()
    email_id = uuid4()
    follow_up_id = uuid4()
    notification_type = "follow_up_due"
    title = "Test Title"
    message = "Test Message"

    mock_result = MagicMock()
    mock_row = MagicMock()
    mock_row.__getitem__.return_value = NotificationModel(
        id=uuid4(),
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=follow_up_id,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    mock_result.first.return_value = mock_row
    mock_session.execute.return_value = mock_result

    # Act
    notification, created = await repository.get_or_create(
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=follow_up_id,
    )

    # Assert
    assert created is True
    assert notification.user_id == user_id
    assert notification.email_id == email_id
    assert notification.follow_up_id == follow_up_id
    assert notification.notification_type == notification_type
    assert notification.title == title
    assert notification.message == message
    # Verify that insert was called
    assert mock_session.execute.call_count == 1
    # Verify that commit was called
    mock_session.commit.assert_awaited_once()


async def test_get_or_create_returns_existing_follow_up_based(repository, mock_session):
    # Arrange
    user_id = uuid4()
    email_id = uuid4()
    follow_up_id = uuid4()
    notification_type = "follow_up_due"
    title = "Test Title"
    message = "Test Message"
    existing_id = uuid4()

    mock_result_insert = MagicMock()
    mock_result_insert.first.return_value = None
    mock_result_select = MagicMock()
    existing_model = NotificationModel(
        id=existing_id,
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=follow_up_id,
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    mock_result_select.scalar_one_or_none.return_value = existing_model

    # We need to differentiate between the two calls to execute
    mock_session.execute.side_effect = [mock_result_insert, mock_result_select]

    # Act
    notification, created = await repository.get_or_create(
        user_id=user_id,
        email_id=email_id,
        notification_type=notification_type,
        title=title,
        message=message,
        follow_up_id=follow_up_id,
    )

    # Assert
    assert created is False
    assert notification.id == existing_id
    assert notification.user_id == user_id
    assert notification.email_id == email_id
    assert notification.follow_up_id == follow_up_id
    assert notification.notification_type == notification_type
    assert notification.title == title
    assert notification.message == message
    # Verify that insert then select were called
    assert mock_session.execute.call_count == 2
    # Verify that commit was NOT called (since no insert)
    mock_session.commit.assert_not_awaited()