# ARA-019 PDF Retrieval and Access Information Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrieve supported PDFs for saved OpenAlex and Semantic Scholar papers, explain access barriers, and let users retry after changing networks or use browser download/upload.

**Architecture:** Extend provider snapshots with per-copy access metadata and discover exact-DOI alternatives. An idempotent PostgreSQL/outbox job downloads through a bounded, DNS-pinned HTTPX boundary and hands valid bytes to the existing ingestion pipeline. Persist discovery/attempt outcomes independently of document processing; use the existing reader, Details, and Activity surfaces.

**Tech Stack:** Python 3.13, FastAPI/Pydantic v2, async SQLAlchemy/psycopg, Alembic, HTTPX, Dramatiq/Redis, MinIO, PyMuPDF child processes; React/strict TypeScript, TanStack Query, shadcn, Vitest/RTL, Playwright. Preserve uv/npm lockfiles; no new dependency is required by this design.

**Spec:** [PDF retrieval and access design](../specs/2026-10-08-fulltext-access-design.md).

## Global Constraints

- Worktree: `/Users/bcakar/orca/workspaces/hw1/ara-019-fulltext`; branch: `ara-019-fulltext`.
- Base: `feat/managed-ollama` commit `ddced814df3de60cd05e926b5a91915360ff2470`; uncommitted ARA-053 work stays with its owner. Incorporate later committed upstream work before migration allocation and final verification.
- All behavior changes use TDD-first: write a Given/When/Then test, run it and record an assertion failure for the missing behavior, implement minimally, run green, refactor, and rerun relevant regressions.
- Every task below repeats that cycle for each independent behavior; do not write a whole implementation after observing only one failing assertion. Collection/import/service errors do not count as the intended red phase.
- PDF maximum: `25 * 1024 * 1024` bytes; enforce claimed length and streamed/decompressed bytes.
- Candidate deadline: 45 seconds, including DNS and redirects; connect/pool deadline 5 seconds; read/write deadline 10 seconds; job discovery-plus-fetch deadline 420 seconds.
- Redirect maximum: 5 hops; validate every hop and resolve relative redirects against the original URL, not the pinned IP URL.
- Non-PDF classification body maximum: 64 KiB; no unbounded HTML parsing.
- Schemes/ports: HTTPS 443 and HTTP 80; reject HTTPS-to-HTTP downgrade.
- Metadata-only browsing and saving must never trigger PDF downloads.
- Network retry starts a fresh full-text request; generic `/jobs/{id}/retry` rejects fulltext with 409 `NEW_FULLTEXT_REQUEST_REQUIRED`. Ingestion retry keeps its existing semantics.
- Use isolated `ara019-test` / `ara019-e2e` projects, unique backend/frontend image tags, and browser ports 8002/5181; do not operate on the other agent's `ara-test`, `ara-e2e`, or development stacks.
- One owner changes migrations and generated contracts. Retain model readiness/admission/queues, paid-request replay prevention, manual metadata overrides, SHA deduplication, and immutable document citations.
- Use Conventional Commits containing ARA-019, with no Co-Authored-By trailer. Do not push or merge into main. Record actual failures, corrections, and outputs in the journal.

## Review Focus

- Browser sign-in does not authenticate the backend: Task 6 keeps institutional access as browser/upload fallback and never claims the university grants access.
- Access denial is temporary with respect to network context: Tasks 2/4/5/7 prove a new UUID can succeed after a denied attempt while old UUIDs still replay.
- A manual upload races an ongoing download: Task 4 checks the paper/lease guard and preserves the newer PDF and historical citations.
- DNS changes between validation and connection, or multiple hosts share an IP: Task 3 pins connection addresses, preserves TLS hostname verification, and isolates original hosts.
- A crash happens after attachment but before retrieval completion: Task 4 checkpoints stable attachment identity/references and proves there is no second download/document/ingest job.

## File map and interfaces

Follow the existing separation; avoid growing provider/download/job/UI logic into one file.

