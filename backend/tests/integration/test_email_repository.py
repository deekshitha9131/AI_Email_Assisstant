import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.dto.gmail import ParsedAttachment, ParsedEmail
from app.domain.exceptions.email import EmailAlreadyExistsError, EmailNotFoundError
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.thread import ThreadModel
from app.infrastructure.database.models.user import UserModel
from app.infrastructure.database.repositories.email_repository import EmailRepository

pytestmark = pytest.mark.integration

_BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def prepared_db(db_engine: AsyncEngine):
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield db_engine

    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def session_factory(prepared_db: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=prepared_db, expire_on_commit=False)


@pytest_asyncio.fixture
async def repo(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as session:
        try:
            yield EmailRepository(session)
        finally:
            await session.rollback()
            await session.close()


async def _create_user(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        user = UserModel(
            email=f"{uuid.uuid4()}@example.com",
            full_name="Repo Test User",
            google_sub_id=f"sub-{uuid.uuid4()}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _create_thread(
    session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        thread = ThreadModel(
            user_id=user_id,
            gmail_thread_id=f"gmail-thread-{uuid.uuid4()}",
            subject="Test thread",
            snippet="snippet",
        )
        session.add(thread)
        await session.commit()
        await session.refresh(thread)
        return thread.id


def _create_kwargs(
    *,
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    gmail_message_id: str,
    received_at: datetime,
    **overrides,
) -> dict:
    base = dict(
        thread_id=thread_id,
        user_id=user_id,
        gmail_message_id=gmail_message_id,
        sender="sender@example.com",
        recipients=["recipient@example.com"],
        received_at=received_at,
        subject="Test subject",
        snippet="Test snippet",
        body_text="Test body",
    )
    base.update(overrides)
    return base


@pytest.fixture
async def user_and_thread(session_factory: async_sessionmaker[AsyncSession]):
    user_id = await _create_user(session_factory)
    thread_id = await _create_thread(session_factory, user_id)
    return user_id, thread_id


async def test_create_and_get_by_id(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    created = await repo.create(
        **_create_kwargs(
            thread_id=thread_id, user_id=user_id, gmail_message_id="m1", received_at=_BASE_TIME
        )
    )

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.gmail_message_id == "m1"
    assert fetched.sender == "sender@example.com"


async def test_get_by_id_returns_none_for_missing_email(repo: EmailRepository) -> None:
    assert await repo.get_by_id(uuid.uuid4()) is None


async def test_get_by_gmail_message_id(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m-unique",
            received_at=_BASE_TIME,
        )
    )

    fetched = await repo.get_by_gmail_message_id(user_id, "m-unique")
    assert fetched is not None
    assert fetched.gmail_message_id == "m-unique"

    assert await repo.get_by_gmail_message_id(user_id, "nonexistent") is None


async def test_get_by_gmail_thread_id_returns_oldest_first(
    repo: EmailRepository, session_factory, user_and_thread
) -> None:
    user_id, thread_id = user_and_thread
    async with session_factory() as session:
        thread = (
            await session.execute(
                text("SELECT gmail_thread_id FROM threads WHERE id = :id"), {"id": thread_id}
            )
        ).scalar_one()

    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m-newer",
            received_at=_BASE_TIME + timedelta(hours=2),
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m-older",
            received_at=_BASE_TIME,
        )
    )

    results = await repo.get_by_gmail_thread_id(user_id, thread)
    assert [e.gmail_message_id for e in results] == ["m-older", "m-newer"]


async def test_get_by_user_id_paginates(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    for i in range(5):
        await repo.create(
            **_create_kwargs(
                thread_id=thread_id,
                user_id=user_id,
                gmail_message_id=f"m{i}",
                received_at=_BASE_TIME + timedelta(hours=i),
            )
        )

    page_1 = await repo.get_by_user_id(user_id, page=1, page_size=2, sort="newest")
    page_2 = await repo.get_by_user_id(user_id, page=2, page_size=2, sort="newest")

    assert [e.gmail_message_id for e in page_1] == ["m4", "m3"]
    assert [e.gmail_message_id for e in page_2] == ["m2", "m1"]


async def test_get_by_user_id_sorts_oldest_first(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    for i in range(3):
        await repo.create(
            **_create_kwargs(
                thread_id=thread_id,
                user_id=user_id,
                gmail_message_id=f"m{i}",
                received_at=_BASE_TIME + timedelta(hours=i),
            )
        )

    results = await repo.get_by_user_id(user_id, sort="oldest")
    assert [e.gmail_message_id for e in results] == ["m0", "m1", "m2"]


async def test_get_by_user_id_rejects_invalid_page(repo: EmailRepository, user_and_thread) -> None:
    user_id, _ = user_and_thread
    with pytest.raises(ValueError):
        await repo.get_by_user_id(user_id, page=0)


async def test_get_by_user_id_filters_unread(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="read",
            received_at=_BASE_TIME,
            is_read=True,
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="unread",
            received_at=_BASE_TIME,
            is_read=False,
        )
    )

    unread_only = await repo.get_by_user_id(user_id, is_read=False)
    assert [e.gmail_message_id for e in unread_only] == ["unread"]


async def test_get_by_user_id_filters_starred(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="starred",
            received_at=_BASE_TIME,
            is_starred=True,
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="unstarred",
            received_at=_BASE_TIME,
            is_starred=False,
        )
    )

    starred_only = await repo.get_by_user_id(user_id, is_starred=True)
    assert [e.gmail_message_id for e in starred_only] == ["starred"]


async def test_get_by_user_id_filters_has_attachments(
    repo: EmailRepository, user_and_thread
) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="with-attach",
            received_at=_BASE_TIME,
            has_attachments=True,
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="without-attach",
            received_at=_BASE_TIME,
            has_attachments=False,
        )
    )

    with_attachments = await repo.get_by_user_id(user_id, has_attachments=True)
    assert [e.gmail_message_id for e in with_attachments] == ["with-attach"]


