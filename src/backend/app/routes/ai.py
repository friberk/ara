from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import AppError
from app.integrations import open_models
from app.integrations.hosted_catalog import HOSTED_MODELS
from app.integrations.llm import (
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
    Features,
    GenerationInput,
    ModelPage,
    Summary,
    SummaryAccepted,
    SummaryPage,
)
from app.services.local_models import list_local_models, model_dto
from app.services.summarization import summary_block

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.get("/features", response_model=Features)
async def features(request: Request):
    """Server features the browser adapts to; open models are experimental (ARA-090)."""
    return Features(open_models=open_models.enabled(request.app.state.resources.settings))


@router.get("/models", response_model=ModelPage)
async def models(request: Request):
    resources = request.app.state.resources
    settings = resources.settings
    items = [
        validate_selection(key, entry.reasoning_efforts[0]) for key, entry in HOSTED_MODELS.items()
    ]
    for item in items:
        item.status = "configured" if configured(settings) else "unavailable"
    if open_models.enabled(settings):
        items.extend(await list_local_models(resources))
        return ModelPage(items=items)
    # A saved local default is reported, unavailable, so nothing switches to a paid model.
    saved = (await saved_defaults(resources)).default_model
    if open_models.open_chat_model(settings, saved):
        item = validate_selection(saved, "default")
        item.unavailable_code = open_models.DISABLED
        item.unavailable_reason = open_models.CHOOSE_MODEL
        items.append(item)
    return ModelPage(items=items)


@router.get("/settings", response_model=Defaults)
async def settings(request: Request):
    return await saved_defaults(request.app.state.resources)


@router.put("/settings", response_model=Defaults)
async def update_settings(body: Defaults, request: Request):
    resources = request.app.state.resources
    if open_models.open_chat_model(resources.settings, body.default_model):
        raise open_models.disabled()
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
    resources = request.app.state.resources
    async with resources.sessions() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(404, "Paper not found")
        items = (
            await session.scalars(
                select(PaperSummary)
                .where(PaperSummary.paper_id == paper_id)
                .order_by(PaperSummary.created_at.desc())
            )
        ).all()
        return SummaryPage(
            items=[Summary.model_validate(item) for item in items],
            blocked=await summary_block(session, resources, paper),
        )
