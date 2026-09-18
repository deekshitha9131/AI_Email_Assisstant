from datetime import UTC, datetime
from uuid import uuid4

from app.ai.rag.indexing_service import EmailIndexingService
from app.ai.schemas.chunk import EmailChunk
from app.ai.schemas.preprocessing import PreprocessedEmail
from app.domain.entities.email import Email
from app.infrastructure.database.repositories.email_chunk_repository import ChunkWithEmbedding


def _email(**overrides) -> Email:
    defaults = dict(
        id=uuid4(),
        thread_id=uuid4(),
        user_id=uuid4(),
        gmail_message_id="m1",
        sender="jane@example.com",
        recipients=["bob@example.com"],
        cc=[],
        bcc=[],
        subject="Subject",
        snippet="snippet",
        body_text="Body content here.",
        body_html=None,
        received_at=datetime.now(UTC),
        is_read=True,
        is_starred=False,
        has_attachments=False,
        label_ids=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Email(**defaults)


class FakePreprocessor:
    def preprocess(self, email: Email) -> PreprocessedEmail:
        return PreprocessedEmail(
            sender=email.sender,
            recipients=email.recipients,
            subject=email.subject,
            body=email.body_text or "",
            truncated=False,
        )


class FakeChunker:
    def __init__(self, chunks: list[EmailChunk] | None = None) -> None:
        self._chunks = (
            chunks if chunks is not None else [EmailChunk(chunk_index=0, content="a chunk")]
        )

    def chunk(self, email: PreprocessedEmail) -> list[EmailChunk]:
        return self._chunks


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.embed_texts_calls: list[list[str]] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embed_texts_calls.append(texts)
        return [[0.1] * 384 for _ in texts]


class FakeChunkRepository:
    def __init__(self) -> None:
        self.replace_calls: list[dict] = []

    async def replace_chunks_for_email(self, *, email_id, thread_id, user_id, received_at, chunks):
        self.replace_calls.append(
            {
                "email_id": email_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "received_at": received_at,
                "chunks": chunks,
            }
        )
        return chunks


async def test_index_email_stores_chunks_with_embeddings() -> None:
    email = _email()
    chunks = [
        EmailChunk(chunk_index=0, content="first chunk"),
        EmailChunk(chunk_index=1, content="second chunk"),
    ]
    embedding_service = FakeEmbeddingService()
    chunk_repository = FakeChunkRepository()
    service = EmailIndexingService(
        preprocessor=FakePreprocessor(),
        chunker=FakeChunker(chunks=chunks),
        embedding_service=embedding_service,
        chunk_repository=chunk_repository,
    )

    count = await service.index_email(email)

    assert count == 2
    assert embedding_service.embed_texts_calls == [["first chunk", "second chunk"]]

    stored_call = chunk_repository.replace_calls[0]
    assert stored_call["email_id"] == email.id
    assert stored_call["thread_id"] == email.thread_id
    assert stored_call["user_id"] == email.user_id
    assert stored_call["received_at"] == email.received_at
    assert all(isinstance(c, ChunkWithEmbedding) for c in stored_call["chunks"])
    assert [c.content for c in stored_call["chunks"]] == ["first chunk", "second chunk"]


async def test_index_email_with_no_chunks_still_clears_existing_ones() -> None:
    email = _email(body_text="")
    embedding_service = FakeEmbeddingService()
    chunk_repository = FakeChunkRepository()
    service = EmailIndexingService(
        preprocessor=FakePreprocessor(),
        chunker=FakeChunker(chunks=[]),
        embedding_service=embedding_service,
        chunk_repository=chunk_repository,
    )

    count = await service.index_email(email)

    assert count == 0
    assert embedding_service.embed_texts_calls == []  # no embedding call for zero chunks
    assert chunk_repository.replace_calls[0]["chunks"] == []


async def test_index_email_uses_email_received_at_not_a_new_timestamp() -> None:
    fixed_time = datetime(2026, 1, 1, tzinfo=UTC)
    email = _email(received_at=fixed_time)
    chunk_repository = FakeChunkRepository()
    service = EmailIndexingService(
        preprocessor=FakePreprocessor(),
        chunker=FakeChunker(),
        embedding_service=FakeEmbeddingService(),
        chunk_repository=chunk_repository,
    )

    await service.index_email(email)

    assert chunk_repository.replace_calls[0]["received_at"] == fixed_time