async def test_get_by_user_id_combines_filters(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="unread-starred",
            received_at=_BASE_TIME,
            is_read=False,
            is_starred=True,
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="unread-unstarred",
            received_at=_BASE_TIME,
            is_read=False,
            is_starred=False,
        )
    )

    results = await repo.get_by_user_id(user_id, is_read=False, is_starred=True)
    assert [e.gmail_message_id for e in results] == ["unread-starred"]


async def test_get_by_user_id_only_returns_this_users_emails(
    repo: EmailRepository, session_factory
) -> None:
    user_a = await _create_user(session_factory)
    thread_a = await _create_thread(session_factory, user_a)
    user_b = await _create_user(session_factory)
    thread_b = await _create_thread(session_factory, user_b)

    await repo.create(
        **_create_kwargs(
            thread_id=thread_a, user_id=user_a, gmail_message_id="a1", received_at=_BASE_TIME
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_b, user_id=user_b, gmail_message_id="b1", received_at=_BASE_TIME
        )
    )

    results = await repo.get_by_user_id(user_a)
    assert [e.gmail_message_id for e in results] == ["a1"]


async def test_create_duplicate_gmail_message_id_raises(
    repo: EmailRepository, user_and_thread
) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id, user_id=user_id, gmail_message_id="dup", received_at=_BASE_TIME
        )
    )

    with pytest.raises(EmailAlreadyExistsError):
        await repo.create(
            **_create_kwargs(
                thread_id=thread_id, user_id=user_id, gmail_message_id="dup", received_at=_BASE_TIME
            )
        )


async def test_update_is_read_and_is_starred(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    created = await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            is_read=True,
            is_starred=False,
        )
    )

    updated = await repo.update(created.id, is_read=False, is_starred=True)

    assert updated.is_read is False
    assert updated.is_starred is True


async def test_update_leaves_unspecified_fields_unchanged(
    repo: EmailRepository, user_and_thread
) -> None:
    user_id, thread_id = user_and_thread
    created = await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            is_read=True,
            is_starred=True,
        )
    )

    updated = await repo.update(created.id, is_read=False)  # is_starred omitted

    assert updated.is_read is False
    assert updated.is_starred is True  # unchanged


