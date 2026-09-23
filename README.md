# AI Email Assistant

An AI-powered email management application that connects to Gmail, analyzes emails using LLMs, generates intelligent reply drafts, and orchestrates the entire workflow through n8n automation — with a strict **human-in-the-loop** approval gate on every outbound message.

Built with FastAPI, React, PostgreSQL/pgvector, Redis, Celery, and n8n.

---

## Overview

The AI Email Assistant helps users manage their Gmail inbox using artificial intelligence. The system connects to Gmail via OAuth, synchronizes emails, analyzes them for category/intent/urgency/sentiment, classifies priority, detects follow-up requirements, and generates AI reply drafts — all while ensuring that **no AI-generated reply is ever sent without explicit human approval**.

```
AI generates → Human reviews → Human approves → Gmail sends
```

---

## Key Features

| Feature | Description |
|---|---|
| **Gmail Integration** | OAuth authentication, email sync, incremental sync, thread handling, send |
| **AI Email Understanding** | Category, intent, urgency, sentiment, summary, confidence scoring |
| **Priority Classification** | Derived from AI urgency — critical/high → `high`, medium → `normal`, low → `low` |
| **AI Draft Generation** | LLM-generated reply drafts persisted separately from compose drafts |
| **Human Approval Gate** | AI drafts require explicit user approval before sending via Gmail |
| **Follow-up Detection** | AI identifies follow-up requirements with due dates and reasons |
| **Notifications** | High-priority email alerts and follow-up due notifications (idempotent) |
| **n8n Automation** | Scheduled workflow orchestration for the entire email processing pipeline |
| **Automation Monitoring** | Real-time dashboard status showing automation health via Redis |

---

## Architecture

```
                        ┌──────────────────────┐
                        │      React UI        │
                        │  Dashboard / Inbox   │
                        │ Drafts / Notifications│
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │       FastAPI        │
                        │ Business Logic / API │
                        └───────┬──────┬───────┘
                                │      │
                   ┌────────────┘      └─────────────┐
                   ▼                                 ▼
            ┌─────────────┐                   ┌─────────────┐
            │    Gmail    │                   │     LLM     │
            │ OAuth / API │                   │ AI Analysis │
            └─────────────┘                   │ AI Drafting │
                                              └─────────────┘
                   │
                   ▼
         ┌──────────────────────┐
         │ PostgreSQL + pgvector│
         │ Emails / Drafts /    │
         │ AI data / Follow-ups │
         └──────────────────────┘

         ┌──────────────────────┐
         │        Redis         │
         │ Sessions / Automation│
         │ Status Snapshots     │
         └──────────────────────┘

         ┌──────────────────────┐
         │       Celery         │
         │ Background Workers   │
         └──────────────────────┘

         ┌──────────────────────┐
         │        n8n           │
         
         │ Automation / Workflow│
         │ Orchestration        │
         └──────────┬───────────┘
                    │
                    ▼
                 FastAPI
```

### Component Responsibilities

| Component | Responsibility |
|---|---|
| **React UI** | User interaction — dashboard, inbox, drafts, notifications, approval |
| **FastAPI** | All business logic — Gmail API calls, AI orchestration, database operations, authentication |
| **PostgreSQL + pgvector** | Persistent storage for emails, drafts, AI analysis, follow-ups, embeddings |
| **Redis** | Session management, Celery broker, automation status snapshots |
| **Celery** | Background task processing |
| **Gmail API** | Email provider — OAuth, read, send |
| **LLM** | Intelligence layer — email analysis, draft generation |
| **n8n** | Workflow automation and scheduling — orchestrates the pipeline without duplicating business logic |

---

## Technology Stack

### Frontend
| Technology | Purpose |
|---|---|
| React | UI framework |
| TypeScript | Type safety |
| Vite | Build tool and dev server |
| Tailwind CSS | Styling |

### Backend
| Technology | Purpose |
|---|---|
| Python | Server language |
| FastAPI | Web framework and REST API |
| Pydantic | Data validation and serialization |
| SQLAlchemy | ORM and database access |
| Alembic | Database migrations |

### Data & Infrastructure
| Technology | Purpose |
|---|---|
| PostgreSQL | Relational database |
| pgvector | Vector similarity search for embeddings |
| Redis | Caching, sessions, automation state |
| Celery / Celery Beat | Background processing and scheduling |
| Docker / Docker Compose | Containerization |
| Nginx | Reverse proxy |
| n8n | Workflow automation |

---

## How It Works

### AI Email Understanding