| Area | Files | Responsibility |
| --- | --- | --- |
| Provider DTOs | Modify `src/backend/app/schemas/research.py`; create `src/backend/app/schemas/fulltext.py` | Additive locations, candidate/status/request/outcome types |
| Provider metadata | Modify `src/backend/app/integrations/academic.py`; create `src/backend/app/services/fulltext_discovery.py` | Normalization, exact DOI lookup, refreshed candidate ranking |
| Persistence | Create `src/backend/app/models/fulltext.py`, `src/backend/app/repositories/fulltext.py`, next Alembic revision; modify model exports and research Document | UUID binding, durable attempt records, acquisition metadata |
| HTTP boundary | Create `src/backend/app/integrations/pdf_download.py`, `src/backend/app/integrations/public_http.py`; modify Settings/Resources | Public DNS checks, explicit-IP/TLS-preserving transport, bounded PDF fetch |
| Job/API service | Create `src/backend/app/services/fulltext.py`, `src/backend/app/routes/fulltext.py`; modify main, jobs routes/repository, actors | Enqueue/read status, execute retrieval, paper links and recovery |
| Attachment | Modify `src/backend/app/services/uploads.py` | Shared byte entrypoint with optional fence/active-document guard |
| UI | Create `src/frontend/src/hooks/queries/fulltext.ts`, `src/frontend/src/features/workspace/FullTextAccess.tsx`; modify ReaderGate/Details/search/Activity/job labels and query keys | Download/access/retry state and existing ingestion handoff |
| Tests/evidence | New targeted backend/UI/E2E tests; modify deterministic fixtures; update API/setup docs and ARA-019 | Red/green evidence, isolated real services, contract drift, current behavior |

Public types are defined by Tasks 1/2 before dependent tasks use them:

- `FullTextCandidate`: Pydantic model `{provider: Provider, external_id: str, source_label: str, url: str, location: FullTextLocation}`.
- `DiscoveryResult`: dataclass `{candidates: list[FullTextCandidate], warnings: list[str]}` in `services/fulltext_discovery.py`.
- `FullTextOutcome`: Literal union of the candidate/overall outcomes in the spec; a job has nullable outcome until terminal.
- `DownloadResult`: internal dataclass in `schemas/fulltext.py`, with `outcome: FullTextOutcome`, `data: bytes | None`, `response_status: int | None`, `final_url: str | None`, `reason: str`, and `retry_after: int | None`. Define this with the other shared types in Task 1; PDF bytes are never part of an API response model.
- `AttachmentGuard`: frozen dataclass in `services/uploads.py`, `{job_id: UUID, generation: int, lease_token: UUID, expected_active_document_id: UUID | None}`.
- `AttachmentSuperseded` and `AttachmentLeaseLost`: exceptions from the shared byte entrypoint; they must never initiate a new paid/model operation.

## Task 0: Isolated execution baseline

**Files:** No product-source changes. Generate ignored overrides beneath `docs/evidence/generated/ara019/`; use existing bootstrap/Compose/lockfiles.

**Interfaces:** Produces shell commands `ara019_test` and `ara019_browser`, and a recorded base SHA. Native execution is sufficient because tasks share migration, job, and API interfaces; do not launch workers unless the user selects delegation.

- [ ] Read AGENTS.md and the spec in this worktree. Inspect `git status`, `git log ara-019-fulltext..feat/managed-ollama`, and the latest committed migration head. Incorporate later committed model work by merge into this branch, preserving the other worktree's uncommitted files. Never checkout/reset that worktree.
- [ ] Run `python3 scripts/bootstrap.py` here; do not copy development credentials or weights. Create ignored `compose.images.yaml` overriding images for api/worker/model-worker/migrate/storage-init/ollama to `ara019-backend:development` and frontend to `ara019-frontend:development`. The external-fixtures image override belongs only in the browser override so it does not create an incomplete service in backend-only Compose.
- [ ] Create ignored `compose.browser.yaml`: override API/frontend ports to `127.0.0.1:8002:8000` / `127.0.0.1:5181:5173`; set API/worker/model-worker CORS origins to localhost/127.0.0.1:5181; override external-fixtures image. Keep Ollama on the test runtime fixture, not the real runtime. Task 5 adds fixture resource-factory commands to this browser-only override.

