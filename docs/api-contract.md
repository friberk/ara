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

## SSE

Events have JSON data, blank-line framing and heartbeat comments. `message.started`: `{message_id}`; `message.delta`: `{text}`; `message.completed`: Message; `message.failed`: `{code,message,message_id?}`. Complete emitted only after persistence. Unknown/invalid frames produce a visible client error; AbortController stops streaming and authoritative history refreshes. Duplicate UUIDs cannot launch inference again. Histories retain partial/interrupted status after process failure.

The lead owns changes to this contract. Generate API types from actual OpenAPI once routes are ready. Report any implementation discrepancy instead of silently adapting unrelated files.
