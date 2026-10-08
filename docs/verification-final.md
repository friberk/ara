# Final application verification

Observed October 8, 2026, on macOS/M3 Pro with OrbStack ARM64. These results concern the implemented core application. Optional OCR, semantic embeddings, local inference and automatic PDF downloads are deferred. GitHub publishing is deferred by the user; CI is prepared but has not run remotely.

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
