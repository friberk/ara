# Independent application review

Initial read-only source review; no database operations or application-file edits during that pass. Findings below preserve the original observed defects. All five were subsequently corrected and independently reviewed again. Live verification is recorded separately.

## Findings

1. **P1 — A transient object-storage write failure permanently blocks that PDF.** `src/backend/app/services/uploads.py:47–60` returns any existing SHA match before attempting storage. The initial request persists that SHA before `put_object`; failure records `STORAGE_UPLOAD_FAILED`. Reuploading identical bytes, even with a new request UUID, therefore returns the failed job and never retries storing the bytes. `src/backend/app/routes/jobs.py:62` also excludes that error from eligible retries. Trigger: stop/unreach MinIO during upload, restore it, reupload the same PDF. Expected: resume storage and ingestion. Missing regression at initial inspection: storage fails once, same-file retry reaches ready without duplicate paper/document. Owner has since started adding this regression.

2. **P1 — Real stream cancellation can skip interrupted-state and partial-text persistence.** `src/backend/app/services/chat.py:258–267` awaits `client.close()` outside cancellation shielding before calling the shielded save. Installed Uvicorn uses ASGI spec 2.3; installed Starlette cancels an AnyIO task group on streaming disconnect. AnyIO level cancellation re-cancels `close()` at its next await, exiting the finally block before save. DB-free executable reproduction used the actual `stream_answer`, a fake streaming client with `close(): await asyncio.sleep(0)`, and cancelled an AnyIO task group after the first delta: output was `Saved states after AnyIO stream cancellation: []`. The message remains processing until lease expiry and recent visible partial text is lost. Missing test: AnyIO/ASGI disconnect cancellation with awaited client cleanup, rather than only `stream.aclose()` as in `test_ai_integration.py:338`.

3. **P2 — Hosted PDF metadata enrichment is never called.** `src/backend/app/services/ingestion.py:155` imports `extract_metadata` from `app.services.summarization`, while it is defined in `app.integrations.llm`. Trigger: a configured key and extracted metadata lacking title or authors. ImportError is swallowed by the broad enrichment fallback, leaving usable PDFs without the intended metadata candidates and always reporting enrichment unavailable. Missing test: configured-key ingestion with missing metadata calls the adapter and persists supported candidates/provenance.

4. **P2 — Exhausted ingestion recovery leaves document permanently processing.** `src/backend/app/repositories/jobs.py:92–99,123–139` transitions the job to failed after its third expired lease without updating its Document. The generic actor-failure path through `fail():119` has the same terminal-state omission. Trigger: an ingest actor dies on its third attempt, then recovery runs. `/jobs` reports failure while paper details still report processing; `src/frontend/src/pages/PaperPage.tsx` continues polling and gates analysis as though work remains active. Missing test: third-attempt expiry and generic failure assert failed job and failed document atomically, then explicit retry restores processing.

5. **P2 — Compose silently ignores a configured daily budget.** `src/backend/app/core/config.py:30` reads `LLM_DAILY_BUDGET_USD`, but `compose.yaml:20–28` does not pass it to API/worker and only mounts `src/backend`, not the root `.env`. Trigger: set a lower daily cap in the normal root `.env` and launch Compose. Both services retain the $5 default. Missing test: compose environment expansion forwards a nondefault cap to both services. This matters because `docs/implementation-plan.md:112` explicitly promises a configurable cap.

## Accepted tradeoffs / verification limits

- Local single-user operation without authentication matches the approved plan; loopback host port bindings and write-Origin checks are present.
- Conservative UTF-8 byte token estimates and unreleased maximum-output budget reservations intentionally underuse capacity; these are not correctness defects.
- Summaries and chats retain immutable document bindings; retrieval and citation lookup constrain document IDs. No concrete cross-document citation leak was found in the inspected paths.
- UUID replay protection and ambiguous-summary-outcome failure avoid automatic paid replay; no live hosted access was tested.
- API-hosted dispatch/recovery pauses while API is down, as documented.

## Resolution review

| Original finding | Issue | Correction and verification |
| --- | --- | --- |
| Same-PDF storage recovery | ARA-025 | Resume retained document after failed/missing object writes; enforce upload UUID binding. Real storage-failure and reupload regressions pass. |
| Cancellation loses partial answer | ARA-026 | Shield bounded stream cleanup and final persistence from AnyIO cancellation. Actual ASGI disconnect test independently passed; PostgreSQL regression retains interrupted text and prevents paid UUID replay. |
| Wrong metadata import | ARA-027 | Import the integration adapter and exercise it through actual HTTP fixtures with persisted candidates/provenance. |
| Terminal job/document mismatch | ARA-028 | Fail both records atomically after exhausted leases or actor failure; explicit eligible retry restores processing. Both termination regressions pass. |
| Missing daily budget forwarding | ARA-029 | Pass the configured budget to API and worker. Independently executed nondefault Compose configuration regression passes. |

The reviewer scored all five resolved. That scope does not imply a whole-application security audit. The lead also inspected the corrections and executed the integrated backend/browser checks.

## Final bounded review

Recorded model and reasoning labels remain tied to each saved response when the form selection changes; the focused regression passed. No new submission-blocking issue was reported.

The lead initially suspected that the live dataset answer's citation lacked support because its dialog showed unrelated complexity text. The reviewer used an explicitly read-only database transaction to inspect the complete cited page-7 chunk. It contained both WMT datasets and their sizes/tokenization details. The defect was the source endpoint's 1,200-character truncation, which hid later evidence. ARA-032 now returns the complete bounded stored chunk; its API regression observes the missing evidence before correction and verifies complete text plus cross-document denial afterward. No live generation or database write was needed for that review.

Citation identity validation still does not prove semantic entailment for arbitrary future answers. Users can inspect the full retrieved passage and original page.
