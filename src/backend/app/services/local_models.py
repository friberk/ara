import asyncio
from contextlib import asynccontextmanager, suppress
from uuid import UUID

from sqlalchemy import func, select

from app.core.errors import AppError
from app.integrations.model_catalog import LOCAL_MODELS, local_spec
from app.integrations.ollama import OllamaRuntime
from app.models.jobs import BackgroundJob
from app.models.local_models import ModelInstallation, ModelRequest, ModelUse
from app.repositories.jobs import enqueue, now
from app.repositories.local_models import (
    acquire_use,
    heartbeat_use,
    installation_locked,
    lock_models,
    pending_owner,
    recovery_operations,
    release_use,
    resume_locked,
)
from app.schemas.ai import Installation, Model
from app.schemas.jobs import JobError, JobStatus


def runtime(resources) -> OllamaRuntime:
    return OllamaRuntime(
        resources.http,
        resources.settings.ollama_base_url,
        stall_seconds=resources.settings.ollama_stall_seconds,
        probe_timeout=resources.settings.ollama_request_timeout_seconds,
        probe_output_tokens=resources.settings.ollama_max_output_tokens,
        probe_threads=resources.settings.ollama_num_threads,
    )


async def stop_runtime_operations(control, operation_id, recovery_operation_ids=()):
    # The new attempt can still be reconciling a prior transfer. Both identities
    # must be quiescent before maintenance ownership can be released.
    if isinstance(recovery_operation_ids, str):
        recovery_operation_ids = [recovery_operation_ids]
    for identifier in dict.fromkeys([operation_id, *recovery_operation_ids]):
        if identifier:
            await control.pause(str(identifier))


def checked_spec(key):
    spec = local_spec(key)
    if spec is None:
        raise AppError(
            404, "LOCAL_MODEL_NOT_FOUND", "This local model is not in the approved catalog."
        )
    return spec


def model_dto(spec, row: ModelInstallation | None, *, context_window=8192) -> Model:
    validation = (row.validation or {}) if row else {}
    state = row.state if row else "missing"
    ready = state == "ready" and row.weights_present and bool(validation)
    error = (
        JobError(code=row.error_code, message=row.error_message or "Model operation failed.")
        if row and row.error_code
        else None
    )
    reason = {
        "missing": "Download weights in Settings to use this model.",
        "queued": "This model download is queued.",
        "downloading": "Wait for the model download to finish.",
        "pausing": "The runtime is settling the paused download.",
        "paused": "Resume the model download in Settings.",
        "verifying": "Wait for model verification to finish.",
        "deleting": "Model weights are being removed.",
        "failed": "Retry this model operation in Settings.",
    }.get(state, "Verify this model in Settings before using it.")
    if state == "failed" and error:
        reason = error.message
    return Model(
        key=spec.key,
        provider="ollama",
        model_id=spec.model_id,
        display_name=spec.display_name,
        status="available" if ready else "unavailable",
        reasoning_efforts=validation.get("reasoning_efforts", ["default"]),
        supports_streaming=validation.get("supports_streaming", False),
        supports_structured_output=validation.get("supports_structured_output", False),
        context_window=context_window,
        unavailable_code=None
        if ready
        else (error.code if state == "failed" and error else "LOCAL_MODEL_NOT_READY"),
        unavailable_reason=None if ready else reason,
        installation=Installation(
            state=state,
            weights_present=row.weights_present if row else False,
            quantization=spec.quantization,
            download_bytes=spec.download_bytes,
            completed_bytes=row.completed_bytes if row else 0,
            total_bytes=row.total_bytes if row else None,
            job_id=row.active_job_id if row else None,
            digest=row.digest if row else None,
            updated_at=row.updated_at if row else None,
            error=error,
        ),
    )


async def list_local_models(resources, *, inspect_runtime=True) -> list[Model]:
    async with resources.sessions() as session:
        rows = {
            row.model_key: row for row in (await session.scalars(select(ModelInstallation))).all()
        }
    items = [
        model_dto(spec, rows.get(spec.key), context_window=resources.settings.ollama_context_window)
        for spec in LOCAL_MODELS.values()
    ]
    for model in items:
        if model.status != "available" or not inspect_runtime:
            continue
        try:
            await check_runtime_validation(resources, checked_spec(model.key), rows[model.key])
        except AppError as error:
            model.status = "unavailable"
            model.unavailable_code, model.unavailable_reason = error.code, error.message
    return items


