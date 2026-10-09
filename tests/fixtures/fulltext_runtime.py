"""Run the normal app/worker with an explicit isolated fixture resource factory."""

import sys

from fulltext_resources import fixture_resources

if sys.argv[1] == "api":
    import uvicorn

    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(), resource_factory=fixture_resources)

    @app.post("/api/v1/__fixtures/fulltext/{case}/grant", include_in_schema=False)
    async def grant(case: str):
        from fulltext_fixture import FullTextFixture

        if case not in FullTextFixture.cases:
            from fastapi import HTTPException

            raise HTTPException(404)
        response = await app.state.resources.http.post(
            f"http://external-fixtures:8080/__fulltext_fixture/{case}/grant", json={}
        )
        response.raise_for_status()
        return response.json()

    uvicorn.run(app, host="0.0.0.0", port=8000)
else:
    from dramatiq.cli import main

    from app.jobs import actors

    actors.Resources = fixture_resources
    sys.argv = [
        "dramatiq",
        "app.jobs.actors",
        "--queues",
        "default",
        "--processes",
        "1",
        "--threads",
        "2",
    ]
    main()
