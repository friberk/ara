# Backend/frontend contract

JSON fields use snake_case. REST prefix `/api/v1`. UUID identifiers are strings; UTC timestamps ISO8601. Collections use `{items:[...]}`; search additionally returns provider, next_cursor (nullable) and total (nullable). Errors `{code,message,request_id,details?}` with correct HTTP status. Never expose secret configuration.

## Core DTOs

- SearchResult: provider (`semantic_scholar`/`openalex`), external_id, title (nullable), authors (`string[]`), year (nullable), abstract (nullable), doi (nullable), external_url (nullable), pdf_url (nullable).
- Paper: id, title, authors, year, abstract, doi, sources (SearchResult[] or equivalent source DTO), document_status (`metadata_only`/`processing`/`ready`/`failed`), active_document_id (nullable), metadata_provenance.
- UploadAccepted: paper_id, document_id, job_id.
- JobStatus: id, kind, state (`queued`/`processing`/`paused`/`completed`/`failed`), stage, progress (0–100), attempts, generation, result (nullable), error_code/error_message (nullable), computed error (nullable safe code/message), available_at, created_at, updated_at, paper_id/paper_title (nullable), model_key/completed_bytes/total_bytes (nullable).
- Summary: id, paper_id, document_id, model, reasoning_effort, content (Markdown string), citations (Citation[]), created_at.
- Citation: chunk_id, document_id, paper_id (nullable; filled when chat history is read, ARA-088), page (1-based physical PDF page), excerpt. The source endpoint returns the complete stored chunk, bounded by ingestion chunk limits, so evidence later in a passage remains visible.
- Chat: id, paper_id (the first included paper; the chat's URL is `/papers/{paper_id}/chats/{id}`), papers (IncludedPaper[] by ordinal), title, title_source, created_at. IncludedPaper: paper_id, document_id (the PDF pinned when the paper joined), title, first_author, year, added_at (ARA-088, below).
- Message: id, role (`user`/`assistant`), content, state (`completed`/`processing`/`interrupted`/`failed`), model (nullable), reasoning_effort (nullable), citations (Citation[]), created_at.
- Model: key (catalog key), provider, model_id (runtime/provider reference), display_name, status (`configured`/`available`/`unavailable`), reasoning_efforts (string[]), reasoning_aliases (optional string-to-string mapping, defaults to `{}`), thinking (nullable typed native controls), supports_streaming, supports_structured_output, context_window (required: a hosted model's native window from the hosted catalog, 1,050,000 for GPT-5.6; local models report their configured allocation), unavailable_reason/unavailable_code (nullable), installation (nullable Installation; hosted models use null).
- Settings: default_model (catalog key), reasoning_effort.

## Requests

- GET /search?provider=openalex&q=...&cursor=...&limit=20 → SearchPage.
- POST /papers `{provider,external_id}` → Paper; server re-fetches canonical result, no trust in browser metadata.
- GET /papers?q=...&limit=...&offset=... → `{items:Paper[]}`.
- GET /papers/{id} → Paper; PATCH `{title?,authors?,year?,abstract?,doi?,venue?}` → Paper; DELETE → 204. Deletion previews, bulk deletion and Look up again are under ARA-095, below.
- POST /documents multipart `{file,paper_id?,request_id}` → UploadAccepted.
- GET /jobs → `{items:Job[]}`; GET /jobs/{id} → Job; POST /jobs/{id}/retry → Job.
- POST /papers/{id}/summaries `{model,reasoning_effort,request_id}` → `{job_id,summary_id?}`; GET same → `{items:Summary[],blocked?}` (ARA-084, below).
- POST /chats `{paper_ids, title?}` → 201 Chat; GET /papers/{id}/chats → `{items:Chat[]}` (chats that include the paper); GET /chats/{id} → ChatSummary. Papers are added and removed at /chats/{id}/papers (ARA-088, below).
- GET /chats/{id}/messages → `{items:Message[]}`.
- POST /chats/{id}/messages/stream `{content,model,reasoning_effort,request_id}` → SSE.
- GET /features → `Features {open_models}`; GET /models → `{items:Model[]}`; GET/PUT /settings → Settings. Open models are experimental and off by default (ARA-090, below).
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

## Automatic retrieval and summaries (ARA-084)

No migration; job kinds and JSONB carry the new state.

- `POST /papers` also queues retrieval, in the save transaction, for a metadata-only paper with an OpenAlex record or a DOI when an OpenAlex API key is configured (ARA-087). Each paper has one automatic request UUID (UUIDv5 of the paper ID), so duplicate or concurrent saves, deliveries and restarts replay one job. A paper with an earlier retrieval job of any kind is not retried automatically.
- `POST /papers/{id}/retrieve-fulltext/automatic` (no body) → 200 `{paper_id,job_id}`: the same automatic request for papers saved earlier. `job_id` is the automatic job (repeats replay it, including a failed one) or null when no OpenAlex key is configured, the paper has a PDF attached, has had any attempt, or has neither an OpenAlex record nor a DOI. 404 `PAPER_NOT_FOUND` for an unknown paper. The workspace calls it once on open.
- A deliberate request after a `rate_limited` failure queues its job and outbox event only once the reported `retry_after` (at most 86,400 s) has passed.
- The ingestion transaction that first marks a document ready queues one `summary` job with the saved default model and effort, payload `automatic: true` and a per-document request UUID. Re-ingesting a ready document (startup chunk-set rebuilds, retries) never does; neither does a document that is not the paper's active PDF, has no passages, or already has a summary or summary job. Nothing starts when the default is a local model that is not ready, hosted generation is unconfigured, or today's budget cannot cover one hosted call; there is no fallback to another model.
- `GET /papers/{id}/summaries` adds nullable `blocked: {code,message,model,reasoning_effort}`: why the saved default cannot summarize the active PDF now, while the paper has no summary or running summary job for it (also before a PDF exists). It reads settings and PostgreSQL only.

Superseded by ARA-087 below: the host allowlist, third-party downloads and network-access guidance were removed.

## Workspace history additions (ARA-034, UI overhaul)

All additions are backward compatible. They support the chat-centred sidebar, the unified composer and progress that survives a reload. Alembic revision `0004_workspace_history` owns the schema changes.

- **Chat lifecycle fields.** `Chat` gains `title_source`: `default` / `auto` / `manual`.
  - A chat created without an explicit title starts as `default` ("Paper discussion").
  - The first user question in a `default` chat sets a deterministic title, `title_from_question(content, 60)`: whitespace collapsed, cut at a word boundary, trailing punctuation stripped, "…" when shortened. It also sets `title_source=auto`, in the same transaction as the user message.
  - Replayed request UUIDs never retitle.
  - An explicit title at creation, or a later rename, sets `manual`, and a manual title is never overwritten.
- **GET /chats?paper_id=&limit=30&offset=** returns `{items: ChatSummary[]}`.
  - `ChatSummary` is `Chat` plus `last_activity_at` (latest message time, else `created_at`), `message_count` and `last_question_preview` (latest user message, at most 140 characters, nullable). Its paper titles are in `papers` (ARA-088 removed `paper_title` and `document_id`).
  - Ordered by `last_activity_at` desc, then id. `limit` is 1–100, default 30.
  - `paper_id` lists every chat that includes the paper. Unknown `paper_id` → empty list.
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

## Experimental open models flag (ARA-090)

`EXPERIMENTAL_OPEN_MODELS` (default `false`) gates the Ollama chat models, the Qwen3 embedding profiles and the Qwen3 reranker. `GET /features` returns `Features {open_models: bool}`; the browser hides open-model UI unless it is `true`. With the flag on, every section below behaves as documented. With it off:

- Catalogs. `GET /models` lists only hosted models, plus the saved default when it is a local chat model, reported with `status="unavailable"`, `unavailable_code="OPEN_MODELS_DISABLED"` and `installation=null`. `GET /retrieval/profiles` lists only the hosted embedding models (`openai-3-large`, `openai-3-small`) and `openai-gpt-6-luna`, plus a saved local library model or reranker, reported unavailable with `local_model_key=null`.
- Routes. `POST /models/{key}/download`, `DELETE /models/{key}/installation`, `POST /jobs/{id}/pause` and `POST /jobs/{id}/resume` are not mounted (404). `GET /jobs` omits `model_download` and `model_delete` jobs; `GET /jobs/{id}` and `POST /jobs/{id}/retry` return 404 for them. The generated TypeScript contract comes from the flag-on schema, so it still describes these routes.
- Refusals. A local chat model, embedding profile or reranker in a request returns 409 `OPEN_MODELS_DISABLED` with a plain message asking for a hosted choice: `PUT /settings`, summary requests, chat answers (a replay of a stored answer still returns it), `GET /chats/{id}/usage`, `GET /retrieval/reindex-estimate` for a local model, and a paper rebuild while the library model is local. `PUT /retrieval/settings` keeps an unchanged saved local choice and refuses a new one. The summary page reports `blocked.code="OPEN_MODELS_DISABLED"` for a saved local default, and no automatic summary starts.
- Retrieval. While the library model is local, every paper is searched by keywords; `PaperRetrieval.mode="keyword"` and `mode_note` says why, its local indexes report `state="unavailable"` with error `OPEN_MODELS_DISABLED`, and answers note keyword search. A hosted preference never uses a local index. A saved local reranker means no reranking. Embed jobs for a local profile settle as unavailable, and the startup reconcile queues them again once the flag returns; turn embeddings settle unavailable and recall skips those turns.
- Jobs. The dispatcher publishes nothing to the `local-models` and `local-generation` lanes and lease recovery skips their jobs, so unsettled model operations and local summaries keep their state until the flag is on. Startup model preparation does not run. Readiness never depended on Ollama.

## Managed local models (ARA-022, ARA-044–049)

Requires `EXPERIMENTAL_OPEN_MODELS=true` and the `open-models` Compose profile (ARA-090).

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
  - Each `EmbeddingProfileOut` has `key`, `provider` (`openai|ollama`), `model_id`, `display_name`, `dimensions`, `status` (`available|unavailable`), a plain-language `unavailable_reason`, and `local_model_key` for local install links, and `price_per_million` (USD per million input tokens; 0 for local models).
  - Keys: `openai-3-large` (default, $0.13), `openai-3-small` ($0.02, 1536 dimensions), `qwen3-embed-4b`, `qwen3-embed-8b`. One model serves the whole library (ARA-091): vectors from different models are not comparable, so a library never mixes them.
- `EmbeddingProfilePage.rerankers: RerankerOut[]` lists the reranker profiles (ARA-074). The default `openai-gpt-6-luna` uses the OpenAI Decisions API and scores the top 40 fused passages (about 2–3 s and $0.004 per answer); `qwen3-rerank-0.6b` runs locally through Ollama (about 9 s). `RerankerOut` has `key`, `provider` (`openai|ollama`), `model_id`, `display_name`, `status` (`available|unavailable`), a plain-language `unavailable_reason`, `local_model_key` for the install link, and `candidates` (fused passages scored per question). Models are catalog data, not hardcoded. The local reranker's `model_id` is `fanyx/Qwen3-Reranker-0.6B-Q8_0:latest`, because Ollama lists an untagged pull as `:latest` and inventory matching is exact.
- Reranking never fails an answer. When it cannot run, the passages keep their fused order, `retrieval.reranked` is `false`, and `retrieval.note` says reranking was unavailable. The server-side retrieval trace keeps the skip code: `MODEL_NOT_CONFIGURED` (no OpenAI key; no note, because Settings already says so), `DAILY_BUDGET_EXCEEDED`, `LOCAL_MODEL_NOT_READY`, `INVALID_RERANKER` (a stored key no longer in the catalog), `LOCAL_MODEL_BUSY` (the local retrieval slot stayed busy past its 20 s wait), `RERANKER_TIMEOUT` (the local pass exceeded its 45 s deadline) or `RERANKER_FAILED`. The trace also records `rerank.query`, the standalone question the reranker judged against. Turning reranking off (`null`) is a choice, not a skip.
- With open models off, only the hosted profiles are listed and a saved local choice is reported unavailable (ARA-090, above).
- `GET`/`PUT /api/v1/retrieval/settings` reads and writes `RetrievalSettings {embedding_profile="openai-3-large", reranker="openai-gpt-6-luna"}`. `reranker` is a reranker profile key from `app/integrations/reranker_catalog.py`, or `null` to turn reranking off. An unknown key returns 422 `INVALID_RERANKER`.
  - These settings are separate from the model defaults in `/settings`.
  - `PUT` validates the key but does not require the profile to be available. Changing `embedding_profile` re-embeds the whole library: every ready document is queued for the new model (idempotent per document and chunk set). A document keeps answering from its ready index until the new one is ready, falls back to keyword search if it has none, and loses the old model's vectors and index rows only after the new index is ready.
- `GET /api/v1/retrieval/reindex-estimate?profile=` returns `ReindexEstimate {profile, papers, tokens, price_per_million, estimated_cost_usd}`: the ready documents that have no ready index for `profile`, their stored chunk token counts, and tokens times the catalog price. Unknown profile: 422 `INVALID_EMBEDDING_PROFILE`. The Settings confirmation dialog reads it before anything changes.
- `GET /api/v1/papers/{paper_id}/retrieval` returns `PaperRetrieval`:
  - `effective_profile`, the library embedding model;
  - `parser`, `chunk_count`, `section_count`;
  - `mode` (`hybrid|keyword|unavailable`) and a plain-language `mode_note`;
  - `indexes: RetrievalIndexOut[]`, each with `profile`, `state` (`queued|embedding|ready|failed|unavailable`), `embedded`, `total`, `updated_at`, `error`.
- There is no per-paper embedding choice (removed in ARA-091): `PUT /papers/{id}/retrieval` and `papers.retrieval_profile` no longer exist.
- `POST /api/v1/papers/{paper_id}/retrieval/rebuild` takes `{request_id}` and returns 202 with `PaperRetrieval`. The rebuild is blue/green: the previous ready index keeps serving until the new one is ready.
- `GET /api/v1/chats/{chat_id}/memory` returns `ChatMemoryState {memory: {version, summary, summarized_messages, model, created_at} | null, total_messages}`. The original messages are never altered.
- `GET /api/v1/chats/{chat_id}/usage?model=&reasoning_effort=` returns `ChatUsage {context: {used_tokens | null, input_budget, window, model}, cost: {total, answers, planning, compaction, embeddings, reranking, local, unrecorded_turns}}` for the composer's context and cost meter (ARA-085). `used_tokens` is what the latest completed answer sent; `input_budget` and `window` are the requested model's, sized as an answer sizes its prompt, so the meter follows the composer's selection (unknown model or effort: 422; unknown chat: 404 `CHAT_NOT_FOUND`). Costs are USD decimal strings (eight places) priced from the model, embedding and reranker catalogs at recorded tokens: answers from `usage`, follow-up planning, query embeddings and reranking from `retrieval.billed` on each answer, compaction from the stored memory versions. Local calls are free and `local` is true when every recorded call was local. Answers from before this was recorded count in `unrecorded_turns`, not in the total; the shared paper summary is not part of a chat's cost.
- `Message` gains three fields:
  - `retrieval: RetrievalSummary | null`, with `mode`, `profile`, `reranked`, `standalone_query`, `search_queries`, `passages_found`, `passages_used`, `limited_by_context` and `note`;
  - `context: ContextUsage | null`, with `window`, `input_budget` (the input cap that applied: the window less answer, reasoning and safety reserves, bounded for a hosted model by its catalog price-tier boundary (272,000 for GPT-5.6); `null` on answers saved before it existed), `input_tokens`, `output_reserved`, `summary_version`, `recent_turns`, `recalled_turns` and `truncated`;
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

The current migration head is `0009_upload_match_tables` (ARA-092), which moves ARA-086's upload-match state out of `model_configurations` into tables (see Labels in the matching section). Before it, `0008_library_embeddings` drops `papers.retrieval_profile`; papers that had an override follow the library setting and are re-indexed at startup if it differs, after which their old-model vectors are pruned. Before it, `0007_feature_merge` joined `0006_fulltext` and `0006_retrieval_context` without changing either existing parent. `alembic upgrade head` applies both independent schema branches from the old main schema, or the missing branch when upgrading an existing feature database. API readiness requires the merge head. Document rows retain full-text acquisition provenance and structured parser/chunk-set fields. Paper-linked jobs include summary, fulltext and embed operations. The shared generated OpenAPI contract includes both access/retrieval schemas and managed-model controls.

The retrieval migration replaces pre-structured chunk rows. Startup queues idempotent re-ingestion using stored PDF originals and previous metadata checkpoints. Analysis waits for valid chunks; previously generated messages and summaries keep stored citations with original document/page/excerpt provenance. An old chunk-ID endpoint can return 404 after replacement; the reader can show the saved citation excerpt and original PDF page. This behavior is distinct from losing the stored analysis or original file.

## Uploaded-paper metadata and uploads (ARA-086)

No migration. The changes are additive:
- `SearchResult` and the stored provider snapshots gain nullable `venue`. Semantic Scholar's empty open-access URL (`""`) is now `null`.
- `Paper` gains:
  - nullable `venue`, read from the linked provider record named by `metadata_provenance.venue`, else from any linked record;
  - nullable `file_name`, the active PDF's original name, so an untitled paper can be named while it is read.
- `UploadAccepted` gains `duplicate` (default `false`). It is `true` when a new request UUID uploads bytes the library already holds; the response then names the existing paper, document and job. A replay of the same request UUID stays `false`.
- Attaching bytes that belong to another paper still returns 409 `DOCUMENT_ALREADY_ATTACHED`, now with `details: [{paper_id}]`. `AppError` responses can carry `details`.

`GET /metadata/settings` → `{source}`, and `PUT /metadata/settings {source}` → `{source}`:
- `source` is `openalex` (the default) or `semantic_scholar`. Extra fields or another value return 422.
- The value is stored under the `metadata` key of `model_configurations`.
- Queued lookups read it when they run.

PDF parsing keeps local values as the fallback and as lookup clues:
- An Info title is ignored when it names a file or a tool. Examples are `paper.dvi`, `*.tex`, `*.pdf`, `Microsoft Word - …`, `untitled`, `Layout 1`, `PII:`, file stems and very short values.
- An Info title is also ignored when it is not printed on the first two pages. The title then comes from the first page: the largest horizontal text in the top 60%, which must be at least 1.15 times the size of the body text. Rotated arXiv stamps are skipped.
- A DOI in the Info subject/keywords or XMP wins over one found in the text. The arXiv ID from page 1 is reported as `arxiv_id`. Placeholder authors such as `Administrator` are dropped.

Lookup job:
- Queuing:
  - Ingestion queues a durable `metadata` job, payload `{paper_id, document_id, clues}`, in the commit that makes the document ready. Reading, summaries and questions never wait for it.
  - Only a paper without a provider record gets a job, and only one per document. A startup re-ingest therefore never asks again, and neither does a paper saved from search.
- Search order:
  - The chosen source is asked first, then the other one: by DOI, then by arXiv ID, then by title.
  - OpenAlex is queried with `filter=doi:…` (using `10.48550/arxiv.<id>` for arXiv) and `filter=title.search:…`. Semantic Scholar is queried with `paper/DOI:…`, `paper/ARXIV:…` and `paper/search/match`.
- Acceptance:
  - A title hit is accepted only when the normalized title has a difflib ratio of at least 0.9, or is a prefix match of 5 or more words, and an author surname or the year agrees with the PDF.
  - An identifier hit must be the paper printed on the first pages, because a DOI in the text can belong to a cited reference.
- Writing values:
  - Provider values replace values from `pdf` or `llm`. Provenance becomes `{source: provider, external_id}`.
  - A record that confirms the printed title keeps the PDF's capitalisation.
  - Fields with provenance `manual`, or already taken from a provider, are never replaced.
  - The provider record is linked as a source unless another paper already owns it or its DOI. In that case the descriptive fields are still filled, DOI deduplication holds, and the result carries `duplicate_paper_id`.
- Outcomes:
  - Job results are `{outcome: matched|no_match|paper_missing, provider, matched_by: doi|arxiv|title, external_id, updated_fields}`.
  - The chosen source's own `no_match` is final.
  - When the chosen source is rate limited or unreachable and the other source cannot match, the job waits in `retry_wait`. The wait is the larger of the longest Retry-After and a 60 s or 120 s backoff, capped at 30 minutes.
  - On the third attempt the job fails with `PROVIDER_RATE_LIMITED` or `PROVIDER_UNAVAILABLE`, and the PDF values are kept.
- Jobs API:
  - `/jobs` accepts `kind=metadata` and links these jobs to their paper.
  - `POST /jobs/{id}/retry` accepts a failed lookup with those two codes.
  - Stages are `queued`, `finding_metadata`, `retry_wait`, `completed` and `failed`.

### XMP clues and library matches (ARA-086 follow-up)

**XMP clues.** The parser reads the PDF's XMP packet in the child process and ranks its fields above the Info dictionary:
- `dc:title` comes first and passes the same junk-title and printed-title checks as the Info title;
- `dc:creator` fills authors when the Info author is empty;
- `prism:doi` or `dc:identifier` is the first DOI clue;
- `prism:publicationName` becomes the `venue` clue, which breaks ties between equally good title matches;
- `prism:coverDate`, `prism:publicationDate` or `prism:coverDisplayDate` gives the year. File dates such as `xmp:CreateDate` are ignored.

A malformed packet gives no clues and never an error. The LLM metadata step keeps its behaviour and gating, with the saved default model and effort. A title that the junk filter rejects counts as missing, so that step can run for it, and its title and DOI then seed the catalog lookup.

**Matching a new upload to the library.** This applies to uploads without `paper_id`, whose ingest payload carries `new_paper: true`. Ingestion compares the PDF's DOI (`normalized_doi`), the arXiv DOI `10.48550/arxiv.<id>` and, failing those, the strict title rule (title ratio ≥ 0.9 plus an agreeing author or year) against library papers:
- **Match without a usable PDF** (no active document, or the active one failed). The upload is attached in the commit that makes it ready. The document moves to that paper, which gets it as its active document, and its processing and automatic summary continue there. The placeholder paper is deleted, a `paper_redirects` row records the target, and the ingest job result carries `match: {paper_id, outcome: "attached", matched_by}`. No model metadata call is made.
- **Match with a PDF.** Ingestion completes the job with `outcome: "match_pending"` before storing pages. The document stays `processing`, and an `upload_matches` row keyed by the placeholder records the library paper, the document, `matched_by` and `found_by: "ingest"`. No model metadata call, pages, chunks, index, catalog lookup or automatic summary start.
- **Late match.** A catalog lookup for a new upload whose record another library paper owns records the same pending match, with `found_by: "lookup"` and job outcome `library_match`, and writes nothing to the upload.

**API.**
- `Paper.upload_match`: nullable `{paper_id, title, has_pdf, matched_by: doi|arxiv|title, found_by: ingest|lookup}`.
- `Paper.pdf_doi_owner`: nullable `{paper_id, title}`. It is set when an upload into a chosen paper carries a DOI that another library paper owns. The upload stays on the chosen paper, and the owner is stored in `documents.doi_owner_paper_id`.
- `GET /papers` leaves pending placeholders out. `GET /uploads/matches` lists them as `{items: Paper[]}`.
- `GET /papers/{placeholder}` answers with the paper an attached or replaced upload joined. That paper's `id` differs, so the client redirects.

`POST /uploads/{placeholder}/match {decision: "attach"|"discard"}`:
- **`attach`** (Replace or Attach) moves the document to the library paper as its active PDF; earlier documents stay its versions. It also moves the placeholder's chats (their `chat_papers` links; a chat that already includes the library paper keeps that paper's pinned PDF) and summaries, deletes the placeholder and returns the library `Paper` (200).
  - An unread document gets a fresh ingest job on that paper.
  - A ready document is indexed for that paper, and the automatic summary is queued once.
- **`discard`** deletes the placeholder and its document (by cascade) as any paper deletion does, queues the durable `storage_cleanup` job for the stored original (ARA-095; it was removed inline before), and returns 204.
- **Repeats are safe.** A second `attach` returns the same paper, and a second `discard` returns 204. A paper without a pending match returns 409 `NO_PENDING_MATCH`.

**Labels.** Matches, redirects and DOI owners live in the `upload_matches` and `paper_redirects` tables and the `documents.doi_owner_paper_id` column (migration `0009_upload_match_tables`; ARA-086 first kept them as prefixed `model_configurations` rows). Foreign keys cascade: deleting a placeholder, library paper or document removes its match; deleting a redirect's target removes the redirect; deleting a DOI owner clears the column. The migration moves valid prefixed rows, drops orphans and deletes the prefixed rows; its downgrade restores them. The API is unchanged. The `processing` document badge now reads "Preparing PDF".

## OpenAlex-only PDF retrieval (ARA-087)

No migration. Supersedes the ARA-019 multi-host downloader.

- Retrieval resolves the paper's OpenAlex work with a free single-work lookup, `GET /works/{W-id}` or `GET /works/doi:{doi}` with `select=id,has_content` (the saved OpenAlex record first, else the DOI). Only `has_content.pdf: true` continues; a 404 or a missing copy ends the job `not_stored`.
- The download is `GET https://content.openalex.org/works/{W-id}.pdf?api_key=…`. Its redirect may only reach `content.openalex.org` (a merged work) or OpenAlex's R2 storage hosts `a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com` and `openalex-pdfs.a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com`, as documented for its PDF bucket; any other target ends `unsafe_url`. The key is sent only to OpenAlex. Requests bypass httpx client logging, and no URL with the key or a signature is stored.
- Outcomes: `downloaded`, `not_stored`, `api_key_required` (no key when the job runs, or 401/403 from OpenAlex), `rate_limited` (429; `retry_after` from `Retry-After`, else `X-RateLimit-Reset`, at most 86,400 s, else null), `unavailable` (lookup or storage failure, timeout), `invalid_pdf`, `unsafe_url`, `already_attached`, `superseded`. Older jobs keep their earlier outcome strings in `result`. None is retried automatically.
- `GET /papers/{id}/fulltext` returns `{paper_id, api_key_configured, retrieval_job?, document_id?, ingest_job_id?, acquisition?}`; `availability`, `locations`, `attempts`, `last_checked_at` and `source_host` are removed. The attempts table is no longer written.
- `POST /papers/{id}/retrieve-fulltext` returns 409 `OPENALEX_API_KEY_REQUIRED` without a key.
- New acquisition records are `{method: "provider_download", provider: "openalex", source: "content", work_id, retrieved_at, retrieval_job_id}`. Earlier records, with candidate URLs, versions and licenses, stay readable.
- `FULLTEXT_ALLOWED_HOSTS` is removed; a stale value in `.env` is ignored.

## Chats over several papers (ARA-088)

Migration `0010_chat_papers` (head; `SCHEMA_REVISION`) replaces `chat_sessions.paper_id` and `document_id` with `chat_papers (chat_id, paper_id, document_id, ordinal, added_at)`: primary key `(chat_id, paper_id)`, unique `(chat_id, ordinal)`, chat and paper foreign keys `ON DELETE CASCADE`, and an index on each of `paper_id` and `document_id`. Every existing chat becomes a one-paper chat at ordinal 0 with the PDF it already used; messages and citation snapshots are not touched. The trigger `chat_papers_last_paper` deletes a chat when its last link is deleted, so deleting a paper still deletes the chats that were only about it, as the old cascade did. The downgrade restores both columns from each chat's lowest ordinal.

- **`POST /chats`** `{paper_ids: UUID[] (one or more, distinct; no upper limit), title?}` → 201 `Chat`. Each paper pins its active PDF, which must be ready; readiness is read in one query. Unknown paper → 404 `PAPER_NOT_FOUND`; a paper without a ready PDF → 409 `PAPER_NOT_READY` naming it; an empty or repeated list → 422. Nothing is created on refusal. `POST /papers/{id}/chats` is removed.
- **`POST /chats/{id}/papers`** `{paper_id}` → 200 `Chat`. The paper is appended with the PDF that is active at that moment; a later upload does not change what the chat reads. Adding an included paper changes nothing. Missing chat → 404 `CHAT_NOT_FOUND`; unknown paper → 404 `PAPER_NOT_FOUND`; no ready PDF → 409 `PAPER_NOT_READY`. There is no paper limit (user decision, 2026-10-10).
- **`DELETE /chats/{id}/papers/{paper_id}`** → 200 `Chat`, whose `paper_id` is the chat's new first paper; the client moves to that paper's chat URL when the paper in its URL was removed. A paper not in the chat → 404 `CHAT_PAPER_NOT_FOUND`; the last paper → 409 `LAST_CHAT_PAPER`. Earlier answers keep their citations; `GET /chats/{id}/messages` names each cited document's paper in `Citation.paper_id`, including papers since removed.
- **`GET /chats/{id}`** → `ChatSummary`, so a link from a paper the chat no longer covers can find its first paper. Missing → 404 `CHAT_NOT_FOUND`.
- **Answers.** A chat may have any number of papers, and the statements an answer runs do not grow with them. Retrieval runs one keyword and one vector search per query across the chat's pinned PDFs (`(document_id, chunk_set) IN (…)`). Each list holds at most 30 passages, and each paper at most max(2, ⌈30/N⌉) of them; the lists are fused with RRF. With several papers the planner also runs on a first question. It sees at most 20 papers, those the question names first, and may return up to 5 `sub_questions` (`{paper, question}`, paper numbered from 1 by ordinal), each searched only within its paper; `Message.retrieval.sub_questions` lists them. Papers the question names, by full title or as a chip names them ("Surname Year"; the composer inserts "@Surname Year" when a paper is added by typing @), and the targets of sub-questions are kept: named papers without a sub-question share one more search, and kept papers answer first. The reranker's head takes the papers in turns. Packing gives every paper a floor of two passages while floors fit; when they don't, the most relevant papers answer, at most 8 (16 passages / 2), and `retrieval.note` says how many. The others add nothing to that turn. Evidence is grouped under one `Paper N: title (first author et al., year)` header per answering paper, with its sub-question cut to 300 characters; the system prompt states only how many papers the chat has. The trace records `sub_questions`, `kept`, per-list `paper` numbers, `papers` (passages per answering document), `papers_in_scope` and `routed_out`. Citation validation accepts any pinned PDF of the chat and still rejects any other document (`UNGROUNDED_OUTPUT`).
- **Local models.** A question to a local model in a chat over several papers → 409 `MULTI_PAPER_LOCAL` ("Chats over several papers need a hosted model…"); a replay still returns its stored answer. Open models are frozen (ARA-090).

## Deleting papers and editing details (ARA-095)

No migration. Deletion relies on the existing foreign keys and the `chat_papers_last_paper` trigger.

**Endpoints.**
- `GET /papers/{id}/deletion-preview` → `DeletionPreview`; 404 `PAPER_NOT_FOUND` for an unknown paper. `POST /papers/deletion-preview` `{paper_ids: UUID[] (1–200)}` → the combined `DeletionPreview`, with unknown IDs in `missing`. Reading a preview changes nothing.
- `DeletionPreview`: `papers` (`PaperLink[]`), `missing` (UUID[] in request order), `pdfs` (stored PDFs, every version), `summaries`, `deleted_chats` (`{id,title}[]`, chats about only these papers), `updated_chats` (chats that keep other papers), `active_jobs` (queued or running work that stops), `answering` (a chat about these papers is writing an answer now).
- `DELETE /papers/{id}` → 204; a repeat or an unknown paper → 404 `PAPER_NOT_FOUND`. A placeholder's old ID is not followed through `paper_redirects`.
- `POST /papers/delete` `{paper_ids}` → `{deleted: UUID[], missing: UUID[]}` in request order, in one transaction; a repeat returns everything as missing. An empty list → 422.
- Either deletion refuses with 409 `CHAT_BUSY` ("Wait for the current answer to finish before deleting.") while a chat about the papers has an answer with a live lease; expired answers are marked interrupted first, as chat deletion does.

**What goes and what stays.**
- The paper and, by cascade, its authors, provider records, documents (every PDF version) with their pages, sections, passages, embeddings and retrieval indexes, summaries, PDF retrieval requests, upload requests, pending upload matches naming it and redirects to it. `documents.doi_owner_paper_id` pointing at it is cleared.
- A chat whose papers are all deleted is deleted with its messages and memories. A chat that also covers other papers keeps them; its first paper (and URL) moves to the lowest remaining ordinal. Saved citations stay readable: `GET /chats/{id}/messages` returns them with `paper_id: null` once their document is gone.
- An upload waiting for Replace or Cancel against a deleted library paper goes on as its own paper: its match row is removed, and its document is re-read (or, if it was already read, indexed and summarized once).
- Locks: the identity locks that saving, uploading, attaching and lookups take (`upload_match:<id>` for the papers and their placeholders, `doi:`, `source:` and `pdf:` keys), then the affected chats, then the papers, in ID order.

**Background work.**
- In the same transaction, every `queued` or `processing` job whose payload names a deleted paper (`paper_id`), one of its documents (`document_id`) or a deleted chat (`chat_id`) becomes `failed` with `error_code` `PAPER_DELETED`, message "Stopped because the paper was deleted.", no lease, and `result {outcome: "paper_deleted", paper_title}`. Rows locked by a worker at that moment are skipped (`SKIP LOCKED`) and settle themselves: ingest, PDF retrieval and metadata lookups fail with `PAPER_DELETED` when they find the paper gone; summary and index jobs end as before (failed, or completed `skipped`) and write nothing. The job retry route does not accept `PAPER_DELETED`.
- `JobStatus.paper_title` keeps the deleted paper's title from `result.paper_title`, with `paper_id: null`, so Activity names it without a link.
- One `storage_cleanup` job (payload `{object_keys, paper_titles}`) is queued with its outbox event in the deletion commit when the papers had PDFs. It removes each object, keeping any key a live document still names; removing a missing object succeeds, so duplicates and reruns are harmless. A storage error waits 30 s, then 60 s, and fails with `STORAGE_UNAVAILABLE` on the third attempt; `POST /jobs/{id}/retry` accepts it. It never writes a paper row. When a deleted PDF was still `uploading`, the job waits 300 s, past the 120 s ingest grace, so an object stored late is removed too.

**Editing and Look up again.**
- `PATCH /papers/{id}` accepts `venue` (≤ 300 characters, nullable). Papers have no venue column, so a manual venue is stored as `metadata_provenance.venue = {source: "manual", value}`; `Paper.venue` reads that value (null when cleared) before the provider record.
- `POST /papers/{id}/metadata-lookup` (no body) → 202 `JobStatus` of a `metadata` job with payload `{paper_id, document_id, refresh: true, clues}`. It needs a title, DOI or provider record, else 409 `LOOKUP_UNAVAILABLE`; unknown paper → 404. A lookup already queued or running for the paper is returned instead of a new one. `clues` carries the paper's earlier lookup clues, so an arXiv ID only the PDF had is kept.
- A refresh reads the paper's current title, authors, year and DOI when it runs. For each source, chosen first, it reads the paper's saved record at that source (`matched_by: "record"`), else searches by DOI, arXiv ID and title as the upload lookup does. A DOI the user entered (`provenance.doi.source == "manual"`) is accepted without the printed-title check. It replaces provider and PDF values, never `manual` ones, and keeps the lookup's rate-limit wait and three attempts.