async def test_update_raises_for_missing_email(repo: EmailRepository) -> None:
    with pytest.raises(EmailNotFoundError):
        await repo.update(uuid.uuid4(), is_read=False)


async def test_delete_removes_email(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    created = await repo.create(
        **_create_kwargs(
            thread_id=thread_id, user_id=user_id, gmail_message_id="m1", received_at=_BASE_TIME
        )
    )

    await repo.delete(created.id)

    assert await repo.get_by_id(created.id) is None


async def test_delete_raises_for_missing_email(repo: EmailRepository) -> None:
    with pytest.raises(EmailNotFoundError):
        await repo.delete(uuid.uuid4())


def _parsed_email(gmail_message_id: str, **overrides) -> ParsedEmail:
    defaults = dict(
        gmail_message_id=gmail_message_id,
        gmail_thread_id="gmail-thread-x",
        sender="sender@example.com",
        recipients=["recipient@example.com"],
        snippet="snippet",
        internal_date=_BASE_TIME,
        label_ids=[],
        subject="Subject",
        body_text="Body",
    )
    defaults.update(overrides)
    return ParsedEmail(**defaults)


async def test_upsert_twice_does_not_duplicate(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    parsed = _parsed_email("m1")

    first, first_created = await repo.upsert(thread_id=thread_id, user_id=user_id, parsed=parsed)
    second, second_created = await repo.upsert(thread_id=thread_id, user_id=user_id, parsed=parsed)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id

    all_matching = await repo.get_by_user_id(user_id)
    assert len(all_matching) == 1


async def test_upsert_with_attachment_stores_attachment(
    repo: EmailRepository, user_and_thread
) -> None:
    user_id, thread_id = user_and_thread
    parsed = _parsed_email(
        "m-with-attachment",
        attachments=[
            ParsedAttachment(
                attachment_id="att-1", filename="report.pdf", mime_type="application/pdf", size=1024
            )
        ],
    )

    result, _ = await repo.upsert(thread_id=thread_id, user_id=user_id, parsed=parsed)

    assert result.has_attachments is True
    assert len(result.attachments) == 1
    assert result.attachments[0].filename == "report.pdf"


async def test_counts_reflect_stored_emails(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            is_read=False,
            is_starred=True,
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m2",
            received_at=_BASE_TIME,
            is_read=True,
            is_starred=False,
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m3",
            received_at=_BASE_TIME,
            is_read=False,
            is_starred=False,
        )
    )

    assert await repo.count_total(user_id) == 3
    assert await repo.count_unread(user_id) == 2
    assert await repo.count_starred(user_id) == 1


async def test_counts_are_zero_for_user_with_no_emails(
    repo: EmailRepository, session_factory
) -> None:
    user_id = await _create_user(session_factory)

    assert await repo.count_total(user_id) == 0
    assert await repo.count_unread(user_id) == 0
    assert await repo.count_starred(user_id) == 0


async def test_counts_are_scoped_per_user(repo: EmailRepository, session_factory) -> None:
    user_a = await _create_user(session_factory)
    thread_a = await _create_thread(session_factory, user_a)
    user_b = await _create_user(session_factory)
    thread_b = await _create_thread(session_factory, user_b)

    await repo.create(
        **_create_kwargs(
            thread_id=thread_a, user_id=user_a, gmail_message_id="a1", received_at=_BASE_TIME
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_b, user_id=user_b, gmail_message_id="b1", received_at=_BASE_TIME
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_b, user_id=user_b, gmail_message_id="b2", received_at=_BASE_TIME
        )
    )

    assert await repo.count_total(user_a) == 1
    assert await repo.count_total(user_b) == 2


# --- add to the existing imports at the top of the file ---
# (no new imports needed beyond what Task 4.1 already has)


# --- append these test functions to the end of the existing file ---


async def test_search_matches_sender(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            sender="invoices@vendor.com",
            subject="Unrelated",
            snippet="unrelated",
            body_text="unrelated",
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m2",
            received_at=_BASE_TIME,
            sender="noreply@other.com",
            subject="Unrelated",
            snippet="unrelated",
            body_text="unrelated",
        )
    )

    results = await repo.search_by_user_id(user_id, query="invoice")

    assert [e.gmail_message_id for e in results] == ["m1"]


