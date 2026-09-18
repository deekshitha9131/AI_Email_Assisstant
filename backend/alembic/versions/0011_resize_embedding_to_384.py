"""Resize embedding column from 1536 to 384 dimensions for local model.

Switches from OpenAI text-embedding-3-small (1536-d) to local
sentence-transformers all-MiniLM-L6-v2 (384-d).

Existing 1536-dimensional embeddings are incompatible with the new
384-dimensional model, so they are set to NULL rather than truncated.
All email records, threads, users, drafts, and other metadata are
fully preserved — only the embedding vectors are cleared.

The column is also made nullable so that emails can exist in the
database even when their embedding has not yet been computed (or
if embedding failed).

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Old and new dimensions
_OLD_DIM = 1536
_NEW_DIM = 384


def upgrade() -> None:
    # 1. Drop the dimension-specific IVFFlat index (cannot ALTER in place)
    op.execute("DROP INDEX IF EXISTS ix_email_chunks_embedding_cosine")

    # 2. Clear all existing embeddings — old 1536-d vectors are incompatible
    #    with the new 384-d model. This preserves every email row.
    op.execute("UPDATE email_chunks SET embedding = NULL")

    # 3. Resize the column from Vector(1536) to Vector(384) and make nullable
    op.alter_column(
        "email_chunks",
        "embedding",
        existing_type=Vector(_OLD_DIM),
        type_=Vector(_NEW_DIM),
        existing_nullable=False,
        nullable=True,
    )

    # 4. Recreate the cosine-similarity index with the new dimension.
    #    IVFFlat requires at least some rows to build lists; on an empty
    #    table (or all-NULL embeddings) PostgreSQL will still accept the
    #    CREATE INDEX — it simply builds an empty index that populates
    #    as new embeddings arrive.
    op.execute(
        "CREATE INDEX ix_email_chunks_embedding_cosine ON email_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    # Reverse: drop new index, resize back, recreate old index
    op.execute("DROP INDEX IF EXISTS ix_email_chunks_embedding_cosine")

    op.execute("UPDATE email_chunks SET embedding = NULL")

    op.alter_column(
        "email_chunks",
        "embedding",
        existing_type=Vector(_NEW_DIM),
        type_=Vector(_OLD_DIM),
        existing_nullable=True,
        nullable=False,
        server_default=sa.text(f"'[{','.join(['0'] * _OLD_DIM)}]'::vector({_OLD_DIM})"),
    )

    op.execute(
        "CREATE INDEX ix_email_chunks_embedding_cosine ON email_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
