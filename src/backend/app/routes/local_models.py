from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request

from app.schemas.jobs import JobStatus, ModelOperationInput
from app.services.local_models import request_delete, request_download

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.post("/{key}/download", response_model=JobStatus, status_code=202)
async def download(key: str, body: ModelOperationInput, request: Request):
    return await request_download(request.app.state.resources, key, body.request_id)


@router.delete("/{key}/installation", response_model=JobStatus, status_code=202)
async def delete_installation(
    key: str, request: Request, idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")]
):
    return await request_delete(request.app.state.resources, key, idempotency_key)