async def test_search_matches_subject(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            subject="Project Invoice",
        )
    )

    results = await repo.search_by_user_id(user_id, query="invoice")

    assert [e.gmail_message_id for e in results] == ["m1"]


async def test_search_matches_snippet(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            subject="Unrelated",
            snippet="Please find the invoice attached",
        )
    )

    results = await repo.search_by_user_id(user_id, query="invoice")

    assert [e.gmail_message_id for e in results] == ["m1"]


async def test_search_matches_body_text(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            subject="Unrelated",
            snippet="unrelated",
            body_text="The invoice total is $500.",
        )
    )

    results = await repo.search_by_user_id(user_id, query="invoice")

    assert [e.gmail_message_id for e in results] == ["m1"]


async def test_search_is_case_insensitive(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            subject="URGENT INVOICE",
        )
    )

    results = await repo.search_by_user_id(user_id, query="invoice")

    assert [e.gmail_message_id for e in results] == ["m1"]


async def test_search_returns_empty_list_for_no_match(
    repo: EmailRepository, user_and_thread
) -> None:
    user_id, thread_id = user_and_thread
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="m1",
            received_at=_BASE_TIME,
            subject="Unrelated subject",
        )
    )

    results = await repo.search_by_user_id(user_id, query="nonexistent-term")

    assert results == []


async def test_search_paginates(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    for i in range(5):
        await repo.create(
            **_create_kwargs(
                thread_id=thread_id,
                user_id=user_id,
                gmail_message_id=f"m{i}",
                received_at=_BASE_TIME + timedelta(hours=i),
                subject=f"Invoice #{i}",
            )
        )

    page_1 = await repo.search_by_user_id(user_id, query="invoice", page=1, page_size=2)
    page_2 = await repo.search_by_user_id(user_id, query="invoice", page=2, page_size=2)

    assert [e.gmail_message_id for e in page_1] == ["m4", "m3"]
    assert [e.gmail_message_id for e in page_2] == ["m2", "m1"]


async def test_count_search_returns_accurate_total(repo: EmailRepository, user_and_thread) -> None:
    user_id, thread_id = user_and_thread
    for i in range(3):
        await repo.create(
            **_create_kwargs(
                thread_id=thread_id,
                user_id=user_id,
                gmail_message_id=f"m{i}",
                received_at=_BASE_TIME,
                subject=f"Invoice #{i}",
            )
        )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_id,
            user_id=user_id,
            gmail_message_id="unrelated",
            received_at=_BASE_TIME,
            subject="Something else entirely",
        )
    )

    assert await repo.count_search_by_user_id(user_id, query="invoice") == 3


async def test_search_enforces_user_isolation(repo: EmailRepository, session_factory) -> None:
    """The core security requirement: a search must never return
    another user's matching emails, even with an identical query."""
    user_a = await _create_user(session_factory)
    thread_a = await _create_thread(session_factory, user_a)
    user_b = await _create_user(session_factory)
    thread_b = await _create_thread(session_factory, user_b)

    await repo.create(
        **_create_kwargs(
            thread_id=thread_a,
            user_id=user_a,
            gmail_message_id="a1",
            received_at=_BASE_TIME,
            subject="Invoice for user A",
        )
    )
    await repo.create(
        **_create_kwargs(
            thread_id=thread_b,
            user_id=user_b,
            gmail_message_id="b1",
            received_at=_BASE_TIME,
            subject="Invoice for user B",
        )
    )

    results_a = await repo.search_by_user_id(user_a, query="invoice")
    results_b = await repo.search_by_user_id(user_b, query="invoice")

    assert [e.gmail_message_id for e in results_a] == ["a1"]
    assert [e.gmail_message_id for e in results_b] == ["b1"]
    assert await repo.count_search_by_user_id(user_a, query="invoice") == 1
