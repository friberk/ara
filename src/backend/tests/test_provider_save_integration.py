"""Saving a paper from a malformed provider record must not store it (ARA-121)."""

import httpx
import pytest
from sqlalchemy import func, select
from test_paper_deletion_integration import client_for

from app.models.research import Paper, PaperSource

pytestmark = pytest.mark.integration


async def stored(resources) -> tuple[int, list[str]]:
    async with resources.sessions() as session:
        papers = await session.scalar(select(func.count(Paper.id)))
        sources = (await session.scalars(select(PaperSource.external_id))).all()
    return papers, list(sources)


async def save(resources, provider, external_id, record):
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=record))
    )
    async with client_for(resources) as client:
        return await client.post(
            "/api/v1/papers", json={"provider": provider, "external_id": external_id}
        )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="ARA-121: a provider record with an empty id is saved through POST /papers.",
)
@pytest.mark.parametrize(
    ("provider", "external_id", "record"),
    [
        pytest.param("openalex", "W1", {"id": "", "display_name": "No identity"}, id="openalex"),
        pytest.param(
            "openalex",
            "W1",
            {"id": "https://openalex.org/", "display_name": "No identity"},
            id="openalex-no-work-part",
        ),
        pytest.param(
            "semantic_scholar",
            "abc",
            {"paperId": "", "title": "No identity"},
            id="semantic-scholar",
        ),
    ],
)
async def test_a_record_with_no_identity_is_refused_and_not_stored(
    resources, provider, external_id, record
):
    response = await save(resources, provider, external_id, record)
    assert await stored(resources) == (0, [])
    assert response.status_code == 502, response.text
    assert response.json()["code"] == "PROVIDER_INVALID_RESPONSE"


async def test_a_malformed_record_is_refused_and_not_stored(resources):
    """The control: a record the client already rejects leaves nothing behind."""
    response = await save(resources, "openalex", "W1", {"id": 5, "display_name": "Bad"})
    assert response.status_code == 502 and response.json()["code"] == "PROVIDER_INVALID_RESPONSE"
    assert await stored(resources) == (0, [])


async def test_a_valid_record_is_saved_under_its_own_identity(resources):
    """The control that shows this route really stores what the provider returns."""
    record = {"id": "https://openalex.org/W1", "display_name": "A real paper"}
    response = await save(resources, "openalex", "W1", record)
    assert response.status_code in {200, 201}, response.text
    assert await stored(resources) == (1, ["W1"])
