from uuid import UUID

from fastapi import APIRouter, Request

from app.repositories.fulltext import fulltext_status
from app.schemas.fulltext import FullTextAccepted, FullTextInput, FullTextStatus
from app.services.fulltext import request_fulltext

router = APIRouter(prefix="/api/v1/papers", tags=["fulltext"])


@router.get("/{paper_id}/fulltext", response_model=FullTextStatus)
async def get_fulltext(paper_id: UUID, request: Request):
    async with request.app.state.resources.sessions() as session:
        return await fulltext_status(session, paper_id)


@router.post("/{paper_id}/retrieve-fulltext", response_model=FullTextAccepted, status_code=202)
async def retrieve_fulltext(paper_id: UUID, body: FullTextInput, request: Request):
    return await request_fulltext(request.app.state.resources, paper_id, body.request_id)
