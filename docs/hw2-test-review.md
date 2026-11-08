# HW2 initial suite: executability and test quality

Reviewed November 8, 2026, at `a8bfb9c`. Application and test sources are identical
to the `b40405b` source used for the [coverage baseline](hw2-baseline.md).
This records evaluation of the existing suite; no application or test improvements
were made. The examples below are selected findings, not an assertion that every
test has been independently audited.

## Overall impression

The suite is executable with the documented dependencies and services. It contains
substantial assertions about returned data, persisted state, citations, error
handling and provider-call counts. Its strongest cases protect paper identity,
document isolation and the rule that retrying a request must not repeat paid work.

Assertion strength is uneven at mocked boundaries. An invalid success fixture can
pass when the test checks only that a request started. Other tests claim to check
two behaviors while exercising only one. The initial coverage figures are strong,
but the controlled checks below show why executed lines alone do not establish
fault detection: three injected faults left all 766 frontend tests passing. No
existing application defect was established in this review.

## 1. Are the tests executable? Three examples

| Example | Fresh execution evidence | What it establishes |
| --- | --- | --- |
| Backend pytest, including real PostgreSQL, Redis and MinIO | **1,228 passed; no skips; 264.99 s.** Ran with `ARA_INTEGRATION=1` through the existing isolated `ara-hw2-test` Compose project. | Unit and integration cases execute with the required services; this is not a host run that silently skips integration tests. |
| Frontend TypeScript, ESLint and Vitest | `npm ci --ignore-scripts`, then `npm run check`: typecheck and lint passed; **766 tests in 94 files passed in 34.11 s**. | The committed dependency set supports type checking and executable component/unit tests. |
| Playwright Chromium | **27 passed in 3.5 minutes**, across nine files, against a fresh `ara-hw2-review-e2e` fixture stack. | The full browser workflows execute through React, the API, worker jobs, storage and deterministic provider fixtures. |

Infrastructure acceptance checks also passed: **46 tests in 7.701 s**.

The first frontend attempt used stale host `node_modules` and had 58 test files
fail during import, with 275 tests passing. Missing Tiptap packages caused these
failures before assertions ran. Installing the committed lockfile in the review
worktree resolved the setup problem. This must not be reported as 58 product bugs.

## 2. Do assertions check intended behavior? Three strong examples

1. **A saved paper remains one paper, even under concurrent saves.**
   `src/backend/tests/test_research_integration.py:11`,
   `test_concurrent_canonical_save_deduplicates_doi_and_preserves_manual_overrides`,
   uses independent database sessions and requires both saves to return the same
   paper ID. It then checks that enrichment preserves manually corrected title
   and authors and retains both provider sources. These assertions directly check
   library identity and preservation of user edits. The browser complement,
   `src/frontend/e2e/research.spec.ts:27`, saves through the UI, reloads, and checks
   that the same DOI from the other provider still produces one library row.

2. **A summary receives paper content and stores document citations.**
   `src/backend/tests/test_ai_integration.py:826`,
   `test_given_summary_fixture_when_generated_then_domain_and_job_complete_together`,
   checks the completed job and stored summary, three citations to the expected
   document, and actual extracted text (`"87 percent"` and `"Conclusion"`) in the
   provider input. Running the same job again must leave the provider-call count
   at one. This addresses content-based summarization and duplicate execution.
   The fixture proves prompt construction and persistence, not the quality of a
   real model's summary.

3. **Replaying a question does not repeat retrieval or paid generation.**
   `src/backend/tests/test_chat_retrieval_integration.py:195`,
   `test_given_replayed_request_when_streaming_then_nothing_is_retrieved_or_generated`,
   sends the same UUID twice, requires the same assistant-message ID and stored
   retrieval information, and checks retrieval, generation and embedding counts
   are exactly `(1, 1, 1)`. A response-status-only test would not catch the same
   class of duplicate-work regression.

## 3. Incorrect fixtures or weak assertions: three examples

The first finding is a confirmed incorrect fixture. The other two concern what
the assertions prove; their intended application behavior is reasonable.

1. **The old-PDF chat test supplies an invalid completion event.**
   `src/frontend/src/features/chat/pinned-pdf.test.tsx:13` claims a conversation
   can keep taking questions after its paper loses its current PDF. Its success
   stream at line 18 ends with `message.completed: { message_id: "m2" }`, while
   `src/frontend/src/api/sse.ts:20` requires a complete message including `id`,
   role, content, state, model, effort, citations and creation time. The test
   finishes after seeing a POST; it does not require a completed new answer.

   **Verified:** the original suite passes this case. Feeding its exact events
   into production `readEvents` delivers started/delta events, then rejects the
   completion with `The response contained invalid stream data. Reload the
   conversation.` The fixture does not model a valid successful conversation.
   A corrected case needs a contract-valid completion and assertions on the
   completed answer and recovery/error state. Evidence: `invalid-sse-fixture.log`.

