# ARA-022 — Managed local models implementation plan

Approved in conversation on October 8, 2026. Implement through TDD/BDD with supervised independent agents; use the existing application architecture and Impeccable design. No GitHub publication. Branch: `feat/managed-ollama`.

## Goal and constraints

Ollama is included in Compose without downloading or loading weights at startup. Users manage IFM K2 Horizon 3.7B, IFM K2 Horizon 7B, and Qwen3.8 27B Q4_K_M through Settings. Missing weights keep model choices visible but unavailable. Background download state survives browser navigation, page closure, and service interruption. Manual pause/resume/retry are required. Deleting default weights preserves the saved default and all chats/summaries; unavailable generation is blocked without paid fallback. Real inference tests use 7B, never the 27B artifact.

Single-user modular monolith; PostgreSQL jobs/outbox authoritative; every task owns its AsyncSession; process/event-loop clients stay local. PDFs remain in MinIO. Local model files belong in an Ollama named volume. Retain the neutral shadcn/Geist design. Every changed behavior needs an observed failing test before implementation and relevant passing regression checks.

## Reviewed catalog

| Key | Reference | Manifest SHA256 | Installation bytes |
| --- | --- | --- | ---: |
| `ifm-k2-horizon-3.7b` | `hf.co/IFM/K2-Horizon-3.7B-GGUF:Q4_K_M` | `2e334d42ac17a07fb7e6447dd5c98d0c501d4f90bef900cc57fd3f6cd067dd2c` | 3156599066 |
| `ifm-k2-horizon-7b` | `hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M` | `3a4c598f85cc1e1977b7384e0e9b5e6181ff3e2ac5a535f68bbf26aaf90dc278` | 5592218900 |
| `qwen3.8-27b` | `qwen3.8:27b-q4_K_M` | `25b843619e944cd0ae6069f94ff4e5e26a16e109ccbc0a66a0f05979ed70098e` | 17741872132 |

Apache-2.0 publisher artifacts. IFM 3.7B revision `1751cb49e31823f4401fc1d195db8a2c61a79783` contains `K2-Horizon-4B-Q4_K_M.gguf`, hash `07773aed93890d4f5d08b421430000d5c8d73cefc74fbdc32e67d820f23207b2`. IFM 7B revision `9fb01f7b397994455262f4b8256e4e00e4949ea9` contains `K2-Horizon-7B-Q4_K_M.gguf`, hash `eb89c15a0ae9712be2ee462bf43802de14200f20f93b73da6eb68c2ebdd28e4e`. Qwen model blob hash `f5f1dd8920d417aac2718b0bda3403da274301efdd6760b4f0f4b864ff2ad57d`. Do not substitute Qwen3.5 or download whole repositories.

