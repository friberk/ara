"""Native Ollama chat protocol. Thinking stays separate from the persisted answer."""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.integrations.llm import Completion, LLMError, estimate_tokens


class OllamaLLM:
    def __init__(
        self,
        settings,
        model_id: str,
        *,
        http_client=None,
        reasoning_efforts: Sequence[str] = ("default",),
    ):
        self.settings, self.model_id = settings, model_id
        self.reasoning_efforts = tuple(reasoning_efforts)
        self._owns_client = http_client is None
        self.client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ollama_request_timeout_seconds, connect=5, pool=5),
            follow_redirects=False,
        )
        self.usage: dict = {}

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def parameters(
        self,
        model,
        effort,
        instructions,
        prompt,
        *,
        stream=False,
        schema=None,
        max_output_tokens=None,
    ):
        if effort not in self.reasoning_efforts:
            raise LLMError(
                "INVALID_REASONING", "This local model does not support that reasoning effort.", 422
            )
        limit = self.settings.ollama_context_window - self.settings.ollama_max_output_tokens - 512
        output_limit = self.settings.ollama_max_output_tokens
        if max_output_tokens is not None:
            if (
                not isinstance(max_output_tokens, int)
                or isinstance(max_output_tokens, bool)
                or not 1 <= max_output_tokens <= output_limit
            ):
                raise LLMError(
                    "CONTEXT_LIMIT", "Intermediate output exceeds the configured allocation.", 413
                )
            output_limit = max_output_tokens
        if estimate_tokens(instructions) + estimate_tokens(prompt) > limit:
            raise LLMError(
                "CONTEXT_LIMIT", "This request exceeds the application context budget.", 413
            )
        arguments = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "stream": stream,
            "options": {
                "num_ctx": self.settings.ollama_context_window,
                "num_predict": output_limit,
                "num_thread": self.settings.ollama_num_threads,
            },
        }
        if effort != "default":
            arguments["think"] = False if effort == "none" else effort
        if schema is not None:
            arguments["format"] = schema
        return arguments

    def parse(self, data: dict) -> tuple[str, bool]:
        if not isinstance(data, dict):
            raise LLMError(
                "MODEL_RESPONSE_INVALID", "The local model returned an invalid response."
            )
        if "error" in data:
            raise LLMError(
                "MODEL_REQUEST_FAILED", "The local model request failed. It was not retried."
            )
        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content", ""), str):
            raise LLMError(
                "MODEL_RESPONSE_INVALID", "The local model returned an invalid response."
            )
        if not isinstance(data.get("done"), bool):
            raise LLMError(
                "MODEL_RESPONSE_INVALID", "The local model returned an invalid response."
            )
        if data["done"]:
            if data.get("done_reason") != "stop":
                raise LLMError("MODEL_INCOMPLETE", "The local model did not complete its answer.")
            counts = [data.get("prompt_eval_count", 0), data.get("eval_count", 0)]
            if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in counts):
                raise LLMError("MODEL_RESPONSE_INVALID", "The local model returned invalid usage.")
            self.usage = {
                "input_tokens": counts[0],
                "output_tokens": counts[1],
                "total_tokens": sum(counts),
            }
        return message.get("content", ""), data["done"]

    def check_http(self, response):
        if response.is_success:
            return
        if response.status_code == 503:
            raise LLMError(
                "LOCAL_MODEL_BUSY",
                "The local model is busy; try again after the current answer.",
                429,
            )
        raise LLMError(
            "MODEL_REQUEST_FAILED", "The local model request failed. It was not retried."
        )

    async def complete(
        self, model, effort, instructions, prompt, *, schema=None, max_output_tokens=None
    ) -> Completion:
        arguments = self.parameters(
            model, effort, instructions, prompt, schema=schema, max_output_tokens=max_output_tokens
        )
        try:
            async with asyncio.timeout(self.settings.ollama_request_timeout_seconds):
                response = await self.client.post(
                    self.settings.ollama_base_url + "/api/chat", json=arguments
                )
                self.check_http(response)
                content, done = self.parse(response.json())
                if not done or not content.strip():
                    raise LLMError(
                        "MODEL_INCOMPLETE", "The local model did not complete its answer."
                    )
                return Completion(content, self.usage)
        except (ValueError, UnicodeError) as exc:
            raise LLMError(
                "MODEL_RESPONSE_INVALID", "The local model returned an invalid response."
            ) from exc
        except (httpx.HTTPError, TimeoutError) as exc:
            raise LLMError(
                "MODEL_REQUEST_FAILED", "The local model request failed. It was not retried."
            ) from exc

    async def stream(self, model, effort, instructions, prompt) -> AsyncIterator[str]:
        arguments = self.parameters(model, effort, instructions, prompt, stream=True)
        done, content = False, ""
        try:
            async with asyncio.timeout(self.settings.ollama_request_timeout_seconds):
                async with self.client.stream(
                    "POST", self.settings.ollama_base_url + "/api/chat", json=arguments
                ) as response:
                    self.check_http(response)
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        if len(line) > 1_000_000:
                            raise LLMError(
                                "MODEL_RESPONSE_INVALID",
                                "The local model returned an invalid response.",
                            )
                        delta, done = self.parse(json.loads(line))
                        content += delta
                        if delta:
                            yield delta
                        if done:
                            break
            if not done:
                raise LLMError(
                    "MODEL_INTERRUPTED", "The local model stream ended before completion."
                )
            if not content.strip():
                raise LLMError("MODEL_INCOMPLETE", "The local model did not complete its answer.")
        except (ValueError, UnicodeError) as exc:
            raise LLMError(
                "MODEL_RESPONSE_INVALID", "The local model returned an invalid response."
            ) from exc
        except (httpx.HTTPError, TimeoutError) as exc:
            raise LLMError(
                "MODEL_REQUEST_FAILED", "The local model request failed. It was not retried."
            ) from exc
