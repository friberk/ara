"""The experimental open-model gate (ARA-090).

Open models are the Ollama chat models, the Qwen3 embedding profiles and the Qwen3 reranker. They
are frozen and off unless EXPERIMENTAL_OPEN_MODELS is true. The gate sits at the boundaries
(catalogs, routes, job dispatch and the embedding factory), not inside the frozen code. Stored
references to open models stay readable, report themselves unavailable and never fall back to a
paid model.
"""

from sqlalchemy import and_, func, or_

from app.core.errors import AppError
from app.integrations.model_catalog import LOCAL_MODELS, local_spec

DISABLED = "OPEN_MODELS_DISABLED"
OFF = "Open models are turned off on this server."
CHOOSE_MODEL = f"{OFF} Choose a hosted model."
CHOOSE_SEARCH = f"{OFF} Choose a hosted search model."
SEARCH_NOTE = f"{OFF} This paper is searched by keywords until you choose a hosted search model."
KEYWORD_NOTE = "Searched by keywords because open models are turned off on this server."
MODEL_OPERATIONS = ("model_download", "model_delete")


def enabled(settings) -> bool:
    return settings.experimental_open_models


def disabled(message: str = CHOOSE_MODEL) -> AppError:
    return AppError(409, DISABLED, message)


def open_chat_model(settings, key: str | None) -> bool:
    """A local chat model while open models are off."""
    return local_spec(key or "") is not None and not enabled(settings)


def open_profile(settings, profile) -> bool:
    """A local embedding or reranker profile while open models are off."""
    return profile.provider == "ollama" and not enabled(settings)


def offered(settings, catalog: dict) -> dict:
    """An embedding or reranker catalog without its local profiles while open models are off."""
    return {key: profile for key, profile in catalog.items() if not open_profile(settings, profile)}


def offered_reranker(settings, key: str | None) -> str | None:
    """A saved local reranker means no reranking while open models are off, never the paid one."""
    from app.integrations.reranker_catalog import RERANKERS

    profile = RERANKERS.get(key or "")
    return None if profile and open_profile(settings, profile) else key


def lane_jobs():
    """SQL for the jobs that only the open-model lanes run: model operations and local generation.

    These are the jobs the dispatcher publishes to `model_publish` and `local_publish`.
    """
    from app.models.jobs import BackgroundJob
    from app.services.dispatcher import LOCAL_GENERATION_KINDS

    return or_(
        BackgroundJob.kind.in_(MODEL_OPERATIONS),
        and_(
            BackgroundJob.kind.in_(LOCAL_GENERATION_KINDS),
            func.coalesce(BackgroundJob.payload["model"].astext, "").in_(list(LOCAL_MODELS)),
        ),
    )
