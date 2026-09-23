import asyncio
import base64
import json
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

import structlog
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from app.core.config import Settings
from app.core.constants import GOOGLE_TOKEN_ENDPOINT
from app.domain.entities.oauth_token import OAuthToken
from app.domain.exceptions.gmail import (
    GmailAPIError,
    GmailAuthenticationError,
    GmailHistoryExpiredError,
    GmailPermissionError,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")

_GMAIL_SERVICE_NAME = "gmail"
_GMAIL_SERVICE_VERSION = "v1"
_DEFAULT_MAX_RESULTS = 100
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_INITIAL_DELAY_SECONDS = 1.0
_RATE_LIMIT_MAX_DELAY_SECONDS = 30.0

_AUTH_FAILURE_STATUSES = frozenset({401, 403})


def _google_error_reasons(error: HttpError) -> set[str]:
    try:
        body = json.loads(error.content.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    error_body = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error_body, dict):
        return set()
    return {
        str(item.get("reason"))
        for item in error_body.get("errors", [])
        if isinstance(item, dict)
        if item.get("reason")
    }


def _rate_limit_delay_seconds(error: HttpError, retry_number: int) -> float:
    retry_after = error.resp.get("retry-after") if error.resp is not None else None
    if retry_after:
        try:
            delay = float(retry_after)
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = (retry_at - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = _RATE_LIMIT_INITIAL_DELAY_SECONDS * (2 ** (retry_number - 1))
    else:
        delay = _RATE_LIMIT_INITIAL_DELAY_SECONDS * (2 ** (retry_number - 1))
    return min(max(delay, 0.0), _RATE_LIMIT_MAX_DELAY_SECONDS)


class GmailClient:

    def __init__(self, *, oauth_token: OAuthToken, settings: Settings) -> None:
        self._oauth_token = oauth_token
        self._settings = settings
        self._service: Resource | None = None

    def _build_credentials(self) -> Credentials:
        """Build google-auth Credentials from the stored (decrypted) OAuth tokens."""
        return Credentials(  # type: ignore[no-untyped-call]
            token=self._oauth_token.access_token,
            refresh_token=self._oauth_token.refresh_token,
            token_uri=GOOGLE_TOKEN_ENDPOINT,
            client_id=self._settings.google_client_id,
            client_secret=self._settings.google_client_secret,
            scopes=self._oauth_token.granted_scopes,
        )

    def _get_service(self) -> Resource:
        """Return the memoized Gmail API `Resource`, building it on first use."""
        if self._service is None:
            try:
                credentials = self._build_credentials()
                self._service = build(
                    _GMAIL_SERVICE_NAME,
                    _GMAIL_SERVICE_VERSION,
                    credentials=credentials,
                    cache_discovery=False,
                )
            except GoogleAuthError as exc:
                raise GmailAuthenticationError(
                    "Failed to build an authenticated Gmail API client from "
                    "the stored OAuth tokens."
                ) from exc
            except Exception as exc:
                raise GmailAPIError(
                    "Failed to initialize the Gmail API client. "
                    "The Gmail API service may be unavailable."
                ) from exc
        return self._service

    async def refresh_access_token(self) -> OAuthToken:
        """Refresh an expired access token and return the updated token set."""
        credentials = self._build_credentials()
        try:
            await asyncio.to_thread(credentials.refresh, Request())
        except GoogleAuthError as exc:
            logger.warning(
                "gmail_access_token_refresh_failed",
                error_type=type(exc).__name__,
            )
            raise GmailAuthenticationError(
                "Gmail could not refresh the stored access token. "
                "The Gmail permission may have been revoked."
            ) from exc

        if not credentials.token or not credentials.expiry:
            raise GmailAuthenticationError("Google returned an incomplete refreshed token.")

        return OAuthToken(
            user_id=self._oauth_token.user_id,
            access_token=credentials.token,
            refresh_token=credentials.refresh_token or self._oauth_token.refresh_token,
            token_expiry=credentials.expiry,
            granted_scopes=self._oauth_token.granted_scopes,
        )

    async def _execute(
        self, operation: Callable[[Resource], T], *, history_request: bool = False
    ) -> T:
        """Run a synchronous googleapiclient call off the event loop and
        translate its errors into this project's domain exceptions."""
        service = self._get_service()
        for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                return await asyncio.to_thread(operation, service)
            except HttpError as exc:
                status = exc.resp.status if exc.resp is not None else None
                reasons = _google_error_reasons(exc)
                is_rate_limited = status == 429 or bool(
                    reasons & {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
                )
                if is_rate_limited and attempt < _RATE_LIMIT_MAX_RETRIES:
                    delay = _rate_limit_delay_seconds(exc, attempt + 1)
                    logger.warning(
                        "gmail_request_rate_limited_retrying",
                        attempt=attempt + 1,
                        delay_seconds=delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                if "accessNotConfigured" in reasons:
                    raise GmailAPIError(
                        "The Gmail API is not enabled for the configured Google Cloud project."
                    ) from exc
                if reasons & {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}:
                    raise GmailAPIError(
                        "Gmail temporarily rate-limited this request. Please retry the sync."
                    ) from exc
                if "insufficientPermissions" in reasons or "forbidden" in reasons:
                    raise GmailPermissionError(
                        "The connected Google account does not grant the required Gmail scope. "
                        "Reconnect Gmail and approve Gmail access."
                    ) from exc
                if status in _AUTH_FAILURE_STATUSES:
                    logger.warning(
                        "gmail_request_authentication_failed",
                        status=status,
                        reasons=sorted(reasons),
                    )
                    raise GmailAuthenticationError(
                        "Gmail rejected the request as unauthenticated or "
                        "unauthorized — the stored OAuth tokens may be expired "
                        "or revoked."
                    ) from exc
                if history_request and status == 404:
                    raise GmailHistoryExpiredError(
                        "Gmail no longer retains the history needed for incremental sync."
                    ) from exc
                raise GmailAPIError(f"Gmail API request failed with status {status}.") from exc
            except GoogleAuthError as exc:
                raise GmailAuthenticationError(
                    "Failed to authenticate with Gmail using the stored OAuth tokens."
                ) from exc
            except (GmailAPIError, GmailAuthenticationError, GmailHistoryExpiredError):
                raise
            except Exception as exc:
                raise GmailAPIError(
                    "An unexpected error occurred while communicating with the Gmail API."
                ) from exc

    async def get_profile(self) -> dict[str, Any]:
        """Return the connected Gmail account's profile."""
        return await self._execute(
            lambda service: service.users().getProfile(userId="me").execute()
        )

    async def list_messages(
        self,
        *,
        query: str | None = None,
        label_ids: list[str] | None = None,
        page_token: str | None = None,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> dict[str, Any]:
        """List message IDs matching the given filters."""

        def _call(service: Resource) -> dict[str, Any]:
            request = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    labelIds=label_ids,
                    pageToken=page_token,
                    maxResults=max_results,
                )
            )
            return cast(dict[str, Any], request.execute())

        return await self._execute(_call)

    async def get_message(self, message_id: str, *, format: str = "full") -> dict[str, Any]:
        """Fetch a single message by Gmail message ID."""
        return await self._execute(
            lambda service: service.users()
            .messages()
            .get(userId="me", id=message_id, format=format)
            .execute()
        )

    async def list_history(
        self, *, start_history_id: str, page_token: str | None = None
    ) -> dict[str, Any]:
        """List mailbox changes since `start_history_id`."""

        def _call(service: Resource) -> dict[str, Any]:
            request = (
                service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=start_history_id,
                    pageToken=page_token,
                )
            )
            return cast(dict[str, Any], request.execute())

        return await self._execute(_call, history_request=True)

    async def send_message(
        self, *, raw_message: str, thread_id: str | None = None
    ) -> dict[str, Any]:

        def _call(service: Resource) -> dict[str, Any]:
            body: dict[str, Any] = {"raw": raw_message}
            if thread_id is not None:
                body["threadId"] = thread_id
            return cast(
                dict[str, Any], service.users().messages().send(userId="me", body=body).execute()
            )

        return await self._execute(_call)

    @staticmethod
    def _build_mime_message(
        *,
        to: list[str],
        cc: list[str],
        bcc: list[str],
        subject: str,
        body_text: str | None,
        body_html: str | None,
    ) -> MIMEMultipart | MIMEText:

        if body_text and body_html:
            message: MIMEMultipart | MIMEText = MIMEMultipart("alternative")
            message.attach(MIMEText(body_text, "plain", "utf-8"))
            message.attach(MIMEText(body_html, "html", "utf-8"))
        elif body_html:
            message = MIMEText(body_html, "html", "utf-8")
        else:
            message = MIMEText(body_text or "", "plain", "utf-8")

        message["To"] = ", ".join(to)
        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)
        message["Subject"] = subject
        return message

    @staticmethod
    def _encode_base64url(message: MIMEMultipart | MIMEText) -> str:
        """Base64URL-encode a MIME message's full byte serialization —
        Gmail's `users.messages.send` requires the `raw` field in
        exactly this encoding."""
        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    async def send_email(
        self,
        *,
        to: list[str],
        subject: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        body_text: str | None = None,
        body_html: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        message = self._build_mime_message(
            to=to,
            cc=cc or [],
            bcc=bcc or [],
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        raw_message = self._encode_base64url(message)
        return await self.send_message(raw_message=raw_message, thread_id=thread_id)
