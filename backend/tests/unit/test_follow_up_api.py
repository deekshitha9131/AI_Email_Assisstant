from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.di_container import get_current_user, get_follow_up_service
from app.domain.entities.user import User
from app.domain.enums.follow_up_status import FollowUpStatus
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.follow_up import FollowUpNotFoundError, FollowUpStatusError


def _user() -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def _follow_up(user_id, *, status=FollowUpStatus.PENDING):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        email_id=uuid4(),
        thread_id=uuid4(),
        due_at=now + timedelta(days=1),
        status=status,
        reason="Check the request.",
        source="user",
        created_at=now,
        updated_at=now,
        completed_at=None,
        dismissed_at=None,
    )


class FakeFollowUpService:
    def __init__(self, follow_up):
        self.follow_up = follow_up

    async def list(self, user):
        return [self.follow_up]

    async def get(self, user, follow_up_id):
        if user.id != self.follow_up.user_id or follow_up_id != self.follow_up.id:
            raise FollowUpNotFoundError("Not found")
        return self.follow_up

    async def complete(self, user, follow_up_id):
        return await self._transition(user, follow_up_id, FollowUpStatus.COMPLETED)

    async def dismiss(self, user, follow_up_id):
        return await self._transition(user, follow_up_id, FollowUpStatus.DISMISSED)

    async def snooze(self, user, follow_up_id, *, due_at):
        if self.follow_up.status in {FollowUpStatus.COMPLETED, FollowUpStatus.DISMISSED}:
            raise FollowUpStatusError("Cannot modify")
        self.follow_up.status = FollowUpStatus.SNOOZED
        self.follow_up.due_at = due_at
        return self.follow_up

    async def _transition(self, user, follow_up_id, status):
        if self.follow_up.user_id != user.id or follow_up_id != self.follow_up.id:
            raise FollowUpNotFoundError("Not found")
        if self.follow_up.status in {FollowUpStatus.COMPLETED, FollowUpStatus.DISMISSED}:
            raise FollowUpStatusError("Cannot modify")
        self.follow_up.status = status
        return self.follow_up


def _client(app_no_lifespan: FastAPI, user: User, service: FakeFollowUpService):
    app_no_lifespan.dependency_overrides[get_current_user] = lambda: user
    app_no_lifespan.dependency_overrides[get_follow_up_service] = lambda: service
    return TestClient(app_no_lifespan, raise_server_exceptions=False)


def test_follow_up_endpoints_enforce_ownership(app_no_lifespan: FastAPI) -> None:
    owner = _user()
    follow_up = _follow_up(uuid4())
    client = _client(app_no_lifespan, owner, FakeFollowUpService(follow_up))

    response = client.get(f"/api/v1/follow-ups/{follow_up.id}")

    assert response.status_code == 404


def test_follow_up_complete_and_dismiss_endpoints(app_no_lifespan: FastAPI) -> None:
    user = _user()
    follow_up = _follow_up(user.id)
    client = _client(app_no_lifespan, user, FakeFollowUpService(follow_up))

    complete_response = client.post(f"/api/v1/follow-ups/{follow_up.id}/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"

    follow_up.status = FollowUpStatus.PENDING
    dismiss_response = client.post(f"/api/v1/follow-ups/{follow_up.id}/dismiss")
    assert dismiss_response.status_code == 200
    assert dismiss_response.json()["status"] == "dismissed"


def test_follow_up_snooze_accepts_future_date(app_no_lifespan: FastAPI) -> None:
    user = _user()
    follow_up = _follow_up(user.id)
    client = _client(app_no_lifespan, user, FakeFollowUpService(follow_up))
    due_at = datetime.now(UTC) + timedelta(days=2)

    response = client.post(
        f"/api/v1/follow-ups/{follow_up.id}/snooze",
        json={"due_at": due_at.isoformat()},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "snoozed"


def test_follow_up_snooze_rejects_past_date(app_no_lifespan: FastAPI) -> None:
    user = _user()
    follow_up = _follow_up(user.id)
    client = _client(app_no_lifespan, user, FakeFollowUpService(follow_up))

    response = client.post(
        f"/api/v1/follow-ups/{follow_up.id}/snooze",
        json={"due_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
    )

    assert response.status_code == 422