Use these functions from the worktree root (paths are relative to the first Compose file):

```sh
ara019_test() {
  docker compose -p ara019-test -f compose.yaml -f compose.test.yaml -f docs/evidence/generated/ara019/compose.images.yaml "$@"
}
ara019_browser() {
  docker compose -p ara019-e2e -f compose.yaml -f compose.test.yaml -f compose.e2e.yaml -f docs/evidence/generated/ara019/compose.images.yaml -f docs/evidence/generated/ara019/compose.browser.yaml "$@"
}
```

- [ ] Validate with `ara019_test config --quiet` and `ara019_browser config --quiet`; inspect service/image/port identity without printing resolved credentials.
- [ ] Build `ara019_test build api frontend`; start only `ara019_test up -d --wait postgres redis minio`; run `ara019_test run --rm --no-deps migrate` and `ara019_test run --rm --no-deps storage-init`.
- [ ] Record baseline from `ara019_test run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest`, then `ara019_test run --rm --no-deps frontend npm ci`, `... frontend npm run check`, and `... frontend npm run build`. Tests own only this isolated database; no dispatcher/worker runs during repository tests. Report any baseline failure by name before feature work and investigate within the task's scope.

## Task 1: Both providers retain access metadata and discover exact-DOI copies

**Files:** Modify schemas/research.py, integrations/academic.py, tests/test_research.py; create schemas/fulltext.py, services/fulltext_discovery.py, tests/test_fulltext_discovery.py. Paths below are under `src/backend` unless otherwise stated.

**Interfaces:** Produces `FullTextLocation`/`FullTextCandidate`; `AcademicSearch.by_doi(provider: Provider, doi: str) -> SearchResult | None`; `discover_fulltext(resources, paper_id: UUID) -> DiscoveryResult`. Consumes existing canonical lookup, DOI normalization, source identity locks, and provider snapshots.

- [ ] Add tests against the existing normalizer before changing it. Start with assertions like:

```python
result = normalize("semantic_scholar", semantic_row)
data = result.model_dump()
assert data.get("is_open_access") is True
assert data.get("locations") == [{
    "pdf_url": "https://aclanthology.org/example.pdf",
    "landing_page_url": semantic_row["url"],
    "is_oa": True, "license": "CCBY", "version": None,
    "host_type": "unknown", "oa_status": "HYBRID",
}]
```

Parameterize OpenAlex multi-location ordering/deduplication, nullable S2 metadata, and parsing an old SearchResult snapshot with no new fields. Assert false/missing OA metadata does not produce an access-denied outcome. Observe `test_search_preserves_semantic_access_metadata` failing on missing fields.
- [ ] Run `ara019_test run --rm --no-deps api uv run --frozen pytest tests/test_research.py tests/test_fulltext_discovery.py -q`; record the actual missing-behavior assertion. New modules may initially cause collection errors; make the seam importable with a test-driven inert interface and rerun until the relevant behavioral assertion fails before implementing its behavior.
- [ ] Add the schemas with the spec's defaults and implement normalization. Keep legacy top-level links valid; prefer the best known OA PDF for legacy `pdf_url` when present. Preserve S2 OA status/license and request `isOpenAccess`.
- [ ] Write/run separate reds for `test_semantic_paper_finds_openalex_copy_by_exact_doi`, `test_cross_provider_doi_mismatch_is_rejected`, `test_provider_failure_preserves_stored_candidates`, `test_discovery_keeps_manual_metadata`, and `test_discovery_does_not_create_second_library_paper`. Assertions: matching DOI's candidate is returned, mismatched candidate is absent, stored PDF survives provider 429, manual title remains, and Paper count stays one.
- [ ] Implement exact DOI requests: OpenAlex `works` with `filter=doi:https://doi.org/{normalized_doi}`, `per-page=1`; Semantic Scholar `paper/DOI:{doi}` encoded as the current canonical path rules require. Verify returned DOI equality. Refresh saved identities with existing canonical calls; merge snapshots using existing identity protection. Rank/deduplicate/cap candidates at 8 under the 45-second combined discovery deadline; surface warnings without discarding valid stored copies.
- [ ] Run focused green and existing search/save/identity tests. Refactor only while green. Commit `feat(research): preserve full-text candidates and DOI discovery (ARA-019)` with actual red/green evidence.

