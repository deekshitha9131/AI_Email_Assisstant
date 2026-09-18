from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.di_container import get_compose_draft_service, get_current_user
from app.domain.entities.compose_draft import ComposeDraft
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.draft import DraftNotFoundError


def _user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _draft(user: User) -> ComposeDraft:
    now = datetime.now(UTC)
    return ComposeDraft(
        id=uuid4(),
        user_id=user.id,
        recipients=["bob@example.com"],
        cc=[],
        bcc=[],
        subject="Subject",
        body_text="Body",
        body_html=None,
        created_at=now,
        updated_at=now,
    )


class FakeComposeDraftService:
    def __init__(self, user: User) -> None:
        self.user = user
        self.draft = _draft(user)
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    async def create(self, user: User, **fields):
        self.create_calls.append(fields)
        return self.draft

    async def list(self, user: User, *, page: int, page_size: int):
        return [self.draft]

    async def get(self, user: User, draft_id):
        if draft_id != self.draft.id:
            raise DraftNotFoundError("not found")
        return self.draft

    async def update(self, user: User, draft_id, **fields):
        await self.get(user, draft_id)
        self.update_calls.append(fields)
        return self.draft

    async def delete(self, user: User, draft_id):
        await self.get(user, draft_id)


@pytest.fixture
def fake_service(app_no_lifespan: FastAPI) -> FakeComposeDraftService:
    user = _user()
    service = FakeComposeDraftService(user)
    app_no_lifespan.dependency_overrides[get_compose_draft_service] = lambda: service
    app_no_lifespan.dependency_overrides[get_current_user] = lambda: user
    return service


def _payload() -> dict:
    return {
        "recipients": [" bob@example.com "],
        "subject": "Subject",
        "body_text": "Body",
    }


def test_create_compose_draft_persists_through_service(
    unit_client: TestClient, fake_service: FakeComposeDraftService
) -> None:
    response = unit_client.post("/api/v1/compose-drafts", json=_payload())

    assert response.status_code == 201
    assert fake_service.create_calls[0]["recipients"] == ["bob@example.com"]


def test_list_update_and_delete_compose_draft(
    unit_client: TestClient, fake_service: FakeComposeDraftService
) -> None:
    draft_id = str(fake_service.draft.id)

    listed = unit_client.get("/api/v1/compose-drafts")
    updated = unit_client.put(f"/api/v1/compose-drafts/{draft_id}", json=_payload())
    deleted = unit_client.delete(f"/api/v1/compose-drafts/{draft_id}")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == draft_id
    assert updated.status_code == 200
    assert fake_service.update_calls
    assert deleted.status_code == 204


def test_compose_draft_not_found_is_not_exposed_across_users(
    unit_client: TestClient, fake_service: FakeComposeDraftService
) -> None:
    response = unit_client.get(f"/api/v1/compose-drafts/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DRAFT_NOT_FOUND"


def test_compose_draft_rejects_invalid_recipient(
    unit_client: TestClient, fake_service: FakeComposeDraftService
) -> None:
    response = unit_client.post(
        "/api/v1/compose-drafts", json={**_payload(), "recipients": ["invalid"]}
    )

    assert response.status_code == 400
    assert fake_service.create_calls == []