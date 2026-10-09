# Final application verification

Observed October 8, 2026, on macOS/M3 Pro with OrbStack ARM64. The first results below concern the earlier core application. Later sections record newer feature verification. OCR, semantic embeddings and automatic PDF downloads remain separate backlog items; local inference is now verified on its feature branch. GitHub publishing is deferred by the user; CI is prepared but has not run remotely.

## Automated checks

| Check | Actual result | Scope |
| --- | --- | --- |
| Backend, `python3 scripts/test-stack.py test` | Lead run: 57 passed in 13.70s; Ruff passed | Isolated `ara-test`, actual PostgreSQL/Redis/MinIO, real child parser/worker, external HTTP fixtures. |
| Final backend after ARA-032, isolated Compose `pytest -q` | Backend owner: 58 passed in 13.60s; full Ruff passed; lead inspected source, regression and full output | Added complete-source regression to the prior 57 tests. Zero failures/skips. Exact commands/red output preserved in [citation report](citation-review-report.md). |
| Frontend, `npm run check` | Lead: 21 tests passed; strict TypeScript and ESLint passed | Forms, states, Markdown, SSE, metadata edits/provenance and model labels. |
| Frontend, `npm run build` | Lead: passed | Main bundle 467.62 kB, deferred paper bundle 173.96 kB; no large-chunk warning. |
| Browser, `npx playwright test` | Lead final run: 6 passed in 13.3s | Both search providers; cross-provider save/dedup/refresh; upload; summary; streaming multi-turn chat/citation/history; mobile/keyboard. Real core services with synthetic external HTTP fixture responses. |
| Infrastructure unittest discovery | Lead: 4 passed | Private bootstrap/preserve-existing settings, guarded reset and nondefault budget forwarding. |
| Fixture HTTP-server unittest discovery | Lead earlier run: 3 passed | Actual search/detail/Responses JSON and delayed SSE endpoints. |
| PDF skill unittest discovery | 6 passed; locked CLI and skill validation passed | Synthetic Markdown/JSON/images/ruled tables, errors and safe output collision behavior. See [foundation evidence](verification-phase0.md). |
| Generated OpenAPI contract | Lead: generated temporary TypeScript from API8001 and byte-compared with committed source; no difference | CI includes the same contract-drift check. |
| Schema and readiness | `0003_upload_requests (head)`; API8000 and Vite proxy5173 returned200 with database/storage/Redis ok | Main development stack. |
| Compose and helper lint | `docker compose config --quiet` and Ruff passed | No resolved secret configuration was printed. |

The browser stack was also recreated from empty isolated test volumes and all six scenarios passed in 17.8s before the final display refinements. Routine repeat checks ran only after changes or to verify newly identified gaps. Test volume resets never targeted development data.

## Persistence and development workflow

The foundation run verified PostgreSQL job state, Redis AOF data and MinIO object checksums surviving ordinary shutdown/recreation. Migration/bucket-init services completed successfully; the durable canary traversed API outbox → Redis → worker → PostgreSQL. API and worker source reload were observed.

A final open-browser CSS timestamp probe emitted Vite's `/src/index.css` update. The filled search input remained intact and `performance.timeOrigin` did not change, confirming a hot update without navigation. File contents did not change for the probe. Actual paper/library/chat history also survived browser refresh.

Desktop1440 and mobile390 paper captures show recorded model labels. The mobile document measured390px wide in a390px viewport. Keyboard testing verifies the skip link. These are focused checks, not a comprehensive accessibility audit.

## Live external services

The ignored `.env` was configured locally and API/worker recreated to load it. The official OpenAI SDK successfully listed the account's models; all three requested exact IDs were present. Live generation was exercised with `gpt-5.6-luna` and low reasoning. Listing Terra/Sol does not prove generation with those two models.

The actual GUI walkthrough used live OpenAlex to find and save *Attention Is All You Need*, refreshed the library, uploaded its 15-page public arXiv PDF, waited for processing, generated a real summary with19 source references, streamed a dataset question, opened its physical-page7 source and refreshed conversation history. All five homework workflows succeeded. Semantic Scholar's live request returned429, surfaced as `PROVIDER_RATE_LIMITED`; successful provider behavior was separately verified with HTTP fixtures.