## Task 2: Durable UUID requests, attempts, migration, and read/enqueue API

**Files:** Create models/fulltext.py, repositories/fulltext.py, routes/fulltext.py, services/fulltext.py, tests/test_fulltext_integration.py, tests/test_fulltext_migration.py, next `alembic/versions/*_fulltext.py`. Modify model exports, models/research.py, main.py, routes/jobs.py, repositories/jobs.py, schemas/fulltext.py.

**Interfaces:** Produces `request_fulltext(resources, paper_id: UUID, request_id: UUID) -> FullTextAccepted`; `fulltext_status(session: AsyncSession, paper_id: UUID) -> FullTextStatus`; `record_attempt(session, *, job_id: UUID, generation: int, lease_token: UUID, ordinal: int, candidate: FullTextCandidate, result: DownloadResult) -> bool`. Services open their own sessions; the repository accepts the current transaction.

- [ ] Write Given/When/Then API assertions against the existing app: a POST with a UUID returns 202 and a `fulltext` job; an unsupported `url` field returns 422; GET for a missing paper returns 404. First observed red is the currently absent route returning 404 rather than 202.
- [ ] Run `ara019_test run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest tests/test_fulltext_integration.py -q` and record assertion failures.
- [ ] Allocate the next Alembic revision only after inspecting the latest committed upstream head. Add request/attempt tables, FKs, uniqueness, bounds, UTC timestamps, and nullable `documents.acquisition`; retain all local-model tables and job states. Add ORM models/exports and test-fixture cleanup for rows not removed by existing paper/job cascades.
- [ ] Implement the POST/GET contracts in the spec. Lock the Paper and request identity; coalesce active jobs and bind every supplied UUID. Capture expected active document and checkpoint a generated attachment UUID. Enqueue job/outbox atomically. GET performs no external requests.
- [ ] Repeat red/green for `test_fulltext_uuid_replays_original_job`, `test_fulltext_uuid_other_paper_conflicts`, `test_concurrent_requests_share_active_job`, `test_new_uuid_after_denial_creates_new_job`, `test_fulltext_attempt_rejects_expired_lease`, `test_jobs_filter_fulltext_by_paper`, and `test_generic_retry_requires_new_fulltext_request`. Assert IDs/state/counts, not only mocked calls.
- [ ] Extend job kind filtering and paper links while preserving model kinds/operations from upstream. Return `NEW_FULLTEXT_REQUEST_REQUIRED` for generic fulltext retry; no changes to local-model pause/resume/preparation behavior.
- [ ] Test migration from empty DB and the previous head in an additional isolated database whose name includes `test`; seed a ModelInstallation and assert its state/default/provenance remain intact after upgrade. Do not downgrade the other agent's database. Run `alembic heads` and assert one head.
- [ ] Run focused and existing workspace/job/local-model regressions, refactor, and commit `feat(fulltext): persist retrieval requests and access attempts (ARA-019)`.

## Task 3: Bounded public PDF downloading with DNS pinning

**Files:** Create integrations/public_http.py, integrations/pdf_download.py, tests/test_public_http.py, tests/test_pdf_download.py; modify core/config.py, core/resources.py, compose.yaml, `.env.example`. Test changed environment forwarding through tests/infrastructure/test_compose_fulltext.py.

