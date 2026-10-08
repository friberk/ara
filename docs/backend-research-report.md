# Backend Phases 1–2 handoff — ARA-006 through ARA-011

Scope: only src/backend files, plus this temporary report. No commits, no root Compose/script/docs/tracker edits, no assignment or writing-skill changes. Foundation report remains /tmp/ara-backend-foundation-report.md. AI modules are owned by the AI agent; this work integrated their routers/summary actor and shared schema/resource/dependency requirements. One accidental broad Ruff format/import pass touched concurrently created AI files; I disclosed it immediately, then restricted subsequent mutation commands to owned files.

Implemented:
- Official-URL Semantic Scholar/OpenAlex httpx adapters; normalized nullable metadata, abstract reconstruction, provider-specific pagination, canonical record lookup, bounded response bytes/timeouts/transient retries, explicit rate-limit/access/outage errors. Provider URL overrides are rejected unless APP_ENV=test; normal app never uses fixtures.
- Canonical POST /api/v1/papers; persistent list/detail/PATCH and field provenance, ordered authors, unique normalized DOI and provider identity. Sorted PostgreSQL transaction advisory locks serialize concurrent DOI/source saves and manual DOI changes; conflicts require reconciliation. Browser metadata is rejected instead of trusted.
- Multipart POST /api/v1/documents with UUID binding, 25MiB/signature/media validation, private MinIO original retention, SHA256 deduplication, attachment conflict checks, durable delayed upload recovery followed by queued ingest. Every deduplicated upload UUID binds to its original through document_upload_requests. Storage failure/missing original resumes by reuploading the same bytes and issuing a new generation/outbox for the same job/document.
- Fresh isolated PyMuPDF subprocess, killed+waited on 120-second timeout; 200-page/4million-text-character limits; safe errors for malformed, encrypted, scanned and parser failure; ordered physical pages and labels, page-preserving overlapping chunks, offsets/token estimates and PostgreSQL generated English TSVECTOR/GIN. API and worker threads never import/run PyMuPDF.
- Deterministic PDF metadata preserves nullable unknowns and never uses creation year as publication year. Optional configured hosted metadata extraction uses the AI agent's source-validated helper; failure preserves usable text. Durable metadata-attempt/result checkpoints prevent an interrupted metadata call from being automatically paid again; extracted versus hosted field provenance is recorded.
- Fenced atomic ingest content/document/job completion. Terminal lease recovery and generic actor exhaustion atomically mark the matching document failed so UI polling stops. Original download and document-scoped chunk citations. Eligible failed ingest/canary jobs can be explicitly retried; paid summary retries require a new generation request.
- Unknown browser Origin rejected for unsafe methods before body parsing. Structured errors/request IDs remain intact.
- Main wires research/document/AI/chat routers. Actor kinds canary/ingest/summary; summary hook exactly run_summary_job(resources,job_id,generation,token,payload). Resources has process-owned llm_slots Semaphore2. Explicit openai/anyio dependencies and uv lock updated.

Migration ownership and schema:
- 0002_research: papers, paper_authors, paper_sources, documents, document_pages, document_chunks + GIN; paper_summaries; chat_sessions/messages with user UUID uniqueness and one processing assistant/session; model_configurations(key,value JSONB), generation_reservations(id,model,amount Numeric12,6,created_at).
- 0003_upload_requests: durable request->document bindings, with backfill of existing original request IDs.
- ChatMessage includes configuration/usage JSONB. Summary fields/model class exactly coordinated with AI agent. Readiness expects 0003_upload_requests. Root applied main/e2e migrations.

Actual test evidence, including genuine corrections:
- /tmp/ara-research-red.txt: seven initial research tests failed before features existed.
- /tmp/ara-research-integration-red.txt: three real-service tests failed before papers repository/ingestion existed.
- /tmp/ara-job-retry-red.txt: retry route returned404 before implementation.
- /tmp/ara-upload-hardening-red.txt: duplicate-hash UUID reused for another original returned202 instead409; real refused socket followed by real MinIO restored left jobfailed insteadqueued. Both bugs corrected with request bindings/resumable original upload.
- /tmp/ara-review-regressions-red.txt: configured metadata branch silently swallowed wrong helper import; both lease expiry and generic actor failure left paperprocessing after jobfailed. Correct helper import/checkpoint and atomic terminal-document updates added; all regressions now green.
- Latest complete isolated real-service suite: docker compose --project-name ara-test --file compose.yaml --file compose.test.yaml run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest -q. Result: 57 passed in 13.41s, zero skips. /tmp/ara-backend-research-green.txt. Includes all foundation/research/AI tests, actual PostgreSQL/Redis/MinIO, real child worker/parser, actual local HTTP metadata fixture, real storage connection failure and missing object recovery through ready, size/page/time limits, canonical API and citation isolation.
- Latest real container Ruff check: All checks passed.
- Latest real container Alembic check: No new upgrade operations detected, exit0.
- Latest host complete backend suite: 29 passed,28 explicitly skipped integrations,5 upstream PyMuPDF SWIG deprecation warnings,2.32s. No host failure; Linux real-service suite emits no warning.
- Independent fresh migration-test database roundtrip: upgradehead/check; downgrade0001_jobs/upgradehead/check; downgradebase/upgradehead/check, all passed. Temporary DB was dropped afterward, leaving existing dev/test databases untouched. /tmp/ara-migration-roundtrip.txt.

Stable handoff: all existing checks are complete and passing; no pending backend edits/checks. Stop further optional changes so root can run the final helper and browser suite. Root owns journal/tracker/contract documentation and live-stack E2E/restart gates. No claim of paid model/account or live scholarly access: credentials absent; HTTP fixtures prove deterministic behavior only. No OCR, arbitrary remote downloads or P1/P2 enhancements implemented. Exactly-once remote inference remains impossible across ambiguous provider failures; persisted reservations/checkpoints/UUID rules prevent automatic ambiguous resubmission. Public publication/authentication/submission are outside this backend handoff.

## Final ARA-032 citation correction

The source excerpt route now returns the complete bounded persisted chunk, preserving evidence after character1200. Actual API/realPostgreSQL regression first failed on missing late evidence, then passed with existing-document cross-scope denial intact. Final backend suite supersedes the earlier57-test count:58passed13.60s; full containerRuffclean. No migration/mainDBwrites/paidcalls. Detailed actual commands/output: /tmp/ara-backend-citation-report.md and /tmp/ara-citation-{red,green,ruff}.txt.
