"""Gmail router.

Implements the sync endpoints from Task 3.3 (initial), Task 3.4
(incremental), and the send endpoint from Task 3.5. Every endpoint
delegates to GmailService — this file only translates between HTTP
concerns (request body, response model) and the service call.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.application.services.gmail_service import GmailService
from app.core.constants import OpenAPITags
from app.core.di_container import CurrentUser, get_gmail_service
from app.presentation.api.v1.schemas.gmail import (
    GmailIncrementalSyncResponse,
    GmailSendRequest,
    GmailSendResponse,
    GmailSentMessageResponse,
    GmailSentMessagesResponse,
    GmailSyncRequest,
    GmailSyncResponse,
)

router = APIRouter(prefix="/gmail", tags=[OpenAPITags.GMAIL])

GmailServiceDep = Annotated[GmailService, Depends(get_gmail_service)]


@router.get(
    "/sent",
    summary="List the authenticated user's sent emails",
    description="Reads a page of sent messages from the authenticated user's Gmail account."
    " Message content is parsed for display and access tokens are never returned.",
    response_model=GmailSentMessagesResponse,
)
async def list_sent_messages(
    current_user: CurrentUser,
    gmail_service: GmailServiceDep,
    page_token: str | None = Query(default=None),
    page_size: int = Query(default=25, ge=1, le=100),
) -> GmailSentMessagesResponse:
    result = await gmail_service.list_sent_messages(
        current_user, page_token=page_token, max_results=page_size
    )
    return GmailSentMessagesResponse(
        items=[GmailSentMessageResponse.model_validate(item) for item in result.items],
        next_page_token=result.next_page_token,
    )


@router.post(
    "/sync",
    summary="Initial Gmail mailbox sync",
    description="Fetches messages from the user's connected Gmail account, "
    "parses them, and stores threads/emails/attachment metadata. Bounded "
    "per call — pass the returned next_page_token back in to resume a "
    "sync that didn't finish the whole mailbox in one call.",
    response_model=GmailSyncResponse,
)
async def sync_mailbox(
    current_user: CurrentUser,
    gmail_service: GmailServiceDep,
    payload: GmailSyncRequest | None = None,
) -> GmailSyncResponse:
    request_payload = payload or GmailSyncRequest()
    summary = await gmail_service.sync_mailbox(current_user, page_token=request_payload.page_token)
    return GmailSyncResponse.model_validate(summary)


@router.post(
    "/sync/incremental",
    summary="Incremental Gmail mailbox sync",
    description="Syncs only messages changed since the last sync, using "
    "Gmail's History API. Requires a completed initial sync "
    "(POST /gmail/sync) first — returns 409 otherwise.",
    response_model=GmailIncrementalSyncResponse,
)
async def sync_incremental(
    current_user: CurrentUser,
    gmail_service: GmailServiceDep,
) -> GmailIncrementalSyncResponse:
    summary = await gmail_service.sync_incremental(current_user)
    return GmailIncrementalSyncResponse.model_validate(summary)


@router.post(
    "/send",
    summary="Send an email via Gmail",
    description="Sends an email through the user's connected Gmail account. "
    "Provide thread_id to send as a reply within an existing Gmail "
    "thread; omit it to start a new conversation. At least one of "
    "body_text or body_html is required.",
    response_model=GmailSendResponse,
)
async def send_email(
    current_user: CurrentUser,
    gmail_service: GmailServiceDep,
    payload: GmailSendRequest,
) -> GmailSendResponse:
    result = await gmail_service.send_email(
        current_user,
        to=payload.to,
        subject=payload.subject,
        cc=payload.cc,
        bcc=payload.bcc,
        body_text=payload.body_text,
        body_html=payload.body_html,
        thread_id=payload.thread_id,
    )
    return GmailSendResponse.model_validate(result)
