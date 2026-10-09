# Backend/frontend contract

JSON fields use snake_case. REST prefix `/api/v1`. UUID identifiers are strings; UTC timestamps ISO8601. Collections use `{items:[...]}`; search additionally returns provider, next_cursor (nullable) and total (nullable). Errors `{code,message,request_id,details?}` with correct HTTP status. Never expose secret configuration.

## Core DTOs

- SearchResult: provider (`semantic_scholar`/`openalex`), external_id, title (nullable), authors (`string[]`), year (nullable), abstract (nullable), doi (nullable), external_url (nullable), pdf_url (nullable).
- Paper: id, title, authors, year, abstract, doi, sources (SearchResult[] or equivalent source DTO), document_status (`metadata_only`/`processing`/`ready`/`failed`), active_document_id (nullable), metadata_provenance.
- UploadAccepted: paper_id, document_id, job_id.
- JobStatus: id, kind, state (`queued`/`processing`/`paused`/`completed`/`failed`), stage, progress (0–100), attempts, generation, result (nullable), error_code/error_message (nullable), computed error (nullable safe code/message), available_at, created_at, updated_at, paper_id/paper_title (nullable), model_key/completed_bytes/total_bytes (nullable).
- Summary: id, paper_id, document_id, model, reasoning_effort, content (Markdown string), citations (Citation[]), created_at.
- Citation: chunk_id, document_id, page (1-based physical PDF page), excerpt. The source endpoint returns the complete stored chunk, bounded by ingestion chunk limits, so evidence later in a passage remains visible.
- Chat: id, paper_id, document_id, title, created_at.
- Message: id, role (`user`/`assistant`), content, state (`completed`/`processing`/`interrupted`/`failed`), model (nullable), reasoning_effort (nullable), citations (Citation[]), created_at.
- Model: key (catalog key), provider, model_id (runtime/provider reference), display_name, status (`configured`/`available`/`unavailable`), reasoning_efforts (string[]), reasoning_aliases (optional string-to-string mapping, defaults to `{}`), thinking (nullable typed native controls), supports_streaming, supports_structured_output, context_window, unavailable_reason/unavailable_code (nullable), installation (nullable Installation; hosted models use null).
- Settings: default_model (catalog key), reasoning_effort.

## Requests

- GET /search?provider=openalex&q=...&cursor=...&limit=20 → SearchPage.
- POST /papers `{provider,external_id}` → Paper; server re-fetches canonical result, no trust in browser metadata.
- GET /papers?q=...&limit=...&offset=... → `{items:Paper[]}`.
- GET /papers/{id} → Paper; PATCH `{title?,authors?,year?,abstract?,doi?}` → Paper.
- POST /documents multipart `{file,paper_id?,request_id}` → UploadAccepted.
- GET /jobs → `{items:Job[]}`; GET /jobs/{id} → Job; POST /jobs/{id}/retry → Job.
- POST /papers/{id}/summaries `{model,reasoning_effort,request_id}` → `{job_id,summary_id?}`; GET same → `{items:Summary[]}`.
- POST /papers/{id}/chats `{title?}` → Chat; GET same → `{items:Chat[]}`.
- GET /chats/{id}/messages → `{items:Message[]}`.
- POST /chats/{id}/messages/stream `{content,model,reasoning_effort,request_id}` → SSE.
- GET /models → `{items:Model[]}`; GET/PUT /settings → Settings.
  - The defaults are `{default_model, reasoning_effort}`. A stored row or PUT body that still carries `memory_model` (ARA-077) is accepted and the field ignored; it is never returned. Follow-up planning and conversation summaries use the chat's own model and the effort active in that turn (ARA-083).
- GET /documents/{id}/download → PDF; GET /documents/{id}/chunks/{chunk_id} → Citation.

## PDF retrieval and access information (ARA-019)

Alembic `0006_fulltext` follows the local-model migration. It adds durable request/attempt records and nullable document acquisition metadata. Old provider snapshots and manually uploaded PDFs remain valid.

