"""Tests for the local sentence-transformers embedding service.

These tests validate the embedding service contract using a deterministic,
lightweight fake model so pytest remains offline and deterministic while the
production implementation continues to use SentenceTransformer lazily.
"""

from unittest.mock import patch

import pytest

from app.ai.rag.embedding import EmbeddingService
from app.core.constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL_NAME
from app.domain.exceptions.ai import EmbeddingProviderError


class FakeEmbeddingVector(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls: list[str | list[str]] = []

    def encode(self, value: str | list[str], normalize_embeddings: bool = True) -> FakeEmbeddingVector | list[FakeEmbeddingVector]:
        self.calls.append(value)

        def vector_for(text: str) -> FakeEmbeddingVector:
            seed = sum((index + 1) * ord(char) for index, char in enumerate(text))
            return FakeEmbeddingVector(
                [((seed + i * 13) % 997) / 997.0 for i in range(EMBEDDING_DIMENSIONS)]
            )

        if isinstance(value, str):
            return vector_for(value)
        return [vector_for(text) for text in value]


@pytest.fixture
def service() -> EmbeddingService:
    model = FakeEmbeddingModel()
    return EmbeddingService(model_loader=lambda: model)


async def test_embed_text_returns_correct_dimension(service: EmbeddingService) -> None:
    """The service must return exactly 384-dimensional vectors."""
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
    """Same input text should produce the same dimension and consistent values."""
    v1 = await service.embed_text("consistent input")
    v2 = await service.embed_text("consistent input")

    assert len(v1) == len(v2) == EMBEDDING_DIMENSIONS
    for a, b in zip(v1, v2, strict=True):
        assert abs(a - b) < 1e-6


async def test_different_inputs_produce_different_vectors(service: EmbeddingService) -> None:
    v1 = await service.embed_text("hello world")
    v2 = await service.embed_text("goodbye universe")

    assert v1 != v2


async def test_embedding_service_accepts_injected_model_loader() -> None:
    model = FakeEmbeddingModel()
    service = EmbeddingService(model_loader=lambda: model)
    result = await service.embed_text("service injection")
    assert len(result) == EMBEDDING_DIMENSIONS
    assert model.calls == ["service injection"]


async def test_no_openai_api_key_required(service: EmbeddingService) -> None:
    """EmbeddingService must work without any OPENAI_API_KEY."""
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
