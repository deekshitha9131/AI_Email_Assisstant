from app.ai.schemas.ai_understanding import (
    EmailCategory,
    EmailIntent,
    EmailSentiment,
    EmailUrgency,
)
from app.ai.schemas.preprocessing import PreprocessedEmail

_CATEGORY_VALUES = ", ".join(category.value for category in EmailCategory)
_INTENT_VALUES = ", ".join(intent.value for intent in EmailIntent)
_URGENCY_VALUES = ", ".join(urgency.value for urgency in EmailUrgency)
_SENTIMENT_VALUES = ", ".join(sentiment.value for sentiment in EmailSentiment)

SYSTEM_PROMPT = (
    "You are an email understanding assistant. Given an email's sender, "
    "recipients, subject, and body, classify it and extract structured "
    "information as one JSON object. Do not respond with markdown or "
    "any text outside the JSON object.\n\n"
    f"category: exactly one of {_CATEGORY_VALUES}\n"
    f"intent: exactly one of {_INTENT_VALUES}\n"
    f"urgency: exactly one of {_URGENCY_VALUES}\n"
    f"sentiment: exactly one of {_SENTIMENT_VALUES}\n"
    "entities: a list of {type, value} pairs for concrete details "
    "mentioned in the email — people, organizations, dates, amounts, "
    "locations, order/confirmation numbers, and similar. Omit anything "
    "you are not reasonably confident about; an empty list is fine if "
    "nothing concrete is mentioned.\n"
    "summary: one or two concise sentences summarizing what the email "
    "is about.\n"
    "confidence: your confidence in this overall classification, as a "
    "number from 0.0 to 1.0.\n"
    "follow_up_needed: true only when the email explicitly requires a "
    "future action, response, or check-in; otherwise false.\n"
    "follow_up_date: an ISO 8601 datetime for the requested follow-up "
    "date when one is explicitly stated, otherwise null. It must be null "
    "when follow_up_needed is false.\n"
    "follow_up_reason: a concise explanation of why follow-up is needed, "
    "otherwise null.\n"
)


def build_user_prompt(email: PreprocessedEmail) -> str:
    recipients = ", ".join(email.recipients) if email.recipients else "(none)"
    return (
        f"From: {email.sender}\n"
        f"To: {recipients}\n"
        f"Subject: {email.subject or '(no subject)'}\n\n"
        f"{email.body}"
    )
