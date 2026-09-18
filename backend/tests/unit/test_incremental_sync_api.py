"""Tests for the POST /gmail/sync/incremental endpoint
(app/presentation/api/v1/routers/gmail.py).

Same dependency_overrides pattern as test_gmail_api.py — no live
database, Redis, or Gmail involved.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dto.gmail import GmailIncrementalSyncSummary
from app.core.di_container import get_current_user, get_gmail_service
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.gmail import GmailAPIError, GmailSyncRequiredError


class FakeGmailService:
    def __init__(self) -> None:
        self.sync_incremental_calls = 0
        self.summary_to_return = GmailIncrementalSyncSummary(
            success=True,
            emails_synced=4,
            threads_updated=2,
            attachments_found=1,
            emails_skipped=0,
            history_id="300",
        )
        self.raise_on_sync: Exception | None = None

    async def sync_incremental(self, user: User) -> GmailIncrementalSyncSummary:
        self.sync_incremental_calls += 1
        if self.raise_on_sync is not None:
            raise self.raise_on_sync
        return self.summary_to_return


def _fake_current_user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        google_sub_id="sub-1",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def fake_gmail_service(app_no_lifespan: FastAPI) -> FakeGmailService:
    service = FakeGmailService()
    app_no_lifespan.dependency_overrides[get_gmail_service] = lambda: service
    app_no_lifespan.dependency_overrides[get_current_user] = _fake_current_user
    return service


def test_incremental_sync_endpoint_returns_summary(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post("/api/v1/gmail/sync/incremental")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["emails_synced"] == 4
    assert body["threads_updated"] == 2
    assert body["attachments_found"] == 1
    assert body["emails_skipped"] == 0
    assert body["history_id"] == "300"
    assert fake_gmail_service.sync_incremental_calls == 1


def test_incremental_sync_endpoint_requires_authentication(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    service = FakeGmailService()
    app_no_lifespan.dependency_overrides[get_gmail_service] = lambda: service

    response = unit_client.post("/api/v1/gmail/sync/incremental")

    assert response.status_code == 401


def test_incremental_sync_endpoint_returns_409_when_initial_sync_required(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    fake_gmail_service.raise_on_sync = GmailSyncRequiredError(
        "No prior Gmail sync found for this account."
    )

    response = unit_client.post(
        "/api/v1/gmail/sync/incremental",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 409
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.json()["error"]["code"] == "GMAIL_INITIAL_SYNC_REQUIRED"


def test_incremental_sync_endpoint_returns_502_on_gmail_api_failure(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    fake_gmail_service.raise_on_sync = GmailAPIError("Gmail returned a 500.")

    response = unit_client.post("/api/v1/gmail/sync/incremental")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "GMAIL_API_ERROR"