- `SearchResult` adds nullable `is_open_access` and default-empty `locations`. Each location has nullable `pdf_url`, `landing_page_url`, `is_oa`, `license`, `version`, `oa_status`, and `host_type` (`publisher`/`repository`/`unknown`). These are provider reports, not download results.
- `POST /papers/{id}/retrieve-fulltext` accepts exactly `{request_id: UUID}` and returns 202 `{paper_id,job_id}`. User-supplied URLs or credentials are rejected. The server refreshes saved identities and verifies exact DOI equality before adding another provider’s source to the same paper; manual bibliographic edits survive.
- A request UUID always replays its original job. Binding it to another paper returns 409 `FULLTEXT_REQUEST_CONFLICT`. Concurrent fresh UUIDs share active retrieval, with each binding persisted. A deliberate retry after a terminal result needs a fresh UUID and can succeed after access changes.
- `GET /papers/{id}/fulltext` reads only PostgreSQL: `paper_id`, `availability` (`open_copy_reported`/`publisher_link_only`/`unknown`), `locations`, nullable `retrieval_job`, `document_id`, `ingest_job_id`, `last_checked_at`, `acquisition`, and bounded `attempts`. Attempts include provider/source label, version/license/OA report, HTTP status, outcome, reason and checked time. Neither browsing, saving, nor this GET contacts PDF hosts.
- `/jobs` supports `kind=fulltext` and `paper_id`. Retrieval stages are `discovering_fulltext`, `fetching_pdf`, `storing_pdf`, `completed` and `failed`; progress describes stages. POST `/jobs/{id}/retry` rejects retrieval with 409 `NEW_FULLTEXT_REQUEST_REQUIRED`. Ingestion still uses its existing retry route.
- Retrieval outcomes distinguish `downloaded`, `access_required`, `blocked`, `not_found`, `rate_limited`, `unavailable`, `invalid_pdf`, `unsafe_url`, `unsupported_source`, `no_pdf_link`, `already_attached`, and `superseded`. A rate-limit result can carry bounded `retry_after` seconds. Authentication/403/HTML responses do not prove a paywall.
- A successful parent carries `{outcome,document_id,ingest_job_id}`. Download/storage completion is separate from extraction readiness; analysis stays gated until the document is ready. Existing usable attachments skip downloads; a newer manual attachment supersedes retrieval. Stable attachment IDs and job lease/generation fences protect recovery and historical citations.
- Acquisition metadata can include provider, candidate/final URL, reported OA/license/version, retrieval time and job ID. PDF Details labels accepted/submitted manuscripts distinctly from a published version. A manual replacement refreshes this metadata immediately.

The backend’s network determines IP-based access. Browser university sessions are not inherited. Retry does not run automatically on focus/network changes; browser links and manual upload remain the fallback. `FULLTEXT_ALLOWED_HOSTS` controls exact supported public hostnames, including redirect hosts. The HTTP boundary pins validated DNS addresses while retaining original Host/TLS verification; it sends no provider credentials, ignores proxy environment configuration, rejects encoded bodies and enforces byte/redirect/time bounds described in README. Normal startup never enables the deterministic fixture relay or fixture control routes.

## Workspace history additions (ARA-034, UI overhaul)

All additions are backward compatible. They support the chat-centred sidebar, the unified composer and progress that survives a reload. Alembic revision `0004_workspace_history` owns the schema changes.

- **Chat lifecycle fields.** `Chat` gains `title_source`: `default` / `auto` / `manual`.
  - A chat created without an explicit title starts as `default` ("Paper discussion").
  - The first user question in a `default` chat sets a deterministic title, `title_from_question(content, 60)`: whitespace collapsed, cut at a word boundary, trailing punctuation stripped, "…" when shortened. It also sets `title_source=auto`, in the same transaction as the user message.
  - Replayed request UUIDs never retitle.
  - An explicit title at creation, or a later rename, sets `manual`, and a manual title is never overwritten.
- **GET /chats?paper_id=&limit=30&offset=** returns `{items: ChatSummary[]}`.
  - `ChatSummary` is `Chat` plus `paper_title` (nullable), `last_activity_at` (latest message time, else `created_at`), `message_count` and `last_question_preview` (latest user message, at most 140 characters, nullable).
  - Ordered by `last_activity_at` desc, then id. `limit` is 1–100, default 30.
  - Unknown `paper_id` → empty list.
