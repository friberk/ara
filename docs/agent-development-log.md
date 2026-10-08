# Coding-agent development journal

This is evidence for the student's reflection, not a fabricated reflection report. Record actual prompts, visible output, corrections and verification. Screenshots are captured separately with secrets redacted.

## 2026-10-08 — Planning

- Prompt: build AI Research Assistant according to hw1.md with the specified stack, Docker, TDD/BDD and multi-agent collaboration; produce a validated plan first.
- Delegated research: infrastructure, frontend/QA and LLM/model compatibility. Agents reported source links and limitations; lead independently checked material findings.
- Context7 calls returned USER_NOT_LOGGED_IN/not connected even though plugin metadata said installed and enabled. User correctly questioned the wording “unavailable”; corrected to a connection-layer mismatch. Official sources substituted; no connection repair claimed.
- Live search: OpenAlex returned200; Semantic Scholar returned429. Host Python urllib certificate verification failed; curl succeeded without disabling TLS. These were probes, not application integrations.
- Found MinIO archived/source-only; planned pinned-source image rather than relying on an unavailable latest image.
- Review caught a chat recovery gap: direct streaming generations also need expiry/recovery so crashes do not permanently block the session.
- User authorized public AGPL-3.0 repo and a local working PyMuPDF skill (including missing parser/notes), with30+hours and fundedOpenAI available.

## Implementation ledger

- Plan approved: user said “Implement the plan.”
- Existing repo has no HEAD; worktree creation requires a baseline. Ruling: use a feature branch in the current empty checkout, preserve reference files, avoid an unnecessary confirmation round.
- Tests at start: none exist. No baseline test success claimed.

### Frontend test environment correction

The lead started the first frontend test while an npm dependency upgrade was still running. Vitest failed on a disappearing internal module (ERR_MODULE_NOT_FOUND), so this run is not feature-level red evidence. Diagnosis: concurrent package mutation invalidated the test runtime. Correction: wait for npm completion and rerun serially before implementation; preserve the output as an orchestration mistake. Updated to current supported Vite8/Vitest5/ESLint10 after registry inspection revealed ESLint9 is unsupported.

### Phase0 gate

Infrastructure agent built the pinned ARM64 MinIO image and verified checksum persistence after recreation. Six core services started with init gates. PostgreSQL canary jobs and Redis markers survived restart; API and worker reload observed. Backend agent fixed a fixture that ignored environment precedence, then executed12tests (including5real-service integrations) and Alembic drift check successfully. Repeated test setup exposed Compose --wait behavior for already-finished one-shot services; the infrastructure agent changed the helper to wait on infrastructure and run init commands explicitly. Corrected helper Ruff+12tests passed. Skill agent ran6parser tests, Ruff, validator and locked CLI. Frontend shell type/lint/test/build passed before feature expansion. Detailed reports exist under /tmp and must be summarized into durable repository evidence.

### Phase3 modeling refinement

Ruling: keep capability registry in typed Python code, persist user defaults in a ModelConfiguration singleton and daily conservative generation reservations in a separate table. This supports race-safe cost controls without duplicating capability truth in database rows. Single backend migration owner, separate AI source owner; no concurrent migration edits.

### Integrated browser and independent review

Search/save passed in Chromium against actual core services and fixture HTTP adapters. The lead used an unnormalized full OpenAlex URL in a setup helper, causing INVALID_PAPER_ID; corrected to the normalized W identifier. Another test used Ready rather than the actual Ready to read label; corrected the assertion rather than product copy. Both are test-author mistakes, not app defects.

Actual mobile inspection measured 390px viewport vs 409px document and 408.66px sidebar/main widths. Root fixed automatic minimum grid tracks with minmax(0,1fr)/min-width0. The subsequent browser scenario and live paper capture both measured 390px document width at a 390px viewport.