Read-only review verified that the answer's exact cited page7 chunk contains the WMT dataset sizes and tokenization details. The endpoint formerly hid them after its1,200-character prefix. ARA-032's correction was verified through the live GUI: the dialog now contains all3,200 characters and the supporting evidence, without a new paid call. Citation identity checks cannot establish semantic entailment for every future generated claim.

Local ignored evidence:

- `docs/evidence/generated/live-demo/live-demo.webm`: continuous real-workflow recording, 7,370,575 bytes.
- `summary.png`, `chat.png`, `source.png`, `result.json`: original live run artifacts.
- `source-final.png`: complete cited passage after the final correction.
- `.impeccable/review/desktop.png`, `paper.png`, `chat.png`, `mobile.png`: final model-label/responsive captures.

The original PDF and generated outputs are not committed or relicensed. Keys were never printed. The demo recording predates the final model-label/source-display fixes; later captures prove their corrected behavior.

## Review and submission boundaries

An independent reviewer found five concrete defects; the owners corrected them with regressions and the reviewer confirmed those five resolutions. A final bounded review found no new submission-blocking issue. See [review evidence](application-review.md) and [authentic journal](agent-development-log.md).

README, license notices, lockfiles, source and prepared CI are ready for later publication. A remote repository link, remotely executed CI, the student's personal reflection and Brightspace submission have not been completed in this session. See the [submission checklist](submission-checklist.md).

## Local source history

The user requested focused Conventional Commits after the first oversized local checkpoint. The verified snapshot was regrouped without changing application source. Component commits are listed below; project documentation and issue evidence follow in a separate documentation commit. Nothing was pushed.

- `4164b07` — docs(plan): record requirements and architecture.
- `8ff066e` — build(tooling): lock Python and TypeScript dependencies.
- `7a16711` — build(docker): provision development and isolated test services.
- `bccd016` — feat(jobs): add async resources and durable background execution.
- `aa2d48b` — feat(search): add academic adapters and persistent paper identity.
- `387fa55` — feat(pdf): retain originals and ingest page-aware paper content.
- `5ec2b98` — feat(ai): add grounded summaries and persistent streaming chat.
- `f237576` — test(backend): verify recovery retrieval and generation contracts.
- `8e6fe96` — feat(workspace): add research search library and model settings.
- `112c959` — feat(reader): add summaries citations and paper conversations.
- `3a69aff` — test(frontend): cover workflow states sources and streaming.
- `8b7dd79` — feat(skills): add the locked local PyMuPDF parser.
- `1390f9c` — test(e2e): exercise homework workflows with HTTP fixtures.
- `0e64197` — ci(checks): enforce builds integration and API contract consistency.

## Managed local models — ARA-022, October 8

Verified on `feat/managed-ollama`, based on `main` at `c403662`. No merge or GitHub push was performed.

| Check | Executed result | Scope |
| --- | --- | --- |
| Lead `python3 scripts/test-stack.py test` | 185 passed in 38.77s; Ruff/build/migrate/bucket init passed | Isolated real PostgreSQL, Redis and MinIO; deterministic external models |
| Frontend `npm run check` / `npm run build` | 356 passed across 54 files; strict TypeScript/ESLint and build passed | Settings, guarded models/defaults, progress, status, chat and existing interface regressions |
| Final Playwright run | 12 passed in 2.0 minutes | Fresh isolated fixture stack; mandatory workflows plus four managed-model journeys |
| Infrastructure / external-fixture unittest | 4 / 3 passed | Bootstrap/reset/Compose configuration and actual fixture HTTP interfaces |
| Generated API contract | Live OpenAPI regenerated and byte-matched | Checked against API8002; no schema changes in the subsequent sampling correction |
| CPU/GPU Compose configuration | All three configurations validated | GPU configurations were not hardware-tested |
| Fresh ordinary Compose startup | Gates/readiness passed; no installed/loaded models; Ollama 20.91 MiB | Isolated `ara-feature`, alternate ports with matching CORS; no automatic weights |
| Actual worker reload | Six rapid writes produced one restart per worker | Default debounced development wrapper; temporary probe removed |
| Runtime source review/tests | Ten control tests, repeated race checks and full server suite passed | Pinned Ollama 0.40.1 plus llama.cpp b11454, reviewed cancellation/control patch |
| Real 7B engine/application | Streaming/schema/default/disabled thinking, exact hashes, range resume, summary/Q&A and restart persistence passed | ARM64 CPU; only 7B weights; empty OpenAI key for application checks |