- **PATCH /chats/{id}** `{title}` (trimmed, 1–200 characters, not blank, extra fields forbidden) → Chat with `title_source=manual`.
  - Missing chat → 404 `CHAT_NOT_FOUND`.
- **DELETE /chats/{id}** → 204, removing the chat and its messages.
  - Locks the chat like message preparation does and expires stale leases first.
  - A live processing assistant message → 409 `CHAT_BUSY`.
  - Missing chat → 404 `CHAT_NOT_FOUND`; clients treat that as already deleted.
- **POST /search-history** `{provider, query}` (query trimmed, 1–300 characters) → `SearchHistoryItem`.
  - Recorded only on explicit user submission; `GET /search` stays free of side effects.
  - Upserts on (provider, casefolded and whitespace-collapsed query): `query` takes the latest spelling, and `last_searched_at` is set to now.
  - `SearchHistoryItem`: id, provider, query, created_at, last_searched_at.
- **GET /search-history?limit=20** → `{items: SearchHistoryItem[]}`, newest `last_searched_at` first. `limit` is 1–100.
- **DELETE /search-history/{id}** → 204; unknown id → 404 `SEARCH_HISTORY_NOT_FOUND`.
- **DELETE /search-history** → 204, clearing all history.
- **Search hits know library state.**
  - `SearchPage.items` becomes `SearchHit[]`, where `SearchHit = SearchResult + saved_paper_id` (nullable).
  - A hit is saved when a paper source has the same provider and external_id, or a paper has the same normalized DOI.
  - Stored `SearchResult` snapshots and `PaperDetail.sources` are unchanged.
- **Jobs link to papers.**
  - `JobStatus` gains `paper_id` and `paper_title` (both nullable).
    - Summary jobs take them from their payload's paper.
    - Ingest jobs take them from their document's paper.
  - `GET /jobs` gains optional filters: `paper_id`, `kind` (`ingest`, `summary`, `model_download` or `model_delete`) and `active` (true = queued, processing or paused; `retry_wait` is a queued stage). Paused jobs are unfinished even while no transfer is running.
- **CORS** allows `DELETE`. The existing Origin guard applies to every unsafe method, including DELETE.

## Managed local models (ARA-022, ARA-044–049)

Alembic revision `0005_local_models` follows `0004_workspace_history`. It extends durable jobs and adds `model_installations`, globally unique `model_requests` UUIDs and `model_uses` leases. PostgreSQL owns installation intent, job generations and global maintenance/inference admission; Redis carries delivery. Complete and partial weights stay in the Ollama volume.

`GET /models` keeps the hosted rows and returns these local keys with `provider="ollama"`: `ifm-k2-horizon-3.7b`, `ifm-k2-horizon-7b`, `qwen3.8-27b`. Their exact references and pinned manifest hashes are in the [approved specification](plans/ARA-022-managed-local-models.md). Missing weights keep rows visible with `status="unavailable"` and an actionable reason. `available` requires successful validation plus current inventory, digest, runtime-version and effective-context checks. An installation can remain `ready` while the model is unavailable after a runtime outage or configuration change; clients must check Model.status as well as installation.state.

| Installation field | Type / meaning |
| --- | --- |
| `state` | `missing`, `queued`, `downloading`, `pausing`, `paused`, `verifying`, `ready`, `deleting`, `failed` |
| `operation` | `download`, `verify`, `delete` or null; current unfinished/failed operation, separate from installation state |
| `weights_present` | boolean; presence alone does not establish usability |
| `quantization` | string; curated artifacts use `Q4_K_M` |
| `download_bytes` | integer; catalog installation size |
| `completed_bytes` | integer; cumulative bytes across unique digest layers |
| `total_bytes` | integer or null; null requires indeterminate progress |
| `job_id` | UUID or null; current owning model operation |
| `digest` | string or null; verified manifest digest |
| `updated_at` | UTC timestamp or null |
| `error` | `{code,message}` or null |