**Interfaces:** `Resolver` protocol in public_http.py has `async resolve(hostname: str, port: int) -> tuple[str, ...]`; `PublicPDFTransport` implements `httpx.AsyncBaseTransport` with injected resolver/transport factory; `PDFDownloader(allowed_hosts: Sequence[str], *, resolver: Resolver | None = None, transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None)` provides `async fetch(candidate: FullTextCandidate) -> DownloadResult` and `async aclose() -> None`. Resources owns `pdf_downloader`, accepts optional injected downloader, and closes it on its own event loop.

- [ ] Write/run `test_valid_pdf_bytes_are_returned`, then implement only that path. Assert returned bytes equal the fixture and no cookie/API-key/Authorization/Referer was sent. Subsequent tests each introduce one missing bound or classification before implementing it.
- [ ] Run `ara019_test run --rm --no-deps api uv run --frozen pytest tests/test_public_http.py tests/test_pdf_download.py -q` for each red/green cycle.
- [ ] Pin tests for public/private/mixed DNS, IPv4-mapped IPv6, disallowed/userinfo/IP-literal URLs, malformed ports, 4096-character bound, relative/cross-host redirects, five-hop limit, downgrade, and DNS rebinding. Assert a prohibited destination receives zero connection attempts and a public candidate connects to the validated literal IP without a second hostname lookup.
- [ ] Implement validation/transport with standard ipaddress/socket/url libraries and HTTPX. Preserve original Host and `sni_hostname`; disable proxy inheritance/automatic redirects; use no keepalive reuse across original hosts. Include a real TLS fixture with certificate for the original hostname: valid name passes, wrong name fails, and two hosts sharing an IP cannot reuse the first host's identity. Test certificates stay test-only; TLS verification never becomes false in production.
- [ ] Add separate failing tests for claimed/chunked/decompressed size overflow, missing/false PDF content type, signature mismatch, 200 login HTML, 401, generic 403, 404/410, 429 with bounded Retry-After, 5xx, stalled stream, slow DNS, and cancellation cleanup. Assert exact outcomes, bounded bytes/time, and closed response streams. Login redirects are classified without following their destination; unknown redirects remain subject to public-host checks.
- [ ] Implement the spec's per-candidate 45-second deadline, 5/10-second HTTP deadlines, 64-KiB non-PDF body cap, and 25-MiB PDF cap. Never report 403 or ordinary HTML as a proven paywall. Maintain the exact outcome distinctions needed by the UI.
- [ ] Test Settings validation/Compose forwarding for `FULLTEXT_ALLOWED_HOSTS` before changing config. Implement exact-host IDNA normalization and the spec's default host list; unsupported hosts produce browser fallback. Do not add a production private-IP test override.
- [ ] Run focused green, Settings/resource-lifecycle/infrastructure regressions, refactor, and commit `feat(fulltext): download validated PDFs through a pinned HTTP boundary (ARA-019)`.

## Task 4: Fenced attachment and worker handoff to existing ingestion

**Files:** Modify services/uploads.py, services/fulltext.py, jobs/actors.py; add tests/test_fulltext_jobs.py and extend tests/test_research_integration.py. Review repositories/jobs.py recovery hooks and preserve upstream dispatcher/model actor routing.

**Interfaces:** `ingest_pdf_bytes(resources, *, data: bytes, filename: str, request_id: UUID, paper_id: UUID | None, guard: AttachmentGuard | None = None, acquisition: dict | None = None) -> UploadAccepted`; existing `upload(resources, file, request_id, paper_id)` retains its public signature. `run_fulltext_job(resources, job_id: UUID, generation: int, lease_token: UUID, payload: dict) -> None` consumes Tasks 1–3 and writes through fence checks. Superseded/lost ownership use the exceptions in File map.

