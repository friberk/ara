# ARA-011–014 AI implementation evidence

Owned files only: `src/backend/app/integrations/llm.py`, services `retrieval.py`, `summarization.py`, `chat.py`, routes `ai.py`, `chat.py`, schemas `ai.py`, tests `test_ai.py`, `test_ai_integration.py`. No commits, migrations, actor/main/config edits, or subagents. Backend owner supplied research models, migration 0002, configuration, SDK dependency/lock, router/actor wiring, `Resources.llm_slots`, and shared real-service fixture.

## Result and acceptance

- Given the exact Sol/Terra/Luna IDs, when selecting generation settings, then unsupported IDs/efforts fail explicitly and `none` is preserved. `/models` reports all capabilities; credential presence reports `configured`, never fake verified account access. `/settings` persists the validated defaults in PostgreSQL.
- Given absent credentials, when requesting analysis, then a safe missing-key error is returned; the application still starts. Official AsyncOpenAI Responses calls use `store=False`, `max_retries=0`, an input cap of 32,000 conservatively estimated tokens (UTF-8 bytes), and 4,000 output tokens including reasoning. Current official model prices support conservative PostgreSQL reservations against a configurable $5/day cap. Reservations survive unknown outcomes and serialize across processes. Per-process inference semaphore limits active calls to two.
- Given a document, when retrieving for a chat, then SQL FTS/OR fallback and bounded section coverage use only the chat's immutable document. Recent completed history is bounded to 4,000 estimated tokens, retrieval to 12,000, and question/history size reduces retrieval to preserve the total context ceiling.
- Given a ready document, when requesting a summary, then one durable job/outbox is queued; duplicate UUID returns the original job and another active request conflicts. Workers process every ordered chunk through full-content or map/reduce coverage. Map checkpoints, usage, and paid-call-inflight state persist. A lost/unknown paid outcome permanently fails rather than automatically resubmitting. Final summary insertion and job completion share a fenced transaction.
- Given a chat request, when streaming, then the user/processing assistant persist before `message.started`; deltas stream with approximately one-second checkpoints and ten-second heartbeats; completion persists before `message.completed`. Error and disconnect paths flush partial content. Expired leases become interrupted, and request UUID replay returns stored state without another paid inference or budget reservation. Session locking and database constraints prevent overlapping answers.
- Given model source markers, when validating final content, then every citation ID must belong to supplied chunks in the selected document. Page numbers and excerpts come from database evidence. Invented IDs fail with safe `UNGROUNDED_OUTPUT`. Metadata helper extracts nullable structured candidates and removes copied fields not found in supplied evidence; ingestion owner gates it on credentials and preserves extraction if enrichment fails.

## Actual verification

1. Initial `uv run pytest tests/test_ai.py -q`: **6 failed**, missing AI modules. Following implementation: **6 passed**.
2. SDK-focused fixtures extended the unit module: **12 passed**, most recent run **0.93s**. Tests cover exact IDs, explicit disabled reasoning, conservative UTF-8 estimation, citation validation, grouping coverage, SSE framing, complete/stream SDK Responses transport, safe 503 without retries, missing credentials, and input ceilings.
3. Initial real-service AI integration run: **4 passed, 1 failed** (POST metadata-only chat returned 404 before the backend owner wired the new routers). Backend owner wired routers; its actual full-service run reported **40 passed in 10.87s**.
4. AI real PostgreSQL/Redis/MinIO fixture run after periodic checkpoint refinement: **9 passed in 2.50s**, including disconnect flush/free replay and invented-source failure.
5. Final expanded actual-service AI integration command:
   `docker compose --project-name ara-test --file compose.yaml --file compose.test.yaml run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest tests/test_ai_integration.py -q`
   **10 passed in 2.49s**. Added true >32k-context document with fifteen chunks, ordered map/reduce coverage, all fifteen retained citations, durable checkpoints, and final reduction evidence. No SQLite substitutions.
6. Full host `uv run pytest -q`: **27 passed, 19 skipped, 5 warnings in 9.76s**. Skipped tests require explicit real-service opt-in. Warnings are existing PyMuPDF SWIG deprecations in research parser tests, not AI errors.
7. Final Ruff check over all owned files: **All checks passed**.