Catalog size is not resident memory, current network bytes, or a guaranteed amount reclaimed by deletion. Progress events are cumulative per layer, and checkpoints are written at most once per second or on stage changes. A resumed attempt reconciles authoritative runtime checkpoints, so previously displayed byte counts may decrease. Transfer completion remains unavailable through verification.

The dispatcher owns a separate cancellable reconciliation loop for previously installed, desired-ready models. Stale capability-schema, runtime-version or context records enqueue one durable verification-only maintenance job. It retains `kind="model_download"` for the existing queue/worker contract, with private `verify_only=true` intent; public `JobStatus.model_operation="verify"` distinguishes preparation in active and historical Activity rows. No weights are pulled on this path, including retries or worker recovery. Queued verification rejects pause/resume as well as running verification. Concurrent reconciliation rechecks state and validation under the global model lock. Missing, deleted, manually paused, failed or already active installations are not automatically restarted; active use defers scheduling. Runtime outages cannot block core job dispatch or startup. GET routes remain read-only.

Stale-ready models report `LOCAL_MODEL_REVALIDATION_REQUIRED` while awaiting automatic preparation. Inventory/runtime availability is checked before freshness, so an offline or malformed-version runtime reports `LOCAL_RUNTIME_UNAVAILABLE`, and absent weights report `MODEL_WEIGHTS_MISSING`. Clients poll pending preparation and queued/verifying jobs every two seconds, then enable selection after successful verification. A genuine failed preparation retains its existing job for explicit retry. If verification discovers missing weights, it records `weights_present=false` and the UI offers an explicit new download request; retrying verification cannot pull. Completed installations report no current operation; completed jobs retain their own operation label. No new endpoint or migration is required for these derived fields.

| Route | Request | Response / rules |
| --- | --- | --- |
| `POST /models/{key}/download` | `{request_id: UUID}` | 202 JobStatus; inventory reconciliation precedes any pull, allowing verification of retained weights |
| `DELETE /models/{key}/installation` | UUID `Idempotency-Key` header | 202 JobStatus; missing installation is safe to remove; unload/remove and confirmed inventory absence precede completion |
| `POST /jobs/{id}/pause` | `{request_id: UUID}` | 202 JobStatus; local downloads only; queued work may pause immediately, running work retains ownership in `pausing` until acknowledged settlement |
| `POST /jobs/{id}/resume` | `{request_id: UUID}` | 202 JobStatus; paused download only; same job, new generation and runtime attempt identity |
| `POST /jobs/{id}/retry` | optional `{request_id: UUID}` | 202 JobStatus; local download/delete retries require the body (422 `MODEL_REQUEST_ID_REQUIRED` if absent); existing ingest clients may omit it |

Operation bodies forbid extra fields. Unknown catalog key returns 404 `LOCAL_MODEL_NOT_FOUND`; UUID reuse across a different model/action/job returns 409 `MODEL_REQUEST_CONFLICT`. Identical UUID/content returns the same durable job's current status. Repeated pause can retry an unconfirmed settlement safely. A historical operation cannot modify a newer installation: 409 `MODEL_OPERATION_SUPERSEDED`. Invalid state/action returns an appropriate 409 (`JOB_NOT_CONTROLLABLE`, `JOB_NOT_PAUSABLE`, `JOB_NOT_RESUMABLE`). Verification cannot be paused; its inference work must settle first. Active mutation or inference conflicts return 409 `LOCAL_MODEL_BUSY` on model controls. No manual pause/resume consumes transfer retry attempts.

Pause support is capability-gated. Unmodified external runtimes return 409 `MODEL_PAUSE_UNSUPPORTED`. A missing/malformed acknowledgment returns retryable 503 `MODEL_PAUSE_UNCONFIRMED`; it does not establish a paused state. The managed version-1 private protocol creates a canceled tombstone when pausing an unknown valid UUID, acknowledges 200, and rejects a late same-UUID pull with 409. That fence lasts for the daemon lifetime. Recovery re-establishes settlement on the current runtime for every unresolved current or previous attempt identity; a plain 404 cannot prove quiescence. The [runtime protocol](../docker/ollama/README.md) is internal, without a public Compose host port.