- [ ] Write/run a guard test against the planned byte seam and current upload API: a retrieval whose expected active document was replaced must not change that document. Add a current-path assertion proving manual upload and retrieval serialize on the Paper. Preserve existing poisoned-upload/missing-object/SHA/UUID regressions before refactoring.
- [ ] Extract the byte entrypoint after its behavior red. Keep existing upload signature/content-type validation at the route adapter; the byte seam enforces signature/size again. Lock request/SHA identities and Paper consistently; retrieval checks job fence and expected active document in the same attachment transaction. Existing cross-paper checksum conflict remains `DOCUMENT_ALREADY_ATTACHED`.
- [ ] Write/run `test_fulltext_pdf_creates_one_ingest_job` with actual PostgreSQL/MinIO and the parser: retrieval completes as `downloaded`, original bytes match, acquisition provenance is stored, ingest reaches ready, and paper has one current document. Run ingestion explicitly in repository tests with dispatchers stopped.
- [ ] Implement bounded discovery/candidate iteration and default-worker dispatch for `fulltext`; no local-model admission or model download. Persist each candidate outcome with the current fence; stop at first successful PDF. On overall failure, persist safe reason/error code and clear the lease; no invalid Document is created for authentication/HTML failure.
- [ ] Add/run reds for OA preference/fallback, a failed discovery with no stored candidates, overall reason precedence, and rate-limit retry time. A denied candidate followed by a valid repository copy must succeed; a mixed failure list retains all attempts in order.
- [ ] Add/run `test_old_uuid_replays_denial_new_uuid_succeeds`, `test_duplicate_delivery_has_one_document_and_ingest`, `test_lost_lease_cannot_attach`, `test_manual_upload_supersedes_download`, `test_existing_ready_pdf_skips_network`, `test_crash_after_attachment_reuses_checkpoint`, `test_storage_failure_can_recover`, and `test_exhausted_recovery_stops_polling`. Assert actual database rows/MinIO bytes/current document and immutable historical chat/summary document IDs. Guard the document-registration phase as well as terminal writes; checking only completion is insufficient.
- [ ] Implement stable attachment UUID/checkpoints before nontransactional storage work. Persist accepted references while the job is still owned. Recovery reconciles those references before fetching; existing storage-failure grace/recovery handles interrupted object writes. If a document bound to the stable UUID exists after a crash but accepted references were not checkpointed, reconstruct them from DocumentUploadRequest/Document under lock. Never redownload when an intact recorded object/ingest handoff already exists.
- [ ] Propagate ownership loss to fetch cancellation/stream cleanup through the existing heartbeat mechanism, extending the fulltext actor path only. Other worker recovery semantics remain intact. Infrastructure exceptions still use bounded durable retry; explicit access/HTTP outcomes finish this attempt without a denial retry loop.
- [ ] Run `ara019_test run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest tests/test_fulltext_jobs.py tests/test_fulltext_integration.py tests/test_research_integration.py tests/test_integration.py -q`, relevant local-model regressions, refactor, and commit `feat(fulltext): hand durable retrieval into fenced PDF ingestion (ARA-019)`.

## Task 5: Deterministic browser fixtures and UI acceptance reds

**Files:** Modify tests/fixtures/server.py/test_server.py; create tests/fixtures/fulltext_runtime.py, tests/fixtures/fulltext_resources.py, tests/fixtures/test_fulltext_server.py, src/frontend/e2e/fulltext.spec.ts. Modify src/backend/app/main.py for a general resource-factory injection seam and src/backend/tests/test_foundation.py for its lifecycle test. Fixture-only logic remains outside app code.

**Interfaces:** General `create_app(settings: Settings | None = None, *, resource_factory: Callable[[Settings], Resources] = Resources) -> FastAPI` constructs lifespan resources; production default remains Resources. Fixture resource factory injects a downloader which talks only to `http://external-fixtures:8080`, accepting only fixture IDs/paths. The fixture worker entrypoint installs the same resource factory before invoking Dramatiq's default worker. Test control routes change only a named fixture case's availability; production exposes no such routes.

