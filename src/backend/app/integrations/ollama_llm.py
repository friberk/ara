"""Native Ollama chat protocol. Thinking stays separate from the persisted answer."""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.integrations.context_registry import local_profile
from app.integrations.llm import LOCAL_TEMPERATURE, Completion, LLMError, output_allocation
from app.integrations.tokens import PromptMessage, check_roles, count_messages


class OllamaLLM:
    def __init__(
        self,
        settings,
        model_id: str,
        *,
        http_client=None,
        reasoning_efforts: Sequence[str] = ("default",),
        thinking: dict | None = None,
    ):
        self.settings, self.model_id = settings, model_id
        self.reasoning_efforts = tuple(reasoning_efforts)
        from app.integrations.ollama import local_think_mapping

        self.thinking = thinking
        self.think_mapping = local_think_mapping(thinking)
        self._owns_client = http_client is None
        self.client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ollama_request_timeout_seconds, connect=5, pool=5),
            follow_redirects=False,
        )
        self.usage: dict = {}
        self.truncated = False

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def request(
        self, model, effort, messages, *, stream=False, schema=None, max_output_tokens=None
    ):
        if effort not in self.reasoning_efforts:
            raise LLMError(
                "INVALID_REASONING", "This local model does not support that reasoning effort.", 422
            )
        check_roles(messages)
        profile = local_profile(self.settings, model, effort, thinking=self.thinking)
        output = output_allocation(profile.max_output, max_output_tokens)
        if count_messages(profile.counter, messages) > profile.input_budget:
            raise LLMError(
                "CONTEXT_LIMIT", "This request exceeds the application context budget.", 413
            )
        arguments = {
            "model": self.model_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "options": {
                "num_ctx": profile.window,
                # Thinking shares num_predict, so it never consumes the answer's allowance.
                "num_predict": output + profile.thinking_allowance,
                "num_thread": self.settings.ollama_num_threads,
                "temperature": LOCAL_TEMPERATURE,
            },
        }
        if effort != "default":
            arguments["think"] = self.think_mapping.get(
                effort, False if effort == "none" else True if effort == "on" else effort
            )
        if schema is not None:
            arguments["format"] = schema
        return arguments

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
        messages = [PromptMessage("system", instructions), PromptMessage("user", prompt)]
        return self.request(
            model,
            effort,
            messages,
            stream=stream,
            schema=schema,
            max_output_tokens=max_output_tokens,
        )

    def parse(self, data: dict, *, accept_truncated: bool = False) -> tuple[str, bool]:
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
            self.truncated = accept_truncated and data.get("done_reason") == "length"
            if data.get("done_reason") != "stop" and not self.truncated:
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
        return await self.complete_request(
            self.parameters(
                model,
                effort,
                instructions,
                prompt,
                schema=schema,
                max_output_tokens=max_output_tokens,
            )
        )

    async def complete_messages(
        self,
        model,
        effort,
        messages,
        *,
        schema=None,
        max_output_tokens=None,
        accept_truncated=False,
    ) -> Completion:
        """`accept_truncated` returns output cut at the length limit, marked, instead of failing."""
        return await self.complete_request(
            self.request(
                model, effort, messages, schema=schema, max_output_tokens=max_output_tokens
            ),
            accept_truncated=accept_truncated,
        )

    async def complete_request(self, arguments, *, accept_truncated=False) -> Completion:
        try:
            async with asyncio.timeout(self.settings.ollama_request_timeout_seconds):
                response = await self.client.post(
                    self.settings.ollama_base_url + "/api/chat", json=arguments
                )
                self.check_http(response)
                content, done = self.parse(response.json(), accept_truncated=accept_truncated)
                if not done or not content.strip():
                    raise LLMError(
                        "MODEL_INCOMPLETE", "The local model did not complete its answer."
                    )
                return Completion(content, self.usage, truncated=self.truncated)
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
        async for delta in self.stream_request(arguments):
            yield delta

    async def stream_messages(self, model, effort, messages) -> AsyncIterator[str]:
        async for delta in self.stream_request(self.request(model, effort, messages, stream=True)):
            yield delta

    async def stream_request(self, arguments) -> AsyncIterator[str]:
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