Manual pause persists across worker/runtime restarts and never auto-resumes. Worker recovery reads inventory before transfer and fences writes by generation and lease token. Global model-use leases last 60 seconds with 10-second heartbeats. Lease loss cancels owned external work. Model transfers have a six-hour attempt ceiling and a two-minute stall threshold by default; retained bytes do not make failed verification selectable.

Settings accepts valid catalog/effort preferences independently of installation availability. Deletion preserves defaults, chats and summaries. Generation using a missing or unverified saved default fails explicitly, with no hosted fallback. Interactive local contention returns HTTP 429 before SSE headers; queued local summaries wait on `local-generation` without spending transfer or paid retry budgets. Model mutations use `local-models`, leaving ordinary PDF/hosted jobs on `default`.

The native Ollama `/api/chat` adapter maps NDJSON content to the existing SSE events and validates structured output through the same Pydantic service interface. Local requests need no hosted key or dollar reservation. `context_window` reports the effective configured allocation (8,192 by default), with 2,048 output and 512 safety tokens reserved. Conservative UTF-8 byte bounds govern assembled prompts when an exact tokenizer is unavailable. Whole-document summaries use ordered batching/reduction and bounded compression of complete intermediate sections, retain source markers and checkpoint completed calls before releasing admission. Oversized or repeatedly noncompliant output fails explicitly rather than truncating coverage.

Local `default` reasoning omits `think`; successfully verified `none` sends `think:false`, `on` sends `think:true`, and named levels pass their exact verified strings. Named levels are advertised only after successful native probes. The final `0.40.1-ara.2` runtime passed all six retained 7B choices; the earlier runtime's named-level rejection is preserved in the development journal. Separate thinking fields never enter answer content. Provider, artifact digest, runtime version, effective context/output/thread configuration and reasoning are persisted in generation configuration; existing Summary/Message response shapes and SSE framing remain unchanged. Replays still return stored state without launching inference again, and citation validation still binds evidence to the selected document.

ARA-055 adds derived `Model.reasoning_aliases` for presentation of equivalent verified controls. Complete pinned IFM verification returns `{"default":"high","on":"high"}` while retaining all six raw `reasoning_efforts`. Default aliases match the exact typed `thinking.default` to a verified control; Boolean enabled-to-High equivalence requires the pinned model declaration and verification of both controls. Returned alias targets resolve directly to supported controls. Binary-only models can alias default to `none` or `on`; unrelated models inherit no IFM equivalence. Missing or malformed proof produces no unverified alias. Hosted models return `{}`. No migration, capability-schema change or reverification is required by this derived field.

Settings and the composer use declared aliases only for available native models. IFM displays None/Low/Medium/High, with legacy default/on preferences resolving to explicit High for future UI requests. Normalized default comparisons avoid automatic writes and false dirty state; unavailable preferences retain their identity and effort. Binary-only models get a Reasoning toggle. Raw default/on API requests remain supported with their original omission/Boolean behavior, and stored preferences, histories, provenance and UUID replay semantics remain unchanged. Historical labels are Runtime preset and Reasoning enabled; past records are not reinterpreted using current capabilities.

## Retrieval and conversation context (ARA-070; ARA-021, ARA-043)

Contract for the retrieval and context overhaul, implemented on `feat/rag-context`. Spec: `docs/superpowers/specs/2026-10-09-rag-context-design.md`.

- `GET /api/v1/retrieval/profiles` returns `EmbeddingProfilePage {items: EmbeddingProfileOut[], default_profile}`.
  - Each `EmbeddingProfileOut` has `key`, `provider` (`openai|ollama`), `model_id`, `display_name`, `dimensions`, `status` (`available|unavailable`), a plain-language `unavailable_reason`, and `local_model_key` for local install links.
  - Keys: `openai-3-large` (default), `qwen3-embed-4b`, `qwen3-embed-8b`.
