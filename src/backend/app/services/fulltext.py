"""Full-text request orchestration; worker downloading is added independently."""

from uuid import UUID

from app.repositories.fulltext import enqueue_request
from app.schemas.fulltext import FullTextAccepted


async def request_fulltext(resources, paper_id: UUID, request_id: UUID) -> FullTextAccepted:
    async with resources.sessions() as session, session.begin():
        return await enqueue_request(session, paper_id, request_id)
