# HW2 improvement round 2

Measured November 8, 2026, on branch `feat/ara-117-hw2-round1-tests`. Tracked as
[ARA-122](../issue_tracker/ARA-122.json). Round 2 changed test code and issue records
only: the application source is identical to the `b40405b` source used for the
[coverage baseline](hw2-baseline.md). [Round 1](hw2-round-1.md) came first. The tests
were frozen before the final measurement and the held-out faults below.

## Strategy

Round 1 gave the agent the application's requirements. Round 2 started from execution
feedback instead:

> Round 2. Round 1 improved assertions but coverage barely moved, so this round starts
> from the coverage report. Don't change anything until I say go.

The agent ranked the uncovered lines by what they protect. The user then added expected
behavior for jobs, providers, the upload zone and reader tabs, and pointed at something
the coverage report could not show:

> mockApi answers every unmatched request with an empty list, across 55 test files, so
> a wrong API call can pass silently. I want an unexpected call to fail its test.

That was measured before anything changed. Of the 449 tests using `mockApi`, 363 relied
on the fallback, and 59% of mocked calls landed on it. No test called a route that does
not exist, but 12 routes answered `{items: []}` where the real API returns one object.
Each route was then made to fail in turn, to separate background noise from tests that
depended on the fallback.

## Comparison

| Measure | Initial suite | Round 1 | Now |
| --- | --- | --- | --- |
| Ruff | Passed | Passed | Passed |
| Backend tests | 1,228 passed | 1,281 passed, 3 expected failures | 1,374 passed, 21 expected failures |
| Backend lines | 8,584 / 9,050 (94.85%) | 8,611 / 9,050 (95.15%) | 8,658 / 9,050 (95.67%) |
| Backend branches | 2,011 / 2,378 (84.57%) | 2,028 / 2,378 (85.28%) | 2,054 / 2,378 (86.38%) |
| Backend run time | 296.46 s | 317.78 s | 331.50 s |
| Frontend tests | 766 | 772 | 803 |
| Frontend lines | 3,184 / 3,322 (95.84%) | 3,186 / 3,322 (95.90%) | 3,189 / 3,323 (95.96%) |
| Frontend branches | 3,474 / 3,968 (87.55%) | 3,474 / 3,968 (87.55%) | 3,485 / 3,968 (87.82%) |
| Playwright | 27 passed (from ARA-116) | 27 passed | 29 passed, twice |
| Infrastructure | 46 OK | 46 OK | 46 OK |
| Fault: `setOpen(true)`, whole Vitest | Missed | Caught (1 test) | Caught (1 test) |
| Fault: upload abort removed, whole Vitest | Missed | Caught (4 tests) | Caught (4 tests) |
| Fault: fixed summary `request_id`, whole Vitest | Missed | Caught (1 test) | Caught (1 test) |
| Invalid chat fixture | Present, test passed | Replaced; old one fails 2 tests | Replaced; old one fails 2 tests |
| Held-out faults caught (of 9) | 7 | Not measured | 7 |
| Bugs detected | 0 | 2, plus 1 unverified | 4 (ARA-118, 119, 120, 121) |

The backend run combined 13 data sets, as in the baseline, and skipped 43 duplicates
(35 in the baseline). The frontend denominator grew by one line because `pane-test-kit.tsx`,
a test helper outside `src/test/`, counts as source under the baseline's exclusions.

| File | Initial lines / branches | Now lines / branches |
| --- | --- | --- |
| `jobs/actors.py` | 81.19% / 65.62% | 94.06% / 87.50% |
| `services/fulltext.py` | 88.03% / 74.00% | 92.96% / 86.00% |
| `integrations/academic.py` | 84.66% / 79.49% | 97.73% / 94.87% |
| `UploadDropzone.tsx` | 80.64% / 82.50% | 83.87% / 87.50% |
| `PdfMenu.tsx` | 92.68% / 74.64% | 95.12% / 87.32% |
| `PaperWorkspacePage.tsx` | 88.88% / 75.00% | 88.88% / 76.66% |
| `PdfViewer.tsx` | 96.28% / 84.47% | 96.28% / 84.47% |

## Held-out faults

The user supplied nine faults the agent had not seen, after the tests were frozen. Each
was applied to a temporary copy of the initial tree (`b40405b`) and of the final tree,
never to the branch. Each replacement was confirmed before running, and the file was
restored and checked afterwards. Unfaulted controls passed on both copies. Backend faults
used pytest with real services and `-x`, so only the first failure is named. Frontend
faults used the whole Vitest suite.

