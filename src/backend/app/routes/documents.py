from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from app.core.errors import AppError
from app.integrations.storage import read_object
from app.models.research import Document, DocumentChunk
from app.schemas.research import Citation, DocumentDetail, UploadAccepted
from app.services.pdf_removal import pdf_removed_error
from app.services.uploads import MAX_UPLOAD_BYTES, upload

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("", response_model=UploadAccepted, status_code=202)
async def upload_pdf(
    request: Request,
    file: Annotated[UploadFile, File()],
    request_id: Annotated[UUID, Form()],
    paper_id: Annotated[UUID | None, Form()] = None,
):
    try:
        return await upload(request.app.state.resources, file, request_id, paper_id)
    finally:
        await file.close()


async def stored_document(session, document_id: UUID) -> Document:
    """A PDF that still has its file; a removed one answers 404 PDF_REMOVED (ARA-097)."""
    document = await session.get(Document, document_id)
    if document is None:
        raise AppError(404, "DOCUMENT_NOT_FOUND", "Document not found.")
    if document.removed:
        raise pdf_removed_error()
    return document


@router.get("/{document_id}", response_model=DocumentDetail)
async def facts(document_id: UUID, request: Request):
    """The file facts the reader's PDF menu shows (ARA-097)."""
    async with request.app.state.resources.sessions() as session:
        document = await stored_document(session, document_id)
        return DocumentDetail(
            id=document.id,
            paper_id=document.paper_id,
            file_name=document.original_filename,
            page_count=document.page_count,
            byte_size=document.byte_size,
            status=document.status,
            acquisition=document.acquisition,
            created_at=document.created_at,
        )


@router.get("/{document_id}/download")
async def download(document_id: UUID, request: Request):
    resources = request.app.state.resources
    async with resources.sessions() as session:
        key = (await stored_document(session, document_id)).object_key
    try:
        data = await resources.storage_call(
            read_object, resources.storage, resources.settings.minio_bucket, key, MAX_UPLOAD_BYTES
        )
    except Exception:
        raise AppError(
            503, "STORAGE_UNAVAILABLE", "The original PDF is temporarily unavailable."
        ) from None
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="paper-{document_id}.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{document_id}/chunks/{chunk_id}", response_model=Citation)
async def excerpt(document_id: UUID, chunk_id: UUID, request: Request):
    async with request.app.state.resources.sessions() as session:
        chunk = await session.scalar(
            select(DocumentChunk).where(
                DocumentChunk.id == chunk_id, DocumentChunk.document_id == document_id
            )
        )
        if chunk is None:
            document = await session.get(Document, document_id)
            if document is not None and document.removed:
                raise pdf_removed_error()
            raise AppError(
                404,
                "CITATION_NOT_FOUND",
                "This source excerpt does not belong to the selected document.",
            )
        return Citation(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            page=chunk.page,
            page_end=chunk.page_end,
            section=chunk.heading or None,
            kind=chunk.kind,
            bboxes=chunk.bboxes,
            excerpt=chunk.text,
        )