Independent review found five concrete implementation defects: permanent identical-PDF blockage after storage failure; AnyIO cancellation before partial persistence; wrong metadata extraction import; terminal ingest jobs leaving document processing; .env dailybudget not forwarded through Compose. Owners received findings promptly. Backend reproduced upload poison and requestUUID rebinding; AI reproduced real Starlette ASGI2.3 cancellation; root observed a failing Compose budget test then green after explicit forwarding. Report saved in docs/application-review.md. These are authentic agent correction examples; no failures were invented.

### Live verification and publication steering

User configured the OpenAI key locally; no key was printed. Containers were recreated to load settings. Official models-list call verified account access and all three requested IDs listed. Through the actual GUI on port5173: real OpenAlex search, save/library refresh, upload of the public arXiv Attention Is All You Need PDF, processing, real Luna/low-reasoning summary, streamed dataset question, page-source dialog and refreshed history all succeeded. Video and screenshots are retained in ignored docs/evidence/generated/live-demo. The original paper is not committed or relicensed; arXiv source/license were inspected. Semantic Scholar still returned a handled429.

User explicitly deferred GitHub pushing; no remote or publication attempted. This overrides the earlier public-publication plan for this session. Local source/license/CI preparation continues.

All five independent review defects were scored resolved. Reviewer independently reran ASGI cancellation and Compose-budget regressions, inspected service tests and distinguished that scoped result from full-app approval. Root fresh clean test-stack pytest passed 57 tests in 13.70s; frontend 20 tests/tsc/ESLint/build passed; clean browser six scenarios passed in 17.8s, including cross-provider DOI deduplication.

### Final display corrections and evidence review

The lead identified an additional required UI gap: chat responses lacked individual model/effort labels despite persistent fields. The frontend owner observed two failing rendering assertions, added labels for saved and streaming responses, and verified that recorded Luna/low stays visible while the form selects Terra/high. Root independently reran strict TypeScript, ESLint, all 21 frontend tests and the production build, then all six browser scenarios. A fresh live screenshot shows the recorded settings without another paid call. See ARA-031.

The lead's first source inspection showed only complexity text and raised a possible citation-support problem. Independent read-only review found the exact cited page-7 chunk also contained the supporting WMT dataset details after character 1,200. The hypothesis was corrected: the endpoint truncated a valid 3,200-character chunk. The backend owner added an actual API/PostgreSQL regression, observed it fail on missing late evidence, returned the complete chunk, and ran the full suite: 58 passed in 13.60s. Cross-document denial remained 404. See ARA-032 and docs/citation-review-report.md. This records the diagnostic correction rather than inventing a hallucinated answer.

Frontend HMR was verified with an open browser and a timestamp-only CSS probe: Vite emitted an update for /src/index.css, the form input remained intact and performance.timeOrigin did not change. No product source content changed for the probe. API/worker reload and named-volume persistence were previously observed during foundation verification.

The demonstration records real external access; deterministic test fixtures remain separate. Generated PDFs, recordings, screenshots and keys stay outside the source commit. The student must write their own reflection and verify submission materials.

### Commit organization correction

The lead initially created one large local implementation commit. The user requested focused groups and Conventional Commits. The unpublished history was regrouped by planning, tooling, infrastructure, jobs, research search, PDF ingestion, AI, frontend, tests, skill and project records. This reorganizes the verified snapshot; it does not invent historical red/green commits. Actual failing output and corrective checks remain in the journal and reports. Source contents and persistent application data are preserved. No remote was configured or pushed.

The staged audit checked all 169 source/configuration/documentation files against the locally configured secret values; none matched. Original assignment files and pre-existing writing skills remain untouched and untracked. Generated recordings/PDFs remain ignored. Publication, the student reflection and Brightspace submission remain pending.

### Main integration and archive

The user instructed: “Merge to main. Keep the branch for archival purposes.” No main branch existed, so the lead created it at the verified feature tip `526ef68`. The complete implementation history is now on main; `feat/ai-research-assistant` remains unchanged at that tip. Branch SHA equality and a clean tracked tree were verified before the documentation update. Application source did not change, so the passing tests remain applicable without another run. No branch was deleted or pushed.
