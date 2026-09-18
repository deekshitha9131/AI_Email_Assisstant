"""Tests for the local sentence-transformers embedding service.

Verifies that the EmbeddingService produces 384-dimensional vectors
using the local all-MiniLM-L6-v2 model — no OpenAI API, no API key,
no HTTP requests to external services.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.ai.rag.embedding import EmbeddingService, _load_model
from app.core.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL_NAME
from app.domain.exceptions.ai import EmbeddingProviderError


@pytest.fixture
def service() -> EmbeddingService:
    return EmbeddingService()


async def test_embed_text_returns_correct_dimension(service: EmbeddingService) -> None:
    """The local model must return exactly 384-dimensional vectors."""
    result = await service.embed_text("hello world")
    assert len(result) == EMBEDDING_DIMENSIONS
    assert len(result) == 384


async def test_embed_text_returns_list_of_floats(service: EmbeddingService) -> None:
    result = await service.embed_text("test input")
    assert isinstance(result, list)
    assert all(isinstance(x, float) for x in result)


async def test_embed_texts_returns_one_vector_per_input(service: EmbeddingService) -> None:
    texts = ["alpha", "beta", "gamma"]
    results = await service.embed_texts(texts)

    assert len(results) == 3
    for vector in results:
        assert len(vector) == EMBEDDING_DIMENSIONS


async def test_embed_texts_with_empty_list_returns_empty(service: EmbeddingService) -> None:
    result = await service.embed_texts([])
    assert result == []


async def test_same_input_produces_compatible_vectors(service: EmbeddingService) -> None:
    """Same input text should produce vectors of the same dimension."""
    v1 = await service.embed_text("consistent input")
    v2 = await service.embed_text("consistent input")

    assert len(v1) == len(v2) == EMBEDDING_DIMENSIONS
    # Vectors should be numerically identical for deterministic model
    for a, b in zip(v1, v2, strict=True):
        assert abs(a - b) < 1e-6


async def test_different_inputs_produce_different_vectors(service: EmbeddingService) -> None:
    v1 = await service.embed_text("hello world")
    v2 = await service.embed_text("goodbye universe")

    assert v1 != v2


async def test_model_loads_successfully() -> None:
    """The all-MiniLM-L6-v2 model should load without error."""
    model = _load_model()
    assert model is not None


async def test_model_is_cached() -> None:
    """Model loading should be memoized — same instance returned."""
    m1 = _load_model()
    m2 = _load_model()
    assert m1 is m2


async def test_no_openai_api_key_required(service: EmbeddingService) -> None:
    """EmbeddingService must work without any OPENAI_API_KEY."""
    # If this call succeeds, no OpenAI key was needed
    result = await service.embed_text("no api key needed")
    assert len(result) == EMBEDDING_DIMENSIONS


async def test_no_openai_import_in_embedding_module() -> None:
    """Verify the embedding module does not import openai."""
    import app.ai.rag.embedding as mod
    source_file = mod.__file__
    assert source_file is not None
    with open(source_file) as f:
        source = f.read()
    assert "import openai" not in source
    assert "from openai" not in source
    assert "AsyncOpenAI" not in source


async def test_embed_text_model_load_failure_raises_provider_error() -> None:
    """If the model fails to load, EmbeddingProviderError is raised."""
    with patch("app.ai.rag.embedding._load_model", side_effect=EmbeddingProviderError("boom")):
        service = EmbeddingService()
        with pytest.raises(EmbeddingProviderError):
            await service.embed_text("hello")


async def test_embedding_model_name_is_correct() -> None:
    """The configured model name should be all-MiniLM-L6-v2."""
    assert EMBEDDING_MODEL_NAME == "all-MiniLM-L6-v2"
