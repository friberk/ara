"""Synthetic Ollama HTTP protocol for deterministic browser tests; no model weights."""

import json
import math
import re
import threading
import time
from uuid import UUID

from vectors import STOP, WORD, fixture_vector

MODELS = {
    "hf.co/IFM/K2-Horizon-3.7B-GGUF:Q4_K_M": (
        "2e334d42ac17a07fb7e6447dd5c98d0c501d4f90bef900cc57fd3f6cd067dd2c",
        3156599066,
    ),
    "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M": (
        "3a4c598f85cc1e1977b7384e0e9b5e6181ff3e2ac5a535f68bbf26aaf90dc278",
        5592218900,
    ),
    "qwen3.8:27b-q4_K_M": (
        "25b843619e944cd0ae6069f94ff4e5e26a16e109ccbc0a66a0f05979ed70098e",
        17741872132,
    ),
    "qwen3-embedding:4b-q4_K_M": (
        "df5bd2e3c74cd8d069d21dc038f1b359fcdc9458fce1c99bd43c9eb1518ff907",
        2496704041,
    ),
    "qwen3-embedding:8b-q4_K_M": (
        "64b933495768fbd3b87c20583d379728a07471e0c66733a9df87cd1901b3c44b",
        4676805193,
    ),
    "fanyx/Qwen3-Reranker-0.6B-Q8_0:latest": (
        "fd021d86a15e539ac1b4f3bec2d1c6b15a3e158f316adb0d1325c713240103b3",
        639152466,
    ),
}


# Passage headers start a line: "[S1] Results · p. 3". Example handles inside instructions do not.
PASSAGE_HANDLE = re.compile(r'(?:^|\\n|\n|")\[(S\d{1,3})\] ')
SOURCE = re.compile(r"source:([0-9a-fA-F-]{36})")
RERANK = re.compile(r"<Query>: (.*?)\n<Document>: (.*?)<\|im_end\|>", re.S)


def embedding_dimensions(model: str) -> int:
    for size, dims in ((":0.6b", 1024), (":4b", 2560), (":8b", 4096)):
        if size in model:
            return dims
    return 1024


def cited_answer(prompt: str, first: str, second: str, wrapper: str = "[{}]") -> str:
    """Cite the first supplied passage handle, else the first legacy source UUID."""
    if "NO-EVIDENCE-FIXTURE" in prompt:
        return "[insufficient-evidence] The supplied passages do not report this."
    handles = list(dict.fromkeys(PASSAGE_HANDLE.findall(prompt)))
    sources = list(dict.fromkeys(SOURCE.findall(prompt)))
    if handles:
        citation = " " + wrapper.format(handles[0])
    elif sources:
        citation = " " + wrapper.format("source:" + sources[0])
    else:
        citation = ""
    return first + citation + second + citation


def relevance(query: str, document: str) -> float:
    terms = {w for w in WORD.findall(query.lower()) if w not in STOP}
    words = {w for w in WORD.findall(document.lower()) if w not in STOP}
    overlap = len(terms & words) / max(1, len(terms))
    return 0.02 + 0.96 * overlap


