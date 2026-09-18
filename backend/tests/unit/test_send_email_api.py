"""Tests for the POST /gmail/send endpoint
(app/presentation/api/v1/routers/gmail.py).

Same dependency_overrides pattern as test_gmail_api.py /
test_incremental_sync_api.py — no live database, Redis, or Gmail
involved. Also exercises GmailSendRequest's own Pydantic validation
(invalid recipient, missing body) purely through the HTTP layer, since
that's exactly the boundary those validators are meant to guard.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dto.gmail import GmailSendResult
from app.core.di_container import get_current_user, get_gmail_service
from app.domain.entities.user import User
from app.domain.enums.user_status import UserStatus
from app.domain.exceptions.gmail import GmailAPIError, GmailNotConnectedError


class FakeGmailService:
    def __init__(self) -> None:
        self.send_calls: list[dict] = []
        self.result_to_return = GmailSendResult(
            success=True, gmail_message_id="sent-1", gmail_thread_id="thread-1"
        )
        self.raise_on_send: Exception | None = None

    async def send_email(self, user: User, **kwargs) -> GmailSendResult:
        self.send_calls.append(kwargs)
        if self.raise_on_send is not None:
            raise self.raise_on_send
        return self.result_to_return


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


def _valid_payload(**overrides) -> dict:
    payload = {
        "to": ["bob@example.com"],
        "cc": ["carol@example.com"],
        "bcc": [],
        "subject": "Project Update",
        "body_text": "Hello there.",
        "body_html": None,
        "thread_id": None,
    }
    payload.update(overrides)
    return payload


def test_send_endpoint_returns_result_on_success(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post("/api/v1/gmail/send", json=_valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["gmail_message_id"] == "sent-1"
    assert body["gmail_thread_id"] == "thread-1"
    assert fake_gmail_service.send_calls[0]["to"] == ["bob@example.com"]


def test_send_endpoint_reply_passes_thread_id(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post(
        "/api/v1/gmail/send", json=_valid_payload(thread_id="18cf90c12ab45")
    )

    assert response.status_code == 200
    assert fake_gmail_service.send_calls[0]["thread_id"] == "18cf90c12ab45"


def test_send_endpoint_rejects_invalid_recipient(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post("/api/v1/gmail/send", json=_valid_payload(to=["not-a-valid-email"]))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_gmail_service.send_calls == []


def test_send_endpoint_rejects_empty_recipient_list(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post("/api/v1/gmail/send", json=_valid_payload(to=[]))

    assert response.status_code == 400
    assert fake_gmail_service.send_calls == []


def test_send_endpoint_trims_recipient_whitespace(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post(
        "/api/v1/gmail/send", json=_valid_payload(to=["  bob@example.com  "])
    )

    assert response.status_code == 200
    assert fake_gmail_service.send_calls[0]["to"] == ["bob@example.com"]


@pytest.mark.parametrize(
    "recipient",
    ["abc", "abc@", "@example.com", "abc@gmail", "abc@@gmail.com", "abc..test@example.com"],
)
def test_send_endpoint_rejects_malformed_recipient_forms(
    app_no_lifespan: FastAPI,
    unit_client: TestClient,
    fake_gmail_service: FakeGmailService,
    recipient: str,
) -> None:
    response = unit_client.post("/api/v1/gmail/send", json=_valid_payload(to=[recipient]))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_gmail_service.send_calls == []


def test_send_endpoint_rejects_missing_body(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post(
        "/api/v1/gmail/send", json=_valid_payload(body_text=None, body_html=None)
    )

    assert response.status_code == 400
    assert fake_gmail_service.send_calls == []


def test_send_endpoint_accepts_html_only_body(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    response = unit_client.post(
        "/api/v1/gmail/send",
        json=_valid_payload(body_text=None, body_html="<p>Hi</p>"),
    )

    assert response.status_code == 200


def test_send_endpoint_requires_authentication(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    service = FakeGmailService()
    app_no_lifespan.dependency_overrides[get_gmail_service] = lambda: service

    response = unit_client.post("/api/v1/gmail/send", json=_valid_payload())

    assert response.status_code == 401


def test_send_endpoint_returns_401_when_gmail_not_connected(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    fake_gmail_service.raise_on_send = GmailNotConnectedError("Gmail is not connected.")

    response = unit_client.post("/api/v1/gmail/send", json=_valid_payload())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "GMAIL_NOT_CONNECTED"


def test_send_endpoint_returns_502_on_gmail_api_failure(
    app_no_lifespan: FastAPI, unit_client: TestClient, fake_gmail_service: FakeGmailService
) -> None:
    fake_gmail_service.raise_on_send = GmailAPIError("Gmail returned a 500.")

    response = unit_client.post("/api/v1/gmail/send", json=_valid_payload())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "GMAIL_API_ERROR"
