"""The real app under real uvicorn on a loopback port, for tests about real connections."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn


@asynccontextmanager
async def live_api(resources) -> AsyncIterator[int]:
    """Serves the app for the body of the `async with`; yields the port."""
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    running = uvicorn.Server(config)
    task = asyncio.create_task(running.serve())
    async with asyncio.timeout(10):
        while not running.started:  # noqa: ASYNC110 -- uvicorn only exposes a flag
            await asyncio.sleep(0.01)
    try:
        yield running.servers[0].sockets[0].getsockname()[1]
    finally:
        running.should_exit = True
        await asyncio.wait_for(task, 10)
