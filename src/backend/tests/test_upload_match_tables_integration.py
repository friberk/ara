"""Upload-match state lives in tables whose foreign keys clean up after deletes (ARA-092)."""

import pytest
from sqlalchemy import delete
from test_upload_match_integration import (
    DOI_TITLE,
    WITH_DOI,
    app_client,
    count,
    detail,
    library_paper,
    pending_upload,
)
from support.front_matter import toolchain_pdf
from test_metadata_enrichment_integration import ingested

pytestmark = pytest.mark.integration


async def test_a_pending_match_is_a_row_keyed_by_the_placeholder(resources):
    from app.models.research import UploadMatch

    saved, _original, accepted = await pending_upload(resources)
    async with resources.sessions() as session:
        row = await session.get(UploadMatch, accepted.paper_id)
    assert (row.library_paper_id, row.document_id) == (saved, accepted.document_id)
    assert (row.matched_by, row.found_by) == ("doi", "ingest")


@pytest.mark.parametrize("deleted", ["library", "placeholder", "document"])
async def test_deleting_what_a_pending_match_points_at_removes_the_match(resources, deleted):
    from app.models.research import Document, Paper, UploadMatch

    saved, _original, accepted = await pending_upload(resources)
    target = {
        "library": (Paper, Paper.id == saved),
        "placeholder": (Paper, Paper.id == accepted.paper_id),
        "document": (Document, Document.id == accepted.document_id),
    }[deleted]
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(target[0]).where(target[1]))
    assert await count(resources, UploadMatch) == 0


async def test_a_pending_placeholder_is_left_out_of_the_listing_through_the_match_table(
    resources,
):
    from app.models.research import UploadMatch

    saved, _original, accepted = await pending_upload(resources)
    async with app_client(resources) as client:
        listed = [item["id"] for item in (await client.get("/api/v1/papers")).json()["items"]]
        assert listed == [str(saved)]
        async with resources.sessions() as session, session.begin():
            await session.execute(delete(UploadMatch))
        listed = [item["id"] for item in (await client.get("/api/v1/papers")).json()["items"]]
    assert set(listed) == {str(saved), str(accepted.paper_id)}


async def test_a_redirect_is_a_row_that_a_deleted_target_takes_with_it(resources):
    from app.models.research import Paper, PaperRedirect

    saved = await library_paper(resources)
    accepted = await ingested(resources, toolchain_pdf(**WITH_DOI))
    async with resources.sessions() as session:
        row = await session.get(PaperRedirect, accepted.paper_id)
    assert row.paper_id == saved
    assert (await detail(resources, accepted.paper_id)).id == saved
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(Paper).where(Paper.id == saved))
    assert await count(resources, PaperRedirect) == 0


async def test_a_doi_owner_is_a_document_column_cleared_when_the_owner_is_deleted(resources):
    from app.models.research import Document, Paper

    owner = await library_paper(resources)
    target = await library_paper(
        resources, work_id="W5", title="An unrelated saved paper", doi="10.5555/other"
    )
    accepted = await ingested(resources, toolchain_pdf(**WITH_DOI), paper_id=target)
    async with resources.sessions() as session:
        assert (await session.get(Document, accepted.document_id)).doi_owner_paper_id == owner
    assert (await detail(resources, target)).pdf_doi_owner.title == DOI_TITLE
    async with resources.sessions() as session, session.begin():
        await session.execute(delete(Paper).where(Paper.id == owner))
    async with resources.sessions() as session:
        assert (await session.get(Document, accepted.document_id)).doi_owner_paper_id is None
    assert (await detail(resources, target)).pdf_doi_owner is None