When an email is analyzed, the AI produces structured output:

| Field | Description |
|---|---|
| `category` | Email classification (e.g., inquiry, notification, request) |
| `intent` | What the sender wants |
| `urgency` | How time-sensitive the email is |
| `sentiment` | Emotional tone of the message |
| `summary` | Concise summary of the content |
| `confidence` | AI confidence score |
| `follow_up_required` | Whether the email needs follow-up |
| `follow_up_date` | Suggested follow-up date (when applicable) |
| `follow_up_reason` | Why follow-up is needed |

### Priority Classification

Priority is derived from the AI's urgency assessment:

| AI Urgency | Mapped Priority |
|---|---|
| `critical` / `high` | **high** |
| `medium` | **normal** |
| `low` | **low** |

The system also provides an explainable priority reason based on the stored AI analysis.

---

## Human-in-the-Loop Drafting

The project follows a strict human-approval workflow:

```
1. AI analyzes the email
       ↓
2. AI generates a reply draft
       ↓
3. Draft is persisted (shown separately from compose drafts)
       ↓
4. User reviews the generated reply alongside the original email
       ↓
5. User explicitly approves the draft
       ↓
6. FastAPI sends the reply through Gmail
       ↓
7. Reply appears in Gmail Sent
```

**Safety mechanisms:**
- AI drafts are **never** automatically sent
- Approval atomically claims the draft before sending, preventing duplicate sends
- Only `generated` status drafts can be approved — already-sent drafts cannot be re-sent

---

## Follow-up Automation

AI can identify when an email requires follow-up. The system tracks follow-ups through their lifecycle:

| Status | Description |
|---|---|
| `pending` | Follow-up detected, awaiting due date |
| `notified` | Due date reached, user notified |
| `snoozed` | User postponed the follow-up |
| `completed` | Follow-up addressed |
| `dismissed` | User dismissed the follow-up |

Follow-up notifications are **idempotent** — re-triggering for an already-notified follow-up does not create duplicate notifications.

---

## n8n Automation

### Architecture Rule

n8n serves as the **orchestration layer**, not the business-logic layer:

```
React       = human interaction / UI
FastAPI     = business logic / Gmail / AI / database
PostgreSQL  = persistent data
LLM         = intelligence
Gmail       = email provider
n8n         = automation / orchestration
```

**Key constraints:**
- n8n does **not** directly access PostgreSQL
- n8n does **not** duplicate Gmail or AI logic
- n8n communicates with FastAPI through protected automation endpoints using bearer-token authentication

### Main Email Automation Workflow

```
Schedule Trigger
      ↓
Gmail Incremental Sync
      ↓
Get Unprocessed Emails
      ↓
Loop / Batch
      ↓
AI Analyze
      ↓
Priority Classification
      ↓
IF High Priority?
   ↙          ↘
  Yes          No
   ↓            ↓
Notification   Draft
   ↓            ↑
   └──→ Draft ──┘
```

- **All emails** proceed to AI draft generation
- **High-priority emails** additionally generate an in-app notification
- AI drafts still require **human approval** before sending

### Follow-up Workflow

```
Schedule / Manual Trigger
         ↓
Get Due Follow-ups
         ↓
Loop / Batch
         ↓
Notify Follow-up
```

### Error Workflow

```
Main Workflow Error
       ↓
Error Trigger
       ↓
Error Information
       ↓
Error Handling
```

### Automation Status

n8n reports successful/failed automation runs to FastAPI. FastAPI stores the latest snapshot in Redis. The Dashboard reads the status through the application status API, displaying:

- Current status (Healthy / Degraded / Error)
- Last successful run timestamp
- Last failure timestamp and error message

---

## Automation Development Phases

The automation system was built incrementally across 17 phases:

| Phase | Milestone |
|---|---|
| 1 | Backend automation foundation — dedicated auth and endpoints |
| 2 | n8n → FastAPI connectivity via internal Docker network |
| 3 | Automatic Gmail incremental sync |
| 4 | Unprocessed email detection |
| 5 | Automatic AI analysis |
| 6 | Idempotency — already-analyzed emails return `already_processed` |
| 7 | AI draft generation |
| 8 | Human approval + Gmail send |
| 9 | Priority routing based on AI classification |
| 10 | High-priority notification creation |
| 11 | Follow-up detection and due-date notifications |
| 12 | Error Workflow for n8n failure handling |
| 13 | Retry behavior with backend idempotency |
| 14 | Dashboard automation status monitoring via Redis |
| 15 | End-to-end validation against running application |
| 16 | UI polish — Dashboard and draft rendering |
| 17 | Final documentation |