- `EmbeddingProfilePage.rerankers: RerankerOut[]` lists the reranker profiles (ARA-074). The default `openai-gpt-6-luna` uses the OpenAI Decisions API and scores the top 40 fused passages (about 2–3 s and $0.004 per answer); `qwen3-rerank-0.6b` runs locally through Ollama (about 9 s). `RerankerOut` has `key`, `provider` (`openai|ollama`), `model_id`, `display_name`, `status` (`available|unavailable`), a plain-language `unavailable_reason`, `local_model_key` for the install link, and `candidates` (fused passages scored per question). Models are catalog data, not hardcoded. The local reranker's `model_id` is `fanyx/Qwen3-Reranker-0.6B-Q8_0:latest`, because Ollama lists an untagged pull as `:latest` and inventory matching is exact.
- Reranking never fails an answer. When it cannot run, the passages keep their fused order, `retrieval.reranked` is `false`, and `retrieval.note` says reranking was unavailable. The server-side retrieval trace keeps the skip code: `MODEL_NOT_CONFIGURED` (no OpenAI key; no note, because Settings already says so), `DAILY_BUDGET_EXCEEDED`, `LOCAL_MODEL_NOT_READY`, `INVALID_RERANKER` (a stored key no longer in the catalog), `LOCAL_MODEL_BUSY` (the local retrieval slot stayed busy past its 20 s wait), `RERANKER_TIMEOUT` (the local pass exceeded its 45 s deadline) or `RERANKER_FAILED`. The trace also records `rerank.query`, the standalone question the reranker judged against. Turning reranking off (`null`) is a choice, not a skip.
- `GET`/`PUT /api/v1/retrieval/settings` reads and writes `RetrievalSettings {embedding_profile="openai-3-large", reranker="openai-gpt-6-luna"}`. `reranker` is a reranker profile key from `app/integrations/reranker_catalog.py`, or `null` to turn reranking off. An unknown key returns 422 `INVALID_RERANKER`.
  - These settings are separate from the model defaults in `/settings`.
  - `PUT` validates the key but does not require the profile to be available.
- `GET /api/v1/papers/{paper_id}/retrieval` returns `PaperRetrieval`:
  - `effective_profile` and `source` (`default|paper`);
  - `parser`, `chunk_count`, `section_count`;
  - `mode` (`hybrid|keyword|unavailable`) and a plain-language `mode_note`;
  - `indexes: RetrievalIndexOut[]`, each with `profile`, `state` (`queued|embedding|ready|failed|unavailable`), `embedded`, `total`, `updated_at`, `error`.
- `PUT /api/v1/papers/{paper_id}/retrieval` takes `{profile: str|null, request_id}`. `null` follows the global default. Replaying the same request UUID returns the same body.
- `POST /api/v1/papers/{paper_id}/retrieval/rebuild` takes `{request_id}` and returns 202 with `PaperRetrieval`. The rebuild is blue/green: the previous ready index keeps serving until the new one is ready.
- `GET /api/v1/chats/{chat_id}/memory` returns `ChatMemoryState {memory: {version, summary, summarized_messages, model, created_at} | null, total_messages}`. The original messages are never altered.
- `Message` gains three fields:
  - `retrieval: RetrievalSummary | null`, with `mode`, `profile`, `reranked`, `standalone_query`, `search_queries`, `passages_found`, `passages_used`, `limited_by_context` and `note`;
  - `context: ContextUsage | null`, with `window`, `input_budget` (the input cap that applied: the window less output and thinking, or the hosted working cap; `null` on answers saved before it existed), `input_tokens`, `output_reserved`, `summary_version`, `recent_turns`, `recalled_turns` and `truncated`;
  - `grounding: "supported" | "insufficient" | null`.
