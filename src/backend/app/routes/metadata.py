"""The metadata source for uploaded PDFs, stored apart from model defaults (ARA-086)."""

from fastapi import APIRouter, Request
from sqlalchemy.dialects.postgresql import insert

from app.models.research import ModelConfiguration
from app.schemas.metadata import MetadataSettings
from app.services.metadata import SETTING_KEY, metadata_source

router = APIRouter(prefix="/api/v1/metadata", tags=["metadata"])


@router.get("/settings", response_model=MetadataSettings)
async def read_settings(request: Request):
    async with request.app.state.resources.sessions() as session:
        return MetadataSettings(source=await metadata_source(session))


@router.put("/settings", response_model=MetadataSettings)
async def update_settings(body: MetadataSettings, request: Request):
    # Lookups already queued read the setting when they run, so they follow the new choice.
    async with request.app.state.resources.sessions() as session, session.begin():
        await session.execute(
            insert(ModelConfiguration)
            .values(key=SETTING_KEY, value=body.model_dump())
            .on_conflict_do_update(index_elements=["key"], set_={"value": body.model_dump()})
        )
    return body
