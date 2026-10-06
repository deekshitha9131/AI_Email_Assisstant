"""Tests for the Hugging Face-backed embedding service contract."""

import math
from typing import Protocol

import httpx
import pytest

from app.ai.rag.embedding import EmbeddingService
from app.core.config import Settings
from app.core.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL_NAME
from app.domain.exceptions.ai import EmbeddingProviderError


class FakeHuggingFaceInference(Protocol):
    calls: list[dict[str, object]]


@pytest.fixture
def service() -> EmbeddingService:
    return EmbeddingService()


async def test_embed_text_returns_normalized_384_dimensional_vector(
    service: EmbeddingService,
) -> None:
    result = await service.embed_text("hello world")
    assert len(result) == EMBEDDING_DIMENSIONS == 384
    assert all(isinstance(value, float) for value in result)
    assert math.isclose(math.sqrt(sum(value * value for value in result)), 1.0)


async def test_embed_texts_batches_inputs(
    service: EmbeddingService,
    fake_huggingface_inference: FakeHuggingFaceInference,
) -> None:
    results = await service.embed_texts(["alpha", "beta", "gamma"])
    assert len(results) == 3
    assert all(len(vector) == EMBEDDING_DIMENSIONS for vector in results)
    assert fake_huggingface_inference.calls[0]["inputs"] == ["alpha", "beta", "gamma"]


async def test_embedding_request_uses_model_and_normalizes_output(
    service: EmbeddingService,
    fake_huggingface_inference: FakeHuggingFaceInference,
) -> None:
    vector = await service.embed_text("test input")
    request = fake_huggingface_inference.calls[0]
    assert request["url"].endswith(
        f"/{EMBEDDING_MODEL_NAME}/pipeline/feature-extraction"
    )
    assert request["authorization"] == "Bearer test-hf-token"
    assert request["normalize"] is True
    assert len(vector) == 384
    assert all(isinstance(value, (int, float)) for value in vector)
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0)


async def test_embed_texts_with_empty_list_does_not_call_provider(
    service: EmbeddingService,
    fake_huggingface_inference: FakeHuggingFaceInference,
) -> None:
    assert await service.embed_texts([]) == []
    assert fake_huggingface_inference.calls == []


async def test_no_openai_api_key_required(service: EmbeddingService) -> None:
    """EmbeddingService must work without any OPENAI_API_KEY."""
    result = await service.embed_text("no api key needed")
    assert len(result) == EMBEDDING_DIMENSIONS


async def test_provider_http_failure_maps_to_embedding_provider_error() -> None:
    async def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    settings = Settings.model_construct(hf_token="test-hf-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unauthorized)) as client:
        service = EmbeddingService(settings, http_client=client)
        with pytest.raises(EmbeddingProviderError, match="HTTP 401"):
            await service.embed_text("test")
