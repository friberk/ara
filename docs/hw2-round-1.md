# HW2 improvement round 1

Measured November 8, 2026, on branch `feat/ara-117-hw2-round1-tests`. Tracked as
[ARA-117](../issue_tracker/ARA-117.json). Round 1 changed test code only: the
application source is identical to the `b40405b` source used for the
[coverage baseline](hw2-baseline.md), checked with `git diff`. Both coverage
denominators are unchanged (94 backend files, 184 frontend files).

## Strategy

The agent was given the application's intended behavior in six areas and asked
which existing test claimed to check each one and whether it really did, before
any test was written:

> PDF upload: after an upload, the app must extract the title, authors,
> publication year and abstract from the PDF itself. […] For each one, tell me
> which existing test claims to check it and whether it really does. Treat the
> app's behavior as correct unless evidence says otherwise.

None of the six was fully checked. The user then ruled on how to count bugs:

> The model fallback is part of the app, so test the upload pipeline as it
> ships, with a mocked model and no provider match. Count something as an app
> bug only if a required field stays empty after that.

After the first batch, the user reviewed it and sent specific gaps: uncovered
lines in `services/metadata.py`, a test that never collapsed, an assertion on a
fixture constant, two tests of one gate, and E2E-03, which had only been renamed.
Those were fixed in a second batch, each proven against a fault.

## Comparison with the initial suite

| Measure | Initial suite | After round 1 | Change |
| --- | --- | --- | --- |
| Ruff | Passed | Passed | None |
| Backend tests (real services) | 1,228 passed | 1,281 passed, 3 strict expected failures | +53 passing, +3 expected failures |
| Backend lines | 8,584 / 9,050 (94.85%) | 8,611 / 9,050 (95.15%) | +27 lines, +0.30 points |
| Backend branches | 2,011 / 2,378 (84.57%) | 2,028 / 2,378 (85.28%) | +17 branches, +0.71 points |
| Frontend tests | 766 in 94 files | 772 in 94 files | +6 |
| Frontend lines | 3,184 / 3,322 (95.84%) | 3,186 / 3,322 (95.90%) | +2 lines, +0.06 points |
| Frontend branches | 3,474 / 3,968 (87.55%) | 3,474 / 3,968 (87.55%) | **None** |
| Playwright | 27 passed (from ARA-116; not part of the coverage baseline) | 27 passed in 3.6 min on a fresh database | Same count |
| Infrastructure | 46 OK | 46 OK | None |
| Fault: `setOpen(!open)` changed to `setOpen(true)`, whole Vitest | 766 passed, **missed** | 1 failed, 771 passed, **caught** | Now detected |
| Fault: upload abort removed, whole Vitest | 766 passed, **missed** | 4 failed, 768 passed, **caught** | Now detected |
| Fault: fixed summary `request_id`, whole Vitest | 766 passed, **missed** | 1 failed, 771 passed, **caught** | Now detected |
| Invalid chat completion fixture | Present, and its test passed | Replaced with a valid one; putting the old one back fails 2 tests | Fixed |
| Application bugs detected | 0 | 2 confirmed (ARA-118, ARA-120); 1 unverified report (ARA-119) | +2 |

## What did not improve or got worse

- **Frontend branch coverage did not change at all.** Lines rose by two. The
  frontend work strengthened assertions on code that was already executed.
- **Coverage gains are small overall.** Backend gains come mostly from
  `services/metadata.py` (+18 lines, +9 branches) and `integrations/public_http.py`
  (+7 lines, +4 branches). `jobs/development_worker.py` also gained 1 line and 2
  branches, but no round 1 test targets it, so that part is incidental.
- **Most uncovered paths from the baseline are untouched.** `jobs/actors.py`,
  `integrations/academic.py`, `services/fulltext.py`, `core/storage_init.py`,
  `UploadDropzone.tsx` (still 80.64% lines, 82.50% branches), `PaperWorkspacePage.tsx`,
  `PdfViewer.tsx` and `PdfMenu.tsx` have the same coverage as before.
- **The backend run got slower:** 296.46 s to 317.78 s.
- **Two bugs remain unfixed.** ARA-118 and ARA-120 are strict expected failures,
  so the suite passes while recording known defects. ARA-119 comes from reading
  the code and has not been reproduced.
- **One browser path was lost.** The old E2E-03 sometimes used the reader's
  “Replace PDF…” menu, depending on run order. Only `pdf-menu.test.tsx` covers that
  menu now.