---

## Reliability & Error Handling

### Idempotency

The system is designed to safely handle retries and duplicate operations:

| Operation | Idempotency Behavior |
|---|---|
| AI analysis | Already-analyzed emails return `already_processed` |
| Notifications | Uniqueness constraints prevent duplicate notifications |
| Follow-up notifications | Re-triggering a notified follow-up is a no-op |
| Draft approval | Atomic claim prevents duplicate Gmail sends |
| n8n retries | Backend operations are safe to replay |

### Error Handling

- FastAPI exposes automation-specific error responses
- n8n uses a dedicated Error Workflow for failure handling
- HTTP requests support retry behavior
- Gmail authentication includes token refresh and retry logic
- The Dashboard displays the latest automation failure information

---

## Security

| Concern | Approach |
|---|---|
| Gmail access | OAuth 2.0 with scoped permissions |
| User authentication | Application session-based auth |
| n8n ↔ FastAPI | Separate automation bearer token |
| Automation user | Requests are mapped to a configured automation user |
| Endpoint protection | Automation endpoints verify ownership and user scope |
| Database access | n8n never directly accesses PostgreSQL |
| AI drafts | Human approval required before any email is sent |
| Email rendering | HTML sanitized via DOMPurify before frontend display |

> ⚠️ **Never commit secrets, OAuth credentials, bearer tokens, API keys, or passwords to the repository.**

---

## Project Structure

```
ai-email-assistant/
│
├── backend/
│   ├── app/
│   │   ├── domain/            # Domain models and business rules
│   │   ├── application/       # Application services and use cases
│   │   ├── infrastructure/    # Database, Gmail, Redis, external integrations
│   │   └── presentation/      # API routes and request/response schemas
│   ├── migrations/            # Alembic database migrations
│   ├── tests/                 # Unit and integration tests
│   └── requirements...
│
├── frontend/
│   ├── src/
│   │   ├── components/        # Reusable UI components
│   │   ├── pages/             # Page-level views (Dashboard, Inbox, Drafts, etc.)
│   │   ├── api/               # API client and service functions
│   │   └── ...
│   └── package.json
│
├── docker-compose.yml         # Main service definitions
├── docker-compose.override.yml
├── infra/                     # Infrastructure configuration
├── nginx/                     # Reverse proxy configuration
├── scripts/                   # Utility scripts
├── docs/                      # Architecture documentation
└── README.md
```

---

## Setup & Installation

### Prerequisites

- Docker and Docker Compose
- Google OAuth credentials (Gmail API enabled)
- LLM API key (for AI analysis and draft generation)

### Quick Start

1. **Clone the repository**

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   cp backend/.env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```
   Edit the `.env` files with your actual credentials (see [Environment Variables](#environment-variables)).

3. **Start the stack:**
   ```bash
   docker compose up -d
   ```

4. **Verify containers are running:**
   ```bash
   docker compose ps
   ```

---

## Environment Variables

The project requires environment-specific configuration. See [`.env.example`](.env.example) for the base template.

**Key variables (use placeholders — never commit real values):**

```env
# Database
DATABASE_URL=<postgresql-connection-string>

# Redis
REDIS_URL=<redis-connection-string>

# Google OAuth
GOOGLE_CLIENT_ID=<google-oauth-client-id>
GOOGLE_CLIENT_SECRET=<google-oauth-client-secret>

# LLM
ANTHROPIC_API_KEY=<anthropic-api-key>
OPENAI_API_KEY=<openai-api-key>

