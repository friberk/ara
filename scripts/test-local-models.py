#!/usr/bin/env python3
"""Opt-in real 7B validation in a dedicated container/volume; never resets app data.

Examples:
  python3 scripts/test-local-models.py --stock
  python3 scripts/test-local-models.py --resume
A fresh --volume ara-ollama-validation-... is required to observe actual resume.
Results go to an explicit JSON file or stdout; model weights remain in Docker.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODEL = "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M"
WEIGHT_DIGEST = (
    "sha256:eb89c15a0ae9712be2ee462bf43802de14200f20f93b73da6eb68c2ebdd28e4e"
)
MANIFEST_DIGEST = (
    "sha256:3a4c598f85cc1e1977b7384e0e9b5e6181ff3e2ac5a535f68bbf26aaf90dc278"
)
STOCK_IMAGE = "ollama/ollama:0.40.1@sha256:69f27594d8127cb43db1edcafa5e2d3cd8f88bdbc54a2cf3ceb11b8d138a24b1"
LABEL = "ara.local-model-validation"


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def request(base: str, path: str, data=None, timeout=900):
    encoded = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(
        base + path, encoded, {"Content-Type": "application/json"}
    )
    return urllib.request.urlopen(req, timeout=timeout)


def json_request(base, path, data=None):
    with request(base, path, data) as response:
        return json.load(response)


def stream(base, path, data, on_event=None):
    events = []
    with request(base, path, data, timeout=21600) as response:
        for line in response:
            if not line.strip():
                continue
            event = json.loads(line)
            events.append(event)
            if on_event:
                on_event(event)
            if "error" in event:
                raise RuntimeError(event["error"])
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stock", action="store_true", help="Prove the stock architecture failure"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Pause a real transfer before resuming"
    )
    parser.add_argument("--volume", default="ara-ollama-validation-models")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.volume.startswith("ara-ollama-validation-") or not all(
        c.isalnum() or c in "-_" for c in args.volume
    ):
        parser.error(
            "volume must begin ara-ollama-validation- and contain only letters, digits, - or _"
        )
    if args.stock and args.resume:
        parser.error("stock Ollama has no acknowledged-pause protocol")
    image = STOCK_IMAGE if args.stock else "ara-ollama:0.40.1-ara.1"
    name = f"ara-ollama-validation-{uuid.uuid4().hex[:10]}"
    # Label ownership is checked even for a pre-existing dedicated test volume.
    listed = docker("volume", "ls", "--format", "{{.Name}}").splitlines()
    if args.volume in listed:
        labels = (
            json.loads(docker("volume", "inspect", args.volume))[0].get("Labels") or {}
        )
        if labels.get(LABEL) != "true":
            parser.error(
                "refusing an existing volume without the validation ownership label"
            )
    else:
        docker("volume", "create", "--label", f"{LABEL}=true", args.volume)
    report = {
        "model": MODEL,
        "image": image,
        "volume": args.volume,
        "stock": args.stock,
    }
    docker(
        "run",
        "-d",
        "--name",
        name,
        "--label",
        f"{LABEL}=true",
        "--memory",
        "12g",
        "--cpus",
        "4",
        "-p",
        "127.0.0.1::11434",
        "-v",
        f"{args.volume}:/root/.ollama",
        "-e",
        "OLLAMA_NOPRUNE=true",
        "-e",
        "OLLAMA_CONTEXT_LENGTH=8192",
        "-e",
        "OLLAMA_MAX_LOADED_MODELS=1",
        "-e",
        "OLLAMA_NUM_PARALLEL=1",
        "-e",
        "OLLAMA_KEEP_ALIVE=2m",
        image,
    )
    try:
        inspect = json.loads(docker("inspect", name))[0]
        port = inspect["NetworkSettings"]["Ports"]["11434/tcp"][0]["HostPort"]
        base = f"http://127.0.0.1:{port}"
        report["image_id"] = inspect["Image"]
        deadline = time.monotonic() + 60
        while True:
            try:
                report["version"] = json_request(base, "/api/version")
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.25)
        if not args.stock:
            assert json_request(base, "/api/ara/capabilities") == {
                "protocol_version": 1,
                "pull_control": True,
            }
        pull_start = time.monotonic()
        if args.resume:
            # Record progress before pause; the ack must wait for all owned I/O.
            operation = str(uuid.uuid4())
            before_pause = {}

            def pause_when_started(event):
                if (
                    event.get("digest") == WEIGHT_DIGEST
                    and 0 < event.get("completed", 0) < event.get("total", 0)
                    and not before_pause
                ):
                    before_pause.update(event)
                    started = time.monotonic()
                    ack = json_request(base, f"/api/ara/pulls/{operation}/pause", {})
                    assert ack == {"state": "paused"}, ack
                    report["pause_ack_seconds"] = time.monotonic() - started

            # Pull reading and pause execute independently to avoid a client-side
            # socket backpressure deadlock while the runtime closes its stream.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = []

                def enqueue_pause(event):
                    if (
                        event.get("digest") == WEIGHT_DIGEST
                        and 0 < event.get("completed", 0) < event.get("total", 0)
                        and not pending
                    ):
                        pending.append(pool.submit(pause_when_started, event))

                try:
                    stream(
                        base,
                        "/api/ara/pull",
                        {"model": MODEL, "operation_id": operation},
                        enqueue_pause,
                    )
                except RuntimeError as error:
                    if not pending or "context canceled" not in str(error):
                        raise
                for future in pending:
                    future.result()
            if not before_pause:
                raise RuntimeError(
                    "resume was not exercised: use a fresh validation volume"
                )
            report["paused_at_bytes"] = before_pause["completed"]
            duplicate = json_request(base, f"/api/ara/pulls/{operation}/pause", {})
            assert duplicate == {"state": "paused"}
            report["partial_files"] = docker(
                "exec", name, "sh", "-c", "ls /root/.ollama/models/blobs/*partial*"
            ).splitlines()
        observed = []

        def progress(event):
            if event.get("digest") == WEIGHT_DIGEST and event.get("completed", 0):
                observed.append(event["completed"])

        path = "/api/pull" if args.stock else "/api/ara/pull"
        events = stream(
            base, path, {"model": MODEL, "operation_id": str(uuid.uuid4())}, progress
        )
        assert events[-1].get("status") == "success", events[-1]
        report["pull_seconds"] = time.monotonic() - pull_start
        report["first_resume_progress_bytes"] = observed[0] if observed else None
        if args.resume:
            assert observed and observed[0] >= report["paused_at_bytes"]
        # Independent on-disk hash and size validation (not only API metadata).
        filename = "/root/.ollama/models/blobs/" + WEIGHT_DIGEST.replace(":", "-")
        weight_hash = docker("exec", name, "sha256sum", filename).split()[0]
        assert weight_hash == WEIGHT_DIGEST.removeprefix("sha256:")
        report["weight_sha256"] = weight_hash
        report["weight_bytes"] = int(docker("exec", name, "stat", "-c", "%s", filename))
        assert report["weight_bytes"] == 5592217984
        show = json_request(base, "/api/show", {"model": MODEL})
        report["architecture"] = show.get("model_info", {}).get("general.architecture")
        assert report["architecture"] == "k2-horizon"
        assert show.get("template"), "missing real chat template"
        report["template_characters"] = len(show["template"])
        report["manifest_digest"] = next(
            m["digest"]
            for m in json_request(base, "/api/tags")["models"]
            if m["name"].lower() == MODEL.lower()
        )
        assert report["manifest_digest"].removeprefix(
            "sha256:"
        ) == MANIFEST_DIGEST.removeprefix("sha256:")
        chat_start = time.monotonic()
        first_token = []

        def chat_event(event):
            if event.get("message", {}).get("content") and not first_token:
                first_token.append(time.monotonic() - chat_start)

        try:
            events = stream(
                base,
                "/api/chat",
                {
                    "model": MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": "What is 2 + 2? Answer in one short sentence.",
                        }
                    ],
                    "stream": True,
                    "think": False,
                    "options": {
                        "num_ctx": 8192,
                        "num_predict": 2048,
                        "num_thread": 4,
                        "temperature": 0,
                    },
                },
                chat_event,
            )
        except (RuntimeError, urllib.error.HTTPError) as error:
            if not args.stock:
                raise
            detail = (
                error.read().decode()
                if isinstance(error, urllib.error.HTTPError)
                else str(error)
            )
            assert "unknown model architecture" in detail and "k2-horizon" in detail, (
                detail
            )
            report["expected_stock_failure"] = detail
        else:
            assert not args.stock, (
                "stock unexpectedly supports K2: reassess compatibility patch"
            )
            assert (
                events[-1].get("done") is True
                and events[-1].get("done_reason") == "stop"
            ), "missing final untruncated completion"
            answer = "".join(
                event.get("message", {}).get("content", "") for event in events
            ).strip()
            assert answer and ("4" in answer or "four" in answer.lower()), answer
            report.update(
                answer=answer,
                first_token_seconds=first_token[0],
                chat_seconds=time.monotonic() - chat_start,
                streamed_chunks=sum(
                    bool(e.get("message", {}).get("content")) for e in events
                ),
                final_metrics=events[-1],
                loaded_models=json_request(base, "/api/ps"),
            )
        if not args.stock:
            schema = {
                "type": "object",
                "properties": {
                    "answer": {"type": "integer"},
                    "explanation": {"type": "string"},
                },
                "required": ["answer", "explanation"],
                "additionalProperties": False,
            }
            structured = stream(
                base,
                "/api/chat",
                {
                    "model": MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": "Return JSON with answer equal to 4 and explanation equal to two plus two.",
                        }
                    ],
                    "format": schema,
                    "think": False,
                    "stream": True,
                    "options": {
                        "num_ctx": 8192,
                        "num_predict": 2048,
                        "num_thread": 4,
                        "temperature": 0,
                    },
                },
            )
            assert structured[-1].get("done_reason") == "stop", structured[-1]
            document = json.loads(
                "".join(e.get("message", {}).get("content", "") for e in structured)
            )
            assert document == {"answer": 4, "explanation": "two plus two"}, document
            report["structured_schema_answer"] = document
            reasoning = stream(
                base,
                "/api/chat",
                {
                    "model": MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": "What is 2 + 2? Answer in one short sentence.",
                        }
                    ],
                    "stream": True,
                    "options": {
                        "num_ctx": 8192,
                        "num_predict": 2048,
                        "num_thread": 4,
                        "temperature": 0,
                    },
                },
            )
            assert reasoning[-1].get("done_reason") == "stop", reasoning[-1]
            final_answer = "".join(
                e.get("message", {}).get("content", "") for e in reasoning
            )
            thoughts = "".join(
                e.get("message", {}).get("thinking", "") for e in reasoning
            )
            assert (
                "4" in final_answer
                and "think" not in final_answer.lower()
                and len(final_answer) < 100
            ), final_answer
            assert thoughts, "default thinking was not observed"
            report["default_thinking"] = {
                "final_answer": final_answer,
                "separate_thinking_characters": len(thoughts),
                "final_metrics": reasoning[-1],
            }
        report["container_memory"] = docker(
            "stats", "--no-stream", "--format", "{{.MemUsage}}", name
        )
        report["memory_peak_bytes"] = docker(
            "exec", name, "cat", "/sys/fs/cgroup/memory.peak"
        )
        report["result"] = "passed"
    finally:
        # Only the uniquely named container created above is removed. Volumes persist.
        docker("rm", "-f", name)
        encoded = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.write_text(encoded)
        print(encoded)


if __name__ == "__main__":
    main()
