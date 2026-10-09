"""Retrieval controls and conversation memory. Stubs until ARA-072 and ARA-077 implement them."""

from uuid import UUID

from fastapi import APIRouter

from app.core.errors import AppError
from app.schemas.retrieval import (
    ChatMemoryState,
    EmbeddingProfilePage,
    PaperRetrieval,
    PaperRetrievalUpdate,
    RebuildInput,
    RetrievalSettings,
)

router = APIRouter(prefix="/api/v1", tags=["retrieval"])


def not_ready() -> AppError:
    return AppError(501, "NOT_IMPLEMENTED", "Retrieval controls are not available yet.")


@router.get("/retrieval/profiles", response_model=EmbeddingProfilePage)
async def profiles():
    raise not_ready()


@router.get("/retrieval/settings", response_model=RetrievalSettings)
async def retrieval_settings():
    raise not_ready()


@router.put("/retrieval/settings", response_model=RetrievalSettings)
async def update_retrieval_settings(body: RetrievalSettings):
    raise not_ready()


@router.get("/papers/{paper_id}/retrieval", response_model=PaperRetrieval)
async def paper_retrieval(paper_id: UUID):
    raise not_ready()


@router.put("/papers/{paper_id}/retrieval", response_model=PaperRetrieval)
async def update_paper_retrieval(paper_id: UUID, body: PaperRetrievalUpdate):
    raise not_ready()


@router.post("/papers/{paper_id}/retrieval/rebuild", response_model=PaperRetrieval, status_code=202)
async def rebuild_paper_retrieval(paper_id: UUID, body: RebuildInput):
    raise not_ready()


@router.get("/chats/{chat_id}/memory", response_model=ChatMemoryState)
async def chat_memory(chat_id: UUID):
    raise not_ready()