2. **The expansion-and-collapse test never collapses.**
   `src/frontend/src/features/summary/SummaryCard.test.tsx:83` clicks Show full
   summary once, then checks `aria-expanded="true"`. It never clicks Collapse
   summary or checks the return to the collapsed state. Its short fixture also
   does not establish actual long-text clipping.

   **Verified:** an isolated transform changed the real toggle from
   `setOpen(!open)` to `setOpen(true)`, making collapse impossible. This named
   test still passed: **1 passed, 8 filtered out**. The whole Vitest suite also
   still passed with this fault: **766 passed in 94 files**. Playwright was not
   run against it. Evidence: `probe-collapse.log`, `verification/full-collapse.log`.

3. **The browser metadata-extraction oracle starts with that metadata already saved.**
   `src/frontend/e2e/workspace.spec.ts:65` is named “metadata is extracted and the
   pages render”. It first saves the provider fixture at line 67, then checks the
   already-known title and author at lines 101–103. The fixture supplies those
   fields before the PDF upload (`tests/fixtures/server.py:41`). It does not check
   extracted year, abstract or PDF provenance, and its alternate path replaces an
   existing PDF.

   The PDF canvas/download assertions remain useful, but title/author persistence
   cannot independently establish PDF metadata extraction. Use a new PDF without
   a preexisting provider record and compare all required fields and provenance
   to an independent expected result. This is a source-based oracle finding;
   extraction was not disabled in a mutation experiment. Backend extraction
   assertions exist at `src/backend/tests/test_research_integration.py:45`.

## 4. Redundancy: two supported examples

1. **Two summary cases exercise the same processing gate.**
   `src/frontend/src/features/summary/SummaryCard.test.tsx:105` and
   `src/frontend/src/features/summary/SummaryCard.coverage.test.tsx:63` both check
   the processing explanation and absence of Generate/Attach controls. Their
   `active_document_id` fixtures differ, but the production gate returns solely
   on `document_status === "processing"` at `SummaryCard.tsx:25`. They are a
   consolidation candidate: retain both input variants through parameterization
   if that distinction is intentional. This does not justify deleting the
   processing behavior's only regression check.

2. **An assertion checks an imported fixture constant, not parser output.**
   `src/backend/tests/test_pdf_metadata.py:126` asserts
   `AUTHORS.startswith("Seunghun Han")`. `AUTHORS` is a fixture constant imported
   at line 109; the assertion does not inspect the extracted metadata. The
   preceding assertions already check the real parser's title, authors, venue
   and publication year. Remove the unnecessary assertion, retaining the useful
   extraction test.

Overlapping parser, API and browser checks are generally valuable because they
exercise different boundaries. Repeated setup and similar citation checks do not
by themselves establish redundant test cases. No wholesale deletion of a testing
layer is supported by this review.

## 5. Missing cases: three concrete examples

1. **Send a search continuation through the backend provider client.**
   `src/backend/tests/test_research.py:24`,
   `test_search_normalizes_nullable_fields_and_paginates`, makes one search and
   checks only that `next_cursor` is non-null. It does not send that cursor back.
   The test at line 86 rejects invalid cursors, but no backend test passes a valid
   cursor to `AcademicSearch.search` and checks the outgoing OpenAlex `cursor`
   (`src/backend/app/integrations/academic.py:326`) or Semantic Scholar `offset`
   (line 319). No Playwright journey follows a continuation either.

   The frontend side is covered.
   `src/frontend/src/features/research/search-states.test.tsx:38` and line 130 press
   Load more, route the mocked request on cursor `c2`, and check that the
   second-page paper appears. Those mocks stop at the API boundary, so they do not
   exercise the translation to each provider's parameters.

   Given two fixture pages, when the returned continuation is followed, then
   assert the exact outgoing OpenAlex cursor or Semantic Scholar offset, distinct
   second-page papers, and an absent continuation at the end. This would detect
   a client that repeatedly submits the first-page cursor.

2. **Upload cancellation must abort transport, not only reset the UI.**
   `src/frontend/src/components/upload/UploadDropzone.test.tsx:93` clicks Cancel
   and verifies the picker reappears and the file name disappears. Its mocked
   upload never resolves; it does not observe transport abort or a late success
   callback. The production abort is in
   `src/frontend/src/components/upload/use-upload.ts:64`.

   **Verified:** removing that abort call in the diagnostic transform left the
   selected cancellation test green: **1 passed, 7 filtered out**. The whole
   Vitest suite also still passed: **766 passed in 94 files**. Playwright was not
   run against this fault. Given a held upload, when Cancel is pressed, then assert
   its signal/XHR is aborted and a later response cannot invoke `onAccepted`.
   Evidence: `probe-cancel.log`, `verification/full-cancel.log`.

3. **Separate deliberate summaries must use different request UUIDs.**
   `src/frontend/src/hooks/queries/summaries.ts:14` correctly creates a new UUID
   for each deliberate generation. Summary tests check UUID-shaped syntax and
   some call counts, but do not compare IDs across two deliberate generations.
   The distinction matters because backend idempotency can replay an earlier
   result for a reused UUID. Upload retries intentionally retain one UUID and
   should continue to do so.

   **Verified:** replacing the summary UUID with one fixed valid UUID left all
   **25 tests in five summary test files passing**, and the whole Vitest suite
   also still passed: **766 passed in 94 files**. Playwright was not run against
   this fault. Given an initial generation and an explicit regeneration, when both
   requests are submitted, then assert distinct IDs and verify that the second is
   a new generation. Evidence: `probe-summary-uuid.log`,
   `verification/full-requestId.log`. These are three hand-picked faults, so no
   mutation score is claimed.

