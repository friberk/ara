import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import redis.asyncio as redis
import urllib3
from minio import Minio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.integrations.openalex_content import ContentDownloader


class Resources:
    """Created and closed on the owning API/worker event loop; sessions are never shared."""

    def __init__(self, settings: Settings, *, pdf_downloader=None):
        self.settings = settings
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"connect_timeout": 5},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), follow_redirects=False)
        self.pdf_downloader = pdf_downloader or ContentDownloader()
        self.ollama_http = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(20, connect=5, pool=5),
            follow_redirects=False,
        )
        self.ollama_generation_http = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.ollama_request_timeout_seconds, connect=5, pool=5),
            follow_redirects=False,
        )
        self.redis = redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        self.storage_pool = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=5, read=10),
            retries=False,
            maxsize=4,
        )
        self.storage = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
            http_client=self.storage_pool,
        )
        self.storage_slots = asyncio.Semaphore(4)
        self.llm_slots = asyncio.Semaphore(2)

    async def storage_call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        async with self.storage_slots:
            return await asyncio.to_thread(function, *args, **kwargs)

    async def close(self) -> None:
        await self.pdf_downloader.aclose()
        await self.http.aclose()
        await self.ollama_http.aclose()
        await self.ollama_generation_http.aclose()
        await self.redis.aclose()
        await self.engine.dispose()
        self.storage_pool.clear()
