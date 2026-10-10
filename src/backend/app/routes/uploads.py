"""Uploads that matched a library paper and wait for the user's choice (ARA-086)."""

from uuid import UUID

from fastapi import APIRouter, Request, Response
from sqlalchemy import String, cast, select

from app.models.research import Paper
from app.repositories.papers import paper_detail
from app.schemas.research import MatchDecision, PaperDetail, PaperPage
from app.services.upload_match import pending_paper_ids, resolve

router = APIRouter(prefix="/api/v1/uploads", tags=["documents"])


@router.get("/matches", response_model=PaperPage)
async def pending_matches(request: Request):
    async with request.app.state.resources.sessions() as session:
        ids = (
            await session.scalars(
                select(Paper.id)
                .where(cast(Paper.id, String).in_(pending_paper_ids()))
                .order_by(Paper.created_at.desc())
                .limit(100)
            )
        ).all()
        return PaperPage(items=[await paper_detail(session, paper_id) for paper_id in ids])


@router.post(
    "/{paper_id}/match",
    response_model=PaperDetail,
    responses={204: {"description": "The upload was discarded."}},
)
async def decide(paper_id: UUID, body: MatchDecision, request: Request):
    resources = request.app.state.resources
    target = await resolve(resources, paper_id, body.decision)
    if target is None:
        return Response(status_code=204)
    async with resources.sessions() as session:
        return await paper_detail(session, target)
