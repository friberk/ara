"""Editing a paper's details, including venue, and looking it up again at any time (ARA-095).

Manual edits keep winning: a lookup refreshes only fields that were not edited by the user.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from support.academic import DOI, DOI_TITLE, openalex_work, providers
from test_metadata_enrichment_integration import detail, run_lookup, use
from test_paper_deletion_integration import client_for
from test_upload_match_integration import library_paper

from app.models.research import Paper

pytestmark = pytest.mark.integration
ICSE = "International Conference on Software Engineering"


async def test_venue_is_editable_and_an_edit_wins_over_the_provider_record(resources):
    saved = await library_paper(resources)
    assert (await detail(resources, saved)).venue == ICSE
    async with client_for(resources) as client:
        edited = await client.patch(f"/api/v1/papers/{saved}", json={"venue": "ICSE 2022"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["venue"] == "ICSE 2022"
        assert edited.json()["metadata_provenance"]["venue"]["source"] == "manual"
        assert edited.json()["metadata_provenance"]["title"]["source"] == "openalex"
        cleared = await client.patch(f"/api/v1/papers/{saved}", json={"venue": None})
        assert cleared.json()["venue"] is None
        too_long = await client.patch(f"/api/v1/papers/{saved}", json={"venue": "x" * 301})
        assert too_long.status_code == 422


async def test_look_up_again_needs_a_doi_or_a_provider_record(resources):
    async with resources.sessions() as session, session.begin():
        paper = Paper(title="Notes without identifiers", metadata_provenance={})
        session.add(paper)
    async with client_for(resources) as client:
        refused = await client.post(f"/api/v1/papers/{paper.id}/metadata-lookup")
        unknown = await client.post(
            "/api/v1/papers/00000000-0000-0000-0000-000000000000/metadata-lookup"
        )
    assert refused.status_code == 409 and refused.json()["code"] == "LOOKUP_UNAVAILABLE"
    assert unknown.status_code == 404


async def test_look_up_again_refreshes_provider_fields_and_keeps_edited_ones(resources):
    """Given a saved paper whose title the user edited, when it is looked up again, then its
    provider record is read again: the abstract, year and venue refresh and the title stays."""
    saved = await library_paper(resources)
    requests = []
    await resources.http.aclose()
    updated = openalex_work(
        title="A different catalog title", year=2023, abstract="Updated abstract.", venue="ICSE"
    )
    use(resources, providers(requests, openalex=lambda request: httpx.Response(200, json=updated)))
    async with client_for(resources) as client:
        await client.patch(f"/api/v1/papers/{saved}", json={"title": "My reading title"})
        queued = await client.post(f"/api/v1/papers/{saved}/metadata-lookup")
        repeat = await client.post(f"/api/v1/papers/{saved}/metadata-lookup")
        listed = await client.get(
            "/api/v1/jobs", params={"paper_id": str(saved), "kind": "metadata"}
        )
    assert queued.status_code == 202, queued.text
    assert queued.json()["kind"] == "metadata" and queued.json()["state"] == "queued"
    # A lookup already waiting is returned rather than repeated.
    assert repeat.json()["id"] == queued.json()["id"]
    assert [item["id"] for item in listed.json()["items"]] == [queued.json()["id"]]

    job = await run_lookup(resources, saved, due=False)
    assert job.state == "completed" and job.result["matched_by"] == "record"
    assert [request.url.path for request in requests] == ["/works/W4224987405"]
    paper = await detail(resources, saved)
    assert paper.title == "My reading title"
    assert (paper.abstract, paper.year, paper.venue) == ("Updated abstract.", 2023, "ICSE")
    assert paper.metadata_provenance["title"] == {"source": "manual"}
    assert paper.metadata_provenance["abstract"]["source"] == "openalex"


async def test_look_up_again_trusts_a_doi_the_user_entered(resources):
    """Given a paper whose title came from a PDF and whose DOI the user typed, the record for
    that DOI is used even though its title differs."""
    async with resources.sessions() as session, session.begin():
        paper = Paper(
            title="Wrong title read from the PDF",
            metadata_provenance={"title": {"source": "pdf"}},
        )
        session.add(paper)
    requests = []
    await resources.http.aclose()
    use(
        resources,
        providers(
            requests,
            openalex=lambda request: httpx.Response(200, json={"results": [openalex_work()]}),
        ),
    )
    async with client_for(resources) as client:
        await client.patch(f"/api/v1/papers/{paper.id}", json={"doi": DOI})
        assert (await client.post(f"/api/v1/papers/{paper.id}/metadata-lookup")).status_code == 202
    job = await run_lookup(resources, paper.id, due=False)
    assert job.result["outcome"] == "matched" and job.result["matched_by"] == "doi"
    refreshed = await detail(resources, paper.id)
    assert refreshed.title == DOI_TITLE and refreshed.venue == ICSE
    assert refreshed.metadata_provenance["doi"] == {"source": "manual"}
    assert [(s.provider, s.external_id) for s in refreshed.sources] == [("openalex", "W4224987405")]


async def test_look_up_again_while_rate_limited_waits_with_the_usual_backoff(resources):
    saved = await library_paper(resources)
    requests = []
    await resources.http.aclose()

    def limited(request):
        return httpx.Response(429, headers={"Retry-After": "120"}, json={"message": "slow"})

    use(resources, providers(requests, openalex=limited, semantic_scholar=limited))
    async with client_for(resources) as client:
        assert (await client.post(f"/api/v1/papers/{saved}/metadata-lookup")).status_code == 202
    before = datetime.now(UTC)
    job = await run_lookup(resources, saved, due=False)
    assert (job.state, job.stage, job.error_code) == (
        "queued",
        "retry_wait",
        "PROVIDER_RATE_LIMITED",
    )
    assert job.available_at >= before + timedelta(seconds=119)
    paper = await detail(resources, saved)
    assert paper.title == DOI_TITLE and paper.venue == ICSE