async def check_runtime_validation(resources, spec, row):
    validation = row.validation or {}
    if (
        validation.get("digest") != spec.expected_digest
        or validation.get("context_window") != resources.settings.ollama_context_window
    ):
        raise AppError(
            409,
            "LOCAL_MODEL_REVALIDATION_REQUIRED",
            "Revalidate this model for the current runtime settings.",
        )
    control = runtime(resources)
    if await control.artifact(spec) is None:
        raise AppError(
            409, "MODEL_WEIGHTS_MISSING", "The model weights are missing from the local runtime."
        )
    version = await control.request("GET", "/api/version")
    if not version.get("version") or version.get("version") != validation.get("runtime_version"):
        raise AppError(
            409,
            "LOCAL_MODEL_REVALIDATION_REQUIRED",
            "Revalidate this model after the runtime changed.",
        )


async def ensure_local_available(resources, key: str) -> Model:
    spec = checked_spec(key)
    async with resources.sessions() as session:
        row = await session.get(ModelInstallation, key)
    model = model_dto(spec, row, context_window=resources.settings.ollama_context_window)
    if model.status != "available":
        raise AppError(409, "LOCAL_MODEL_NOT_READY", "Download and verify this local model first.")
    await check_runtime_validation(resources, spec, row)
    return model


async def local_generation_provenance(resources, key: str) -> dict:
    async with resources.sessions() as session:
        row = await session.get(ModelInstallation, checked_spec(key).key)
        return {
            "provider": "ollama",
            "artifact_digest": row.digest if row else None,
            "runtime_version": (row.validation or {}).get("runtime_version") if row else None,
        }


@asynccontextmanager
async def local_inference_slot(resources, key: str):
    await ensure_local_available(resources, key)
    token = await acquire_use(resources.sessions, key)
    owner = asyncio.current_task()
    lost = False

    async def keep_lease():
        nonlocal lost
        while True:
            await asyncio.sleep(10)
            try:
                live = await heartbeat_use(resources.sessions, token)
            except Exception:
                live = False
            if not live:
                lost = True
                owner.cancel()
                return

    heartbeat = asyncio.create_task(keep_lease())
    try:
        yield
    except asyncio.CancelledError:
        if lost:
            raise AppError(
                409, "LOCAL_MODEL_LEASE_LOST", "Local generation lost its runtime lease."
            ) from None
        raise
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await release_use(resources.sessions, token)


async def replay(session, request_id, key, action, *, job_id=None):
    previous = await session.get(ModelRequest, request_id)
    if previous is None:
        return None
    if (
        previous.model_key != key
        or previous.action != action
        or (job_id and previous.job_id != job_id)
    ):
        raise AppError(
            409,
            "MODEL_REQUEST_CONFLICT",
            "This request UUID was already used for a different model operation.",
        )
    job = await session.get(BackgroundJob, previous.job_id)
    return JobStatus.model_validate(job)


async def request_operation(resources, key: str, request_id: UUID, *, action: str) -> JobStatus:
    checked_spec(key)
    async with resources.sessions() as session, session.begin():
        await lock_models(session)
        previous = await replay(session, request_id, key, action)
        if previous:
            return previous
        if await pending_owner(session):
            raise AppError(
                409, "LOCAL_MODEL_BUSY", "The runtime is settling a previous model operation."
            )
        row = await installation_locked(session, key)
        active = await session.get(BackgroundJob, row.active_job_id) if row.active_job_id else None
        if active and active.state in {"queued", "processing", "paused"}:
            raise AppError(
                409, "LOCAL_MODEL_BUSY", "This model already has an unfinished operation."
            )
        if action == "delete" and await session.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.kind.in_(["model_download", "model_delete"]),
                BackgroundJob.state == "processing",
            )
        ):
            raise AppError(
                409, "LOCAL_MODEL_BUSY", "The local runtime is performing model maintenance."
            )
        if await session.scalar(select(ModelUse.token).where(ModelUse.expires_at > func.now())):
            raise AppError(409, "LOCAL_MODEL_BUSY", "A local generation is using the runtime.")
        job = await enqueue(
            session,
            kind="model_download" if action == "download" else "model_delete",
            payload={"model_key": key, "request_id": str(request_id)},
        )
        job.model_key = key
        job.completed_bytes, job.total_bytes = row.completed_bytes, row.total_bytes
        row.active_job_id = job.id
        row.desired_state = "ready" if action == "download" else "missing"
        row.state = "queued" if action == "download" else "deleting"
        row.error_code = row.error_message = None
        row.updated_at = now()
        session.add(
            ModelRequest(request_id=request_id, model_key=key, action=action, job_id=job.id)
        )
        await session.flush()
        return JobStatus.model_validate(job)


