from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.integrations.llm import (
    HOSTED_REASONING_EFFORTS,
    PRICES,
    LLMError,
    configured,
    saved_defaults,
    validate_model_available,
    validate_selection,
)
from app.models.jobs import BackgroundJob
from app.models.research import Document, ModelConfiguration, Paper, PaperSummary
from app.repositories.jobs import enqueue
from app.schemas.ai import (
    Defaults,
    GenerationInput,
    ModelPage,
    Summary,
    SummaryAccepted,
    SummaryPage,
)
from app.services.local_models import list_local_models, model_dto

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.get("/models", response_model=ModelPage)
async def models(request: Request):
    settings = request.app.state.resources.settings
    items = [validate_selection(key, HOSTED_REASONING_EFFORTS[key][0]) for key in PRICES]
    for item in items:
        item.status = "configured" if configured(settings) else "unavailable"
    items.extend(await list_local_models(request.app.state.resources))
    return ModelPage(items=items)


@router.get("/settings", response_model=Defaults)
async def settings(request: Request):
    return await saved_defaults(request.app.state.resources)


@router.put("/settings", response_model=Defaults)
async def update_settings(body: Defaults, request: Request):
    resources = request.app.state.resources
    try:
        validate_selection(body.default_model, body.reasoning_effort)
        from app.integrations.model_catalog import local_spec
        from app.models.local_models import ModelInstallation

        spec = local_spec(body.default_model)
        if spec and body.reasoning_effort != "default":
            async with resources.sessions() as session:
                row = await session.get(ModelInstallation, spec.key)
                saved = await session.get(ModelConfiguration, "defaults")
                previous = Defaults.model_validate(saved.value) if saved else None
                preserved = (
                    previous
                    and previous.default_model == body.default_model
                    and previous.reasoning_effort == body.reasoning_effort
                    and not (row and row.validation)
                )
                if (
                    not preserved
                    and body.reasoning_effort not in model_dto(spec, row).reasoning_efforts
                ):
                    raise LLMError(
                        "INVALID_REASONING",
                        "This local model does not support that reasoning effort.",
                        422,
                    )
    except LLMError as exc:
        raise AppError(exc.status, exc.code, exc.message) from None
    async with request.app.state.resources.sessions() as session, session.begin():
        await session.execute(
            insert(ModelConfiguration)
            .values(key="defaults", value=body.model_dump())
            .on_conflict_do_update(index_elements=["key"], set_={"value": body.model_dump()})
        )
    return body


@router.post("/papers/{paper_id}/summaries", response_model=SummaryAccepted, status_code=202)
async def create_summary(paper_id: UUID, body: GenerationInput, request: Request):
    resources = request.app.state.resources
    try:
        validate_selection(body.model, body.reasoning_effort)
        # Replays remain readable even if the provider is offline. Availability HTTP runs
        # before taking the paper write lock; the transaction repeats all document checks.
        async with resources.sessions() as preflight:
            paper = await preflight.get(Paper, paper_id)
            if paper is None:
                raise HTTPException(404, "Paper not found")
            existing = await preflight.scalar(
                select(BackgroundJob).where(
                    BackgroundJob.kind == "summary",
                    BackgroundJob.payload["paper_id"].astext == str(paper_id),
                    BackgroundJob.payload["request_id"].astext == str(body.request_id),
                )
            )
            if existing:
                if (
                    existing.payload["model"] != body.model
                    or existing.payload["reasoning_effort"] != body.reasoning_effort
                ):
                    raise HTTPException(
                        409, "Request UUID was already used with different settings"
                    )
                return SummaryAccepted(
                    job_id=existing.id, summary_id=(existing.result or {}).get("summary_id")
                )
            document = (
                await preflight.get(Document, paper.active_document_id)
                if paper.active_document_id
                else None
            )
            if document is None or document.status != "ready":
                raise HTTPException(
                    409, "Upload and process a paper PDF before requesting a summary"
                )
        await validate_model_available(resources, body.model, body.reasoning_effort)
        async with resources.sessions() as session, session.begin():
            paper = await session.scalar(
                select(Paper).where(Paper.id == paper_id).with_for_update()
            )
            if paper is None:
                raise HTTPException(404, "Paper not found")
            # Request identity belongs to the paper and remains stable across document replacements.
            existing = await session.scalar(
                select(BackgroundJob).where(
                    BackgroundJob.kind == "summary",
                    BackgroundJob.payload["paper_id"].astext == str(paper_id),
                    BackgroundJob.payload["request_id"].astext == str(body.request_id),
                )
            )
            if existing:
                if (
                    existing.payload["model"] != body.model
                    or existing.payload["reasoning_effort"] != body.reasoning_effort
                ):
                    raise HTTPException(
                        409, "Request UUID was already used with different settings"
                    )
                return SummaryAccepted(
                    job_id=existing.id, summary_id=(existing.result or {}).get("summary_id")
                )
            document = (
                await session.get(Document, paper.active_document_id)
                if paper.active_document_id
                else None
            )
            if document is None or document.status != "ready":
                raise HTTPException(
                    409, "Upload and process a paper PDF before requesting a summary"
                )
            if await session.scalar(
                select(BackgroundJob.id).where(
                    BackgroundJob.kind == "summary",
                    BackgroundJob.state.in_(["queued", "processing"]),
                    BackgroundJob.payload["document_id"].astext == str(document.id),
                )
            ):
                raise HTTPException(409, "A summary for this document is already processing")
            payload = {
                **body.model_dump(mode="json"),
                "paper_id": str(paper_id),
                "document_id": str(document.id),
            }
            job = await enqueue(session, kind="summary", payload=payload)
            return SummaryAccepted(job_id=job.id)
    except LLMError as exc:
        raise AppError(exc.status, exc.code, exc.message) from None


@router.get("/papers/{paper_id}/summaries", response_model=SummaryPage)
async def summaries(paper_id: UUID, request: Request):
    async with request.app.state.resources.sessions() as session:
        if await session.get(Paper, paper_id) is None:
            raise HTTPException(404, "Paper not found")
        items = (
            await session.scalars(
                select(PaperSummary)
                .where(PaperSummary.paper_id == paper_id)
                .order_by(PaperSummary.created_at.desc())
            )
        ).all()
        return SummaryPage(items=[Summary.model_validate(item) for item in items])
