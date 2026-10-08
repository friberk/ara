from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.models.research import SearchHistory
from app.schemas.research import SearchHistoryInput, SearchHistoryItem, SearchHistoryPage

router = APIRouter(prefix="/api/v1/search-history", tags=["history"])


def normalized_query(query: str) -> str:
    return " ".join(query.casefold().split())


@router.post("", response_model=SearchHistoryItem)
async def record_search(body: SearchHistoryInput, request: Request):
    async with request.app.state.resources.sessions() as session, session.begin():
        item = await session.scalar(
            insert(SearchHistory)
            .values(
                provider=body.provider,
                query=body.query,
                normalized_query=normalized_query(body.query),
            )
            .on_conflict_do_update(
                constraint="uq_search_history_query",
                set_={"query": body.query, "last_searched_at": func.now()},
            )
            .returning(SearchHistory)
        )
        return SearchHistoryItem.model_validate(item)


@router.get("", response_model=SearchHistoryPage)
async def search_history(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    async with request.app.state.resources.sessions() as session:
        items = (
            await session.scalars(
                select(SearchHistory)
                .order_by(SearchHistory.last_searched_at.desc(), SearchHistory.id)
                .limit(limit)
            )
        ).all()
        return SearchHistoryPage(items=[SearchHistoryItem.model_validate(x) for x in items])


@router.delete("/{item_id}", status_code=204, response_class=Response)
async def forget_search(item_id: UUID, request: Request):
    async with request.app.state.resources.sessions() as session, session.begin():
        removed = await session.scalar(
            delete(SearchHistory).where(SearchHistory.id == item_id).returning(SearchHistory.id)
        )
        if removed is None:
            raise AppError(404, "SEARCH_HISTORY_NOT_FOUND", "Search history item not found.")
    return Response(status_code=204)


@router.delete("", status_code=204, response_class=Response)
async def clear_search_history(request: Request):
    async with request.app.state.resources.sessions() as session, session.begin():
        await session.execute(delete(SearchHistory))
    return Response(status_code=204)
