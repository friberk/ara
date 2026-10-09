from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, text, update

from app.core.errors import AppError
from app.models.jobs import BackgroundJob, JobOutbox
from app.models.local_models import ModelInstallation, ModelUse
from app.repositories.jobs import fence, now


def recovery_operations(payload: dict) -> list[str]:
    """Unresolved predecessors, including legacy single-ID recovery payloads."""
    legacy = payload.get("recovery_operation_id")
    if "_recovery_operation_ids" in payload:
        identifiers = [*payload["_recovery_operation_ids"], legacy]
    elif legacy:
        # Old workers could overwrite the predecessor. Fence its earlier history
        # conservatively when reading an older single-ID checkpoint.
        history = [item["operation_id"] for item in payload.get("_operation_history", [])]
        identifiers = history[: history.index(legacy) + 1] if legacy in history else [legacy]
    else:
        identifiers = []
    identifiers.append(payload.get("_pull_operation_id"))
    return list(dict.fromkeys(identifier for identifier in identifiers if identifier))


async def pending_owner(session):
    return await session.scalar(
        select(BackgroundJob.id)
        .where(
            or_(
                BackgroundJob.payload["recovery_operation_id"].astext.is_not(None),
                func.coalesce(
                    func.jsonb_array_length(BackgroundJob.payload["_recovery_operation_ids"]), 0
                )
                > 0,
                and_(
                    BackgroundJob.payload["_pull_operation_id"].astext.is_not(None),
                    or_(
                        BackgroundJob.state != "processing",
                        BackgroundJob.lease_expires_at <= func.now(),
                    ),
                ),
            )
        )
        .order_by(BackgroundJob.created_at, BackgroundJob.id)
        .limit(1)
    )


async def lock_models(session) -> None:
    # All mutation admission and inference admission use one transaction-scoped lock.
    # No lock or transaction is held over HTTP calls.
    await session.execute(text("SELECT pg_advisory_xact_lock(593045)"))


async def installation_locked(session, key: str) -> ModelInstallation:
    row = await session.get(ModelInstallation, key, with_for_update=True)
    if row is None:
        row = ModelInstallation(model_key=key)
        session.add(row)
        await session.flush()
    return row


async def claim_model_job(sessions, job_id: UUID, generation: int) -> UUID | None:
    async with sessions() as session, session.begin():
        await lock_models(session)
        job = await session.get(BackgroundJob, job_id, with_for_update=True)
        if (
            job is None
            or job.kind not in {"model_download", "model_delete"}
            or job.state != "queued"
            or job.generation != generation
            or job.available_at > now()
        ):
            return None
        installation = await installation_locked(session, job.model_key)
        if installation.active_job_id != job.id:
            return None
        pending = await pending_owner(session)
        if pending and pending != job.id:
            return None
        if await session.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.kind.in_(["model_download", "model_delete"]),
                BackgroundJob.state == "processing",
                BackgroundJob.lease_expires_at > func.now(),
                BackgroundJob.id != job.id,
            )
        ):
            return None
        if await session.scalar(select(ModelUse.token).where(ModelUse.expires_at > func.now())):
            return None
        token = uuid4()
        job.state, job.stage = "processing", "inventory"
        job.lease_token, job.lease_expires_at = token, now() + timedelta(seconds=60)
        job.runtime_operation_id = uuid4()
        job.payload = {
            **job.payload,
            "_operation_history": [
                *job.payload.get("_operation_history", []),
                {"operation_id": str(job.runtime_operation_id), "generation": generation},
            ],
        }
        job.updated_at = now()
        installation.state = "downloading" if job.kind == "model_download" else "deleting"
        if installation.desired_state == "paused":
            installation.state, job.stage = "pausing", "pausing"
        installation.updated_at = now()
        return token