- Messages persisted before this change report `retrieval`/`context` as `null`.
- `Citation` gains `page_end`, `section` (heading path), `kind` (`front_matter|text|table|references`) and `bboxes` (`[[page,x0,y0,x1,y1]]`). Persisted answers keep canonical `[source:<chunk-uuid>]` markers; the model's short `[S#]` handles never reach clients.
- `GET /documents/{id}/chunks/{chunk_id}` returns the same provenance fields. A section-aware chunk can span pages: `page` is its first physical page and `page_end` its last.
- `Model` gains `kind` (`chat|embedding|reranker`). The composer lists only `chat` models; Settings shows every kind.
- New SSE event `message.status`: `{message_id, stage}`, where `stage` is `waiting|planning|retrieving|reranking|generating`. It is emitted between `message.started` and the first `message.delta`. Clients ignore unknown stages.
  - `waiting` comes first, and only when a local question finds the local model busy with background work (such as a conversation summary). The stream waits up to 60 s; if the work outlasts it, the stream ends with `message.failed {code: "LOCAL_MODEL_BUSY"}` and the answer is saved as failed. Another local answer in progress still returns 429 before the stream.
  - A producer cancelled by a lost runtime lease ends with `message.failed {code: "LOCAL_MODEL_LEASE_LOST"}`.
- Local `compact_chat` jobs run only once the chat is idle: they become available 60 s after being queued, and each new question or completed turn pushes that back. A compaction that returns an empty or headings-only summary fails with `COMPACTION_EMPTY` and stores no version. A local summary cut at its length limit keeps its complete lines, and its job result records `truncated: true`; if those lines add nothing to the previous summary, the job fails with `COMPACTION_TRUNCATED`. A failed range is retried with the next completed turn, at most three times; a paid summary whose outcome is unknown (`GENERATION_OUTCOME_UNKNOWN`) is never repeated. Recall still covers turns that no summary holds (ARA-081 tracks better local summaries).
- At API startup, documents from an older chunk set (including every document from before migration 0006) are re-ingested automatically, and missing or `unavailable` indexes are queued once their profile can embed. The same reconciliation runs after the default embedding profile changes and after a local embedding model verifies. Until a document's re-ingest finishes, a question about it returns 409 "This paper is being prepared for the new search. Try again in a minute."

## SSE

Events have JSON data, blank-line framing and heartbeat comments. `message.started`: `{message_id}`; `message.delta`: `{text}`; `message.completed`: Message; `message.failed`: `{code,message,message_id?}`. Complete emitted only after persistence. Unknown/invalid frames produce a visible client error; AbortController stops streaming and authoritative history refreshes. Duplicate UUIDs cannot launch inference again. Histories retain partial/interrupted status after process failure.

The lead owns changes to this contract. Generate API types from actual OpenAPI once routes are ready. Report any implementation discrepancy instead of silently adapting unrelated files.

Ordinary pull errors and deadlines also require settlement. An unconfirmed stop retains all pending UUIDs in a durable `settling` job stage and blocks other local inference/model mutations. Cleanup deliveries settle the prior transfer before retry/failure; they do not replay the transfer or spend another transfer attempt. Manual pause can still persist intent during cleanup.

Local native requests explicitly set temperature `0.0`. Chat stores the applied settings at generation admission. Summaries durably snapshot provider/artifact/runtime/context/output/thread/reasoning/temperature settings under admission before inference, then copy that snapshot at final persistence. Later configuration drift or legacy partials without provenance fail explicitly; model deletion cannot erase successful generation provenance. Lower sampling temperature does not guarantee factual support, and citation validation remains mandatory.

## Combined schema deployment — ARA-082

The current migration head is `0007_feature_merge`, joining `0006_fulltext` and `0006_retrieval_context` without changing either existing parent. `alembic upgrade head` applies both independent schema branches from the old main schema, or the missing branch when upgrading an existing feature database. API readiness requires the merge head. Document rows retain full-text acquisition provenance and structured parser/chunk-set fields. Paper-linked jobs include summary, fulltext and embed operations. The shared generated OpenAPI contract includes both access/retrieval schemas and managed-model controls.

The retrieval migration replaces pre-structured chunk rows. Startup queues idempotent re-ingestion using stored PDF originals and previous metadata checkpoints. Analysis waits for valid chunks; previously generated messages and summaries keep stored citations with original document/page/excerpt provenance. An old chunk-ID endpoint can return 404 after replacement; the reader can show the saved citation excerpt and original PDF page. This behavior is distinct from losing the stored analysis or original file.
