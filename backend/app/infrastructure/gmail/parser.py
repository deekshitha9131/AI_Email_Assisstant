import base64
import binascii
import html
from datetime import UTC, datetime
from email.utils import getaddresses
from html.parser import HTMLParser
from typing import Any

from app.application.dto.gmail import ParsedAttachment, ParsedEmail
from app.domain.exceptions.gmail import GmailParseError

_MIME_TEXT_PLAIN = "text/plain"
_MIME_TEXT_HTML = "text/html"


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.chunks.append(data)


def _html_to_text(html_content: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html_content)
    extractor.close()
    lines = [" ".join(line.split()) for line in "".join(extractor.chunks).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _decode_base64url(data: str) -> bytes:
    padding_needed = -len(data) % 4
    padded = data + "=" * padding_needed
    try:
        return base64.b64decode(padded.replace("-", "+").replace("_", "/"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GmailParseError("Failed to decode Base64URL message body data.") from exc


def _decode_body_text(data: str) -> str:
    return _decode_base64url(data).decode("utf-8", errors="replace")


def _headers_map(payload: dict[str, Any]) -> dict[str, str]:
    return {
        header["name"].lower(): header.get("value", "")
        for header in payload.get("headers", [])
        if "name" in header
    }


def _get_header(headers: dict[str, str], name: str) -> str | None:
    value = headers.get(name.lower())
    return value if value else None


def _parse_address_list(header_value: str | None) -> list[str]:
    if not header_value:
        return []
    return [address for _display_name, address in getaddresses([header_value]) if address]


def _parse_sender(header_value: str | None) -> str:
    addresses = _parse_address_list(header_value)
    if not addresses:
        raise GmailParseError("Gmail message is missing a usable From header.")
    return addresses[0]


def _parse_internal_date(raw_message: dict[str, Any]) -> datetime:
    raw_value = raw_message.get("internalDate")
    if raw_value is None:
        raise GmailParseError("Gmail message is missing internalDate.")
    try:
        epoch_ms = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise GmailParseError(
            f"Gmail message has a non-numeric internalDate: {raw_value!r}"
        ) from exc
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)


def _is_attachment_part(part: dict[str, Any]) -> bool:

    return bool(part.get("filename"))


def _walk_part(
    part: dict[str, Any],
    *,
    plain_text_chunks: list[str],
    html_chunks: list[str],
    attachments: list[ParsedAttachment],
) -> None:
    mime_type = part.get("mimeType", "")
    body = part.get("body", {}) or {}

    if _is_attachment_part(part):
        attachment_id = body.get("attachmentId")
        if attachment_id is not None:
            attachments.append(
                ParsedAttachment(
                    attachment_id=attachment_id,
                    filename=part["filename"],
                    mime_type=mime_type or "application/octet-stream",
                    size=int(body.get("size", 0)),
                )
            )
        return

    data = body.get("data")
    if mime_type == _MIME_TEXT_PLAIN and data:
        plain_text_chunks.append(_decode_body_text(data))
    elif mime_type == _MIME_TEXT_HTML and data:
        html_chunks.append(_decode_body_text(data))

    for child_part in part.get("parts", []) or []:
        _walk_part(
            child_part,
            plain_text_chunks=plain_text_chunks,
            html_chunks=html_chunks,
            attachments=attachments,
        )


class EmailParser:

    def parse_message(self, raw_message: dict[str, Any]) -> ParsedEmail:

        message_id = raw_message.get("id")
        thread_id = raw_message.get("threadId")
        payload = raw_message.get("payload")

        if not message_id:
            raise GmailParseError("Gmail message is missing its id.")
        if not thread_id:
            raise GmailParseError("Gmail message is missing its threadId.")
        if not payload:
            raise GmailParseError("Gmail message is missing its payload.")

        headers = _headers_map(payload)

        plain_text_chunks: list[str] = []
        html_chunks: list[str] = []
        attachments: list[ParsedAttachment] = []
        _walk_part(
            payload,
            plain_text_chunks=plain_text_chunks,
            html_chunks=html_chunks,
            attachments=attachments,
        )

        body_text = "\n".join(plain_text_chunks) if plain_text_chunks else None
        body_html = "\n".join(html_chunks) if html_chunks else None
        if body_text is None and body_html:
            body_text = _html_to_text(body_html)

        return ParsedEmail(
            gmail_message_id=message_id,
            gmail_thread_id=thread_id,
            subject=_get_header(headers, "Subject"),
            sender=_parse_sender(_get_header(headers, "From")),
            recipients=_parse_address_list(_get_header(headers, "To")),
            cc=_parse_address_list(_get_header(headers, "Cc")),
            bcc=_parse_address_list(_get_header(headers, "Bcc")),
            snippet=html.unescape(raw_message.get("snippet", "")),
            internal_date=_parse_internal_date(raw_message),
            label_ids=list(raw_message.get("labelIds", [])),
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
        )
