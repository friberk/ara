from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from app.core.errors import AppError
from app.integrations.academic import AcademicSearch
from app.integrations.openalex_content import api_key
from app.models.research import Paper
from app.repositories.fulltext import enqueue_automatic
from app.repositories.jobs import job_statuses
from app.repositories.papers import mark_saved, paper_detail, patch_paper, save_canonical
from app.schemas.jobs import JobStatus
from app.schemas.research import (
    DeletedPapers,
    DeletionPreview,
    PaperDetail,
    PaperIds,
    PaperPage,
    PaperPatch,
    Provider,
    SavePaper,
    SearchPage,
)
from app.services.deletion import delete_papers, deletion_preview
from app.services.metadata import queue_refresh
from app.services.upload_match import library_papers

router = APIRouter(prefix="/api/v1", tags=["research"])


@router.get("/search", response_model=SearchPage)
async def search(
    request: Request,
    provider: Provider,
    q: str = Query(min_length=1, max_length=300),
    cursor: str | None = Query(default=None, max_length=2000),
    limit: int = Query(default=20, ge=1, le=50),
):
    resources = request.app.state.resources
    page = await AcademicSearch(resources.http, resources.settings).search(
        provider, q.strip(), cursor, limit
    )
    async with resources.sessions() as session:
        await mark_saved(session, page.items)
    return page


@router.post("/papers", response_model=PaperDetail)
async def save(body: SavePaper, request: Request, response: Response):
    resources = request.app.state.resources
    canonical = await AcademicSearch(resources.http, resources.settings).canonical(
        body.provider, body.external_id
    )
    async with resources.sessions() as session, session.begin():
        paper, created = await save_canonical(session, canonical)
        # The job commits with the paper: OpenAlex's stored PDF is fetched without a click.
        await enqueue_automatic(session, paper.id, enabled=api_key(resources.settings) is not None)
        response.status_code = 201 if created else 200
        return await paper_detail(session, paper.id)


@router.get("/papers", response_model=PaperPage)
async def library(
    request: Request,
    q: str | None = Query(default=None, max_length=300),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    async with request.app.state.resources.sessions() as session:
        # Uploads waiting for a match decision are listed by GET /uploads/matches (ARA-086).
        statement = (
            select(Paper.id)
            .where(library_papers())
            .order_by(Paper.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if q:
            statement = statement.where(Paper.title.ilike(f"%{q}%"))
        ids = (await session.scalars(statement)).all()
        return PaperPage(items=[await paper_detail(session, id) for id in ids])


@router.get("/papers/{paper_id}", response_model=PaperDetail)
async def detail(paper_id: UUID, request: Request):
    async with request.app.state.resources.sessions() as session:
        return await paper_detail(session, paper_id)


@router.patch("/papers/{paper_id}", response_model=PaperDetail)
async def edit(paper_id: UUID, body: PaperPatch, request: Request):
    async with request.app.state.resources.sessions() as session, session.begin():
        return await patch_paper(session, paper_id, body)


@router.post("/papers/{paper_id}/metadata-lookup", response_model=JobStatus, status_code=202)
async def look_up_again(paper_id: UUID, request: Request):
    """Look the paper up again in the metadata source; edited fields stay (ARA-095)."""
    async with request.app.state.resources.sessions() as session, session.begin():
        job = await queue_refresh(session, paper_id)
        return (await job_statuses(session, [job]))[0]


@router.get("/papers/{paper_id}/deletion-preview", response_model=DeletionPreview)
async def preview_deletion(paper_id: UUID, request: Request):
    """What deleting the paper removes; nothing changes (ARA-095)."""
    async with request.app.state.resources.sessions() as session:
        preview = await deletion_preview(session, [paper_id])
    if preview.missing:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    return preview


@router.post("/papers/deletion-preview", response_model=DeletionPreview)
async def preview_deletions(body: PaperIds, request: Request):
    """The combined preview for several papers; unknown IDs are listed as missing."""
    async with request.app.state.resources.sessions() as session:
        return await deletion_preview(session, body.paper_ids)


@router.delete("/papers/{paper_id}", status_code=204, response_class=Response)
async def delete_paper(paper_id: UUID, request: Request):
    """Delete the paper and what hangs off it (services/deletion.py); a repeat answers 404."""
    resources = request.app.state.resources
    async with resources.sessions() as session, session.begin():
        deleted, _ = await delete_papers(session, resources, [paper_id])
    if not deleted:
        raise AppError(404, "PAPER_NOT_FOUND", "Paper not found.")
    return Response(status_code=204)


@router.post("/papers/delete", response_model=DeletedPapers)
async def delete_several(body: PaperIds, request: Request):
    """Delete several papers in one transaction; papers already gone are listed as missing."""
    resources = request.app.state.resources
    async with resources.sessions() as session, session.begin():
        deleted, missing = await delete_papers(session, resources, body.paper_ids)
    return DeletedPapers(deleted=deleted, missing=missing)