The final application sampling check stored a summary covering all three chunks in 38.32 seconds and streamed a cited answer in 10.41 seconds (49 SSE events). Both used temperature 0.0 and recorded the pinned artifact, runtime, context/output/thread/reasoning settings. The saved summary exactly matched its durable provenance snapshot, and hosted reservations remained zero. One preceding default-sampling summary was rejected for missing usable source markers; it was not stored as a valid summary or automatically replayed. Temperature 0 reduces sampling variability, not the need to validate citations or inspect factual support.

Restarting PostgreSQL, MinIO, Ollama, API and both workers preserved histories, local defaults, the byte-identical original PDF and verified weights. The measured full application peak was 11.85 GiB under a 12 GiB ceiling, steady usage about 6.65 GiB, and OOM counters were zero. Leave memory for other services; weights, loaded tensors, KV cache and filesystem cache have different lifetimes. See [runtime evidence](../docker/ollama/README.md).

Independent runtime, backend, generation, frontend and whole-branch reviews reproduced defects before correction. Final probes cleared all findings; the latest whole-branch review also passed 38 native adapter tests and a deletion-race provenance probe after the temperature correction. Native amd64, NVIDIA/AMD hardware and live 3.7B/27B inference were not tested. ARA-050 separately tracks seven baseline development-tool dependency advisories; they were not introduced or force-remediated by this feature.

After the sampling correction, refreshed fixture workers passed E2E-11 and E2E-12 again: two tests in 43.8 seconds. The feature preview runs on localhost:5191 with an empty model store; its ignored worktree configuration uses the separate `ara-feature` project and leaves the original development data intact.

## Automatic readiness and protocol failures — ARA-053–054, October 8

The user's installed-but-unselectable IFM report was reproduced in `ara-feature`. Its 3.7B weights were present, but the old capability record required a manual refresh. Readiness now refreshes automatically with durable verification-only jobs. Settings and Activity show preparation, preserve saved preferences and offer explicit recovery only when needed. No migration or new endpoint was required.

| Check | Executed result | Scope |
| --- | --- | --- |
| Backend full suite / Ruff | 365 passed in 44.08s; lint and whitespace checks passed | Isolated real PostgreSQL/Redis/MinIO; deterministic external responses |
| Frontend check / production build | 375 passed across 54 files; strict TypeScript/ESLint and build passed | Readiness polling/status, operation labels, failure recovery, saved-effort preservation; existing warning output retained |
| Full Playwright | 12 passed in 1.9 minutes | Fresh `ara-e2e` fixture stack; mandatory workflows and managed-model journeys |
| Protocol cross-review | Independently 38 unit + 10 SQL cases passed | Malformed shape errors terminate safely without lease/pull/recovery loops; original P1 cleared |
| Final generated contract | Byte-identical after regeneration from source OpenAPI | Nullable installation/job operation enums; no handwritten TypeScript duplication |
| Real automatic 7B readiness | Exactly one verification-only job; six controls available | Retained weights, browser navigation/closure, API restart; default/history counts and digest preserved, hosted reservations zero, no pull/OOM |
| Updated protocol boundary with real 7B | Six controls, streaming and structured output passed | Retained ARM64 CPU runtime under inference admission, hosted key empty; no new installation job |
| Actual feature 3.7B | Automatic preparation completed; Settings selection and six controls verified | Existing user-installed weights; saved defaults unchanged, no browser mutation/verification request; 7B/27B siblings remained missing |
| Preparation layouts | No horizontal overflow at 1440px and 390px in both themes | Existing shadcn/Geist design; native theme controls and browser closure tested |

The first readiness regressions failed 30 backend cases plus two lifecycle tests. Offline/freshness review added four failing cases before correction. Protocol regressions failed 41 and passed seven before the boundary fix. These are actual observed test results; test-harness timing/locator corrections are distinguished from product failures in the [development journal](agent-development-log.md).

The preview now contains the user's ready 3.7B installation; the older empty-store statement above describes its initial ARA-022 startup. Tests use 7B fixtures and retained 7B inference; the 3.7B check establishes background installation readiness, without a full paper-quality benchmark. Native amd64/GPU and 27B remain untested. No new weights, paid generation, main merge or GitHub push occurred. Focused code commits: `a2d1861`, `0b312f4`, `459290d`.