async def acquire_use(sessions, key: str) -> UUID:
    async with sessions() as session, session.begin():
        await lock_models(session)
        installation = await session.get(ModelInstallation, key)
        if (
            installation is None
            or installation.state != "ready"
            or not installation.weights_present
        ):
            raise AppError(
                409, "LOCAL_MODEL_NOT_READY", "Download and verify this local model first."
            )
        if await pending_owner(session):
            raise AppError(
                409, "LOCAL_MODEL_BUSY", "The runtime is settling a previous model operation."
            )
        # Download validation runs actual inference, so serialize inference with all maintenance.
        if await session.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.kind.in_(["model_download", "model_delete"]),
                BackgroundJob.state == "processing",
            )
        ):
            raise AppError(
                409, "LOCAL_MODEL_BUSY", "The local runtime is performing model maintenance."
            )
        lease = await session.get(ModelUse, "inference", with_for_update=True)
        if lease and lease.expires_at > now():
            raise AppError(409, "LOCAL_MODEL_BUSY", "A local generation is already running.")
        token = uuid4()
        if lease:
            lease.model_key, lease.token, lease.expires_at = (
                key,
                token,
                now() + timedelta(seconds=60),
            )
        else:
            session.add(
                ModelUse(
                    slot="inference",
                    model_key=key,
                    token=token,
                    expires_at=now() + timedelta(seconds=60),
                )
            )
        return token


async def heartbeat_use(sessions, token: UUID) -> bool:
    async with sessions() as session, session.begin():
        return (
            await session.scalar(
                update(ModelUse)
                .where(ModelUse.token == token, ModelUse.expires_at > func.now())
                .values(expires_at=now() + timedelta(seconds=60))
                .returning(ModelUse.token)
            )
            is not None
        )


async def release_use(sessions, token: UUID) -> bool:
    async with sessions() as session, session.begin():
        return (
            await session.scalar(
                delete(ModelUse).where(ModelUse.token == token).returning(ModelUse.token)
            )
            is not None
        )


async def checkpoint(
    sessions,
    job_id,
    generation,
    token,
    *,
    completed=None,
    total=None,
    stage=None,
    weights_present=None,
    validation=None,
    layers=None,
    pull_completed=False,
) -> bool:
    async with sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return False
        installation = await installation_locked(session, job.model_key)
        if installation.active_job_id != job.id:
            return False
        if stage in {"downloading", "verifying"} and installation.desired_state == "paused":
            return False
        if stage == "downloading":
            job.payload = {**job.payload, "_pull_operation_id": str(job.runtime_operation_id)}
        if pull_completed or stage == "verifying":
            job.payload = {**job.payload, "_pull_operation_id": None}
        if layers is not None:
            job.payload = {**job.payload, "_pull_layers": layers}
        if completed is not None:
            installation.completed_bytes = completed
            installation.total_bytes = total
            job.completed_bytes, job.total_bytes = installation.completed_bytes, total
            job.progress = min(99, int(completed * 100 / total)) if total else 0
        if stage is not None:
            # A transfer checkpoint must not overwrite a user pause request.
            if installation.desired_state != "paused":
                installation.state, job.stage = stage, stage
        if weights_present is not None:
            installation.weights_present = weights_present
        if validation is not None:
            installation.validation, installation.digest = validation, validation["digest"]
        job.updated_at = installation.updated_at = now()
        return True


RETRYABLE_MODEL_ERRORS = {
    "LOCAL_RUNTIME_UNAVAILABLE",
    "MODEL_PULL_STALLED",
    "MODEL_PULL_INCOMPLETE",
    "MODEL_PULL_FAILED",
    "MODEL_ATTEMPT_TIMEOUT",
    "MODEL_PAUSE_UNCONFIRMED",
}


def record_failure_locked(job, installation, error):
    active = job.payload.get("_pull_operation_id")
    if "_pull_operation_id" not in job.payload and job.stage == "downloading":
        active = str(job.runtime_operation_id)
    marker = job.payload.get("_model_failure")
    if marker is None:
        marker = {"code": error.code, "message": error.message, "status": error.status_code}
        if active:
            job.attempts = min(3, job.attempts + 1)
    pending = recovery_operations(job.payload)
    if active or pending:
        pending = list(dict.fromkeys([*pending, active, str(job.runtime_operation_id)]))
        pending = [identifier for identifier in pending if identifier]
    job.payload = {
        **job.payload,
        "_model_failure": marker,
        "_pull_operation_id": active,
        "_recovery_operation_ids": pending,
        "recovery_operation_id": pending[0] if pending else None,
    }
    job.error_code = installation.error_code = marker["code"]
    job.error_message = installation.error_message = marker["message"]
    job.updated_at = installation.updated_at = now()
    return pending


