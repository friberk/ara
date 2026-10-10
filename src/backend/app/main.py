import asyncio
import logging
import re
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.resources import Resources
from app.routes.ai import router as ai_router
from app.routes.chat import router as chat_router
from app.routes.documents import router as documents_router
from app.routes.fulltext import router as fulltext_router
from app.routes.history import router as history_router
from app.routes.jobs import router
from app.routes.local_models import router as local_models_router
from app.routes.metadata import router as metadata_router
from app.routes.research import router as research_router
from app.routes.retrieval import router as retrieval_router
from app.routes.uploads import router as uploads_router
from app.services.dispatcher import dispatcher_loop
from app.services.health import readiness
from app.services.reindex import prepare_search

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    resource_factory: Callable[[Settings], Resources] = Resources,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.secret_values())
        resources = resource_factory(settings)
        app.state.resources = resources
        from app.jobs.actors import execute_job
        from app.jobs.model_actors import execute_local_summary, execute_model_job

        dispatcher = asyncio.create_task(
            dispatcher_loop(
                resources,
                execute_job.send,
                model_publish=execute_model_job.send,
                local_publish=execute_local_summary.send,
            )
        )
        search = asyncio.create_task(prepare_search(resources))
        try:
            yield
        finally:
            for task in (search, dispatcher):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await resources.close()

    app = FastAPI(title="AI Research Assistant", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", supplied) else str(uuid4())
        )
        origin = request.headers.get("Origin")
        if (
            request.method in {"POST", "PATCH", "PUT", "DELETE"}
            and origin
            and origin not in settings.cors_origins
        ):
            response = error(
                request, 403, "ORIGIN_NOT_ALLOWED", "This browser origin is not allowed."
            )
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        try:
            response = await call_next(request)
        except Exception:
            logger.error("Unhandled request error", extra={"request_id": request.state.request_id})
            response = error(request, 500, "INTERNAL_ERROR", "An unexpected error occurred.")
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError):
        content = {
            "code": exc.code,
            "message": exc.message,
            "request_id": request.state.request_id,
            "details": exc.details,
        }
        headers = {}
        if exc.retry_after is not None:
            content["retry_after"] = exc.retry_after
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(content, status_code=exc.status_code, headers=headers)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        codes = {404: "NOT_FOUND", 409: "CONFLICT", 503: "SERVICE_UNAVAILABLE"}
        return error(
            request, exc.status_code, codes.get(exc.status_code, "REQUEST_ERROR"), str(exc.detail)
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        return error(
            request, 422, "VALIDATION_ERROR", "The request contains invalid values.", details
        )

    @app.get("/health/live", tags=["health"])
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready(request: Request):
        checks = await readiness(request.app.state.resources)
        healthy = all(value == "ok" for value in checks.values())
        return JSONResponse(
            {"status": "ready" if healthy else "unavailable", "checks": checks},
            status_code=200 if healthy else 503,
        )

    app.include_router(router(settings.app_env == "development"))
    app.include_router(research_router)
    app.include_router(fulltext_router)
    app.include_router(documents_router)
    app.include_router(ai_router)
    app.include_router(local_models_router)
    app.include_router(chat_router)
    app.include_router(history_router)
    app.include_router(retrieval_router)
    app.include_router(metadata_router)
    app.include_router(uploads_router)
    return app


def error(request, status, code, message, details=None):
    return JSONResponse(
        {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", str(uuid4())),
            "details": details or [],
        },
        status_code=status,
    )


app = create_app()