## 6. Flakiness

No test failed intermittently in any recorded run, and no retries were involved.
These are the runs that happened during evaluation, not a dedicated repeated-run
experiment, so they show no observed flakiness rather than proving there is none.

| Layer | Full runs on unchanged tests | Result | Duration range |
| --- | --- | --- | --- |
| Backend pytest with real services | 5 (three coverage measurements, this review, independent reproduction) | 1,228 passed in every run, no skips | 264.99–304.98 s |
| Frontend Vitest | 3 (baseline, this review, independent reproduction) | 766 passed in every run | 29.61–42.25 s |
| Infrastructure | 3 | 46 passed in every run | 7.701–9.878 s |
| Playwright Chromium | 1 | 27 passed, with `retries: 0` in `playwright.config.ts` | 3.5 min |

The Playwright result is one run, so it gives no evidence about repeatability.
Setup failures on a stale host install or with Docker stopped are excluded because
they happened before assertions ran, and they are recorded separately.

Two risks come from reading the source; neither failed in these runs.

1. **A browser test depends on what ran before it.** `src/frontend/e2e/workspace.spec.ts:77`
   notes that earlier browser tests may already have attached `research.pdf`, and
   E2E-03 takes a different path depending on the paper's status. The same test can
   therefore exercise first upload or PDF replacement, depending on run order.
2. **Some backend tests wait on real time.** `src/backend/tests/test_worker_reload.py`,
   `test_retrieval_slot_integration.py` and `test_integration.py` use fixed sleeps of
   up to 0.5 s, which could become timing-sensitive on a slower machine.

## Method, evidence and limits

Three independent read-only reviews examined backend, frontend and browser
requirements and tests. The lead checked selected findings against source and
fresh execution, and ran the parser diagnostic and three in-memory fault checks.
The faults were injected only by an ignored Vite transform inheriting the real
configuration. Every probe log confirms the intended transform was applied.
Tracked source, tests, manifests and lockfiles remain unchanged.

These introduced faults are diagnostic probes, not preexisting application bugs.
They are not new or improved tests and do not count as either of HW2's required
improvement rounds. The diagnostic runs were not combined with the initial
coverage percentages. A separate clean reproduction of those percentages is
recorded in [the baseline](hw2-baseline.md#independent-reproduction).

The shared frontend `mockApi` helper returns HTTP 200 with `{ items: [] }` for
unmatched requests (`src/frontend/src/test/fetch-routes.ts:27`). Reviewers therefore
checked whether each selected case asserts the intended request and result.
PDF component mocks also establish highlighting behavior against simulated text
layers, rather than proving real pdf.js loading; browser canvas checks provide
complementary evidence. Provider fixtures establish deterministic orchestration,
not live-provider access or factual entailment of real LLM output.

Raw local evidence is ignored by Git under
`docs/evidence/generated/hw2-test-review/`:

- `backend.log`, `frontend.log`, `frontend-install.log`, `infrastructure.log`
- `frontend-stale-host.log` (setup failure, retained)
- `playwright-list.log`, `browser-setup.log`, `playwright-install.log`, `playwright.log`, `playwright-report/index.html`
- `invalid-sse-fixture.log`
- `audit.vite.config.mts`, `probe-collapse.log`, `probe-cancel.log`, `probe-summary-uuid.log`
- `probe-config-error.log` (the initial diagnostic config needed `.mts` outside the ESM package)
- `verification/`: the independent reproduction (`reproduce.py`, `frontend.log`, `backend-setup.log`, `backend-full.log`, `backend-report.log`, `backend-full.json`, `frontend-coverage-summary.json`) and the whole-suite fault runs (`full-collapse.log`, `full-cancel.log`, `full-requestId.log`)

The backend command, from the review worktree, was:

```bash
docker compose -p ara-hw2-test -f compose.yaml -f compose.test.yaml \
  run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest -q
```

The frontend command was `npm run check` after installing the committed lockfile.
Browser execution uses the documented three Compose files, with isolated project
`ara-hw2-review-e2e`, generated research/second PDFs under
`/tmp/ara-hw2-review-fixtures/`, and the matching `E2E_PDF_PATH` and
`E2E_SECOND_PDF_PATH` passed to Playwright.

For example, the isolated collapse probe was:

```bash
HW2_AUDIT_MUTATION=collapse npx --no-install vitest run \
  src/features/summary/SummaryCard.test.tsx -t 'When expanded and collapsed' \
  --config ../../docs/evidence/generated/hw2-test-review/audit.vite.config.mts
```

The report can state: **the initial suite executes and includes meaningful
behavioral assertions, but some mocked success paths, test descriptions and
missing boundary checks permit false confidence.** The examples identify specific
targets for later improvement while preserving the initial baseline.
