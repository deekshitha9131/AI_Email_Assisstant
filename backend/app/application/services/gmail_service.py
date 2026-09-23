from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import asyncio
from typing import Any, TypeVar

import structlog

from app.application.dto.gmail import (
    GmailSentMessage,
    GmailSentMessages,
    GmailIncrementalSyncSummary,
    GmailSendResult,
    GmailSyncSummary,
    ParsedEmail,
)
from app.core.config import Settings
from app.core.constants import GMAIL_LIST_PAGE_SIZE
from app.ai.rag.indexing_service import EmailIndexingService
from app.domain.entities.user import User
from app.domain.exceptions.gmail import (
    GmailAuthenticationError,
    GmailHistoryExpiredError,
    GmailNotConnectedError,
    GmailSyncInProgressError,
    GmailSyncRequiredError,
)
from app.infrastructure.database.repositories.email_repository import EmailRepository
from app.infrastructure.database.repositories.thread_repository import ThreadRepository
from app.infrastructure.database.repositories.user_repository import UserRepository
from app.infrastructure.gmail.client import GmailClient
from app.infrastructure.gmail.parser import EmailParser

logger = structlog.get_logger(__name__)

_RELEVANT_HISTORY_KEYS = ("messagesAdded", "labelsAdded", "labelsRemoved")
_INITIAL_SYNC_MESSAGE_LIMIT = 10
_INCREMENTAL_SYNC_LOCKS: dict[Any, asyncio.Lock] = {}
T = TypeVar("T")


@dataclass
class _MessageSyncOutcome:
    skipped: bool
    thread_id: str | None
    attachments_count: int


