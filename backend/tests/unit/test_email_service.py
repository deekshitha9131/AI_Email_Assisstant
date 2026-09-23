"""Tests for app/application/services/email_service.py.

Fakes EmailRepository entirely — this is a pure test of EmailService's
orchestration and ownership-enforcement logic, not of SQL. Real
repository behavior (pagination, filtering, sorting, counts) is already
covered by tests/integration/test_email_repository.py (Task 4.1).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.services.email_service import EmailService
from app.domain.entities.email import Email
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.email import EmailNotFoundError


def _user(user_id=None) -> User:
    return User(
        id=user_id or uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _email(*, user_id, email_id=None) -> Email:
    return Email(
        id=email_id or uuid4(),
        thread_id=uuid4(),
        user_id=user_id,
        gmail_message_id="m1",
        sender="sender@example.com",
        recipients=["user@example.com"],
        cc=[],
        bcc=[],
        subject="Subject",
        snippet="snippet",
        body_text="body",
        body_html=None,
        received_at=datetime.now(UTC),
        is_read=True,
        is_starred=False,
        has_attachments=False,
        label_ids=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class FakeEmailRepository:
    def __init__(self, *, emails: list[Email] | None = None) -> None:
        self._emails = {e.id: e for e in (emails or [])}
        self.get_by_user_id_calls: list[dict] = []
        self.count_by_user_id_calls: list[dict] = []

    async def get_by_id(self, email_id):
        return self._emails.get(email_id)

    async def get_by_user_id_for_list(self, user_id, **kwargs):
        self.get_by_user_id_calls.append({"user_id": user_id, **kwargs})
        return [e for e in self._emails.values() if e.user_id == user_id]

    async def get_by_user_id(self, user_id, **kwargs):
        self.get_by_user_id_calls.append({"user_id": user_id, **kwargs})
        return [e for e in self._emails.values() if e.user_id == user_id]

    async def count_by_user_id(self, user_id, **kwargs):
        self.count_by_user_id_calls.append({"user_id": user_id, **kwargs})
        return len([e for e in self._emails.values() if e.user_id == user_id])


async def test_list_emails_passes_params_through_to_repository() -> None:
    user = _user()
    repo = FakeEmailRepository(emails=[_email(user_id=user.id)])
    service = EmailService(email_repository=repo)

    await service.list_emails(
        user,
        page=2,
        page_size=10,
        sort="oldest",
        is_read=False,
        is_starred=True,
        has_attachments=None,
    )

    assert repo.get_by_user_id_calls[0] == {
        "user_id": user.id,
        "page": 2,
        "page_size": 10,
        "sort": "oldest",
        "is_read": False,
        "is_starred": True,
        "has_attachments": None,
    }
    assert repo.count_by_user_id_calls[0] == {
        "user_id": user.id,
        "is_read": False,
        "is_starred": True,
        "has_attachments": None,
    }


async def test_list_emails_returns_items_and_total() -> None:
    user = _user()
    repo = FakeEmailRepository(emails=[_email(user_id=user.id), _email(user_id=user.id)])
    service = EmailService(email_repository=repo)

    items, total = await service.list_emails(user, page=1, page_size=20, sort="newest")

    assert len(items) == 2
    assert total == 2


async def test_list_emails_only_returns_this_users_emails() -> None:
    user_a = _user()
    user_b = _user()
    repo = FakeEmailRepository(emails=[_email(user_id=user_a.id), _email(user_id=user_b.id)])
    service = EmailService(email_repository=repo)

    items, total = await service.list_emails(user_a, page=1, page_size=20, sort="newest")

    assert total == 1
    assert all(e.user_id == user_a.id for e in items)


async def test_get_email_returns_owned_email() -> None:
    user = _user()
    email = _email(user_id=user.id)
    repo = FakeEmailRepository(emails=[email])
    service = EmailService(email_repository=repo)

    result = await service.get_email(user, email.id)

    assert result.id == email.id


async def test_get_email_raises_for_missing_email() -> None:
    user = _user()
    repo = FakeEmailRepository(emails=[])
    service = EmailService(email_repository=repo)

    with pytest.raises(EmailNotFoundError):
        await service.get_email(user, uuid4())


async def test_get_email_raises_for_another_users_email() -> None:
    """The core ownership guarantee: an email that genuinely exists but
    belongs to a different user must be indistinguishable from a
    missing one — same exception, same eventual 404."""
    owner = _user()
    other_user = _user()
    email = _email(user_id=owner.id)
    repo = FakeEmailRepository(emails=[email])
    service = EmailService(email_repository=repo)

    with pytest.raises(EmailNotFoundError):
        await service.get_email(other_user, email.id)
