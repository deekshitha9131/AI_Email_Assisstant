"""Tests for app/infrastructure/gmail/parser.py.

Every fixture below is a hand-built dict matching Gmail API's actual
message shape (not a mock of the parser itself) — this exercises the
real recursive MIME-walking and Base64URL-decoding logic end to end,
the same "fake the far end, exercise the real code" philosophy as
test_gmail_client.py and test_oauth_client.py.
"""

import base64
from datetime import UTC, datetime

import pytest

from app.application.dto.gmail import ParsedEmail
from app.domain.exceptions.gmail import GmailParseError
from app.infrastructure.gmail.parser import EmailParser


def _b64url(text: str) -> str:
    """Encode text the way Gmail does: Base64URL, no padding — mirrors
    what the parser's own `_decode_base64url` expects to reverse."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _headers(**kwargs: str) -> list[dict[str, str]]:
    return [{"name": name, "value": value} for name, value in kwargs.items()]


@pytest.fixture
def parser() -> EmailParser:
    return EmailParser()


# ---------------------------------------------------------------------------
# Simple (non-multipart) plain text message
# ---------------------------------------------------------------------------


def test_parses_simple_plain_text_message(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "snippet": "Hey, just checking in...",
        "internalDate": "1735689600000",  # 2025-01-01T00:00:00Z
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(
                Subject="Quick check-in",
                From="Jane Doe <jane@example.com>",
                To="bob@example.com",
            ),
            "body": {"data": _b64url("Hey, just checking in on the project.")},
        },
    }

    result = parser.parse_message(raw_message)

    assert isinstance(result, ParsedEmail)
    assert result.gmail_message_id == "msg-1"
    assert result.gmail_thread_id == "thread-1"
    assert result.subject == "Quick check-in"
    assert result.sender == "jane@example.com"
    assert result.recipients == ["bob@example.com"]
    assert result.cc == []
    assert result.bcc == []
    assert result.snippet == "Hey, just checking in..."
    assert result.internal_date == datetime(2025, 1, 1, tzinfo=UTC)
    assert result.label_ids == ["INBOX", "UNREAD"]
    assert result.body_text == "Hey, just checking in on the project."
    assert result.body_html is None
    assert result.attachments == []
    assert result.has_attachments is False


# ---------------------------------------------------------------------------
# Multipart: plain + HTML alternative
# ---------------------------------------------------------------------------


def test_parses_multipart_alternative_plain_and_html(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-2",
        "threadId": "thread-2",
        "snippet": "See below",
        "internalDate": "1735689600000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": _headers(From="jane@example.com", To="bob@example.com, carol@example.com"),
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64url("Plain version.")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64url("<p>HTML version.</p>")},
                },
            ],
        },
    }

    result = parser.parse_message(raw_message)

    assert result.body_text == "Plain version."
    assert result.body_html == "<p>HTML version.</p>"
    assert result.recipients == ["bob@example.com", "carol@example.com"]
    # No Subject header at all — must default to None, not raise or blank-string.
    assert result.subject is None


# ---------------------------------------------------------------------------
# Nested multipart (mixed containing alternative) + attachment
# ---------------------------------------------------------------------------


def test_parses_nested_multipart_with_attachment(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-3",
        "threadId": "thread-3",
        "snippet": "Report attached",
        "internalDate": "1735689600000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": _headers(
                Subject="Q4 report",
                From="jane@example.com",
                To="bob@example.com",
                Cc="carol@example.com",
                Bcc="dave@example.com",
            ),
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64url("See attached report.")},
                        },
                        {
                            "mimeType": "text/html",
                            "body": {"data": _b64url("<p>See attached report.</p>")},
                        },
                    ],
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "q4-report.pdf",
                    "body": {"attachmentId": "att-1", "size": 20480},
                },
            ],
        },
    }

    result = parser.parse_message(raw_message)

    assert result.body_text == "See attached report."
    assert result.body_html == "<p>See attached report.</p>"
    assert result.cc == ["carol@example.com"]
    assert result.bcc == ["dave@example.com"]
    assert result.has_attachments is True
    assert len(result.attachments) == 1

    attachment = result.attachments[0]
    assert attachment.attachment_id == "att-1"
    assert attachment.filename == "q4-report.pdf"
    assert attachment.mime_type == "application/pdf"
    assert attachment.size == 20480


def test_parses_multiple_attachments(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-4",
        "threadId": "thread-4",
        "snippet": "Two files",
        "internalDate": "1735689600000",
        "labelIds": [],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": _headers(From="jane@example.com", To="bob@example.com"),
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64url("Files attached.")}},
                {
                    "mimeType": "image/png",
                    "filename": "screenshot.png",
                    "body": {"attachmentId": "att-a", "size": 1024},
                },
                {
                    "mimeType": "text/csv",
                    "filename": "data.csv",
                    "body": {"attachmentId": "att-b", "size": 512},
                },
            ],
        },
    }

    result = parser.parse_message(raw_message)

    assert {a.filename for a in result.attachments} == {"screenshot.png", "data.csv"}
    assert result.has_attachments is True


def test_preserves_long_gmail_attachment_id(parser: EmailParser) -> None:
    long_attachment_id = "attachment-" + "x" * 300
    raw_message = {
        "id": "msg-long-attachment",
        "threadId": "thread-long-attachment",
        "snippet": "Long attachment ID",
        "internalDate": "1735689600000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": _headers(From="jane@example.com", To="bob@example.com"),
            "parts": [
                {
                    "mimeType": "application/octet-stream",
                    "filename": "large-token.bin",
                    "body": {"attachmentId": long_attachment_id, "size": 10},
                }
            ],
        },
    }

    result = parser.parse_message(raw_message)

    assert result.attachments[0].attachment_id == long_attachment_id


# ---------------------------------------------------------------------------
# Edge cases: missing body, missing attachments, missing optional headers
# ---------------------------------------------------------------------------


def test_message_with_no_body_parses_with_none_bodies(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-5",
        "threadId": "thread-5",
        "snippet": "",
        "internalDate": "1735689600000",
        "labelIds": [],
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(From="jane@example.com", To="bob@example.com"),
            "body": {},  # no "data" key at all
        },
    }

    result = parser.parse_message(raw_message)

    assert result.body_text is None
    assert result.body_html is None
    assert result.attachments == []


def test_message_with_no_attachments_returns_empty_list(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-6",
        "threadId": "thread-6",
        "snippet": "No attachments here",
        "internalDate": "1735689600000",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(From="jane@example.com", To="bob@example.com"),
            "body": {"data": _b64url("Just text.")},
        },
    }

    result = parser.parse_message(raw_message)

    assert result.attachments == []
    assert result.has_attachments is False


def test_missing_optional_headers_default_gracefully(parser: EmailParser) -> None:
    """No Subject, no Cc, no Bcc — none of these are required, all must
    default rather than raise."""
    raw_message = {
        "id": "msg-7",
        "threadId": "thread-7",
        "snippet": "Minimal message",
        "internalDate": "1735689600000",
        "labelIds": [],
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(From="jane@example.com", To="bob@example.com"),
            "body": {"data": _b64url("Minimal.")},
        },
    }

    result = parser.parse_message(raw_message)

    assert result.subject is None
    assert result.cc == []
    assert result.bcc == []


def test_header_lookup_is_case_insensitive(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-8",
        "threadId": "thread-8",
        "snippet": "",
        "internalDate": "1735689600000",
        "labelIds": [],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "from", "value": "jane@example.com"},  # lowercase
                {"name": "SUBJECT", "value": "Shouted subject"},  # uppercase
                {"name": "To", "value": "bob@example.com"},
            ],
            "body": {"data": _b64url("Body.")},
        },
    }

    result = parser.parse_message(raw_message)

    assert result.sender == "jane@example.com"
    assert result.subject == "Shouted subject"


# ---------------------------------------------------------------------------
# Malformed payloads — must raise GmailParseError, not crash uncontrolled
# ---------------------------------------------------------------------------


def test_missing_message_id_raises_parse_error(parser: EmailParser) -> None:
    raw_message = {
        "threadId": "thread-9",
        "internalDate": "1735689600000",
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(From="jane@example.com"),
            "body": {},
        },
    }

    with pytest.raises(GmailParseError):
        parser.parse_message(raw_message)


def test_missing_thread_id_raises_parse_error(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-10",
        "internalDate": "1735689600000",
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(From="jane@example.com"),
            "body": {},
        },
    }

    with pytest.raises(GmailParseError):
        parser.parse_message(raw_message)


def test_missing_payload_raises_parse_error(parser: EmailParser) -> None:
    raw_message = {"id": "msg-11", "threadId": "thread-11", "internalDate": "1735689600000"}

    with pytest.raises(GmailParseError):
        parser.parse_message(raw_message)


def test_missing_from_header_raises_parse_error(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-12",
        "threadId": "thread-12",
        "internalDate": "1735689600000",
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(To="bob@example.com"),  # no From at all
            "body": {"data": _b64url("Body.")},
        },
    }

    with pytest.raises(GmailParseError):
        parser.parse_message(raw_message)


def test_missing_internal_date_raises_parse_error(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-13",
        "threadId": "thread-13",
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(From="jane@example.com"),
            "body": {"data": _b64url("Body.")},
        },
    }

    with pytest.raises(GmailParseError):
        parser.parse_message(raw_message)


def test_non_numeric_internal_date_raises_parse_error(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-14",
        "threadId": "thread-14",
        "internalDate": "not-a-timestamp",
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(From="jane@example.com"),
            "body": {"data": _b64url("Body.")},
        },
    }

    with pytest.raises(GmailParseError):
        parser.parse_message(raw_message)


def test_invalid_base64_body_raises_parse_error(parser: EmailParser) -> None:
    raw_message = {
        "id": "msg-15",
        "threadId": "thread-15",
        "internalDate": "1735689600000",
        "payload": {
            "mimeType": "text/plain",
            "headers": _headers(From="jane@example.com"),
            # "!!!not-valid-base64!!!" contains characters outside the
            # Base64URL alphabet — must be rejected, not silently
            # produce garbage bytes.
            "body": {"data": "!!!not-valid-base64!!!"},
        },
    }

    with pytest.raises(GmailParseError):
        parser.parse_message(raw_message)
