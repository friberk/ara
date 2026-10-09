from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from app.integrations.academic import AcademicSearch
from app.models.research import Paper
from app.repositories.fulltext import enqueue_automatic
from app.repositories.papers import mark_saved, paper_detail, patch_paper, save_canonical
from app.schemas.research import PaperDetail, PaperPage, PaperPatch, Provider, SavePaper, SearchPage

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
        # The job commits with the paper: a listed PDF or a DOI is fetched without a click.
        await enqueue_automatic(session, paper.id)
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
        statement = select(Paper.id).order_by(Paper.created_at.desc()).limit(limit).offset(offset)
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