# n8n Automation
N8N_AUTOMATION_TOKEN=<automation-bearer-token>
N8N_AUTOMATION_USER_ID=<automation-user-id>
```

> The `.env` files must remain local and should never be committed to version control.

---

## Running the Application

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Health Check | http://localhost:8000/health |
| API Readiness | http://localhost:8000/api/v1/health/ready |
| API Docs | http://localhost:8000/docs |
| n8n Workflows | http://localhost:5678 |

---

## API / Automation Endpoints

### Application Health

```
GET  /health
GET  /api/v1/health/ready
GET  /api/v1/status
```

### Automation Endpoints (bearer token required)

```
POST /api/v1/automation/status
POST /api/v1/automation/gmail/sync/incremental
GET  /api/v1/automation/emails/unprocessed
POST /api/v1/automation/emails/{email_id}/analyze
GET  /api/v1/automation/emails/{email_id}/priority
POST /api/v1/automation/emails/{email_id}/draft
POST /api/v1/automation/emails/{email_id}/notifications/high-priority
GET  /api/v1/automation/follow-ups/due
POST /api/v1/automation/follow-ups/{follow_up_id}/notify
```

All automation endpoints require the configured bearer token via `Authorization: Bearer <token>` header.

---

## Testing & Validation

The project was validated through:

- ✅ Backend unit and integration tests
- ✅ Frontend TypeScript compilation checks
- ✅ API endpoint validation
- ✅ Docker service health verification
- ✅ n8n workflow execution (all phases)
- ✅ Real Gmail synchronization
- ✅ AI analysis and priority classification
- ✅ Notification creation
- ✅ Follow-up automation
- ✅ AI draft generation
- ✅ Human approval → Gmail send
- ✅ n8n retry and error workflow testing
- ✅ Dashboard automation status validation

---

## End-to-End Example

### Email Processing Flow

```
 1. New email arrives in Gmail
         ↓
 2. n8n triggers incremental Gmail sync
         ↓
 3. FastAPI synchronizes the email to PostgreSQL
         ↓
 4. n8n detects the unprocessed email
         ↓
 5. AI analyzes the email (category, intent, urgency, sentiment, summary)
         ↓
 6. Email receives a priority classification
         ↓
 7. High-priority emails generate an in-app notification
         ↓
 8. AI generates a reply draft
         ↓
 9. User reviews the draft in the Drafts page
         ↓
10. User approves the draft
         ↓
11. FastAPI sends the reply through Gmail
         ↓
12. Reply appears in Gmail Sent
```

### Follow-up Flow

```
 1. AI detects a follow-up requirement during analysis
         ↓
 2. Follow-up is persisted with a due date
         ↓
 3. n8n periodically checks for due follow-ups
         ↓
 4. Due follow-ups trigger a notification
         ↓
 5. User addresses the follow-up (complete / snooze / dismiss)
```

---

## Demo Flow

1. Open **Dashboard** — show Gmail connected, AI available, automation healthy
2. Open **Inbox** — show synchronized emails
3. Select an email — show AI analysis (category, intent, urgency, sentiment, summary)
4. Show **priority classification** with explainable reason
5. Open **Drafts** — show AI-generated draft with original email and generated reply
6. **Approve and Send** — reply is sent through Gmail
7. Verify reply in **Gmail Sent**
8. Demonstrate **notification** for a high-priority email
9. Demonstrate **follow-up** automation
10. Show **n8n workflows** — main automation, follow-up, error workflow
11. Show **Automation Status** card — healthy status with timestamps

---

## Design Decisions

| Decision | Rationale |
|---|---|
| **n8n for orchestration** | Separates scheduling/workflow logic from application code. FastAPI remains the single source of business logic. |
| **FastAPI owns all business logic** | Avoids duplicating Gmail, AI, database, and application logic across n8n and the backend. |
| **Human approval before sending** | Prevents AI from autonomously sending replies — critical safety mechanism. |
| **Redis for automation status** | Only the latest operational status is needed, so a Redis snapshot is sufficient instead of a historical runs table. |
| **PostgreSQL + pgvector** | Provides persistent relational storage plus vector similarity search for email embeddings. |
| **Idempotent operations** | Enables safe retries at every automation step without data corruption or duplicate side effects. |

---

## Interview Talking Points

This project demonstrates practical experience across multiple engineering domains:

| Area | Implementation |
|---|---|
| **Full-Stack AI Application** | End-to-end from React UI through FastAPI to LLM integration |
| **LLM Integration** | Structured AI outputs (classification, analysis, draft generation) |
| **Gmail OAuth / API** | Real email provider integration with token management |
| **Backend Architecture** | FastAPI with Clean Architecture layers (domain, application, infrastructure, presentation) |
| **PostgreSQL + pgvector** | Relational data + vector embeddings for similarity search |
| **Redis** | Session management, task brokering, operational state storage |
| **Celery** | Background task processing with scheduled beats |
| **n8n Workflow Automation** | Multi-step orchestration with error handling and retry logic |
| **Idempotency** | Safe replay of operations across the automation pipeline |
| **Error Handling** | Dedicated error workflows, retry behavior, failure monitoring |
| **Human-in-the-Loop AI** | AI generates, human reviews and approves — no autonomous sending |
| **Follow-up Automation** | AI-detected follow-ups with lifecycle management |
| **Docker / Infrastructure** | Containerized multi-service application with reverse proxy |

---

## License

This is a portfolio/demonstration project.