| # | Fault | Initial tree | Final tree | Test that caught it |
| --- | --- | --- | --- | --- |
| 1 | Abstract words not sorted by position (`academic.py`) | **Missed** (1,228 passed) | **Missed** (1,374 passed) | None |
| 2 | Duplicate paper not reused (`papers.py`) | Caught | Caught | `test_concurrent_canonical_save_deduplicates_doi_and_preserves_manual_overrides` |
| 3 | PDF signature check accepts anything (`uploads.py`, 2 places) | Caught | Caught | `test_upload_rejects_invalid_signature_and_stores_scanned_failure` |
| 4 | Summary reads another document's chunks (`summarization.py`) | Caught | Caught | `test_given_local_full_paper_when_summarizing_then_every_section_is_reduced_under_context` |
| 5 | Citation document check removed (`citations.py`) | Caught | Caught | `test_given_unknown_or_foreign_unicode_source_alongside_known_when_validating_then_reject` |
| 6 | Replay check bypassed (`chat.py`) | Caught | Caught | `test_given_local_chat_when_answering_then_provenance_citations_and_uuid_replay` |
| 7 | Citation link always opens page 1 (`CitationChip.tsx`) | Caught | Caught | Two tests in `CitationChip.test.tsx` |
| 8 | Composer can submit while busy (`Composer.tsx`) | **Missed** (766 passed) | **Missed** (803 passed) | None |
| 9 | Search results deduplicated by provider only (`search.ts`) | Caught | Caught | Two tests in `search-states.test.tsx`, one in `queries.test.tsx` |

**The two rounds did not change this score: 7 of 9 on both trees.** All seven catches on
the final tree came from tests that already existed in the initial suite. Because `-x`
stops at the first failure, this does not show whether a new test would also have caught
a backend fault.

Fault 1's first run on the final tree stopped at
`test_startup_refreshes_each_existing_paper_once_and_fixes_a_junk_title`. That failure
had nothing to do with the fault (see the flake below), so it was not counted as a catch.
Rerun under the same protocol, the fault was missed.

## What did not improve or got worse

- **Held-out detection did not improve.** Seven of nine before and after, with the same
  two misses.
- **One coverage regression.** `hooks/queries/usage.ts` lost a branch (6 to 5). Its
  incomplete-reply path ran only because the old mock returned junk.
- **Coverage gains are small overall:** +0.82 points of backend lines and +0.12 of
  frontend lines against the initial suite.
- **Unchanged or nearly so:** `PdfViewer.tsx`, `core/storage_init.py` (50%), and
  `PaperWorkspacePage.tsx` lines. Its key behavior is tested in the browser, which is not
  instrumented.
- **Still uncovered:** `actors.py` 69, 104-106, 118, 120 and `fulltext.py` 73-80, 114,
  160, 228, 305-308.
- **The backend run is about 12% slower** than the initial suite.
- **Four bugs remain unfixed**, held as 21 strict expected failures.
- **Self-chosen faults overstated progress.** Every fault chosen during the round was
  caught, while the independent set scored the same as the initial suite. The self-chosen
  results show those specific faults are caught, and no mutation score is claimed.

## Flakiness

Every test passed every time in the planned repeats: Vitest 803 of 803 three times; the
backend files touched in rounds 1 and 2 (307 passed, 21 expected failures) three times;
Playwright 29 of 29 twice, each on a fresh database.

Two flakes were found outside those repeats:

- **Fixed:** `App.test.tsx` failed 1 run in 40 under heavy CPU load, sending
  `graph transformer`. Enter submits React's committed draft, and user-event's next timer
  could beat the render of the last keystroke. A real browser dropped nothing in 90
  searches, up to 20× CPU throttle, so this was treated as a test flake. After the fix it
  failed 0 of 80 runs, and a scheduler slowed by 8 ms, which had failed five tests, passed
  twice. The race remains in the application code.
- **Not fixed, because the tests are frozen:** `test_startup_refreshes_each_existing_paper_once_and_fixes_a_junk_title`
  failed once during the held-out runs. Its helper sorts jobs by `created_at`, and
  `queue_backfill` creates them in one transaction, so they tie and the order is arbitrary.
  It predates these rounds.

## Other findings

