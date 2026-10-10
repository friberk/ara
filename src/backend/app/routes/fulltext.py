from uuid import UUID

from fastapi import APIRouter, Request

from app.integrations.openalex_content import api_key
from app.repositories.fulltext import enqueue_automatic, fulltext_status
from app.schemas.fulltext import AutomaticFullText, FullTextAccepted, FullTextInput, FullTextStatus
from app.services.fulltext import request_fulltext

router = APIRouter(prefix="/api/v1/papers", tags=["fulltext"])


@router.get("/{paper_id}/fulltext", response_model=FullTextStatus)
async def get_fulltext(paper_id: UUID, request: Request):
    resources = request.app.state.resources
    async with resources.sessions() as session:
        return await fulltext_status(
            session, paper_id, api_key_configured=api_key(resources.settings) is not None
        )


@router.post("/{paper_id}/retrieve-fulltext", response_model=FullTextAccepted, status_code=202)
async def retrieve_fulltext(paper_id: UUID, body: FullTextInput, request: Request):
    return await request_fulltext(request.app.state.resources, paper_id, body.request_id)


@router.post("/{paper_id}/retrieve-fulltext/automatic", response_model=AutomaticFullText)
async def retrieve_fulltext_automatically(paper_id: UUID, request: Request):
    """Start retrieval for a paper saved before automatic retrieval or without a key at the time;
    every repeat replays it."""
    resources = request.app.state.resources
    async with resources.sessions() as session, session.begin():
        return await enqueue_automatic(
            session, paper_id, enabled=api_key(resources.settings) is not None
        )
