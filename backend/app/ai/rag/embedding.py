import asyncio
from functools import lru_cache

import structlog
from sentence_transformers import SentenceTransformer

from app.core.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL_NAME
from app.domain.exceptions.ai import EmbeddingProviderError

logger = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    """Load the sentence-transformers model once and cache it for reuse.

    The model is downloaded on first use and cached locally by the
    sentence-transformers library (~/.cache/torch/sentence_transformers).
    Subsequent calls return the same in-memory instance.
    """
    logger.info("embedding_model_loading", model=EMBEDDING_MODEL_NAME)
    try:
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    except Exception as exc:
        raise EmbeddingProviderError(
            f"Failed to load embedding model {EMBEDDING_MODEL_NAME!r}: {exc}"
        ) from exc
    logger.info("embedding_model_loaded", model=EMBEDDING_MODEL_NAME)
    return model


class EmbeddingService:
    """Local embedding service using sentence-transformers.

    Replaces the previous OpenAI-based implementation. The model
    (all-MiniLM-L6-v2) runs locally — no API key, no HTTP requests
    to OpenAI, no usage quota.

    The model is loaded once (lazily, on first embed call) and reused
    for all subsequent requests via a module-level cache.
    """

    def _validate_dimensions(self, embedding: list[float]) -> None:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise EmbeddingProviderError(
                f"Embedding model returned {len(embedding)} dimensions, "
                f"expected {EMBEDDING_DIMENSIONS}. This indicates a model "
                "mismatch — check EMBEDDING_MODEL_NAME in app/core/constants.py."
            )

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single piece of text — used for retrieval queries."""
        loop = asyncio.get_running_loop()
        try:
            embedding = await loop.run_in_executor(
                None, self._embed_text_sync, text
            )
        except EmbeddingProviderError:
            raise
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Local embedding failed: {exc}"
            ) from exc

        self._validate_dimensions(embedding)
        return embedding

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts — used for indexing email chunks."""
        if not texts:
            return []

        loop = asyncio.get_running_loop()
        try:
            embeddings = await loop.run_in_executor(
                None, self._embed_texts_sync, texts
            )
        except EmbeddingProviderError:
            raise
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Local batch embedding failed: {exc}"
            ) from exc

        for embedding in embeddings:
            self._validate_dimensions(embedding)
        return embeddings

    @staticmethod
    def _embed_text_sync(text: str) -> list[float]:
        model = _load_model()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    @staticmethod
    def _embed_texts_sync(texts: list[str]) -> list[list[float]]:
        model = _load_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vectors]
