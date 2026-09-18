"""Gmail request/response schemas.

The API contract boundary for the /gmail/* endpoints — mirror the
application DTOs (app/application/dto/gmail.py) field-for-field via
`from_attributes`, same pattern UserRead uses for the User domain
entity. GmailSendRequest (Task 3.5) also enforces "invalid recipient"
and "no body content" at this boundary via Pydantic — before the
service or Gmail API are ever involved, consistent with UserCreate's
existing use of EmailStr.
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class GmailSyncRequest(BaseModel):
    """Optional resume token from a previous sync's response — omitted
    (or null) starts a fresh sync from the beginning of the mailbox."""

    page_token: str | None = Field(default=None)


class GmailSyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    threads_synced: int
    emails_synced: int
    attachments_found: int
    emails_skipped: int
    next_page_token: str | None = None


class GmailIncrementalSyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    emails_synced: int
    threads_updated: int
    attachments_found: int
    emails_skipped: int
    history_id: str


class GmailSendRequest(BaseModel):
    """`to` requires at least one address (`min_length=1`) — a send
    request with zero recipients isn't a business-rule edge case, it's
    a malformed request, so it's rejected here at the schema boundary
    rather than reaching the service. `EmailStr` on every recipient
    list is what makes "invalid recipient" a 400 VALIDATION_ERROR
    automatically, with no custom validation code needed."""

    to: list[EmailStr] = Field(min_length=1)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    subject: str = Field(min_length=1, max_length=998)
    body_text: str | None = Field(default=None)
    body_html: str | None = Field(default=None)
    thread_id: str | None = Field(
        default=None,
        description="If provided, Gmail sends this as a reply within the "
        "given thread. If omitted, Gmail starts a new conversation.",
    )

    @field_validator("to", "cc", "bcc", mode="before")
    @classmethod
    def normalize_recipients(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [recipient.strip() if isinstance(recipient, str) else recipient for recipient in value]

    @model_validator(mode="after")
    def validate_at_least_one_body(self) -> "GmailSendRequest":
        if not self.body_text and not self.body_html:
            raise ValueError("At least one of body_text or body_html must be provided.")
        return self


class GmailSendResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    gmail_message_id: str
    gmail_thread_id: str