Sources: [IFM 3.7B](https://huggingface.co/IFM/K2-Horizon-3.7B-GGUF), [IFM 7B](https://huggingface.co/IFM/K2-Horizon-7B-GGUF), [Qwen3.8](https://ollama.com/library/qwen3.8:27b-q4_K_M).

## Runtime and storage

Pin Ollama 0.40.1 (`cf2a313a298066d572c36812e5ad30a21c0db13b`) and immutable image/source identity. Default CPU execution works across container platforms. Provide NVIDIA/AMD overrides. Internal port 11434 only; core readiness never depends on Ollama. Named volume preserves complete and partial weights. Resource defaults: 12 GiB configurable ceiling, context 8192, output 2048, one local inference/download/loaded model, two-minute idle unload. A ceiling is not startup allocation. The current VM is 15.66 GiB; Qwen CPU use needs more memory. Expose actual resource errors without claiming a weight-size equals RAM requirement.

First validate actual IFM7B stock execution. If needed, use the user-approved reviewed custom Ollama build with upstream llama.cpp b11454 (`4625240437c6821ee5c2da99e12d4817c6a8f07f`), adapting existing hooks/Clef patches and testing templates/parsers. This is not a one-line version bump. Stock pull cancellation has no acknowledged stop and may hang in unbuffered progress delivery. A reviewed operation-scoped control extension must make progress/retry waits cancellable, acknowledge settled transfer checkpoints, and never restart the daemon to pause. Detect capabilities and do not promise reliable pause against unmodified external runtimes. `OLLAMA_NOPRUNE=true` retains partials; document scoped cleanup.

Separate `model-worker` queues handle model operations and long local summaries, leaving PDF/hosted work responsive. Keep 60-second leases, 10-second heartbeats, two-minute transfer stalls, six-hour per-attempt transfer ceiling, bounded retries, immediate cancellation on lost lease. Aggregate cumulative bytes per digest, not per event. Persist at most once/second and on stage changes; unknown totals are indeterminate. Terminal success plus installed/digest/runtime verification precedes completion.

## Frozen public contracts

All endpoints under `/api/v1`. Keep existing hosted response fields and SSE events.

- `GET /models`: existing Model fields plus nullable `unavailable_reason` (human text), nullable `unavailable_code`, nullable `installation` for hosted models. Installation fields: `state` (`missing`, `queued`, `downloading`, `pausing`, `paused`, `verifying`, `ready`, `deleting`, `failed`), `weights_present: bool`, `quantization: str`, `download_bytes: int`, `completed_bytes: int`, `total_bytes: int | null`, `job_id: UUID | null`, `digest: str | null`, `updated_at: datetime | null`, `error: JobError | null`. Local status is `available` only when verified and runtime usable, otherwise `unavailable` with reason. Local context_window reflects the effective allocation. `default` is an allowed local reasoning sentinel; advertise named efforts only when validated.
- `POST /models/{key}/download`: JSON `{request_id: UUID}`, 202 JobStatus. Same UUID/content replays original operation; conflicting reuse 409.
- `DELETE /models/{key}/installation`: UUID `Idempotency-Key` header, 202 JobStatus; already absent is idempotent success. Active mutation/generation conflicts 409.
- `POST /jobs/{id}/pause` and `/resume`: JSON `{request_id: UUID}`, 202 JobStatus. Persist intent immediately; stage `pausing` remains processing until acknowledgment. Pause/resume do not exhaust transfer retries. Repeated requests safe.
- Extend existing `/jobs/{id}/retry` for local operations (optional request body for backwards compatibility), retaining hosted non-replay rules.
- JobStatus state adds `paused`; fields add nullable `model_key`, `completed_bytes`, `total_bytes`. Job filters accept `model_download`, `model_delete`; paused is unfinished but need not be polled while no state transition is pending.

Alembic owns `ModelInstallation`, durable model-use leases, operation UUID uniqueness, and paused state migration. Row locking prevents duplicate model mutations. Recovery reads tags/show before pull so already-completed transfer is reconciled. Manual pause never auto-resumes. Deletion unloads idle models before removing weights, rejects active use, confirms tags removal, retains histories/defaults. Queued generation checks availability at start.

## LLM boundary

Add provider-aware catalog/adapter selection. Ollama native `/api/chat` maps NDJSON to existing app SSE; completion/structured output use the same service interface with Pydantic validation. Local calls do not require OPENAI_API_KEY, hosted price registry membership, or hosted dollars. All responses retain request UUID safety, citation validation, histories, provider/artifact/runtime/effective settings provenance. Enforce context per model across retrieval/history/full-document summary batching and reduction; preserve full-document coverage. Incomplete/truncated outputs fail explicitly. Busy interactive local inference returns actionable 429; background local summaries wait without burning transfer/paid retry budgets.

## UI and acceptance

Local models section between Default model and Appearance. Missing: Download; transfer: bytes/progress/Pause; pausing: pending; paused: Resume; verifying: status; ready: Delete weights; failed: inline reason/Try again. Explain background continuity once. Unavailable picker rows are muted and keyboard discoverable with guarded activation, hover/focus/touch explanation and Settings anchor link. Download completion never auto-selects. Root model query polls active work every 2 seconds, periodically while visible/idle, and refetches on focus/mount. Activity includes model jobs. Announce stage changes, not each byte. Confirm deletion without promising full size is reclaimed from shared blobs.

BDD: missing weights block selection; browser closure preserves download; pause persists across restart; resume reuses ranges; verification failures retain bytes but block use; deleting default preserves default/history and blocks paid fallback; active inference/delete race is rejected.

## Tasks and ownership

1. ARA-044 Runtime: Docker image, operation control, resource configuration, GPU overrides and real 7B compatibility. Own `docker/ollama*`, Compose/config example, live runner. First gate: bounded cancellation/resume and IFM7B smoke.
2. ARA-045 Durable operations: schemas/catalog, migration/models, runtime HTTP integration, repositories/services/routes/actors and recovery. One owner for migration/shared contract. Tests: duplicates/deliveries, layer progress, stalls/lease loss, pauses/restarts, digest drift, safe deletion and use races.
3. ARA-046 LLM: provider adapter/routing, Settings/Resources, chat/summary/metadata context and provenance. Consume shared catalog/contracts. Tests: no hosted key/budget for local, model context boundaries, SSE/structured failures, preserved hosted behavior.
4. ARA-047 UI: Settings/picker/Activity/queries and RTL. Consume frozen API. Test accessible controls, navigation/remount restoration, pending/verified distinction, retries/default preservation/deletion conflicts.
5. ARA-048 QA: deterministic HTTP/runtime fixtures and browser workflows, isolated real persistence services, opt-in real7B only. Measure memory/latency, streaming, summary/Q&A, pause/resume, crashes, delete/reinstall. Do not claim Qwen/3.7 live tests from fixtures.
6. ARA-049 Documentation/review: commands, hardware, patch provenance/licenses, limitations, regression checks and actual journal evidence. Complete docs at each task; final independent branch review before integration.

Every task: write failing behavior test, execute/record red, implement, execute green, refactor/regress, focused Conventional Commit carrying ARA ID. New feature branch; preserve archives, no Co-Authored-By and no push. Definition of Done includes automated checks actually executed, API contract regenerated, Compose persistence, tracker and authentic journal updates. No human-hour scope freeze.
