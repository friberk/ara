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

## 2026-10-08 — UI overhaul planning

- Prompt: the user judged the frontend "terrible" and asked for a rethink into a chat-centred layout like chatgpt.com, claude.ai, Scite, Elicit, SciSpace or Undermind, using shadcn, with a sleek model switcher. They asked for a plan first, using the frontend-design and Impeccable plugins.
- Mid-task instructions: work on a separate UI overhaul branch, deploy multiple agents and use git worktrees. Later: "for the color schema, follow the shadcn defaults … black/white based."
- Answers to the structured planning questions:
  - Unified composer information architecture.
  - In-app PDF viewer.
  - Light and dark themes following the system setting.
  - Additive backend endpoints allowed. The user corrected the agent's deadline framing: "don't get confused by the deadline. We have time. Just do whatever required without being constrained by the time".
- Evidence gathering:
  - The Playwright MCP browser failed: `Chromium distribution 'chrome' is not found`.
  - The lead instead captured the running app with the project's own cached Playwright Chromium, writing to a session scratch directory outside the repository.
  - Captures at 1440 and 390 showed a docs-like page shell, native selects and file inputs, chat hidden behind a second tab, raw LaTeX in summaries and duplicate page buttons.
- Read-only explorers mapped the frontend and the backend API. A planning agent then checked the plan against the code.
- Corrections the planning agent found:
  - The two fixture providers share one DOI, so E2E-02 changes once search hits know their library state.
  - CI generates the contract from the test API on port 8001, where the canary route is hidden. Regenerating from the dev API would fail the check.
  - The `ara-test` and `ara-e2e` Compose project names are fixed, so backend and browser suites cannot run concurrently from several worktrees.
- Approved plan:
  - Branch `feat/ui-overhaul`.
  - Additive API work on `feat/ui-api` in a worktree, owned by one backend agent, which also owns migration 0004.
  - The lead builds the foundation: tokens, shell, composer, model switcher and query layer.
  - Four disjoint frontend feature agents in their own worktrees: content, conversation, workspace/reader, and research/library.
  - Serial end-to-end verification, then a fresh Impeccable finish review and regenerated design documentation.
- The brand commitment in PRODUCT.md now records the user-pinned direction. Issues: ARA-033 to ARA-040.

### UI overhaul: backend history API (ARA-034)

A backend agent worked in its own worktree on `feat/ui-api` and owned migration 0004 and the API schemas.

**Red phase:** the targeted run had 16 failures and 13 passes (`ImportError` for `title_from_question`, 404 on the new routes, `KeyError: 'saved_paper_id'`, an unfiltered job list, and the DELETE preflight returning `400 Disallowed CORS method`).

**Corrections during implementation:**
- Pydantic rejected `SearchResult` instances in a `list[SearchHit]` field, so the integration now builds `SearchHit` items.
- The first full run failed only the readiness test, which still pinned revision 0003. The pin moved to `0004_workspace_history`.

**Agent's final run:** 74 passed and Ruff was clean.

**Trailer request:** mid-run, the user asked that commits carry no Co-Authored-By trailer and that existing ones be amended. The lead stripped the trailer from the three overhaul commits with `git filter-branch --msg-filter` (trees verified identical) and repointed the untouched feature worktrees. It then rebased `feat/ui-api` onto the rewritten tip, stripped the trailer from the six backend commits, and merged by fast-forward.

**Lead verification:**
- Ran `docker compose run --rm migrate` on the development stack; readiness returned ready, and `GET /chats` returned real chats with paper titles.
- Independently reran `python3 scripts/test-stack.py test`: 74 passed in 14.54s.
- Regenerated `src/api/generated.ts` from the e2e test API on port 8001, matching CI, and replaced the provisional frontend types with generated aliases. Vitest passed 28 of 28.

### TDD process correction (ARA-033)

The user asked whether the work followed TDD. Audit result:
- **Backend (ARA-034):** test-first, with the red run recorded by the backend agent.
- **Lead's frontend foundation:** written before its tests. The later failures were test or environment issues, not red phases.
- **Recent-list change:** the only lead change that followed red-green (2 failing tests, then green).

The ARA-033 verification text had said "Red/green observed", which overstated the process; it now states this accurately. For the remaining lead work, tests come first, and each feature agent's red evidence is checked when it reports.

### Foundation component tests

The user asked for every foundation component to have its own tests, and set a standing rule: TDD-first from now on. Because the foundation code already existed, this was a test backfill, not test-first work.

The lead added 54 tests across the API client, composer, model and provider switchers, paper picker, feedback, upload, jobs, theme, sidebar, palette, header slot and query hooks. The new tests exposed two real defects:
- `UploadDropzone` forwarded the mutation's extra arguments (the File and mutation context) to `onAccepted`.
- The `renderWithProviders` rerender lost its providers ("No QueryClient set").

Strict tsc and the React Compiler lint rule also rejected the first versions of two tests: unsafe `matchMedia` casts, and probe components reassigning outer variables. Those tests were rewritten with `renderHook`.

To show the tests guard behaviour, seven deliberate breakages were applied one at a time and each was caught by a failing test, with sources restored after each. Final check: 85 tests passed across 25 files.

The four feature agents were reminded to work strictly red-first and to report red evidence for review.

### UI overhaul: content and research merges

The content agent (ARA-035) and the research agent (ARA-038) reported test-first work with real red excerpts, and the lead merged both with `--no-ff`. Integrated result: 147 tests passing and a 393 KB main chunk.

Corrections from the agents:
- **Content:** jsdom MathML elements lack `style`, which broke accessibility queries, so the tests now use `hidden: true`.
- **Content:** the citation dialog lost focus on close; the chip is now nested in `DialogTrigger`.
- **Research:** a background refetch after saving showed a spurious rate-limit alert.

The research agent stated plainly that its visual-fix commit and about a dozen small behaviours were implemented without tests. It was asked to add labelled test-after coverage with mutation checks.

Lead follow-up:
- Saving a paper had invalidated every loaded search page, which re-queried OpenAlex or Semantic Scholar. The red test showed `saved_paper_id` staying null. The cache is now updated in place.
- A characterisation test showed the agent's ToggleGroup role request was unnecessary, because Radix already renders `radiogroup`.
- Full-suite runs failed 1–2 different tests each time. Each file passed alone, and the failures were 1 s `findBy` timeouts under 12-worker contention. The research agent independently diagnosed the same cause. Testing Library's async timeout is now 3 s, and three consecutive runs passed 150/150.

### UI overhaul: conversation pane merge (ARA-036)

The conversation agent built the chat-first pane test-first (9 chat tests red against the stub, then green). It fixed a lint-detected ref read during render, and caught its own stale-list "Conversation not found" flash with a failing test.

**Lead review of the port.** It retains the legacy streaming safeguards (abort, terminal guard, cross-document citation rejection, no automatic resend) and consumes queued questions safely under StrictMode.

**Behaviour change.** Stop now keeps the partial answer as "Interrupted" with a polite status instead of an alert. An early stream end still raises an alert.

**Integration.** The merge into `feat/ui-overhaul` passed 162 tests and lint had 0 errors.

**Open item.** The agent's E2E spec assumes a reader region and a highlight status text. That contract was sent to the workspace agent before its merge, so the two are built to the same names.