`request.is_disconnected()` never reports a disconnect under this app's HTTP middleware:
it returned `False` on all 22 calls, and removing the check at `chat.py:682` changes
nothing. This is not a billing bug. Against real uvicorn and a raw socket, the paid
provider stream still stopped, because Starlette cancels the response on disconnect. The
check is dead code. This was tested without Caddy in front.

## Bugs recorded

| Issue | Expected failures | What happens |
| --- | --- | --- |
| [ARA-118](../issue_tracker/ARA-118.json) | 2 | A printed year or abstract stays empty after the upload pipeline. |
| [ARA-119](../issue_tracker/ARA-119.json) | 1 | A client gone after sending the whole body still gets a paper added. Reproduced against the real API. |
| [ARA-120](../issue_tracker/ARA-120.json) | 1 | A non-numeric redirect port escapes `fetch`. |
| [ARA-121](../issue_tracker/ARA-121.json) | 17 | Malformed provider data crashes a search, or builds a row with no identity, an impossible year or a cursor that cannot be followed. Empty identities are stored through the real save route. |

## Known weaknesses

These are recorded and deliberately not fixed. Items 1 to 10 come from a fresh read-only
reviewer, which audited the tests changed in rounds 1 and 2. It ran nothing. The agent
confirmed items 2, 3 and 4 against the code.

| # | Type | Finding | Confidence |
| --- | --- | --- | --- |
| 1 | Wrong expectation | ARA-119's test demands server-side behavior, while the reviewer's brief said Cancel is client side. The user asked for this reproduction, so the agent would keep it. | Medium |
| 2 | Weak | `pinned-pdf.test.tsx` has no citations, so a citation check against the wrong document would pass. Its comment that the final text proves completion is untrue, because the history refetch supplies the same text. | High |
| 3 | Inconsistent | A non-string PDF link keeps its row on Semantic Scholar but is an error on OpenAlex, and tests lock in both. | Medium |
| 4 | Weak | Nothing tests that `failOnUnexpectedRequests` throws or is wired into `setup.ts`. | High |
| 5 | Weak | Expected failures in the metadata and provider tests do not pin their reason, so a different failure could stay hidden. | Medium |
| 6 | Redundant | Late-response Cancel tests add little beyond the abort check and use a fixed 30 ms wait. | High |
| 7 | Wrong fixture | The “empty last page with a cursor” docstring contradicts OpenAlex's documentation. | Medium |
| 8 | Wrong fixture | A touched route in `SummaryCard.automatic.test.tsx` returns a `FullTextStatus` shape that does not exist. | High, low impact |
| 9 | Weak | The IP-literal case in `test_public_http_policy.py` passes without the IP check, and one test name overclaims. | High, low impact |
| 10 | Redundant | The late-delivery-after-failure test overlaps two others. | Medium |
| 11 | Regression | `hooks/queries/usage.ts` lost a branch, as described above. | Measured |
| 12 | Missed fault | Abstract word order from OpenAlex (held-out fault 1). Fixtures always list positions in order. | Measured |
| 13 | Missed fault | The composer can submit while busy (held-out fault 8). | Measured |
| 14 | Flake | `test_startup_refreshes_each_existing_paper_once_and_fixes_a_junk_title`, as described above. | Measured once |

At artificial scheduler delays of 25–40 ms, a few unrelated tests also fail (dialogs,
`PdfViewer`, a toast's visibility). None have failed in normal runs.

## Limits

Coverage does not include Playwright, and no live provider or real model was used. The
late-response tests use the suite's `FetchBackedXhr`. Three repeats can show flakiness but
cannot rule it out, and the browser suite was repeated only twice. Faults made during the
round were applied in memory, or by mounting a changed copy of one file into a container.
Backend results for the held-out faults name only the first failing test.

## Reproduction

Coverage uses the configuration and commands in [the baseline](hw2-baseline.md), with
project `ara-hw2-r1-test`, the Coverage.py 7.17.1 overlay and `@vitest/coverage-v8` 5.0.3.
Playwright used `compose.e2e.yaml` with host ports 5190 and 8011, after removing that
project's database and storage volumes before each run.

Raw logs and reports are ignored by Git, under `docs/evidence/generated/hw2-final/`
(`backend-full.json`, `frontend/`, `vitest-*.json`, `backend-new-*.log`, `playwright-*.log`,
`heldout/`, `tools/`) and `docs/evidence/generated/hw2-round2/`.
