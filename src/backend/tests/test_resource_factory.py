"""A resource factory can provide process-owned implementations without test flags."""

import asyncio
import inspect

from app.core.config import Settings


async def test_lifespan_uses_and_closes_supplied_resource_factory(monkeypatch):
    from app import main

    class Owned:
        closed = False

        async def close(self):
            self.closed = True

    resource = Owned()

    async def idle(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "dispatcher_loop", idle)

    def factory(_settings):
        return resource

    options = (
        {"resource_factory": factory}
        if "resource_factory" in inspect.signature(main.create_app).parameters
        else {}
    )
    app = main.create_app(Settings(_env_file=None), **options)
    async with app.router.lifespan_context(app):
        assert app.state.resources is resource
    assert resource.closed
