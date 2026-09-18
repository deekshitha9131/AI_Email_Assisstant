"""Tests for app/presentation/exception_handlers.py.

Every raise path the API can produce is exercised here against the
standard error envelope shape. Ad hoc test routes are attached per-test
(never part of the shipped app) specifically to trigger each exception
type deliberately.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.exceptions import BusinessValidationError, ConflictError, NotFoundError
from tests.utils import assert_error_envelope


def test_not_found_error_returns_404(app_no_lifespan: FastAPI, unit_client: TestClient) -> None:
    @app_no_lifespan.get("/__test/not-found")
    async def _raise() -> None:
        raise NotFoundError("Thread not found.")

    response = unit_client.get("/__test/not-found")

    body = assert_error_envelope(response, status_code=404, code="NOT_FOUND")
    assert body["error"]["message"] == "Thread not found."


def test_conflict_error_returns_409(app_no_lifespan: FastAPI, unit_client: TestClient) -> None:
    @app_no_lifespan.get("/__test/conflict")
    async def _raise() -> None:
        raise ConflictError("Draft already sent.")

    response = unit_client.get("/__test/conflict")

    assert_error_envelope(response, status_code=409, code="CONFLICT")


def test_business_validation_error_returns_422(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    @app_no_lifespan.get("/__test/business-validation")
    async def _raise() -> None:
        raise BusinessValidationError("Draft body cannot be empty.")

    response = unit_client.get("/__test/business-validation")

    assert_error_envelope(response, status_code=422, code="BUSINESS_VALIDATION_ERROR")


def test_unmatched_route_returns_404_in_standard_envelope(unit_client: TestClient) -> None:
    response = unit_client.get("/this-route-does-not-exist")

    assert_error_envelope(response, status_code=404, code="HTTP_ERROR")


def test_unhandled_exception_returns_500_without_leaking_internals(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    @app_no_lifespan.get("/__test/boom")
    async def _raise() -> None:
        raise RuntimeError("some internal detail that must never reach the client")

    response = unit_client.get("/__test/boom", headers={"Origin": "http://localhost:5173"})

    body = assert_error_envelope(response, status_code=500, code="INTERNAL_SERVER_ERROR")
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    # The whole point of the generic handler: internal exception text
    # must never appear in the client-facing message.
    assert "internal detail" not in body["error"]["message"]


def test_request_validation_error_returns_400_with_field_detail(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    from pydantic import BaseModel

    class _Payload(BaseModel):
        required_field: str

    @app_no_lifespan.post("/__test/validate")
    async def _endpoint(payload: _Payload) -> dict:
        return {"received": payload.required_field}

    response = unit_client.post("/__test/validate", json={})

    body = assert_error_envelope(response, status_code=400, code="VALIDATION_ERROR")
    assert "fields" in body["error"]
    assert any(f["field"] == "required_field" for f in body["error"]["fields"])


def test_every_error_response_carries_a_request_id_header(
    app_no_lifespan: FastAPI, unit_client: TestClient
) -> None:
    @app_no_lifespan.get("/__test/for-request-id")
    async def _raise() -> None:
        raise NotFoundError("irrelevant")

    response = unit_client.get("/__test/for-request-id", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["X-Request-ID"] == "trace-abc-123"
    assert response.json()["error"]["request_id"] == "trace-abc-123"