Errors/corrections: Two commands attempted uv from repository root (pytest/ruff not found) and were rerun from `src/backend`; one ad-hoc edit used unavailable `python` and was rerun with `python3`; initial Ruff reported line lengths/import sorting and these were formatted/fixed. The backend owner reported accidentally formatting AI files during concurrent module work; there were no semantic changes. DB mutation runs were coordinated with backend owner; one start overlapped its finishing missing-route regression briefly, without observed data-related failures. No failures were concealed or claimed as live provider success.

## Integration details and limits

`app.routes.ai.router` / `app.routes.chat.router` are module-level APIRouter objects. Actor kind is `summary`; handler signature is `run_summary_job(resources, job_id, generation, lease_token, payload)` and owns both fenced domain persistence and final job state. `extract_metadata(resources, evidence)` returns a nullable bibliographic dict and is optional. Effective generation configuration and usage are persisted with summaries and assistant messages.

No actual API key was configured and no live/paid hosted-model call was made. Deterministic fixtures prove integration behavior, not account access or semantic factual accuracy. Citation membership validates source identity, not logical entailment of every generated sentence; manual checks remain necessary. UTF-8 byte budgeting deliberately yields a smaller usable context than a model tokenizer. Reservations retain the maximum allocation until the UTC budget day changes, including interrupted or unused requests. SDK retry is disabled because exactly-once paid generation across an ambiguous transport/process failure cannot be guaranteed. No embeddings, pgvector, local weights, or OCR were added.

Official docs actually fetched: [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), and [Responses streaming](https://developers.openai.com/api/docs/guides/streaming-responses). Model Markdown pages were also fetched for exact current pricing. These support the requested IDs/capabilities; they do not establish this account's access.

## Critical review correction: AnyIO disconnect cancellation

The earlier `stream.aclose()` regression did not simulate Starlette's actual ASGI 2.3 disconnect path. Independent review identified that AnyIO level cancellation interrupted `await client.close()` before the later asyncio-shielded partial save. I reproduced this with the real `StreamingResponse` ASGI driver: after the first delta, `receive()` returned `http.disconnect`, the provider close contained an asynchronous checkpoint, and the regression failed (`closed == []`, expected `[True]`). Actual red command: `uv run pytest tests/test_ai.py -k anyio -q` → **1 failed, 12 deselected in 0.59s**. This was a real lifecycle coverage gap in the original implementation and tests.

Correction: shield the complete `finally` using `anyio.CancelScope(shield=True)`. Pump cancellation/await is bounded to 2s, provider close to 2s, and partial/interrupted persistence to 5s. Persistence runs from an inner `finally`, including when close raises. There is no yield inside the cancel scope. An unavailable database can still prevent this bounded final flush; the persisted lease expiry then releases the processing state and UUID replay still never resubmits inference.

Actual green verification:

- Exact ASGI cancellation unit regression: **1 passed, 12 deselected in 0.54s**.
- Complete AI unit module: **13 passed in 0.98s**.
- New actual PostgreSQL regression uses the official SDK plus an HTTP fixture transport whose `aclose()` awaits. It drives ASGI 2.3 disconnect after a visible delta and checks client close, stored interrupted content, and free UUID replay: **1 passed, 10 deselected in 2.01s**.
- Combined AI unit + actual-service integration command: `docker compose --project-name ara-test --file compose.yaml --file compose.test.yaml run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest tests/test_ai.py tests/test_ai_integration.py -q` → **24 passed in 2.52s**.
- Host combined AI modules: **13 passed, 11 skipped in 0.90s** (integration opt-in absent).
- All owned-file Ruff checks: **All checks passed**.

Real-service DB ownership was explicitly granted by the backend owner before these runs and returned afterward. Backend owner was notified of the new direct AnyIO import so the already-transitively-locked package can be declared explicitly in its owned dependency files.

Official [AnyIO cancellation documentation](https://anyio.readthedocs.io/en/stable/cancellation.html) was fetched and confirms level cancellation repeats at yield points and shielded finalization is required.
