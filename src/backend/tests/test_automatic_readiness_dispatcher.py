"""Optional model inspection belongs to the dispatcher lifecycle, not its dispatch path."""

import asyncio
from contextlib import suppress
from types import SimpleNamespace

from app.services import dispatcher, local_models


async def test_given_slow_optional_runtime_when_dispatching_then_core_jobs_and_shutdown_continue(
    monkeypatch,
):
    inspected, dispatched, settled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def inspect(resources):
        inspected.set()
        try:
            await asyncio.Event().wait()
        finally:
            settled.set()

    async def recover(sessions):
        return None

    async def dispatch(sessions, publish, **kwargs):
        dispatched.set()
        await asyncio.sleep(0)

    monkeypatch.setattr(local_models, "reconcile_local_models", inspect, raising=False)
    monkeypatch.setattr(dispatcher, "recover", recover)
    monkeypatch.setattr(dispatcher, "dispatch_once", dispatch)
    resources = SimpleNamespace(
        sessions=object(),
        settings=SimpleNamespace(recovery_interval_seconds=30, dispatch_interval_seconds=0.001),
    )
    task = asyncio.create_task(dispatcher.dispatcher_loop(resources, lambda *args: None))
    try:
        await asyncio.wait_for(inspected.wait(), timeout=1)
        await asyncio.wait_for(dispatched.wait(), timeout=1)
        assert not settled.is_set()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert settled.is_set()


async def test_given_optional_refresh_failure_when_dispatching_then_regular_polls_continue(
    monkeypatch,
):
    inspected, twice = asyncio.Event(), asyncio.Event()
    count = 0

    async def inspect(resources):
        inspected.set()
        raise ConnectionError("synthetic optional runtime failure")

    async def recover(sessions):
        return None

    async def dispatch(sessions, publish, **kwargs):
        nonlocal count
        count += 1
        if count >= 2:
            twice.set()

    monkeypatch.setattr(local_models, "reconcile_local_models", inspect, raising=False)
    monkeypatch.setattr(dispatcher, "recover", recover)
    monkeypatch.setattr(dispatcher, "dispatch_once", dispatch)
    resources = SimpleNamespace(
        sessions=object(),
        settings=SimpleNamespace(recovery_interval_seconds=30, dispatch_interval_seconds=0.001),
    )
    task = asyncio.create_task(dispatcher.dispatcher_loop(resources, lambda *args: None))
    try:
        await asyncio.wait_for(inspected.wait(), timeout=1)
        await asyncio.wait_for(twice.wait(), timeout=1)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