async def request_download(resources, key: str, request_id: UUID) -> JobStatus:
    return await request_operation(resources, key, request_id, action="download")


async def request_delete(resources, key: str, request_id: UUID) -> JobStatus:
    return await request_operation(resources, key, request_id, action="delete")


async def settle_pause(resources, job_id, generation, token=None) -> bool:
    async with resources.sessions() as session, session.begin():
        await lock_models(session)
        job = await session.get(BackgroundJob, job_id, with_for_update=True)
        if job is None or job.generation != generation or job.state not in {"processing", "queued"}:
            return False
        if token is not None and job.lease_token != token:
            return False
        row = await installation_locked(session, job.model_key)
        if row.desired_state != "paused" or row.active_job_id != job.id or job.stage == "verifying":
            return False
        job.state = job.stage = row.state = "paused"
        job.payload = {
            key: value
            for key, value in job.payload.items()
            if key not in {"recovery_operation_id", "_recovery_operation_ids", "_pull_operation_id"}
        }
        job.lease_token = job.lease_expires_at = None
        job.updated_at = row.updated_at = now()
        return True


async def transition_job(resources, job_id: UUID, action: str, request_id: UUID) -> JobStatus:
    operation_id = None
    async with resources.sessions() as session, session.begin():
        await lock_models(session)
        job = await session.get(BackgroundJob, job_id, with_for_update=True)
        if job is None:
            raise AppError(404, "JOB_NOT_FOUND", "Job not found.")
        if job.kind not in {"model_download", "model_delete"} or (
            job.kind == "model_delete" and action != "retry"
        ):
            raise AppError(
                409, "JOB_NOT_CONTROLLABLE", "Only local model downloads support this action."
            )
        previous = await replay(session, request_id, job.model_key, action, job_id=job.id)
        if previous and not (
            action == "pause"
            and previous.state in {"queued", "processing"}
            and previous.stage == "pausing"
        ):
            return previous
        row = await installation_locked(session, job.model_key)
        if row.active_job_id != job.id:
            raise AppError(
                409, "MODEL_OPERATION_SUPERSEDED", "A newer model operation owns this installation."
            )
        if action == "pause":
            if job.state not in {"queued", "processing", "paused"}:
                raise AppError(
                    409, "JOB_NOT_PAUSABLE", "This download cannot be paused in its current state."
                )
            # Runtime capabilities are checked outside the transaction below when processing.
            if job.state == "processing" or (
                job.state == "queued" and recovery_operations(job.payload)
            ):
                if job.stage == "verifying":
                    raise AppError(
                        409,
                        "JOB_NOT_PAUSABLE",
                        "Model verification must settle before another operation.",
                    )
                operation_id = (
                    job.payload.get("recovery_operation_id")
                    if job.state == "queued"
                    else str(job.runtime_operation_id)
                )
                generation, token = job.generation, job.lease_token
            else:
                job.state = job.stage = row.state = "paused"
                row.desired_state = "paused"
        elif action in {"resume", "retry"}:
            required = "paused" if action == "resume" else "failed"
            if job.state != required:
                raise AppError(
                    409,
                    "JOB_NOT_RESUMABLE",
                    "This download cannot be resumed in its current state.",
                )
            if action == "retry":
                job.attempts = 0
            resume_locked(session, job, row)
        else:
            raise AppError(400, "INVALID_MODEL_ACTION", "Unknown model operation.")
        if operation_id is None:
            session.add(
                ModelRequest(
                    request_id=request_id, model_key=job.model_key, action=action, job_id=job.id
                )
            )
            job.updated_at = row.updated_at = now()
            await session.flush()
            return JobStatus.model_validate(job)
    control = runtime(resources)
    if not await control.supports_pause():
        raise AppError(
            409, "MODEL_PAUSE_UNSUPPORTED", "This runtime cannot pause downloads safely."
        )
    # Persist the desired state before requesting remote settlement. Recovery honors it.
    async with resources.sessions() as session, session.begin():
        await lock_models(session)
        job = await session.get(BackgroundJob, job_id, with_for_update=True)
        previous = await replay(session, request_id, job.model_key, action, job_id=job.id)
        if previous and previous.state not in {"queued", "processing"}:
            return previous
        if (
            job.generation != generation
            or job.state not in {"queued", "processing"}
            or (token is not None and job.lease_token != token)
        ):
            raise AppError(
                409,
                "MODEL_OPERATION_CHANGED",
                "The model operation changed before pause could be applied.",
            )
        row = await installation_locked(session, job.model_key)
        if row.active_job_id != job.id:
            raise AppError(
                409, "MODEL_OPERATION_SUPERSEDED", "A newer model operation owns this installation."
            )
        if job.stage == "verifying":
            raise AppError(
                409, "JOB_NOT_PAUSABLE", "Model verification must settle before another operation."
            )
        operation_id = str(job.runtime_operation_id)
        token = job.lease_token
        recovery_operation_ids = recovery_operations(job.payload)
        row.desired_state, row.state, job.stage = "paused", "pausing", "pausing"
        job.updated_at = row.updated_at = now()
        if previous is None:
            session.add(
                ModelRequest(
                    request_id=request_id, model_key=job.model_key, action=action, job_id=job.id
                )
            )
    await stop_runtime_operations(control, operation_id, recovery_operation_ids)
    await settle_pause(resources, job_id, generation, token)
    async with resources.sessions() as session:
        return JobStatus.model_validate(await session.get(BackgroundJob, job_id))


