"""Bounded HTTP control of the managed Ollama runtime; no process-local job state."""

import json
from dataclasses import dataclass, field

import httpx

from app.core.errors import AppError
from app.integrations.model_catalog import LocalModelSpec


def local_model_thinking(show_data: dict) -> dict | None:
    """Accept current metadata only; an HTTP 200 does not prove a named level."""
    thinking = show_data.get("thinking")
    if not isinstance(thinking, dict):
        return None
    values = thinking.get("values")
    default = thinking.get("default")
    if not isinstance(values, list) or not values:
        return None
    if any(
        type(value) not in {bool, str}
        or (isinstance(value, str) and (not value or len(value) > 20 or value == "default"))
        for value in [*values, default]
    ):
        return None
    if not any(type(value) is type(default) and value == default for value in values):
        return None
    mapping = {}
    for value in values:
        key = "on" if value is True else "none" if value is False else value
        if key in mapping and type(mapping[key]) is not type(value):
            return None
        mapping[key] = value
    return {"values": list(values), "default": default}


def local_think_mapping(thinking: dict | None) -> dict[str, bool | str]:
    if not thinking:
        return {}
    return {
        "on" if value is True else "none" if value is False else value: value
        for value in thinking["values"]
    }


def local_model_reasoning(show_data: dict) -> list[str]:
    return ["default", *local_think_mapping(local_model_thinking(show_data))]


@dataclass
class PullProgress:
    layers: dict[str, tuple[int, int | None]] = field(default_factory=dict)

    def __post_init__(self):
        # Previous attempts may have lost cached partials during a runtime restart.
        # Preserve known layer totals, but trust only bytes observed in this attempt.
        self.layers = {digest: (0, size[1]) for digest, size in self.layers.items()}

    def apply(self, event: dict) -> tuple[int, int | None]:
        digest = event.get("digest")
        if isinstance(digest, str):
            previous, previous_total = self.layers.get(digest, (0, None))
            completed = event.get("completed", previous)
            total = event.get("total", previous_total)
            if (
                not isinstance(completed, int)
                or isinstance(completed, bool)
                or completed < 0
                or (
                    total is not None
                    and (not isinstance(total, int) or isinstance(total, bool) or total < 0)
                )
            ):
                raise AppError(
                    502, "MODEL_PROTOCOL_ERROR", "The runtime returned invalid transfer progress."
                )
            self.layers[digest] = max(previous, completed), total
        completed = sum(item[0] for item in self.layers.values())
        total = (
            sum(item[1] for item in self.layers.values())
            if self.layers and all(item[1] is not None for item in self.layers.values())
            else None
        )
        return completed, total


def runtime_error(value: str) -> AppError:
    detail = value.lower()
    if "memory" in detail:
        return AppError(
            409, "MODEL_MEMORY_LIMIT", "The model exceeds the local runtime memory limit."
        )
    if "space" in detail or "disk" in detail:
        return AppError(507, "MODEL_DISK_FULL", "The local runtime has insufficient disk space.")
    return AppError(
        502, "MODEL_RUNTIME_ERROR", "The local model runtime could not complete this operation."
    )


def protocol_error() -> AppError:
    return AppError(502, "MODEL_PROTOCOL_ERROR", "The runtime returned an invalid response.")


def inventory_models(data: dict) -> list[dict]:
    models = data.get("models", [])
    if not isinstance(models, list) or any(not isinstance(item, dict) for item in models):
        raise protocol_error()
    return models


def probe_message(data: dict) -> dict:
    if not isinstance(data, dict):
        raise protocol_error()
    message = data.get("message", {})
    if (
        not isinstance(message, dict)
        or not isinstance(message.get("content", ""), str)
        or not isinstance(message.get("thinking", ""), str)
    ):
        raise protocol_error()
    return message


