# HW2 initial test evaluation

Measured on November 3, 2026, against application and test commit
`b40405b397fec8405223fe6135f9f659acf91aaf`. This evaluates the existing
agent-generated HW1 suite before HW2 improvement rounds. No application code,
tests, dependency manifests or lockfiles were changed for the measurement.

This existing suite serves as HW2's initial suite instead of a newly generated one.
The instructor was told that the first homework used TDD and so already had a test
suite, and confirmed that this is acceptable. The journal records test-first work
and also some labelled test-after cases (ARA-033, for example), so the suite should
not be described as uniformly test-first.

## Coverage and execution

Verified initial baseline, including the real-service backend integration tests:

| Suite | Executable lines | Branches | Execution |
| --- | --- | --- | --- |
| Backend: pytest with PostgreSQL, Redis and MinIO | 8,584 / 9,050 (94.85%) | 2,011 / 2,378 (84.57%) | 1,228 passed; no skips; 296.46 s |
| Frontend: Vitest/React Testing Library | 3,184 / 3,322 (95.84%) | 3,474 / 3,968 (87.55%) | 766 tests in 94 files passed; 42.25 s |

Frontend statement coverage is 93.75% (4,041/4,310); function coverage is 91.43%
(1,335/1,460). Coverage includes 184 source files, including files that no test
imports. The include is `src/**/*.{ts,tsx}`; exclusions are test/spec files,
`src/test/**`, declarations and the generated OpenAPI `src/api/generated.ts`.
Hand-written UI primitives remain included. Vitest and its V8 provider are both
5.0.3. The application dependencies come from `npm ci` using the committed lockfile;
the coverage provider is installed separately and linked into `node_modules`.

Backend coverage uses Coverage.py 7.17.1, with `source = app`, branch measurement,
the C tracer, and thread/greenlet/multiprocessing/subprocess collection. Its 94 source
files include models, schemas, routes, repositories, services, integrations, RAG code
and job code. Tests and Alembic
migrations are outside this denominator.

Infrastructure checks passed separately: 46 tests in 9.878 s. They are not part
of either application's coverage denominator. Playwright journeys were not run
or instrumented; these percentages describe pytest and Vitest execution, not
browser or live-provider verification. No cross-language coverage average is used.

## Important uncovered paths

Backend candidates, based on the final report and source inspection:

| Source under `src/backend/` | Line coverage | Branch coverage | Uncovered examples |
| --- | --- | --- | --- |
| `app/integrations/public_http.py` | 87.34% | 64.29% | Several unsafe URL and disallowed destination rejection paths |
| `app/jobs/actors.py` | 81.19% | 65.62% | Some ingest/summary dispatch and cancellation paths in the actor wrapper |
| `app/integrations/academic.py` | 84.66% | 79.49% | Malformed provider responses and lookup error/fallback handling |
| `app/services/fulltext.py` | 88.03% | 74.00% | Some lost-lease, superseded-attachment and deletion-during-retrieval handling |
| `app/services/metadata.py` | 92.33% | 84.09% | Storage failures while re-reading a PDF; adopting a DOI or authors from a re-read PDF; a job lost or paper deleted during re-read; lookup timeout |
| `app/core/storage_init.py` | 50.00% | 50.00% | Bucket-creation race and error handling; the `main()` entry point that initializes the private bucket |

The experimental model actors are also lower (64.00% lines, 25.00% branches),
and remain included in the denominator. Open models remain frozen; these results
are not authorization to extend that feature.

Frontend candidates:

| Source | Line coverage | Branch coverage | Uncovered examples |
| --- | --- | --- | --- |
| `src/frontend/src/components/upload/UploadDropzone.tsx` | 80.64% | 82.50% | Secondary picker/retry callbacks; drag-over and drag-leave handlers; empty selection |
| `src/frontend/src/features/workspace/PaperWorkspacePage.tsx` | 88.88% | 75.00% | Closing an active reader tab and choosing its replacement; expanding the reader |
| `src/frontend/src/features/workspace/PdfViewer.tsx` | 96.28% | 84.47% | IntersectionObserver callback that adds/removes nearby rendered pages |
| `src/frontend/src/features/workspace/PdfMenu.tsx` | 92.68% | 74.64% | Loading/unavailable PDF facts and some replacement/removal dialog callbacks |

These paths were not exercised by this run. Some may be exercised by browser
journeys, which are outside this measurement.

## Sampled test correctness

The existing suite contains behavioral assertions. Examples inspected:

- `tests/test_ai.py` checks that invented citation IDs are rejected and valid
  citations preserve the page and excerpt. Its fixture adapter calls the real
  `app.rag.citations.passage_citations` validator.
- `tests/test_chat_papers_integration.py` checks pinned PDF membership, refusal
  status codes, unchanged database state after invalid input, and idempotent adds.
