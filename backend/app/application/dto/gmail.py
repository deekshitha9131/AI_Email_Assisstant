"""Gmail parsing and sync DTOs.

Per the frozen blueprint (docs/architecture/03-engineering-blueprint-original.md
§1.2): "Internal data-transfer objects between layers." ParsedEmail/
ParsedAttachment (Task 3.2) carry a single parsed Gmail message.
GmailSyncSummary (Task 3.3) / GmailIncrementalSyncSummary (Task 3.4)
carry sync results. GmailSendResult (Task 3.5) carries a send result.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ParsedAttachment:
    """Attachment metadata only — per Phase 3 scope, no file bytes are
    ever downloaded or stored here."""

    attachment_id: str
    filename: str
    mime_type: str
    size: int


@dataclass
class ParsedEmail:
    """A single Gmail message, normalized into application-friendly shape."""

    gmail_message_id: str
    gmail_thread_id: str
    sender: str
    recipients: list[str]
    snippet: str
    internal_date: datetime
    label_ids: list[str]
    subject: str | None = None
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    body_text: str | None = None
    body_html: str | None = None
    attachments: list[ParsedAttachment] = field(default_factory=list)

    @property
    def has_attachments(self) -> bool:
        return len(self.attachments) > 0


@dataclass
class GmailSyncSummary:
    """Result of one GmailService.sync_mailbox() call (initial sync,
    Task 3.3)."""

    success: bool
    threads_synced: int
    emails_synced: int
    attachments_found: int
    emails_skipped: int
    next_page_token: str | None = None


@dataclass
class GmailIncrementalSyncSummary:
    """Result of one GmailService.sync_incremental() call (Task 3.4)."""

    success: bool
    emails_synced: int
    threads_updated: int
    attachments_found: int
    emails_skipped: int
    history_id: str


@dataclass
class GmailSendResult:
    """Result of one GmailService.send_email() call (Task 3.5).

    `gmail_thread_id` always reflects Gmail's own response — for a
    reply this matches the `thread_id` the caller supplied; for a new
    conversation it's the thread Gmail created to hold this first
    message, which the caller had no way to know in advance.
    """

    success: bool
    gmail_message_id: str
    gmail_thread_id: str


@dataclass
class GmailSentMessage:
    """Parsed message returned by the authenticated Gmail Sent mailbox."""

    gmail_message_id: str
    gmail_thread_id: str
    sender: str
    recipients: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str | None
    snippet: str
    body_text: str | None
    body_html: str | None
    sent_at: datetime


@dataclass
class GmailSentMessages:
    """One page of messages from Gmail's Sent mailbox."""

    items: list[GmailSentMessage]
    next_page_token: str | None = None