class OllamaFixture:
    def __init__(self):
        self.lock = threading.Lock()
        self.installed = set()
        self.partial = {}
        self.operations = {}

    def get(self, handler, path):
        if path == "/api/ara/capabilities":
            handler.send_json({"protocol_version": 1, "pull_control": True})
        elif path == "/api/version":
            handler.send_json({"version": "synthetic-ollama-fixture-1"})
        elif path == "/api/tags":
            with self.lock:
                models = [
                    {
                        "name": name,
                        "model": name,
                        "digest": MODELS[name][0],
                        "size": MODELS[name][1],
                    }
                    for name in self.installed
                ]
            handler.send_json({"models": models})
        elif path == "/api/ps":
            handler.send_json({"models": []})
        else:
            return False
        return True

    def mutate(self, handler, path, body, structured_value):
        if path == "/api/ara/pull":
            self.pull(handler, body)
        elif path.startswith("/api/ara/pulls/") and path.endswith("/pause"):
            operation_id = path.split("/")[-2]
            with self.lock:
                operation = self.operations.get(operation_id)
                if operation is None:
                    operation = {
                        "cancel": threading.Event(),
                        "stopped": threading.Event(),
                    }
                    operation["cancel"].set()
                    operation["stopped"].set()
                    self.operations[operation_id] = operation
            if operation is None:
                handler.send_json({"error": "Unknown synthetic operation"}, 404)
            else:
                operation["cancel"].set()
                if operation["stopped"].wait(5):
                    handler.send_json({"state": "paused"})
                else:
                    handler.send_json(
                        {"error": "Synthetic transfer has not stopped"}, 503
                    )
        elif path == "/api/show":
            model = str(body.get("model", ""))
            if "embedding" in model:
                handler.send_json(
                    {
                        "template": "",
                        "capabilities": ["embedding"],
                        "model_info": {
                            "fixture.context_length": 32768,
                            "fixture.embedding_length": embedding_dimensions(model),
                        },
                    }
                )
            elif "reranker" in model.lower():
                handler.send_json(
                    {
                        "template": "{{ .Prompt }}",
                        "capabilities": ["completion"],
                        "model_info": {"fixture.context_length": 32768},
                    }
                )
            else:
                handler.send_json(
                    {
                        "template": "{{ .Prompt }}",
                        "capabilities": ["completion", "thinking"],
                        "thinking": {
                            "values": [False, True, "low", "medium", "high"],
                            "default": "high",
                        },
                        "model_info": {"fixture.context_length": 8192},
                    }
                )
        elif path == "/api/embed":
            self.embed(handler, body)
        elif path == "/api/generate":
            if body.get("logprobs") and "reranker" in str(body.get("model", "")).lower():
                self.rerank(handler, body)
            else:
                handler.send_json({"done": True, "done_reason": "stop"})
        elif path == "/api/delete":
            with self.lock:
                self.installed.discard(body.get("model"))
                self.partial.pop(body.get("model"), None)
            handler.send_json({})
        elif path == "/api/chat":
            self.chat(handler, body, structured_value)
        else:
            return False
        return True

    def installed_or_404(self, handler, model) -> bool:
        with self.lock:
            installed = model in self.installed
        if not installed:
            handler.send_json({"error": "Synthetic model weights missing"}, 404)
        return installed

    def embed(self, handler, body):
        model = str(body.get("model", ""))
        if not self.installed_or_404(handler, model):
            return
        texts = body.get("input", [])
        texts = [texts] if isinstance(texts, str) else texts
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            handler.send_json({"error": "Invalid synthetic embed input"}, 400)
            return
        dims = body.get("dimensions") or embedding_dimensions(model)
        handler.send_json(
            {
                "model": model,
                "embeddings": [fixture_vector(text, dims) for text in texts],
                "total_duration": 1,
                "load_duration": 0,
                "prompt_eval_count": sum(max(1, len(text.split())) for text in texts),
            }
        )

    def rerank(self, handler, body):
        model = str(body.get("model", ""))
        if not self.installed_or_404(handler, model):
            return
        match = RERANK.search(str(body.get("prompt", "")))
        if not body.get("raw") or match is None:
            handler.send_json({"error": "Synthetic reranker expects a raw template"}, 400)
            return
        p_yes = relevance(*match.groups())
        yes, no = math.log(p_yes), math.log(1 - p_yes)
        token, logprob = ("yes", yes) if p_yes >= 0.5 else ("no", no)
        handler.send_json(
            {
                "model": model,
                "response": token,
                "done": True,
                "done_reason": "length",
                "prompt_eval_count": len(match.group(2).split()) + 40,
                "eval_count": 1,
                "logprobs": [
                    {
                        "token": token,
                        "logprob": logprob,
                        "top_logprobs": [
                            {"token": "yes", "logprob": yes},
                            {"token": "no", "logprob": no},
                        ],
                    }
                ],
            }
        )

    def ndjson(self, handler, event):
        handler.wfile.write((json.dumps(event) + "\n").encode())
        handler.wfile.flush()

    def streaming_headers(self, handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "application/x-ndjson")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True

    def pull(self, handler, body):
        model = body.get("model")
        operation_id = body.get("operation_id")
        try:
            if UUID(operation_id).int == 0 or model not in MODELS:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            handler.send_json({"error": "Invalid synthetic pull"}, 400)
            return
        operation = {"cancel": threading.Event(), "stopped": threading.Event()}
        with self.lock:
            if operation_id in self.operations:
                handler.send_json({"error": "Duplicate synthetic operation"}, 409)
                return
            self.operations[operation_id] = operation
            completed = self.partial.get(model, 0)
        digest, total = MODELS[model]
        self.streaming_headers(handler)
        try:
            while completed < total and not operation["cancel"].is_set():
                completed = min(total, completed + max(1, total // 25))
                with self.lock:
                    self.partial[model] = completed
                self.ndjson(
                    handler,
                    {
                        "status": "pulling synthetic layer",
                        "digest": "sha256:" + digest,
                        "completed": completed,
                        "total": total,
                    },
                )
                operation["cancel"].wait(0.4)
            if operation["cancel"].is_set():
                self.ndjson(handler, {"error": "context canceled"})
            else:
                with self.lock:
                    self.installed.add(model)
                self.ndjson(handler, {"status": "success"})
        except (BrokenPipeError, ConnectionResetError):
            # A worker disconnect owns cancellation; closing a browser never reaches here.
            operation["cancel"].set()
        finally:
            operation["stopped"].set()

    def chat(self, handler, body, structured_value):
        model = body.get("model")
        with self.lock:
            installed = model in self.installed
        if not installed:
            handler.send_json({"error": "Synthetic model weights missing"}, 404)
            return
        thinking = body.get("think", "high")
        if not (
            type(thinking) is bool
            or (isinstance(thinking, str) and thinking in {"low", "medium", "high"})
        ):
            handler.send_json({"error": "Unsupported synthetic thinking control"}, 400)
            return
        prompt = json.dumps(body.get("messages", []))
        schema = body.get("format")
        if isinstance(schema, dict):
            answer = json.dumps(structured_value(schema, schema))
        elif "Reply OK" in prompt:
            answer = "OK"
        else:
            # The retained 7B medium chat used this wrapper in a live run.
            # Exercise canonicalization in the browser instead of hiding it in mocks.
            answer = cited_answer(
                prompt,
                "The paper evaluates a retrieval-first pipeline on the Orion-12 dataset. "
                "Its measured accuracy is 86 percent, using twelve synthetic examples.",
                "\n\nThe small synthetic dataset limits the result's "
                "applicability to real research libraries.",
                wrapper="【{}】" if thinking == "medium" else "[{}]",
            )
        message = {"role": "assistant", "content": answer}
        if body.get("think") is not False:
            message["thinking"] = (
                "Synthetic reasoning fixture; never part of the displayed answer."
            )
        terminal = {
            "model": model,
            "message": message,
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 100,
            "eval_count": 30,
        }
        if not body.get("stream", True):
            handler.send_json(terminal)
            return
        self.streaming_headers(handler)
        try:
            if "thinking" in message:
                self.ndjson(
                    handler,
                    {
                        "model": model,
                        "message": {
                            "role": "assistant",
                            "thinking": message["thinking"],
                            "content": "",
                        },
                        "done": False,
                    },
                )
            for start in range(0, len(answer), 35):
                self.ndjson(
                    handler,
                    {
                        "model": model,
                        "message": {
                            "role": "assistant",
                            "content": answer[start : start + 35],
                        },
                        "done": False,
                    },
                )
                time.sleep(0.025)
            self.ndjson(
                handler, {**terminal, "message": {"role": "assistant", "content": ""}}
            )
        except (BrokenPipeError, ConnectionResetError):
            pass