- `SummaryCard.coverage.test.tsx` checks that two clicks result in exactly one
  paid summary request, and checks recovery from an inline loading error.

This was a sample review, not a complete correctness audit. Two concrete concerns
deserve evaluation in the improvement rounds:

1. `src/frontend/src/test/fetch-routes.ts` returns a successful empty collection
   for every unmatched mocked request. That can conceal an unexpected API call or
   an incomplete fixture unless a test explicitly checks the requests.
2. `PdfViewer.test.tsx` substitutes a mock for `react-pdf`. Its assertions check
   the application's highlighting logic, but do not establish real PDF rendering,
   browser layout or scrolling behavior.

## Failures and fault detection

The first host backend run had 627 passes, 600 skips and one failure:
`test_retrieval_dependencies_import_without_network`. The host lacked the
`cl100k_base` tokenizer cache, while the Dockerfile already preloads it. Running
the Dockerfile's tokenizer setup on the host resolved the failure without code
or test edits. The rerun had 628 passes and 600 skips in 65.89 s.

That partial run covered 4,803/9,050 lines (53.07%) and 730/2,378 branches
(30.70%). It predates the tracing corrections below and is retained as diagnostic
evidence, not a comparable full backend baseline.

The first infrastructure run had two class-setup errors while Docker was stopped;
after Docker started, all 46 tests passed. Neither environment failure establishes
an application defect. A passing suite does not establish that no bugs exist, and
no new mutation experiment has been performed in this baseline evaluation.

