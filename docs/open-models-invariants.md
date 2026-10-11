# Open-model invariants

Rules for code that manages or runs open (local) models: the Ollama runtime, `model-worker`, local chat, embedding and reranking models, and their jobs. Read this before changing `app/integrations/ollama*.py`, `app/integrations/open_models.py`, `app/services/local_models.py`, `app/jobs/model_actors.py` or `docker/ollama/`.

Open models are experimental and frozen since 2026-10-09 (ARA-090). They sit behind `EXPERIMENTAL_OPEN_MODELS` (off by default) and the `open-models` Compose profile. Don't extend or refactor them unless the user lifts the freeze, and keep their tests passing with the flag on. Most rules below apply only while the flag is on; the weights volume and its logs matter either way. User-facing behaviour, measured memory and the GPU overrides are in [the technical reference](reference.md#experimental-open-models-frozen); the original design is [ARA-022](plans/ARA-022-managed-local-models.md).

## Weights and readiness

- Complete and partial weights live in the `ollama-models` named volume. `docker compose down` must never take `--volumes`.
- Startup never downloads weights. Stale installations prepare through background verification jobs.
- Core API readiness never depends on Ollama.
- Logs: `docker compose logs --tail 100 model-worker ollama`.
- Default inference runs on CPU. The NVIDIA and AMD overrides are optional and need compatible Linux hosts.

## Mutations and inference admission

- Model mutations (pull, delete) and global inference admission take durable ownership in PostgreSQL.
- A pause is complete only after the managed runtime acknowledges that work has settled. Never infer settlement from a 404, and never restart the daemon to pause.
- Pausing an unknown but valid operation UUID records a canceled tombstone in that daemon, so a late pull with the same UUID is rejected.
- Recovery settles every unresolved current or previous operation UUID before it releases ownership.
- A transfer failure that the runtime has not confirmed stays fenced in durable `settling` cleanup until it is acknowledged. While any UUID is pending, admit no inference and no other mutation.

## Selection and generation

- A local model becomes selectable only after its artifact, runtime and context capabilities are verified.
- Deleting weights preserves the saved default and all chat history.
- A local request never falls back to paid (hosted) generation.
- Summary provenance is checkpointed under admission, not re-read after generation.
- Native sampling sets temperature 0.0 explicitly.

## Reasoning controls

- Native entries use the verified `thinking.values` and `thinking.default` with exact Boolean or string mappings. Never infer named levels from an HTTP 200 or from the obsolete `thinking_levels`.
- IFM models show None, Low, Medium and High. Models that only support on/off reasoning show a Reasoning toggle.
- Legacy preferences resolve only through the verified per-model `reasoning_aliases`, each pointing directly at a supported level.
- Capability-schema or runtime changes must be verified with retained weights, using the opt-in engine check in [the reference](reference.md#managed-local-models) (`scripts/test-local-models.py --retained-only`).

## Automatic preparation

- Models that were ready and are still wanted refresh automatically through durable verification-only jobs. Routine upgrades need no manual Verify.
- Preserve the user's pause, delete and failure intent, and inference admission.
- Verification retries and recovery never pull missing weights.
- Keep runtime inspection off the core dispatch loop.
- Derive installation operation labels and historical job labels without migrations.

## The Ollama boundary

Validate Ollama inventory, metadata and probe responses where they enter the integration. A malformed field raises a safe, permanent protocol error and settles the model job. Attribute or type errors must never cause an endless expired-lease recovery loop. Cancellation and database outages keep their own semantics.

## What has been proven

- IFM K2 Horizon 7B has live ARM64 CPU evidence for the paper workflows.
- The user's 3.7B passed automatic readiness (ARA-053).
- Fixtures prove deterministic behaviour only, not paper quality, 27B or GPU feasibility.
- The `12g` memory limit is a ceiling, not memory used at startup, and on its own it does not fit 27B.
- Memory-aware loading on the shared runtime (ARA-080) and delta-style running summaries for small local models (ARA-081) are deferred.
