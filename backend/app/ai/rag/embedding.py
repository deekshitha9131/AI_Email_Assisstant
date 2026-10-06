import math
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL_NAME
from app.domain.exceptions.ai import EmbeddingProviderError

_HF_INFERENCE_URL = (
    "https://router.huggingface.co/hf-inference/models/"
    f"{EMBEDDING_MODEL_NAME}/pipeline/feature-extraction"
)
_HTTP_TIMEOUT_SECONDS = 30.0


def _create_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)


class EmbeddingService:
    """Create normalized embeddings through Hugging Face Inference Providers."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client

    def _validate_dimensions(self, embedding: list[float]) -> None:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise EmbeddingProviderError(
                f"Embedding model returned {len(embedding)} dimensions, "
                f"expected {EMBEDDING_DIMENSIONS}."
            )

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single piece of text — used for retrieval queries."""
        return (await self.embed_texts([text]))[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts — used for indexing email chunks."""
        if not texts:
            return []

        token = self._settings.hf_token.strip()
        if not token:
            raise EmbeddingProviderError(
                "HF_TOKEN is not configured. Set it in the backend environment."
            )

        headers = {"Authorization": f"Bearer {token}"}
        payload = {"inputs": texts, "parameters": {"normalize": True}}
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    _HF_INFERENCE_URL, headers=headers, json=payload
                )
            else:
                async with _create_http_client() as client:
                    response = await client.post(
                        _HF_INFERENCE_URL, headers=headers, json=payload
                    )
        except httpx.TimeoutException as exc:
            raise EmbeddingProviderError(
                "The Hugging Face embedding request timed out."
            ) from exc
        except httpx.RequestError as exc:
            raise EmbeddingProviderError(
                "Could not connect to the Hugging Face Inference API."
            ) from exc

        if not response.is_success:
            raise EmbeddingProviderError(
                f"The Hugging Face Inference API returned HTTP {response.status_code}."
            )

        try:
            result: Any = response.json()
        except ValueError as exc:
            raise EmbeddingProviderError(
                "The Hugging Face Inference API returned invalid JSON."
            ) from exc

        if (
            not isinstance(result, list)
            or len(result) != len(texts)
            or any(not isinstance(vector, list) for vector in result)
        ):
            raise EmbeddingProviderError(
                "The Hugging Face Inference API returned an unexpected embedding response."
            )

        embeddings = [self._normalize_embedding(vector) for vector in result]
        for embedding in embeddings:
            self._validate_dimensions(embedding)
        return embeddings

    def _normalize_embedding(self, values: Sequence[object]) -> list[float]:
        try:
            if any(isinstance(value, bool) for value in values):
                raise TypeError("Boolean values are not valid embedding coordinates.")
            embedding = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise EmbeddingProviderError(
                "The Hugging Face Inference API returned non-numeric embedding values."
            ) from exc

        if not all(math.isfinite(value) for value in embedding):
            raise EmbeddingProviderError(
                "The Hugging Face Inference API returned non-finite embedding values."
            )

        magnitude = math.sqrt(sum(value * value for value in embedding))
        if magnitude == 0:
            raise EmbeddingProviderError(
                "The Hugging Face Inference API returned a zero-length embedding vector."
            )

        return [value / magnitude for value in embedding]