- [ ] Write/run tests for fixture PDF bytes, open/publisher/no-link metadata, 200 HTML, 403, 429, unsafe redirect, and denial-then-PDF state transition before implementing fixture endpoints. Use distinct paper IDs/DOIs per case so existing research/chat specs are not polluted. Keep control endpoints confined to the fixture server. Run `python3 -m unittest discover -s tests/fixtures -v` for the standard-library server tests; generate PDF bytes with the existing locked PyMuPDF fixture helper inside the backend environment when needed.
- [ ] Add/run a failing lifecycle test for `resource_factory` invocation before adding the general seam. Configure the browser-only ignored override to launch fixture API/default worker with these factories; model-worker/runtime remain the existing deterministic fixtures. Document that browser fixtures test workflow behavior, while Task 3 exercises the production safety transport.
- [ ] Write Playwright Given/When/Then journeys before Task 6 adds the UI: both providers save/Get PDF/read; S2 no-open-link discovers a DOI copy; denial survives refresh then a fresh retry succeeds after fixture access changes; HTML keeps analysis blocked and browser/upload fallback available. Original manual upload/summary/chat/citation journeys remain in their existing specs. Run each intended missing-UI assertion red before its corresponding UI implementation.
- [ ] Start only this stack with `ara019_browser up --build -d --wait`. From `src/frontend`, run `npm ci`, install the locked Chromium runner if absent, and run `E2E_BASE_URL=http://127.0.0.1:5181 npx playwright test e2e/fulltext.spec.ts`. Use host Playwright so both the browser base URL and Origin match 5181. Record that Get PDF/access controls are absent; service readiness, fixture routing, missing browser binaries, and incorrect selectors are harness problems, not feature reds.
- [ ] Commit tested fixture behavior and the deliberately red browser acceptance tests as `test(fulltext): define retrieval and access browser journeys (ARA-019)`. Explicitly label the pending UI assertions in the journal; this intermediate checkpoint is not a green branch or a completion claim. Task 6 makes those journeys green before final checks.

## Task 6: Access information and retry controls in the existing UI

**Files:** Create hooks/queries/fulltext.ts, features/workspace/FullTextAccess.tsx and their RTL tests; modify features/workspace/ReaderGate.tsx, DetailsPanel.tsx, workspace.test.tsx, features/research/PaperCard.tsx and search tests, features/activity/ActivityPage.tsx and tests, components/jobs/job-labels.ts and tests, hooks/queries/papers.ts, lib/query-keys.ts, api/types.ts/generated.ts. Paths under `src/frontend/src` unless stated.

**Interfaces:** `useFullText(paperId: string | undefined)` returns typed FullTextStatus and polls every 1500ms only while retrieval/ingestion is active; `useRetrieveFullText(paperId: string)` accepts `{request_id: string}`. `FullTextAccess({paper, onAccepted}: {paper: Paper; onAccepted?: (accepted: UploadAccepted) => void})` renders discovery/access/progress controls and hands successful ingestion references to the existing gate. Use generated schema aliases; never hand-maintain contract fields.

- [ ] Regenerate OpenAPI types from this branch's isolated API after backend contracts settle. Regeneration is a derived artifact; verify its byte comparison rather than writing a test that mirrors generated text.
- [ ] Write/run `Given an open-copy report, When Get PDF is clicked, Then one UUID request is posted and progress appears`; `Given unknown availability with a DOI, Then Find PDF and Upload PDF are available`; and `Given a denied attempt, Then the observed reason and network guidance appear`. Assertions target role/text/request body; do not rely only on snapshots or mocks being called.
- [ ] Run `ara019_test run --rm --no-deps frontend npm test -- src/features/workspace/FullTextAccess.test.tsx src/hooks/queries/fulltext.test.tsx` and observe missing UI behavior before implementation.
- [ ] Implement query keys/hooks/component using existing controls and inline errors. Restore active/last attempt from server data on remount. A click creates one UUID; repeat transport submission reuses it, a later deliberate retry creates a new one. Refetch on focus reads state but does not POST.
- [ ] Repeat red/green for `denial → retry → processing → ready`, early retrieval completion while extraction is pending, reload/navigation with active work, generic 403/HTML without a paywall label, 429 timing, discovery failure with stored sources, and a last failed attempt beside an already-ready manually attached PDF. Exact copy comes from the spec; current document readiness always wins.
- [ ] Integrate into ReaderGate and Details with one shared component. Search results show only provider-reported access hints, never contact PDF hosts. Tests preserve save cache behavior and reject unsafe source links. Known version/license/source appears in PDF details; older records render without it.
- [ ] Add Activity label/stage/paper-link tests before changes. Fulltext failures offer a paper link and **Retry download** using a fresh fulltext request; ingestion retains **Retry processing**; summary/local-model controls keep their existing meaning. Incorporate upstream ARA-053 labels rather than reverting them. Retain canary filtering.
- [ ] Verify keyboard actions, stage live-region announcements without repeated polling chatter, disabled pending/retry timing, safe new-tab links, and wrapping at 390px with RTL plus Task 5's browser assertions. Preserve manual upload for every failed/unsupported retrieval outcome.
- [ ] Run full `npm run check` and `npm run build` in this isolated frontend and make Task 5's browser journeys green. Refactor, record actual red/green results, and commit `feat(ui): show PDF access and institutional retry actions (ARA-019)`.