class GmailService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        thread_repository: ThreadRepository,
        email_repository: EmailRepository,
        indexing_service: EmailIndexingService | None = None,
        settings: Settings,
        parser: EmailParser | None = None,
    ) -> None:
        self._user_repository = user_repository
        self._thread_repository = thread_repository
        self._email_repository = email_repository
        self._indexing_service = indexing_service
        self._settings = settings
        self._parser = parser or EmailParser()

    async def _save_refreshed_token(self, user: User, gmail_client: GmailClient) -> GmailClient:
        refreshed_token = await gmail_client.refresh_access_token()
        await self._user_repository.save_oauth_tokens(
            user.id,
            access_token=refreshed_token.access_token,
            refresh_token=refreshed_token.refresh_token,
            token_expiry=refreshed_token.token_expiry,
            granted_scopes=refreshed_token.granted_scopes,
        )
        return GmailClient(oauth_token=refreshed_token, settings=self._settings)

    async def _get_connected_client(self, user: User) -> GmailClient:
        oauth_token = await self._user_repository.get_oauth_tokens(user.id)
        if oauth_token is None:
            raise GmailNotConnectedError(
                "Gmail is not connected for this account. Please connect Gmail first."
            )
        gmail_client = GmailClient(oauth_token=oauth_token, settings=self._settings)
        if oauth_token.is_expired:
            gmail_client = await self._save_refreshed_token(user, gmail_client)
        return gmail_client

    async def _call_with_auth_retry(
        self,
        user: User,
        gmail_client: GmailClient,
        operation: Callable[[GmailClient], Awaitable[T]],
    ) -> tuple[T, GmailClient]:
        try:
            return await operation(gmail_client), gmail_client
        except GmailAuthenticationError:
            refreshed_client = await self._save_refreshed_token(user, gmail_client)
            return await operation(refreshed_client), refreshed_client

    async def _fetch_parse_and_store(
        self, gmail_client: GmailClient, user: User, message_id: str
    ) -> tuple[_MessageSyncOutcome, GmailClient]:
        """Fetch one full Gmail message, parse it, and upsert its thread
        and email records. Shared by sync_mailbox and sync_incremental."""
        raw_message, gmail_client = await self._call_with_auth_retry(
            user,
            gmail_client,
            lambda client: client.get_message(message_id),
        )

        try:
            parsed: ParsedEmail = self._parser.parse_message(raw_message)
        except Exception as exc:
            logger.warning(
                "gmail_sync_skipped_unparseable_message",
                user_id=str(user.id),
                message_id=message_id,
                error=str(exc),
            )
            return (
                _MessageSyncOutcome(skipped=True, thread_id=None, attachments_count=0),
                gmail_client,
            )

        thread = await self._thread_repository.upsert(
            user_id=user.id,
            gmail_thread_id=parsed.gmail_thread_id,
            subject=parsed.subject,
            snippet=parsed.snippet,
            history_id=None,
        )
        email, _ = await self._email_repository.upsert(
            thread_id=thread.id, user_id=user.id, parsed=parsed
        )

        if self._indexing_service is not None:
            try:
                from app.workers.ai_tasks.indexing_tasks import index_email_task
                # Fire and forget the indexing task
                index_email_task.delay(str(email.id))
            except Exception as exc:
                logger.warning(
                    "gmail_embedding_failed_after_email_persisted",
                    user_id=str(user.id),
                    message_id=message_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    exc_info=True,
                )
                # Fire and forget the AI analysis task (understanding)
                try:
                    from app.workers.classification_tasks.analysis_tasks import analyze_email_task
                    analyze_email_task.delay(str(email.id))
                except Exception as exc:
                    logger.warning(
                        'gmail_analysis_failed_after_email_persisted',
                        user_id=str(user.id),
                        message_id=message_id,
                        error_type=type(exc).__name__,
                        error=str(exc),
                        exc_info=True,
                    )

        return (
            _MessageSyncOutcome(
                skipped=False, thread_id=str(thread.id), attachments_count=len(parsed.attachments)
            ),
            gmail_client,
        )

    async def sync_mailbox(self, user: User, *, page_token: str | None = None) -> GmailSyncSummary:
        gmail_client = await self._get_connected_client(user)

        threads_synced: set[str] = set()
        emails_synced = 0
        emails_skipped = 0
        attachments_found = 0
        next_page_token = page_token
        while True:
            list_response, gmail_client = await self._call_with_auth_retry(
                user,
                gmail_client,
                lambda client, token=next_page_token: client.list_messages(
                    label_ids=["INBOX"],
                    page_token=token,
                    max_results=GMAIL_LIST_PAGE_SIZE,
                ),
            )
            message_refs = list_response.get("messages") or []

            for ref in message_refs:
                message_id = ref.get("id") if isinstance(ref, dict) else None
                if not message_id:
                    logger.warning(
                        "gmail_sync_skipped_invalid_message_reference",
                        user_id=str(user.id),
                        message_reference=ref,
                    )
                    emails_skipped += 1
                    continue
                outcome, gmail_client = await self._fetch_parse_and_store(
                    gmail_client, user, message_id
                )
                if outcome.skipped:
                    emails_skipped += 1
                else:
                    emails_synced += 1
                    attachments_found += outcome.attachments_count
                    if outcome.thread_id is not None:
                        threads_synced.add(outcome.thread_id)
            next_page_token = list_response.get("nextPageToken")
            if not next_page_token or not message_refs:
                break

        if next_page_token is None:
            profile, gmail_client = await self._call_with_auth_retry(
                user,
                gmail_client,
                lambda client: client.get_profile(),
            )
            profile_history_id = profile.get("historyId")
            if profile_history_id:
                await self._user_repository.update_gmail_history_id(
                    user.id, str(profile_history_id)
                )

        logger.info(
            "gmail_sync_complete",
            user_id=str(user.id),
            threads_synced=len(threads_synced),
            emails_synced=emails_synced,
            emails_skipped=emails_skipped,
            attachments_found=attachments_found,
            resumable=next_page_token is not None,
        )

        return GmailSyncSummary(
            success=True,
            threads_synced=len(threads_synced),
            emails_synced=emails_synced,
            attachments_found=attachments_found,
            emails_skipped=emails_skipped,
            next_page_token=next_page_token,
        )

    @staticmethod
    def _extract_changed_message_ids(history_records: list[dict[str, Any]]) -> list[str]:
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for record in history_records:
            for key in _RELEVANT_HISTORY_KEYS:
                for entry in record.get(key, []) or []:
                    message = entry.get("message") or {}
                    message_id = message.get("id")
                    if message_id and message_id not in seen:
                        seen.add(message_id)
                        ordered_ids.append(message_id)
        return ordered_ids

    async def sync_incremental(self, user: User) -> GmailIncrementalSyncSummary:
        lock = _INCREMENTAL_SYNC_LOCKS.setdefault(user.id, asyncio.Lock())
        if lock.locked():
            raise GmailSyncInProgressError(
                "An incremental Gmail sync is already running for this user."
            )
        await lock.acquire()

        try:
            return await self._sync_incremental_locked(user)
        finally:
            lock.release()
            if not lock.locked() and _INCREMENTAL_SYNC_LOCKS.get(user.id) is lock:
                _INCREMENTAL_SYNC_LOCKS.pop(user.id, None)

    async def _sync_incremental_locked(self, user: User) -> GmailIncrementalSyncSummary:
        gmail_client = await self._get_connected_client(user)

        stored_history_id = await self._user_repository.get_gmail_history_id(user.id)
        if stored_history_id is None:
            logger.info(
                "gmail_incremental_bootstrap_started",
                user_id=str(user.id),
                message_limit=_INITIAL_SYNC_MESSAGE_LIMIT,
            )
            threads_updated: set[str] = set()
            emails_synced = 0
            emails_skipped = 0
            attachments_found = 0

            list_response, gmail_client = await self._call_with_auth_retry(
                user,
                gmail_client,
                lambda client: client.list_messages(
                    label_ids=["INBOX"],
                    max_results=_INITIAL_SYNC_MESSAGE_LIMIT,
                ),
            )
            for ref in (list_response.get("messages") or [])[:_INITIAL_SYNC_MESSAGE_LIMIT]:
                message_id = ref.get("id") if isinstance(ref, dict) else None
                if not message_id:
                    emails_skipped += 1
                    continue
                outcome, gmail_client = await self._fetch_parse_and_store(
                    gmail_client, user, message_id
                )
                if outcome.skipped:
                    emails_skipped += 1
                else:
                    emails_synced += 1
                    attachments_found += outcome.attachments_count
                    if outcome.thread_id is not None:
                        threads_updated.add(outcome.thread_id)

            profile, gmail_client = await self._call_with_auth_retry(
                user,
                gmail_client,
                lambda client: client.get_profile(),
            )
            latest_history_id = profile.get("historyId")
            if not latest_history_id:
                raise GmailSyncRequiredError(
                    "Gmail did not return a history cursor after the bootstrap sync."
                )
            await self._user_repository.update_gmail_history_id(user.id, str(latest_history_id))
            return GmailIncrementalSyncSummary(
                success=True,
                emails_synced=emails_synced,
                threads_updated=len(threads_updated),
                attachments_found=attachments_found,
                emails_skipped=emails_skipped,
                history_id=str(latest_history_id),
            )

        threads_updated: set[str] = set()
        emails_synced = 0
        emails_skipped = 0
        attachments_found = 0
        messages_processed = 0
        latest_history_id = stored_history_id
        page_token: str | None = None
        seen_message_ids: set[str] = set()

        try:
            while True:
                history_response, gmail_client = await self._call_with_auth_retry(
                    user,
                    gmail_client,
                    lambda client, history_page_token=page_token: client.list_history(
                        start_history_id=stored_history_id, page_token=history_page_token
                    ),
                )

                response_history_id = history_response.get("historyId")
                if response_history_id:
                    latest_history_id = str(response_history_id)

                history_records = history_response.get("history") or []
                changed_message_ids = self._extract_changed_message_ids(history_records)

                for message_id in changed_message_ids:
                    if message_id in seen_message_ids:
                        continue
                    seen_message_ids.add(message_id)
                    outcome, gmail_client = await self._fetch_parse_and_store(
                        gmail_client, user, message_id
                    )
                    messages_processed += 1

                    if outcome.skipped:
                        emails_skipped += 1
                    else:
                        emails_synced += 1
                        attachments_found += outcome.attachments_count
                        if outcome.thread_id is not None:
                            threads_updated.add(outcome.thread_id)

                page_token = history_response.get("nextPageToken")
                if page_token is None:
                    break
        except GmailHistoryExpiredError:
            logger.info(
                "gmail_incremental_history_expired_full_sync_started",
                user_id=str(user.id),
            )
            full_sync = await self.sync_mailbox(user)
            latest_history_id = await self._user_repository.get_gmail_history_id(user.id)
            if latest_history_id is None:
                raise GmailHistoryExpiredError(
                    "Gmail history expired and a replacement sync cursor was not returned."
                )
            return GmailIncrementalSyncSummary(
                success=True,
                emails_synced=full_sync.emails_synced,
                threads_updated=full_sync.threads_synced,
                attachments_found=full_sync.attachments_found,
                emails_skipped=full_sync.emails_skipped,
                history_id=latest_history_id,
            )

        await self._user_repository.update_gmail_history_id(user.id, latest_history_id)

        logger.info(
            "gmail_incremental_sync_complete",
            user_id=str(user.id),
            threads_updated=len(threads_updated),
            emails_synced=emails_synced,
            emails_skipped=emails_skipped,
            attachments_found=attachments_found,
            history_id=latest_history_id,
        )

        return GmailIncrementalSyncSummary(
            success=True,
            emails_synced=emails_synced,
            threads_updated=len(threads_updated),
            attachments_found=attachments_found,
            emails_skipped=emails_skipped,
            history_id=latest_history_id,
        )

    async def send_email(
        self,
        user: User,
        *,
        to: list[str],
        subject: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        body_text: str | None = None,
        body_html: str | None = None,
        thread_id: str | None = None,
    ) -> GmailSendResult:
        gmail_client = await self._get_connected_client(user)

        response, _ = await self._call_with_auth_retry(
            user,
            gmail_client,
            lambda client: client.send_email(
                to=to,
                subject=subject,
                cc=cc,
                bcc=bcc,
                body_text=body_text,
                body_html=body_html,
                thread_id=thread_id,
            ),
        )

        gmail_message_id = response["id"]
        gmail_thread_id = response.get("threadId") or thread_id or ""

        logger.info(
            "gmail_email_sent",
            user_id=str(user.id),
            gmail_message_id=gmail_message_id,
            gmail_thread_id=gmail_thread_id,
            is_reply=thread_id is not None,
        )

        return GmailSendResult(
            success=True,
            gmail_message_id=gmail_message_id,
            gmail_thread_id=gmail_thread_id,
        )

    async def list_sent_messages(
        self, user: User, *, page_token: str | None = None, max_results: int = 25
    ) -> GmailSentMessages:
        """Read one page of sent messages from the user's Gmail mailbox."""
        gmail_client = await self._get_connected_client(user)
        response, gmail_client = await self._call_with_auth_retry(
            user,
            gmail_client,
            lambda client: client.list_messages(
                label_ids=["SENT"], page_token=page_token, max_results=max_results
            ),
        )

        items: list[GmailSentMessage] = []
        for message_reference in response.get("messages") or []:
            message_id = message_reference.get("id") if isinstance(message_reference, dict) else None
            if not message_id:
                continue
            raw_message, gmail_client = await self._call_with_auth_retry(
                user, gmail_client, lambda client, id=message_id: client.get_message(id)
            )
            try:
                parsed = self._parser.parse_message(raw_message)
            except Exception as exc:
                logger.warning(
                    "gmail_sent_message_skipped_unparseable",
                    user_id=str(user.id),
                    message_id=message_id,
                    error=str(exc),
                )
                continue
            items.append(
                GmailSentMessage(
                    gmail_message_id=parsed.gmail_message_id,
                    gmail_thread_id=parsed.gmail_thread_id,
                    sender=parsed.sender,
                    recipients=parsed.recipients,
                    cc=parsed.cc,
                    bcc=parsed.bcc,
                    subject=parsed.subject,
                    snippet=parsed.snippet,
                    body_text=parsed.body_text,
                    body_html=parsed.body_html,
                    sent_at=parsed.internal_date,
                )
            )

        return GmailSentMessages(items=items, next_page_token=response.get("nextPageToken"))