An initial full instrumented run passed all 1,228 tests in 277.27 s, but its
coverage data was invalid: the configuration omitted SQLAlchemy's greenlet
concurrency. It marked executed lines after database awaits as missing. A focused
run of the eight existing upload-match integration cases with greenlet tracing
covered 122/127 lines in `services/upload_match.py`, while the misconfigured full
run recorded only 107/127. This controlled check confirmed undercounting without
changing tests or source. The initial report is preserved as
`backend-without-greenlet.json`; it must not be used as the HW2 baseline.
[Coverage.py's configuration reference](https://coverage.readthedocs.io/en/latest/config.html#run-concurrency)
requires explicitly naming greenlet when the application uses it.

The greenlet-configured full run also passed all 1,228 tests (304.98 s), but its
child-process coverage was incomplete. A subprocess probe showed the coverage
startup `.pth` file could not import `greenlet` before uv exposed application
dependencies. Installing the lockfile's exact greenlet version, 3.5.6, in the
temporary coverage overlay fixed startup: the child reported an active tracer
and empty stderr. That incomplete report is preserved as
`backend-without-child-bootstrap.json`. Probe data is isolated and excluded from
all test coverage. The final run uses both corrected concurrency and the verified
child bootstrap.

The final complete run passed 1,228 tests without skips in 296.46 s and combined
13 distinct process data sets (35 duplicate data files skipped). The developer
reload wrapper now records 47/61 lines, and the PDF parser records 203/219 lines,
confirming that child execution is represented. Overall backend coverage is
8,584/9,050 lines (94.85%) and 2,011/2,378 branches (84.57%). Coverage.py's combined
line-and-branch percentage is 92.71%; that is a different metric from line coverage.
No application bugs were detected in the final measured suites. A complete
correctness audit and a fresh fault-detection experiment remain separate work.

## Problems to carry into the homework report

| Problem | Evidence and resolution | Classification |
| --- | --- | --- |
| OrbStack could not start | `orbctl start` and an escalated retry both reported `missing TCC permission for data storage directory: permission denied`. The user opened OrbStack; Docker then responded. | Environment; not an application bug |
| Host tokenizer cache was incomplete | First host run: 627 passed, 600 skipped, one failure. Preloaded both encodings exactly as the Dockerfile does; unchanged suite then had 628 passes and 600 skips. | Host setup differs from the supported container environment |
| Infrastructure checks needed Docker | Two Caddy test classes failed during setup while Docker was unavailable; unchanged rerun after startup passed all 46 tests. | Environment; not failed product assertions |
| Installing temporary frontend coverage tooling re-resolved dependencies | Restored application dependencies with `npm ci` before measuring; retained the provider in a separate tools tree. Moving that tree outside a directory named `node_modules` initially caused `Cannot find package 'std-env'`; placing it under `tools/node_modules` fixed resolution. | Instrumentation setup; no measured test run used the re-resolved application dependencies |
| Child-process tracing could not bootstrap | The temporary uv overlay exposed coverage before greenlet. A direct child probe reproduced the startup import error; adding the lockfile’s greenlet version to the tooling overlay gave an active child tracer and empty stderr. The full measurement was rerun from a clean data prefix. | Incomplete measurement, not missing tests |
| Backend tracing omitted greenlets | First full run passed 1,228 tests but undercounted executed database code. Eight existing upload-match cases with the corrected tracer covered more service lines than that full report. Full coverage was rerun with explicit thread/greenlet/multiprocessing support and a separate data file. | Invalid measurement, not an application bug or a test improvement |

The development journal records the prompts and decisions. Original logs and the
superseded coverage data are retained locally; the corrections must not be
presented as newly generated tests or as bugs found in the application.

## Evidence and reproduction

Raw logs, JSON and HTML reports are stored locally under
`docs/evidence/generated/hw2-baseline/`, which is ignored by Git. Important files:

- `frontend.log`, `frontend/coverage-summary.json`, `frontend/index.html`
- `backend-unit.log`, `backend-unit-final.log`, `backend-unit.json`
- `backend-setup.log`, `backend-full.log`, `backend-full.json`, `backend-html/index.html`
- `infrastructure.log`, `infrastructure-docker.log`
- `child-bootstrap-failure.log`, `child-bootstrap-fixed.log`
- `backend-without-greenlet.json`, `backend-without-child-bootstrap.json` (superseded)

The measurements use the isolated `ara-hw2-test` Compose project. Its setup follows
the commands printed by:

```bash
python3 scripts/bootstrap.py
python3 scripts/test-stack.py test --project-name ara-hw2-test --dry-run
```

The final measurement replaces the last pytest step with `uv run --frozen --with coverage==7.17.1 --with greenlet==3.5.6 python -m coverage run
--rcfile=/coverage/backend-docker.coveragerc -m pytest -q`, with `ARA_INTEGRATION=1`
and the evidence directory mounted at `/coverage`. Its runner,
`measure-backend-final.py`, did not repeat the setup and Ruff steps. It reused the
stack prepared by the first full run (`measure-backend.py`), whose Ruff step reported
`All checks passed!` (`backend-without-greenlet-setup.log`). The source did not
change between those runs. To reproduce from a new stack, run every printed step
except the last, then the instrumented command. The configuration is:

```ini
[run]
branch = True
core = ctrace
source = app
data_file = /coverage/.coverage.backend-final
parallel = True
concurrency = multiprocessing,greenlet,thread
patch = subprocess

[report]
precision = 2
show_missing = True
```

After pytest, the same instrumented container command runs `coverage combine
--keep`, `coverage json`, `coverage html` and `coverage report`, with that rcfile.
Line and branch percentages are calculated separately from the JSON counts;
Coverage.py's default report percentage combines line and branch opportunities.

To reproduce the frontend tooling without re-resolving the application dependencies,
run this from `src/frontend` in an isolated worktree:

```bash
npm ci --ignore-scripts
ara_coverage_tools=$(mktemp -d)
npm install --prefix "$ara_coverage_tools" --ignore-scripts --save-exact \
  @vitest/coverage-v8@5.0.3 vitest@5.0.3
ln -s "$ara_coverage_tools/node_modules/@vitest/coverage-v8" \
  node_modules/@vitest/coverage-v8
```

The frontend measurement invocation, from `src/frontend`, was:

```bash
npx --no-install vitest run --coverage --coverage.provider=v8 \
  --coverage.include='src/**/*.{ts,tsx}' \
  --coverage.exclude='src/**/*.{test,spec}.{ts,tsx}' \
  --coverage.exclude='src/test/**' \
  --coverage.exclude='src/**/*.d.ts' \
  --coverage.exclude='src/api/generated.ts' \
  --coverage.reportsDirectory=../../docs/evidence/generated/hw2-baseline/frontend \
  --coverage.reporter=text --coverage.reporter=json \
  --coverage.reporter=json-summary --coverage.reporter=html \
  --coverage.reportOnFailure
```

## Independent reproduction

On November 8, 2026, Claude Code followed these instructions from a clean
`git archive` export of `b40405b`, in a separate `ara-hw2-audit-test` Compose project
that was removed afterwards. This run included the setup and Ruff steps.

| Check | Result | Compared with the baseline |
| --- | --- | --- |
| Ruff | `All checks passed!` | Same result as the first full run |
| Backend | 1,228 passed in 297.31 s; 8,584/9,050 lines; 2,011/2,378 branches | Covered lines and branches identical in all 94 files; again combined 13 data sets and skipped 35 |
| Frontend | 766 tests in 94 files passed in 29.61 s; 3,184/3,322 lines; 3,474/3,968 branches | Lines and branches identical |
| Frontend statements and functions | 4,039/4,310 (93.71%) and 1,333/1,460 (91.30%) | Two fewer of each; the cause was not investigated |

Use lines and branches when comparing later rounds. The logs and reports are under
the ignored `docs/evidence/generated/hw2-test-review/verification/`.

Keep the initial reports and source scope fixed when comparing later rounds.
[The test review](hw2-test-review.md) evaluates correctness and fault detection.
HW2 still requires at least two rounds of agent-guided test improvement; this
measurement does not count as an improvement round.
