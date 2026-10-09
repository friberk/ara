"""Synthetic Ollama HTTP protocol for deterministic browser tests; no model weights."""

import json
import re
import threading
import time
from uuid import UUID

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
}


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
                    operation = {"cancel": threading.Event(), "stopped": threading.Event()}
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
                    handler.send_json({"error": "Synthetic transfer has not stopped"}, 503)
        elif path == "/api/show":
            handler.send_json(
                {
                    "template": "{{ .Prompt }}",
                    "capabilities": ["completion", "thinking"],
                    "thinking_levels": [False],
                    "model_info": {"fixture.context_length": 8192},
                }
            )
        elif path == "/api/generate":
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
        prompt = json.dumps(body.get("messages", []))
        schema = body.get("format")
        if isinstance(schema, dict):
            answer = json.dumps(structured_value(schema, schema))
        elif "Reply OK" in prompt:
            answer = "OK"
        else:
            sources = list(dict.fromkeys(re.findall(r"source:([0-9a-fA-F-]{36})", prompt)))
            citation = f" [source:{sources[0]}]" if sources else ""
            answer = (
                "The paper evaluates a retrieval-first pipeline on the Orion-12 dataset. "
                "Its measured accuracy is 86 percent, using twelve synthetic examples."
                + citation
                + "\n\nThe small synthetic dataset limits the result's "
                "applicability to real research libraries." + citation
            )
        message = {"role": "assistant", "content": answer}
        if body.get("think") is not False:
            message["thinking"] = "Synthetic reasoning fixture; never part of the displayed answer."
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
                        "message": {"role": "assistant", "content": answer[start : start + 35]},
                        "done": False,
                    },
                )
                time.sleep(0.025)
            self.ndjson(handler, {**terminal, "message": {"role": "assistant", "content": ""}})
        except (BrokenPipeError, ConnectionResetError):
            pass