- **The browser suite did not grow.** It has the same 27 journeys; only E2E-03
  became stronger.
- **Two concerns from the review stand.** `mockApi` still answers unmatched requests
  with an empty collection, and `PdfViewer.test.tsx` still mocks `react-pdf`.
- **The fault results do not generalize.** The three faults were known before the
  tests were written, and every fault was hand-picked, so no mutation score is
  claimed. They show these tests catch these faults.
- **Most new tests were not test-first.** They cover behavior that already worked
  and passed when first run. Their red step is the fault check, done afterwards.
  Only the three bug tests failed first.

## What changed

| Area | Tests now check | Faults caught (failing tests) |
| --- | --- | --- |
| PDF metadata | The shipped pipeline with a mocked model and no provider match; positive parser unit tests for abstract and year | Values not saved (4), model values not merged (1), parser abstract (4), parser year (4) |
| Stored PDF re-read | Storage failures, DOI adoption and ownership, authors, manual values, a paper deleted mid-read | 9 faults, each caught (1 to 2 tests) |
| E2E-03 | Upload of a PDF with no record; title, authors, year and abstract from the PDF, saved and on screen; provider lookup found nothing | Wrong title, authors, year, abstract from a faulted parser in the real worker (1 each) |
| Summary IDs | Two requests differ; a new ID makes a new job and a repeated ID replays | Fixed UUID (1), backend ignores the ID (1) |
| Summary card | Collapse really closes; one merged processing-gate test with both document states | `setOpen(true)` (1), gate removed (2), Attach PDF offered (2) |
| Pinned chat | Valid completion and final answer; a backend follow-up after removal or replacement | Old fixture (2), scope uses the active PDF (2) |
| Cancel upload | Abort observed and a late response ignored, on all three in-flight buttons | Abort removed (4) |
| PDF downloads | Non-default ports refused and explicit `:443` allowed | Port check removed (7) |
| Search | Exact cursor or offset through client and API; distinct second page; empty last page ends results | Cursor ignored (3), empty-page cursor (1), route drops cursor (1), query dropped (1) |

Also removed the assertion on a fixture constant at `test_pdf_metadata.py:126`; with
XMP authors broken, that test still fails at its real authors assertion. Citation
journeys now wait for the automatic summary, because they had silently depended on
the old E2E-03 running first.

## Bugs detected

| Issue | Status | What happens |
| --- | --- | --- |
| [ARA-118](../issue_tracker/ARA-118.json) | Accepted; strict expected failure (2 cases) | A printed year or abstract stays empty after the pipeline. The model is asked only when title or authors are missing, and a correct two-column abstract fails the verbatim evidence check. Each cause was confirmed by removing it in memory. |
| [ARA-120](../issue_tracker/ARA-120.json) | Accepted; strict expected failure | A redirect with a non-numeric port raises `httpx.InvalidURL` from `fetch` instead of returning `unsafe_url`. No request is sent. |
| [ARA-119](../issue_tracker/ARA-119.json) | Unverified | Cancelling after the whole body has arrived may still create the paper. Source reading only. |

## Limits

Backend and frontend coverage do not include Playwright, and no live provider or
real model was used. The late-response tests use the suite's `FetchBackedXhr`, a
model of the browser's XHR. In-memory backend parser faults cannot reach the child
process, so E2E-03's faults mount a changed parser copy in the worker instead. Those
E2E faults fail at the saved-values check, which runs before the on-screen checks.
Targeted backend fault runs were made while the tests were being written, not repeated
on the final tree; the three original faults and the invalid fixture were.

## Reproduction

Coverage uses the configuration and commands in [the baseline](hw2-baseline.md),
with project `ara-hw2-r1-test`, the Coverage.py 7.17.1 overlay and
`@vitest/coverage-v8` 5.0.3. The backend run combined the same number of data sets
as the baseline (13 combined, 35 duplicates skipped). Playwright used
`compose.e2e.yaml` with host ports 5190 and 8011, because another fixture stack held
the default ports, after removing that project's database and storage volumes.

Raw logs and reports are ignored by Git, under
`docs/evidence/generated/hw2-round1/final/`: `backend-full.log`, `backend-full.json`,
`backend-setup.log`, `frontend.log`, `frontend/`, `full-collapse.log`,
`full-cancel.log`, `full-requestId.log`, `full-oldFixture.log`, `playwright.log` and
`infrastructure.log`. The fault tools are `hw2_probe.py` and `audit.vite.config.mts`
one level up; each applies a fault in memory only.