async def run_model_job(resources, job_id, generation, token):
    """Run one fenced attempt; inventory reconciliation precedes any transfer."""
    from app.integrations.ollama import PullProgress
    from app.repositories.jobs import fence
    from app.repositories.local_models import (
        checkpoint,
        finish_model_job,
        resolve_recovery_operation,
    )

    async with resources.sessions() as session:
        job = await session.scalar(select(BackgroundJob).where(*fence(job_id, generation, token)))
        if job is None:
            return
        row = await session.get(ModelInstallation, job.model_key)
        desired_state = row.desired_state
    spec, control = checked_spec(job.model_key), runtime(resources)
    try:
        async with asyncio.timeout(min(resources.settings.ollama_pull_timeout_seconds, 21_600)):
            if desired_state == "paused":
                await stop_runtime_operations(
                    control, str(job.runtime_operation_id), recovery_operations(job.payload)
                )
                await settle_pause(resources, job_id, generation, token)
                return
            marker = job.payload.get("_model_failure")
            if marker:
                await settle_model_failure(
                    resources,
                    job_id,
                    generation,
                    token,
                    AppError(marker["status"], marker["code"], marker["message"]),
                )
                return
            if job.kind == "model_delete":
                await control.delete(spec)
            else:
                # Recovery must quiesce every predecessor even when its weights
                # became visible before its worker committed success.
                for abandoned in recovery_operations(job.payload):
                    await control.pause(abandoned)
                    if not await resolve_recovery_operation(
                        resources.sessions, job_id, generation, token, abandoned
                    ):
                        return
                try:
                    present = await control.artifact(spec)
                except AppError as error:
                    if error.code == "MODEL_DIGEST_MISMATCH":
                        await checkpoint(
                            resources.sessions, job_id, generation, token, weights_present=True
                        )
                    raise
                if present is None:
                    controlled = await control.supports_pause()
                    if not await checkpoint(
                        resources.sessions, job_id, generation, token, stage="downloading"
                    ):
                        return
                    progress = PullProgress(layers=dict(job.payload.get("_pull_layers", {})))
                    clock = asyncio.get_running_loop()
                    advanced_at = clock.time()
                    saved_at = advanced_at - 1
                    last_completed = 0
                    async for event in control.pull(
                        spec.model_id, str(job.runtime_operation_id), controlled=controlled
                    ):
                        completed, total = progress.apply(event)
                        stamp = clock.time()
                        if completed > last_completed:
                            advanced_at, last_completed = stamp, completed
                        if stamp - advanced_at > resources.settings.ollama_stall_seconds:
                            raise AppError(
                                504,
                                "MODEL_PULL_STALLED",
                                "The local model download stopped making progress.",
                            )
                        if stamp - saved_at >= 1 or event.get("status") == "success":
                            if not await checkpoint(
                                resources.sessions,
                                job_id,
                                generation,
                                token,
                                completed=completed,
                                total=total,
                                layers=progress.layers,
                            ):
                                return
                            saved_at = stamp
                    if not await checkpoint(
                        resources.sessions, job_id, generation, token, pull_completed=True
                    ):
                        return
                if await control.artifact(spec) is None:
                    raise AppError(
                        409,
                        "MODEL_WEIGHTS_MISSING",
                        "The downloaded model is absent from runtime inventory.",
                    )
                if not await checkpoint(
                    resources.sessions,
                    job_id,
                    generation,
                    token,
                    stage="verifying",
                    weights_present=True,
                ):
                    return
                validation = await control.verify(
                    spec, context_window=resources.settings.ollama_context_window
                )
                if not await checkpoint(
                    resources.sessions, job_id, generation, token, validation=validation
                ):
                    return
            await finish_model_job(resources.sessions, job_id, generation, token)
    except TimeoutError:
        await settle_model_failure(
            resources,
            job_id,
            generation,
            token,
            AppError(
                504, "MODEL_ATTEMPT_TIMEOUT", "The local model operation exceeded its deadline."
            ),
        )
    except AppError as error:
        await settle_model_failure(resources, job_id, generation, token, error)