## Task 7: Restart/recovery and final integration

**Files:** Extend Task 5's browser assertions with restart/recovery checks; update README.md, docs/api-contract.md, ARA-019, and docs/agent-development-log.md with verified evidence. Every defect found here gets a failing regression before its fix.

**Interfaces:** Consumes the complete API/UI and fixture resource factories from Tasks 1–6. Produces recorded acceptance evidence, regenerated contract, and a verified feature branch; no main merge or push.

- [ ] Start only this fixture stack with `ara019_browser up --build -d --wait`. From `src/frontend`, run `E2E_BASE_URL=http://127.0.0.1:5181 npx playwright test`. Observe success, refresh/remount, mobile links, and retrieval→ingestion→reader handoff. Screenshot/trace artifacts stay ignored.
- [ ] Restart this fixture project's API/worker and PostgreSQL/MinIO without deleting volumes; assert saved metadata, attempt reasons, originals, and analysis/citation history survive. Kill/recover an active retrieval in this project and verify fencing/deduplication. A reset, if needed, may remove only `ara019-e2e` volumes after verifying the exact project name.
- [ ] Incorporate the latest committed `feat/managed-ollama` changes without touching its worktree; resolve shared docs/Activity/contracts and recheck one Alembic head. Regenerate OpenAPI types only after integration.
- [ ] Final checks: full isolated backend `pytest` and Ruff; frontend `npm run check`/build; full Playwright suite; infrastructure/fixture-server unittest discovery; generated contract byte comparison; Compose config validation; migration and restart observations. Repeat only checks affected by subsequent fixes. Do not treat the main branch's historical counts or another agent's report as this branch's fresh output.
- [ ] A live public-PDF fetch may be recorded separately using a known provider result and this branch. A university-network smoke requires an actual available subscription/network; otherwise leave that claim unverified and record the deterministic denial→success evidence accurately. No routine paid generation, runtime rebuild, or model-weight downloads.
- [ ] Update ARA-019 to completed only when acceptance and actual checks pass; update API/setup docs with allowed-host configuration, access wording, backend-network location, browser login fallback, and observed limitations. Log genuine prompts/failures/corrections and commit `test(fulltext): verify access retries and paper workflows (ARA-019)` followed by a focused docs commit if needed. Keep main and archived branches intact; no push.

## Plan self-review and execution handoff

Coverage: metadata/discovery (Task 1), durable state/API/migration (Task 2), download bounds/network safety (Task 3), attachment/recovery/version provenance (Task 4), browser fixtures/acceptance reds (Task 5), access/progress/actions (Task 6), restart/upstream integration (Task 7). All nine acceptance criteria map to these tasks. Each Review Focus item has named tests in its owning task. Public signatures/types agree across task boundaries.

Execution must begin with user review of this plan and spec. Native execution uses `superpowers:executing-plans` and keeps one owner of shared interfaces; delegated execution is available if explicitly chosen. Implementation has not started; all checklist boxes remain open. The plan describes expected assertions and commands, not tests already executed.
