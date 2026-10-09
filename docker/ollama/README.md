# Managed Ollama runtime

The default `runtime` target is a native CPU Linux build for amd64 or arm64. It starts the server with an empty persistent model store; startup never pulls or loads model weights. `ollama-models` contains weights and partial downloads. The service is internal to Compose, with no host port or Docker socket. Core API readiness does not depend on it.

The application caps context at 8192 and output at 2048; the runtime allows one loaded model and one inference at a time, with a two-minute keep-alive and configurable 12 GiB container limit. The backend passes `OLLAMA_NUM_THREADS=4` by default to match the four-CPU quota; allowing the runner to auto-select 12 threads under that quota caused severe throttling in live validation. The memory ceiling includes weights, KV cache, and filesystem cache; it does not promise that every catalog model fits. macOS Docker uses CPU inference. NVIDIA and AMD acceleration require a native compatible Linux host and the respective override.

## Pinned sources and licenses

- Ollama 0.40.1: `cf2a313a298066d572c36812e5ad30a21c0db13b` (MIT).
- Original llama.cpp pin: `b11351`. It rejects the curated 7B model with `unknown model architecture: 'k2-horizon'` in a real `/api/chat` call.
- Compatibility llama.cpp: `b11454`, commit `4625240437c6821ee5c2da99e12d4817c6a8f07f` (MIT).
- Upstream context: [Ollama issue 18698, comment 6024936344](https://github.com/ollama/ollama/issues/18698#issuecomment-6024936344).
- Stock validation image: `ollama/ollama:0.40.1@sha256:69f27594d8127cb43db1edcafa5e2d3cd8f88bdbc54a2cf3ceb11b8d138a24b1`.
- Build/runtime/GPU base image digests are explicit in `docker/ollama.Dockerfile`.
- Ollama, Go dependencies, llama.cpp, and vendored license aggregates are included in the resulting image. Model weights have their own upstream licenses and are never embedded in the runtime image.

`001-llama-cpp-hooks.patch` remains Ollama's unchanged patch; all hunks apply to b11454. `002-clef-b11454.patch` adapts Ollama's decision-model patch: newer upstream already declares and implements `common_decision_type`/`common_get_decision_type`, so those duplicate hunks are removed. The full-context CLEF configuration follows upstream's embedding setup; the decision graph skips upstream's classifier projection and vocabulary projection to retain the hidden states expected by Ollama's `score_fields` endpoint. The added server-decision include is preserved. Existing score collection/task hooks otherwise remain intact. K2 itself comes from upstream b11454, not an invented local architecture implementation.

## Private pull-control protocol, version 1

- `GET /api/ara/capabilities` → `{"protocol_version":1,"pull_control":true}`.
- `POST /api/ara/pull` with `{"model":"...","operation_id":"UUID"}` streams ordinary Ollama pull NDJSON. A UUID belongs to one attempt for the daemon lifetime; duplicates return 409. Resume uses a new UUID.
- `POST /api/ara/pulls/{operation_id}/pause` cancels that attempt and responds `{"state":"paused"}` only after its handler has joined its transfer/checkpoint work. Repeated pause is safe. Pausing an unknown valid UUID atomically reserves a completed, canceled tombstone and acknowledges pause; any later pull with that UUID is rejected with 409. This preserves a stop barrier when a daemon restart loses the old active registry. A full registry rejects a new pause barrier with 503 rather than acknowledging without protection. A completed attempt is already quiescent and can acknowledge pause.

Cancellation releases an operation's download references. The last owner marks that digest as closing, cancels and joins preparation/transfer/checkpoint work, then releases that digest for reuse. Per-digest ready/released signals keep network requests and file-settlement waits outside the global manager mutex, so a stalled HEAD for one digest cannot block another digest's cancellation. A different operation that still owns a shared blob continues downloading it. Public `/api/pull` progress sends also observe cancellation. Private pull handlers allow 100 ms for a canceled response to drain, then interrupt any blocked Write/Flush using a request-scoped response deadline. Their watcher is joined before Gin can recycle the writer. The response drain grace does not promise a universal transfer/checkpoint pause deadline. Retry waits observe cancellation rather than sleeping up to 32 seconds. `OLLAMA_NOPRUNE=true` preserves partials over daemon restarts; no daemon restart is used to implement pause. There is no broad orphan cleanup or deletion of other operations' files. The operation tombstone registry is bounded to 10,000 entries and rejects new attempts when full rather than forgetting duplicate IDs.

The slow-registry test checks transfer cessation, checkpointed range resume, duplicate operation rejection, repeat pause and invalid request handling. Additional tests cover an unrelated stalled HEAD, two owners sharing initialization, response backpressure plus handler cleanup, a reading client's complete HTTP stream, and fresh-daemon/concurrent/capacity pause tombstones. A separate retry test reaches the four-second retry delay and checks cancellation joins it within 500 ms. These are measured fixture assertions, not a universal deadline for slow disks or every registry.

## Validation

Build CPU: `docker build --target runtime -f docker/ollama.Dockerfile -t ara-ollama:0.40.1-ara.1 .`. Build concurrency defaults to two jobs. The build executes the private protocol tests. For a race/full server suite, use the pinned source plus `003-pull-control.patch` and the two `ara_pull*.go` files, then run `go test -race ./server -run TestARA` and `go test ./server`.

The explicit live command `python3 scripts/test-local-models.py --resume --volume ara-ollama-validation-new-run --output /tmp/ara-local-model-result.json` downloads **only** `hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M`, pauses/resumes a real transfer, verifies the 5,592,217,984-byte weight SHA-256 and manifest identity, and checks the model's real chat template, streamed content, terminal completion, latency, and cgroup memory. Use a fresh validation volume to exercise resume. `--stock` checks the stock architecture failure. The runner only removes its own uniquely named test container and preserves its labeled test volume.

Core/test Compose uses an empty offline fixture instead of building the runtime. The fixture rejects actual downloads/inference. It demonstrates deterministic empty-state behavior, not provider/model access.

NVIDIA: `docker compose -f compose.yaml -f compose.nvidia.yaml up --build`. Set `OLLAMA_CUDA_ARCHITECTURES` for the actual GPU if needed; install NVIDIA Container Toolkit on the host.

AMD: `docker compose -f compose.yaml -f compose.amd.yaml up --build`. Set `OLLAMA_AMDGPU_TARGETS`, `OLLAMA_VIDEO_GID`, and `OLLAMA_RENDER_GID` to match the host. Requires supported ROCm devices and kernel drivers.

Hardware scope: live validation in this change uses Linux ARM64 CPU under Docker on macOS. Linux amd64 CPU and both GPU targets are provided but are not claimed as hardware-tested. The newer decision-model branches are build-reviewed but no additional decision-model weights were authorized for live regression testing.

## Measured ARM64 validation

The initial CPU image `sha256:a02404d87f797cc72d0abd4bf48ce04df70c3da5c5aa4c6bc9a915b6b9897660` completed the 7B live checks. The real transfer resumed at byte 75,625, finished in 95.28 seconds including pause/resume, and matched both pinned hashes. The final streamed answer finished with `done_reason=stop`; first content arrived at 9.81 seconds including a 9.18-second model load. A warm JSON-schema request completed in 1.55 seconds. Default thinking was separated into `message.thinking`; the answer remained in `message.content`. Explicit `think:false` worked. The API rejected explicit `low`, `medium`, and `high` as unsupported, despite corresponding branches in the upstream Jinja template, so the app must not advertise those levels from template text alone. `xhigh` is also unsupported.

Steady container usage was 6.53 GiB; cgroup peak was 11.42 GiB during hashing/loading/inference. These measurements used an otherwise active 15.66 GiB Docker VM and include cache pressure. A separate live isolation test (`python3 docker/ollama/test_live_isolation.py --base http://127.0.0.1:11435`) paused synthetic registry traffic in 1.7 ms and verified no subsequent transferred bytes while real 7B inference returned a final answer in 0.82 seconds. The fixture requires a host reachable from the runtime as `host.docker.internal` (Docker Desktop supplies this; Linux requires an explicit host mapping).

After independent cancellation review, image `sha256:f0c8e95243f7acbe5fdbc510830e1dd5622ae054a4fce1979db692cd80db14a5` passed all ten private-protocol tests in three repeated race-enabled runs, the full Ollama server suite, and retained-7B live revalidation. First content arrived at 9.56 seconds including an 8.94-second model load; schema output and default-thinking separation passed again. Steady memory was 6.52 GiB and peak 10.30 GiB. Independent pull pause acknowledged in 2.3 ms while concurrent real inference completed. A fresh unknown UUID pause acknowledged 200, a late pull was rejected with 409, and repeated pause acknowledged 200. No additional model weights were downloaded for this review.

## Full application 7B check

An isolated Compose project ran the FastAPI application, both worker queues, PostgreSQL, Redis and MinIO against the reviewed real runtime with `OPENAI_API_KEY` empty. It reused the retained 7B weights, verified installation, processed the three-page synthetic research PDF, and generated a stored summary covering all three chunks. The summary finished in 36.30 seconds. A paper question streamed 124 application SSE events in 14.36 seconds and cited the correct document's pages 1 and 2. Manual inspection matched its Orion-12 dataset, twelve examples and 86 percent accuracy to the synthetic source. This demonstrates the application's integration; the fixture makes no claim about research benchmarks.

PostgreSQL recorded the Ollama provider, pinned artifact digest, runtime version, 8192 context, 2048 output, four threads and disabled thinking for both responses. Hosted cost reservations remained zero. The full application run reached a cgroup peak of 12,721,811,456 bytes (11.85 GiB), with approximately 6.65 GiB steady usage and zero OOM events under the 12 GiB limit. The measured margin is small; plan extra host/VM memory for the other services. These readings include filesystem cache.

Restarting PostgreSQL, MinIO, Ollama, API and both workers preserved the summary, chat, saved local default, byte-identical original PDF and verified installation. No additional weights were downloaded, and no 3.7B, 27B, amd64 or GPU inference was tested.