async def settle_model_failure(resources, job_id, generation, token, error):
    from app.repositories.local_models import (
        finish_model_job,
        record_model_failure,
        resolve_recovery_operation,
    )

    pending = await record_model_failure(resources.sessions, job_id, generation, token, error)
    if pending is None:
        return
    try:
        for operation in pending:
            await runtime(resources).pause(operation)
            if not await resolve_recovery_operation(
                resources.sessions, job_id, generation, token, operation
            ):
                return
    except AppError:
        # Preserve the original outcome and all unacknowledged identities. Cleanup
        # remains queued and blocks other model use until the runtime settles it.
        pass
    await finish_model_job(resources.sessions, job_id, generation, token, error=error)


async def execute_model_attempt(resources, job_id, generation):
    """Heartbeat failure cancels remote work before abandoning ownership."""
    from app.repositories.jobs import heartbeat
    from app.repositories.local_models import claim_model_job

    token = await claim_model_job(resources.sessions, job_id, generation)
    if token is None:
        return
    async with resources.sessions() as session:
        owned = await session.get(BackgroundJob, job_id)
        operation_id = str(owned.runtime_operation_id)
        recovery_operation_ids = recovery_operations(owned.payload)
    work = asyncio.create_task(run_model_job(resources, job_id, generation, token))
    try:
        while not work.done():
            done, _ = await asyncio.wait({work}, timeout=10)
            if done:
                break
            try:
                async with resources.sessions() as session:
                    job = await session.get(BackgroundJob, job_id)
                    row = await session.get(ModelInstallation, job.model_key) if job else None
                if job:
                    recovery_operation_ids = recovery_operations(job.payload)
                live = bool(
                    job
                    and row
                    and job.state == "processing"
                    and job.lease_token == token
                    and job.generation == generation
                )
                if live:
                    live = await heartbeat(resources.sessions, job_id, generation, token, 60)
            except Exception:
                live = False
                row = None
            if row and row.desired_state == "paused" and live:
                try:
                    await stop_runtime_operations(
                        runtime(resources), operation_id, recovery_operation_ids
                    )
                    await settle_pause(resources, job_id, generation, token)
                    live = False
                except AppError:
                    # Retry acknowledgment while keeping pausing visible.
                    pass
            if not live:
                work.cancel()
                with suppress(AppError):
                    await stop_runtime_operations(
                        runtime(resources), operation_id, recovery_operation_ids
                    )
                break
        with suppress(asyncio.CancelledError):
            await work
    finally:
        unfinished = not work.done()
        work.cancel()
        with suppress(asyncio.CancelledError):
            await work
        if unfinished:
            with suppress(AppError):
                await stop_runtime_operations(
                    runtime(resources), operation_id, recovery_operation_ids
                )