async def record_model_failure(sessions, job_id, generation, token, error):
    async with sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return None
        installation = await installation_locked(session, job.model_key)
        if installation.active_job_id != job.id or installation.desired_state == "paused":
            return None
        return record_failure_locked(job, installation, error)


async def finish_model_job(sessions, job_id, generation, token, *, error: AppError | None = None):
    async with sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return False
        installation = await installation_locked(session, job.model_key)
        if installation.active_job_id != job.id or installation.desired_state == "paused":
            return False
        pending = (
            record_failure_locked(job, installation, error)
            if error
            else recovery_operations(job.payload)
        )
        job.lease_token = job.lease_expires_at = None
        job.updated_at = installation.updated_at = now()
        if pending:
            # Terminal outcomes are deferred too: unresolved I/O remains a global
            # admission barrier and the outbox gives its owner a cleanup attempt.
            job.state, job.stage, installation.state = "queued", "settling", "queued"
            job.generation += 1
            job.available_at = now() + timedelta(seconds=30)
            session.add(
                JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at)
            )
            return True
        if error:
            marker = job.payload["_model_failure"]
            code, message = marker["code"], marker["message"]
            job.payload = {
                key: value for key, value in job.payload.items() if key != "_model_failure"
            }
            if job.kind == "model_download" and code in RETRYABLE_MODEL_ERRORS and job.attempts < 3:
                job.state, job.stage, installation.state = "queued", "retry_wait", "queued"
                job.generation += 1
                job.available_at = now() + timedelta(seconds=30)
                session.add(
                    JobOutbox(
                        job_id=job.id, generation=job.generation, available_at=job.available_at
                    )
                )
                return True
            job.state = job.stage = installation.state = "failed"
            job.error_code = installation.error_code = code
            job.error_message = installation.error_message = message
        else:
            job.state = job.stage = "completed"
            job.progress = 100
            installation.state = "ready" if job.kind == "model_download" else "missing"
            installation.weights_present = job.kind == "model_download"
            installation.error_code = installation.error_message = None
            job.error_code = job.error_message = None
            job.result = {"model_key": job.model_key, "digest": installation.digest}
            if job.kind == "model_delete":
                installation.validation = installation.digest = None
                installation.completed_bytes, installation.total_bytes = 0, None
        return True


def resume_locked(session, job, installation):
    job.state = job.stage = installation.state = "queued"
    installation.desired_state = "ready" if job.kind == "model_download" else "missing"
    job.generation += 1
    job.lease_token = job.lease_expires_at = None
    job.runtime_operation_id = None
    job.error_code = job.error_message = installation.error_code = installation.error_message = None
    job.available_at = job.updated_at = installation.updated_at = now()
    session.add(JobOutbox(job_id=job.id, generation=job.generation, available_at=job.available_at))


async def resolve_recovery_operation(sessions, job_id, generation, token, operation_id) -> bool:
    """Forget only the prior operation whose remote quiescence was acknowledged."""
    async with sessions() as session, session.begin():
        job = await session.scalar(
            select(BackgroundJob).where(*fence(job_id, generation, token)).with_for_update()
        )
        if job is None:
            return False
        installation = await installation_locked(session, job.model_key)
        if installation.active_job_id != job.id:
            return False
        pending = recovery_operations(job.payload)
        if operation_id not in pending:
            return False
        remaining = [identifier for identifier in pending if identifier != operation_id]
        job.payload = {
            **job.payload,
            "_recovery_operation_ids": remaining,
            "recovery_operation_id": remaining[0] if remaining else None,
            "_pull_operation_id": None
            if job.payload.get("_pull_operation_id") == operation_id
            else job.payload.get("_pull_operation_id"),
        }
        job.updated_at = now()
        return True
