"""Embedding adapters over LlamaIndex. Embedding is idempotent and cheap, so it may retry."""

import asyncio
import math
from functools import cache
from typing import Protocol

import httpx
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding
from ollama import ResponseError
from openai import APIConnectionError, APIStatusError
from pydantic import ValidationError

from app.core.errors import AppError
from app.integrations.embedding_catalog import EmbeddingProfile

BUSY_RETRY_SECONDS = 1
OLLAMA_KEEP_ALIVE = "10m"
# Phase 0 S1: a constant num_ctx and num_thread per model avoids runner reloads, and
# omitting num_thread made a CPU batch 3.4x slower. Chunks are far below 2,048 tokens.
OLLAMA_EMBED_CONTEXT = 2048


class Embedder(Protocol):
    profile: EmbeddingProfile

    def sent_text(self, text: str) -> str:
        """The exact document input the provider receives, for `input_hash`."""

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_queries(self, texts: list[str]) -> list[list[float]]: ...

    async def close(self) -> None: ...


def create_embedder(resources, profile: EmbeddingProfile, *, transport=None) -> Embedder:
    if profile.provider == "openai":
        return OpenAIEmbedder(resources, profile, transport=transport)
    return OllamaEmbedder(resources, profile, transport=transport)


def invalid() -> AppError:
    return AppError(502, "EMBEDDING_INVALID", "The embedding model returned unusable vectors.")


def unit_vectors(profile: EmbeddingProfile, vectors, count: int) -> list[list[float]]:
    """Validate native dimensions and L2-normalize, so cosine distance is comparable."""
    if len(vectors) != count:
        raise invalid()
    result = []
    for vector in vectors:
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError):
            raise invalid() from None
        norm = math.sqrt(sum(value * value for value in values))
        if len(values) != profile.dimensions or not math.isfinite(norm) or norm == 0:
            raise invalid()
        result.append([value / norm for value in values])
    return result


@cache
def cl100k():
    import tiktoken

    # OpenAI reports text-embedding-3 usage in cl100k tokens (Phase 0 S1).
    return tiktoken.get_encoding("cl100k_base")


class BoundedOpenAIEmbedding(OpenAIEmbedding):
    """LlamaIndex's retry decorator is the only retry layer: the SDK client never retries."""

    def _get_credential_kwargs(self, is_async: bool = False) -> dict:
        return {**super()._get_credential_kwargs(is_async), "max_retries": 0}


class OpenAIEmbedder:
    def __init__(self, resources, profile: EmbeddingProfile, *, transport=None):
        from app.integrations.llm import configured

        settings = resources.settings
        if not configured(settings):
            raise AppError(503, "MODEL_NOT_CONFIGURED", "Add an OpenAI API key on the server.")
        self.resources, self.profile = resources, profile
        self.http = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(60, connect=5))
        self.model = BoundedOpenAIEmbedding(
            model=profile.model_id,
            api_key=settings.openai_api_key.get_secret_value(),
            api_base=settings.openai_base_url,
            dimensions=None,
            embed_batch_size=profile.batch_size,
            max_retries=2,
            timeout=60,
            async_http_client=self.http,
        )

    def sent_text(self, text: str) -> str:
        # LlamaIndex flattens newlines before sending text to OpenAI.
        return text.replace("\n", " ")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        await self.reserve(texts)
        return await self.call(lambda: self.model.aget_text_embedding_batch(texts), len(texts))

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        await self.reserve(texts)

        async def queries():
            return [await self.model.aget_query_embedding(text) for text in texts]

        return await self.call(queries, len(texts))

    async def reserve(self, texts: list[str]) -> None:
        from app.integrations.llm import LLMError, reserve_embedding

        tokens = sum(len(cl100k().encode(self.sent_text(text))) for text in texts)
        try:
            await reserve_embedding(self.resources, self.profile, tokens)
        except LLMError as exc:
            raise AppError(exc.status, exc.code, exc.message) from None

    async def call(self, operation, count: int) -> list[list[float]]:
        try:
            vectors = await operation()
        except APIStatusError as exc:
            if exc.status_code in {401, 403, 404}:
                raise AppError(
                    503, "MODEL_UNAVAILABLE", "The embedding model is unavailable for this account."
                ) from None
            if exc.status_code == 429:
                raise AppError(
                    429, "MODEL_RATE_LIMITED", "The embedding provider is rate limited; try later."
                ) from None
            raise failed() from None
        except APIConnectionError:
            raise failed() from None
        return unit_vectors(self.profile, vectors, count)

    async def close(self) -> None:
        await self.http.aclose()


def failed() -> AppError:
    return AppError(502, "EMBEDDING_FAILED", "The embedding request failed.")


class OllamaEmbedder:
    def __init__(self, resources, profile: EmbeddingProfile, *, transport=None):
        settings = resources.settings
        self.resources, self.profile = resources, profile
        client_kwargs = {
            "timeout": httpx.Timeout(settings.ollama_request_timeout_seconds, connect=5)
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self.model = OllamaEmbedding(
            model_name=profile.model_id,
            base_url=settings.ollama_base_url,
            embed_batch_size=profile.batch_size,
            query_instruction=profile.query_instruction,
            text_instruction=None,
            keep_alive=OLLAMA_KEEP_ALIVE,
            ollama_additional_kwargs={
                "num_ctx": OLLAMA_EMBED_CONTEXT,
                "num_thread": settings.ollama_num_threads,
            },
            client_kwargs=client_kwargs,
        )

    def sent_text(self, text: str) -> str:
        return self.model._format_text(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.call(lambda: self.model.aget_text_embedding_batch(texts), len(texts))

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        async def queries():
            return [await self.model.aget_query_embedding(text) for text in texts]

        return await self.call(queries, len(texts))

    async def call(self, operation, count: int) -> list[list[float]]:
        try:
            return await self.admitted(operation, count)
        except AppError as error:
            # One generation and one retrieval holder may overlap; another search waits once.
            if error.code != "LOCAL_MODEL_BUSY":
                raise
        await asyncio.sleep(BUSY_RETRY_SECONDS)
        return await self.admitted(operation, count)

    async def admitted(self, operation, count: int) -> list[list[float]]:
        from app.services import local_models

        async with local_models.retrieval_inference_slot(
            self.resources, self.profile.local_model_key
        ):
            vectors = await self.request(operation)
        return unit_vectors(self.profile, vectors, count)

    async def request(self, operation):
        from app.integrations.ollama import runtime_error

        try:
            return await operation()
        except ResponseError as exc:
            raise runtime_error(str(exc.error)) from None
        except (ConnectionError, httpx.HTTPError):
            raise AppError(
                503, "LOCAL_RUNTIME_UNAVAILABLE", "The local model runtime is unavailable."
            ) from None
        except (ValidationError, TypeError, ValueError):
            raise invalid() from None

    async def close(self) -> None:
        await self.model._async_client.close()