class OllamaRuntime:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        *,
        stall_seconds=120,
        probe_timeout=900,
        probe_output_tokens=2048,
        probe_threads=4,
    ):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.stall_seconds = stall_seconds
        self.probe_timeout = probe_timeout
        self.probe_output_tokens = probe_output_tokens
        self.probe_threads = probe_threads

    async def request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.client.request(
                method, self.base_url + path, timeout=kwargs.pop("timeout", 30), **kwargs
            )
            if (
                response.status_code == 404
                and method == "POST"
                and path.startswith("/api/ara/pulls/")
                and path.endswith("/pause")
            ):
                raise AppError(
                    503,
                    "MODEL_PAUSE_UNCONFIRMED",
                    "The runtime has not confirmed this operation is settled. "
                    "Retry after restoring the managed runtime.",
                )
            if response.is_error:
                try:
                    data = response.json()
                    detail = data.get("error", "") if isinstance(data, dict) else ""
                except ValueError:
                    detail = ""
                if detail:
                    raise runtime_error(str(detail))
            response.raise_for_status()
            data = response.json() if response.content else {}
            if not isinstance(data, dict):
                raise protocol_error()
            return data
        except (httpx.HTTPError, ValueError):
            raise AppError(
                503, "LOCAL_RUNTIME_UNAVAILABLE", "The local model runtime is unavailable."
            ) from None

    async def supports_pause(self) -> bool:
        try:
            response = await self.client.get(self.base_url + "/api/ara/capabilities", timeout=10)
            if response.status_code == 404:
                return False
            response.raise_for_status()
            data = response.json()
            return data.get("protocol_version") == 1 and data.get("pull_control") is True
        except (httpx.HTTPError, ValueError):
            raise AppError(
                503, "LOCAL_RUNTIME_UNAVAILABLE", "The local model runtime is unavailable."
            ) from None

    async def pause(self, operation_id: str) -> None:
        if not await self.supports_pause():
            raise AppError(
                409, "MODEL_PAUSE_UNSUPPORTED", "This runtime cannot pause downloads safely."
            )
        data = await self.request("POST", f"/api/ara/pulls/{operation_id}/pause")
        if data.get("state") != "paused":
            raise AppError(
                503, "MODEL_PAUSE_FAILED", "The runtime has not confirmed a paused transfer."
            )

    async def pull(self, model: str, operation_id: str, *, controlled: bool):
        path = "/api/ara/pull" if controlled else "/api/pull"
        body = {"model": model, "stream": True}
        if controlled:
            body["operation_id"] = operation_id
        success = False
        try:
            async with self.client.stream(
                "POST",
                self.base_url + path,
                json=body,
                timeout=httpx.Timeout(self.stall_seconds, connect=10),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise AppError(502, "MODEL_PULL_FAILED", "The local model download failed.")
                    success |= event.get("status") == "success"
                    yield event
            if not success:
                raise AppError(
                    502, "MODEL_PULL_INCOMPLETE", "The local model download did not finish."
                )
        except httpx.TimeoutException:
            raise AppError(
                504, "MODEL_PULL_STALLED", "The local model download stopped making progress."
            ) from None
        except (httpx.HTTPError, ValueError, TypeError):
            raise AppError(
                503, "LOCAL_RUNTIME_UNAVAILABLE", "The local model runtime is unavailable."
            ) from None

    async def artifact(self, spec: LocalModelSpec, *, verify_digest=True) -> dict | None:
        data = await self.request("GET", "/api/tags")
        for item in inventory_models(data):
            if item.get("name") == spec.model_id or item.get("model") == spec.model_id:
                digest = str(item.get("digest", "")).removeprefix("sha256:")
                if verify_digest and digest != spec.expected_digest:
                    raise AppError(
                        409,
                        "MODEL_DIGEST_MISMATCH",
                        "The installed model differs from the approved artifact.",
                    )
                return item
        return None

    async def verify(self, spec: LocalModelSpec, *, context_window: int) -> dict:
        if await self.artifact(spec) is None:
            raise AppError(
                409,
                "MODEL_WEIGHTS_MISSING",
                "The downloaded model is absent from runtime inventory.",
            )
        show = await self.request("POST", "/api/show", json={"model": spec.model_id})
        template = show.get("template", "")
        capabilities = show.get("capabilities", [])
        model_info = show.get("model_info", {})
        if (
            not isinstance(template, str)
            or not isinstance(capabilities, list)
            or any(not isinstance(value, str) for value in capabilities)
            or not isinstance(model_info, dict)
        ):
            raise protocol_error()
        lengths = [v for k, v in model_info.items() if k.endswith(".context_length")]
        if any(type(value) is not int or value <= 0 for value in lengths):
            raise protocol_error()
        if spec.kind == "embedding":
            from app.integrations.embeddings import OLLAMA_EMBED_CONTEXT

            # Embedders run at their own fixed num_ctx, not the chat context window.
            if lengths and min(lengths) < OLLAMA_EMBED_CONTEXT:
                raise AppError(
                    409,
                    "MODEL_CONTEXT_UNSUPPORTED",
                    "The local embedding model cannot support the embedding context.",
                )
            return await self.verify_embedding(spec, capabilities, context_window=context_window)
        if not template or "completion" not in capabilities:
            raise AppError(
                409,
                "MODEL_VALIDATION_FAILED",
                "The local model does not provide a usable chat template.",
            )
        if lengths and min(lengths) < context_window:
            raise AppError(
                409,
                "MODEL_CONTEXT_UNSUPPORTED",
                "The local model cannot support the configured context.",
            )
        version = await self.request("GET", "/api/version")
        runtime_version = version.get("version")
        if not isinstance(runtime_version, str) or not runtime_version.strip():
            raise protocol_error()
        probe = await self.request(
            "POST",
            "/api/chat",
            timeout=self.probe_timeout,
            json={
                "model": spec.model_id,
                "messages": [{"role": "user", "content": "Reply OK."}],
                "stream": False,
                "keep_alive": 0,
                "options": {
                    "num_ctx": context_window,
                    "num_predict": self.probe_output_tokens,
                    "num_thread": self.probe_threads,
                    "temperature": 0.0,
                },
            },
        )
        message = probe_message(probe)
        if (
            probe.get("done") is not True
            or probe.get("done_reason") != "stop"
            or not message.get("content", "").strip()
        ):
            raise AppError(
                409, "MODEL_VALIDATION_FAILED", "The local model did not return a usable response."
            )
        # Probe actual streaming, rather than promising it from the catalog.
        streamed = ""
        done = False
        try:
            async with self.client.stream(
                "POST",
                self.base_url + "/api/chat",
                json={
                    "model": spec.model_id,
                    "messages": [{"role": "user", "content": "Reply OK."}],
                    "stream": True,
                    "keep_alive": 0,
                    "options": {
                        "num_ctx": context_window,
                        "num_predict": self.probe_output_tokens,
                        "num_thread": self.probe_threads,
                        "temperature": 0.0,
                    },
                },
                timeout=self.probe_timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    event = json.loads(line)
                    streamed += probe_message(event).get("content", "")
                    if event.get("done") is True and event.get("done_reason") != "stop":
                        raise AppError(
                            409,
                            "MODEL_VALIDATION_FAILED",
                            "The local model streaming probe was truncated.",
                        )
                    done |= event.get("done") is True
        except (httpx.HTTPError, ValueError, TypeError):
            raise AppError(
                409, "MODEL_VALIDATION_FAILED", "The local model streaming probe failed."
            ) from None
        if not done or not streamed.strip():
            raise AppError(
                409, "MODEL_VALIDATION_FAILED", "The local model streaming probe failed."
            )
        reasoning = ["default"]
        thinking = local_model_thinking(show)
        candidates = local_think_mapping(thinking)
        # Older runtimes may have no metadata. Only a demonstrated change from
        # default private thinking to none can establish the boolean off control.
        if "thinking" not in show and message.get("thinking"):
            candidates["none"] = False
        verified_mapping = {}
        for effort, value in candidates.items():
            try:
                response = await self.request(
                    "POST",
                    "/api/chat",
                    timeout=self.probe_timeout,
                    json={
                        "model": spec.model_id,
                        "messages": [{"role": "user", "content": "Reply only OK."}],
                        "stream": False,
                        "think": value,
                        "keep_alive": 0,
                        "options": {
                            "num_ctx": context_window,
                            "num_predict": self.probe_output_tokens,
                            "num_thread": self.probe_threads,
                            "temperature": 0.0,
                        },
                    },
                )
                candidate_message = probe_message(response)
                if (
                    response.get("done") is True
                    and response.get("done_reason") == "stop"
                    and candidate_message.get("content", "").strip()
                    and (value is not False or not candidate_message.get("thinking"))
                ):
                    reasoning.append(effort)
                    verified_mapping[effort] = value
            except AppError as error:
                if error.code not in {"MODEL_RUNTIME_ERROR"}:
                    raise
        structured = False
        try:
            response = await self.request(
                "POST",
                "/api/chat",
                timeout=self.probe_timeout,
                json={
                    **({"think": False} if verified_mapping.get("none") is False else {}),
                    "model": spec.model_id,
                    "messages": [{"role": "user", "content": 'Return only {"ok":true}.'}],
                    "stream": False,
                    "keep_alive": 0,
                    "format": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                    "options": {
                        "num_ctx": context_window,
                        "num_predict": self.probe_output_tokens,
                        "num_thread": self.probe_threads,
                        "temperature": 0.0,
                    },
                },
            )
            content = json.loads(probe_message(response).get("content", ""))
            structured = (
                response.get("done") is True
                and response.get("done_reason") == "stop"
                and content == {"ok": True}
                and type(content.get("ok")) is bool
            )
        except (ValueError, TypeError, AttributeError):
            pass
        except AppError as error:
            if error.code not in {"MODEL_RUNTIME_ERROR"}:
                raise
        return {
            "digest": spec.expected_digest,
            "runtime_version": runtime_version,
            "context_window": context_window,
            "reasoning_efforts": reasoning,
            "thinking_schema": 1,
            "thinking": thinking,
            "think_mapping": verified_mapping,
            "supports_streaming": True,
            "supports_structured_output": structured,
        }

    async def runtime_version(self) -> str:
        version = (await self.request("GET", "/api/version")).get("version")
        if not isinstance(version, str) or not version.strip():
            raise protocol_error()
        return version

    async def verify_embedding(self, spec, capabilities, *, context_window: int) -> dict:
        """Embedders need the embedding capability and must return their native dimensions."""
        from app.integrations.embeddings import OLLAMA_EMBED_CONTEXT

        if "embedding" not in capabilities:
            raise AppError(
                409, "MODEL_VALIDATION_FAILED", "The local model does not provide embeddings."
            )
        runtime_version = await self.runtime_version()
        probe = await self.request(
            "POST",
            "/api/embed",
            timeout=self.probe_timeout,
            json={
                "model": spec.model_id,
                "input": "probe",
                "keep_alive": 0,
                "options": {"num_ctx": OLLAMA_EMBED_CONTEXT, "num_thread": self.probe_threads},
            },
        )
        vectors = probe.get("embeddings")
        if (
            not isinstance(vectors, list)
            or len(vectors) != 1
            or not isinstance(vectors[0], list)
            or len(vectors[0]) != spec.embedding_dimensions
        ):
            raise AppError(
                409,
                "MODEL_VALIDATION_FAILED",
                "The local embedding model returned unexpected dimensions.",
            )
        # thinking_schema and context_window keep the shared freshness check meaningful.
        return {
            "kind": "embedding",
            "digest": spec.expected_digest,
            "runtime_version": runtime_version,
            "context_window": context_window,
            "thinking_schema": 1,
            "embedding_dimensions": spec.embedding_dimensions,
            "reasoning_efforts": ["default"],
            "supports_streaming": False,
            "supports_structured_output": False,
        }

    async def delete(self, spec: LocalModelSpec) -> None:
        if await self.artifact(spec, verify_digest=False) is None:
            return
        await self.request("POST", "/api/generate", json={"model": spec.model_id, "keep_alive": 0})
        running = await self.request("GET", "/api/ps")
        if any(
            item.get("name") == spec.model_id or item.get("model") == spec.model_id
            for item in inventory_models(running)
        ):
            raise AppError(
                409, "MODEL_UNLOAD_FAILED", "The model is still loaded; deletion was stopped."
            )
        await self.request("DELETE", "/api/delete", json={"model": spec.model_id})
        if await self.artifact(spec, verify_digest=False) is not None:
            raise AppError(
                502, "MODEL_DELETE_FAILED", "The local model remains in runtime inventory."
            )
