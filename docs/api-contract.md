# Backend/frontend contract

JSON fields use snake_case. REST prefix `/api/v1`. UUID identifiers are strings; UTC timestamps ISO8601. Collections use `{items:[...]}`; search additionally returns provider, next_cursor (nullable) and total (nullable). Errors `{code,message,request_id,details?}` with correct HTTP status. Never expose secret configuration.

## Core DTOs

- SearchResult: provider (`semantic_scholar`/`openalex`), external_id, title (nullable), authors (`string[]`), year (nullable), abstract (nullable), doi (nullable), external_url (nullable), pdf_url (nullable).
- Paper: id, title, authors, year, abstract, doi, sources (SearchResult[] or equivalent source DTO), document_status (`metadata_only`/`processing`/`ready`/`failed`), active_document_id (nullable), metadata_provenance.
- UploadAccepted: paper_id, document_id, job_id.
- Job: id, kind, state (`queued`/`processing`/`completed`/`failed`), stage, progress (0–100), error (nullable safe code/message), result (nullable), attempts.
- Summary: id, paper_id, document_id, model, reasoning_effort, content (Markdown string), citations (Citation[]), created_at.
- Citation: chunk_id, document_id, page (1-based physical PDF page), excerpt. The source endpoint returns the complete stored chunk, bounded by ingestion chunk limits, so evidence later in a passage remains visible.
- Chat: id, paper_id, document_id, title, created_at.
- Message: id, role (`user`/`assistant`), content, state (`completed`/`processing`/`interrupted`/`failed`), model (nullable), reasoning_effort (nullable), citations (Citation[]), created_at.
- Model: key (exact hosted model ID), provider, model_id, display_name, status (`configured`/`available`/`unavailable`), reasoning_efforts (string[]), supports_streaming, supports_structured_output, context_window.
- Settings: default_model (exact ID), reasoning_effort.

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
- GET /documents/{id}/download → PDF; GET /documents/{id}/chunks/{chunk_id} → Citation.

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
  - `GET /jobs` gains optional filters: `paper_id`, `kind` (`ingest` or `summary`) and `active` (true = queued, processing or retry_wait).
- **CORS** allows `DELETE`. The existing Origin guard applies to every unsafe method, including DELETE.

## SSE

Events have JSON data, blank-line framing and heartbeat comments. `message.started`: `{message_id}`; `message.delta`: `{text}`; `message.completed`: Message; `message.failed`: `{code,message,message_id?}`. Complete emitted only after persistence. Unknown/invalid frames produce a visible client error; AbortController stops streaming and authoritative history refreshes. Duplicate UUIDs cannot launch inference again. Histories retain partial/interrupted status after process failure.

The lead owns changes to this contract. Generate API types from actual OpenAPI once routes are ready. Report any implementation discrepancy instead of silently adapting unrelated files.
