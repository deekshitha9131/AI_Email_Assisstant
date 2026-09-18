from typing import Final

PROJECT_NAME: Final[str] = "AI Email Assistant Platform"
PROJECT_DESCRIPTION: Final[str] = (
    "An AI-native assistant that triages, understands, and drafts replies "
    "to Gmail email, with a human-approval gate on every outbound message."
)
PROJECT_VERSION: Final[str] = "0.1.0"

API_V1_PREFIX: Final[str] = "/api/v1"


class OpenAPITags:
    HEALTH: Final[str] = "Health"
    AUTH: Final[str] = "Auth"
    GMAIL: Final[str] = "Gmail"
    EMAILS: Final[str] = "Emails"
    THREADS: Final[str] = "Threads"
    AI_UNDERSTANDING: Final[str] = "AI Understanding"
    DRAFTS: Final[str] = "Drafts"


OPENAPI_TAGS_METADATA: Final[list[dict[str, str]]] = [
    {
        "name": OpenAPITags.HEALTH,
        "description": "Liveness and readiness checks for orchestration and monitoring.",
    },
    {
        "name": OpenAPITags.AUTH,
        "description": "Google OAuth handshake and session management.",
    },
    {
        "name": OpenAPITags.EMAILS,
        "description": (
            "Locally stored inbox — listing and detail retrieval, "
            "read entirely from PostgreSQL (never Gmail directly)."
        ),
    },
    {
        "name": OpenAPITags.THREADS,
        "description": "Email thread listing, filtering, and detail retrieval.",
    },
    {
        "name": OpenAPITags.AI_UNDERSTANDING,
        "description": "AI-generated email classification, intent, urgency, "
        "sentiment, entities, and summary.",
    },
    {
        "name": OpenAPITags.DRAFTS,
        "description": "AI-generated draft replies and the human-approval workflow.",
    },
    ]

# --- Pagination defaults ---
DEFAULT_PAGE_SIZE: Final[int] = 25
MAX_PAGE_SIZE: Final[int] = 100

GMAIL_LIST_PAGE_SIZE: Final[int] = 100
MAX_MESSAGES_PER_SYNC: Final[int] = 1000
EMBEDDING_DIMENSIONS: Final[int] = 384
EMBEDDING_MODEL_NAME: Final[str] = "all-MiniLM-L6-v2"

# --- AI preprocessing ---
AI_PREPROCESSING_MAX_BODY_CHARACTERS: Final[int] = 8000

# --- RAG chunking (Task 6.2) ---
CHUNK_SIZE: Final[int] = 500
CHUNK_OVERLAP: Final[int] = 50

# --- RAG retrieval (Task 6.6) ---
# Architecturally decided (Phase 6.1): the number of chunks a
# similarity search returns by default.
TOP_K: Final[int] = 5

# --- Health check status values ---
HEALTH_STATUS_OK: Final[str] = "ok"
HEALTH_STATUS_DEGRADED: Final[str] = "degraded"
HEALTH_STATUS_ERROR: Final[str] = "error"

# --- Standard response header ---
REQUEST_ID_HEADER: Final[str] = "X-Request-ID"

GOOGLE_OAUTH_SCOPES: Final[list[str]] = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

GOOGLE_AUTHORIZATION_ENDPOINT: Final[str] = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT: Final[str] = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT: Final[str] = "https://www.googleapis.com/oauth2/v3/userinfo"

# --- Cookies ---
SESSION_COOKIE_NAME: Final[str] = "session_id"

OAUTH_STATE_COOKIE_NAME: Final[str] = "oauth_state"
OAUTH_STATE_COOKIE_MAX_AGE_SECONDS: Final[int] = 600  # 10 minutes
