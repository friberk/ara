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

### First browser run of the research spec (ARA-039)

The lead ran `research.spec.ts` against the e2e fixture stack.

- **E2E-01:** passed.
- **E2E-02:** failed on a rerun because the earlier run had already saved the fixture paper. The spec assumes a fresh database. After resetting only the `ara-e2e` volumes, it passed in 3.7s.
- **Mobile test:** timed out. The Playwright trace showed `<a>Skip to content</a> intercepts pointer events` 106 times: while focused, the skip link sat on top of the mobile sidebar toggle. It moved to top-centre.
- **Mobile test, second failure:** the next run failed at `toBeHidden`, because one Escape did not close the sheet. The screenshot showed focus on a sidebar item. A new unit test reproduced it (red). The cause was shadcn's `SidebarMenuButton`, which always mounts a Tooltip and only hides its content on mobile or when expanded, so the invisible tooltip took the first Escape. Tooltips now mount only on the collapsed desktop rail. A guard test keeps the rail labels; it was first wrong (it matched two "Toggle Sidebar" buttons) and was fixed, then confirmed red by disabling tooltips.

The mobile E2E now passes in 5.1s and Vitest passes 225/225. The legacy `workflows.spec.ts` was retired in favour of the per-feature specs.

### UI overhaul: workspace integration, full E2E and cleanup

**Workspace merge.** The workspace agent integrated its reader with the real conversation pane on its own branch. Its TDD audit separated assertion reds, missing-module reds, and test-after work that was mutation-verified. The lead merged it and, on real data, verified the evidence jump: clicking a "p. 7" chip in an answer announced "Highlighted the cited passage on page 7.", and the mobile view switched to the PDF tab. The integrated suite passed 293 tests.

**First full E2E run.** It passed 7 of 8. E2E-02 failed because Playwright runs spec files alphabetically and the conversation spec's setup saves the fixture paper through the API. A Playwright project dependency now runs the research journey first. All 8 then passed on a fresh e2e database.

**Cleanup.**
- Removed the legacy pages and components.
- Dropped four unused dependencies.
- Declared pdfjs-dist explicitly.
- Moved helpers and contexts out of component files so ESLint reports zero problems.

**Bundle size correction.** The lead had been reporting the entry chunk alone as "main". A comparison of first-paint JS (entry plus modulepreloads) showed about 550 KB raw (172 KB gzip) both before and after the refactor. That is the honest number.

**Final checks.** E2E still passed 8/8 after the cleanup, and the Impeccable detector reported 0 findings. The fresh finish reviewer received 36 validated captures.

### Impeccable finish review and fixes (ARA-040)

A fresh-context `impeccable-finish-reviewer` received 36 validated captures and the direction contract. Its disposition was **fix**, with seven material findings:
1. The evidence jump marked a whole ~3,200-character chunk (nearly all of page 7) instead of the supporting passage.
2. The dark-mode mark rendered tan on white pages.
3. Activity exposed internal canary jobs.
4. The summary card was sliced under the conversation header.
5. A metadata-only paper showed dead disabled controls.
6. A citation chip could wrap alone.
7. DESIGN.md was stale.

**Lead fixes (3, 4 and 5).** All test-first. Two older test-after tests encoded the superseded disabled-control behaviour and were rewritten to the new intent. One invented empty-state title in a new test was corrected to the existing copy before implementation. Five mutations were caught.

**Evidence agent fixes (1, 2 and 6).** Done test-first in a fresh worktree:
- Chips now pass their claim sentence. The reader scores excerpt sentences against it and marks the best ones character-precisely, using Text.splitText and `<mark>` with no innerHTML, then centres the first strong line.
- The agent's visual check showed whole-answer context strongly marking an unrelated sentence, so Sources chips now use only the sentences citing their page.
- A first stylesheet test passed vacuously (Vitest returns an empty `?raw` import) and was redone.
- The agent ran E2E against the test API only, with an Origin override confined to fixture data.

**Lead integration.** 338 tests passing, 0 lint problems, Playwright 8/8 on a fresh e2e database. The recaptures show only "Not only do individual attention heads…" marked on page 7, the same yellow in both themes, and an "Attach PDF" primary action for papers without a PDF. The recaptures went back to the same reviewer for a verdict pass.

### Verdict pass, documentation and closing drift

The same finish reviewer re-scored the recaptured screens: fixes 1–6 resolved, with one disclosed non-material residual (the mark can start a glyph late because of pdf.js text-layer geometry). Fix 7 needed only DESIGN.md.

`impeccable-documenter` replaced DESIGN.md and wrote `.impeccable/design.json` from the shipped code, and listed drift instead of hiding it. The lead fixed two items test-first:
- ModelSwitcher's `toast.error` broke the inline-errors rule; failures now stay in the open menu as an alert.
- The unused `--evidence` token: the reader had hard-coded its own copy, so the token now has one value in both themes and the reader uses it.

Mutations confirmed both fixes. Final run: Vitest 339/339, ESLint 0, Playwright 8/8 on a fresh e2e database.

### UI overhaul merged into main

The user asked: "Can we merge to main?", then: "Also keep the branches for record."

`main` had not moved since `feat/ui-overhaul` was cut, so the merge was a fast-forward to `dd9a96d`. The branch and all agent branches are kept as archives, and nothing was pushed because no remote is configured and publishing is deferred.

Verification on `main`:
- Strict tsc clean
- ESLint 0 problems
- Vitest 339/339
- Production build passing
- Running development stack healthy

The final full E2E run (8/8) and the backend suite (74/74) ran on the same code.

### Premature push toward the homework baseline (ARA-041)

The user asked what remained after the UI overhaul. The lead answered that the core was complete and recommended: “I’d prioritize the demo and reflection over further feature work.” The roadmap also contained human-oriented effort ranges and a predetermined freeze. The response did not establish an actual time/resource constraint before recommending that the user stop iterating.

The user corrected this: “No, we have time for other things. Also log this behavior. The agent is pushing towards an MVP rather than keep iterating.” The user emphasized the difference between human and agent throughput, illustrating it as one agent hour versus one hundred human hours. This is the user's comparison, not a benchmark measured by this session.

Correction: reaching the mandatory workflows does not end the intended system's development. Reopen the remaining enhancement backlog; replace assumed human-hour schedules with dependencies, observed agent execution throughput and measured technical constraints. Submission preparation remains required and can run alongside feature iterations. The user decides scope reductions. AGENTS.md now records this standing policy, and the plan no longer prescribes an automatic freeze.

The next user request was a list of remaining work with scope and descriptions. No enhancement was presented as implemented during that listing; remaining application work and submission/tooling tasks are recorded separately in the tracker. This exchange itself is an authentic reflection example of the user correcting the agent's project-management bias.

Documentation audit follow-up: the first checker rejected ARA-006 because its legacy SearchPage file had been removed by the UI overhaul. It incorrectly required historical source paths to exist in the current tree. The shell command continued after the assertion, so documentation was committed before that check passed. The corrected audit resolves historical paths in linked commits and gates subsequent mutations on its exit code. It then found ARA-011 lacked the reader commit containing its old Citations component; that commit reference was added. No application source changed and no application test success was inferred from these documentation checks.


## October 8, 2026 — ARA-022 managed local model implementation

The user approved Ollama model management, added IFM K2 Horizon 3.7B, requested TDD, existing Impeccable/shadcn design, live 7B tests, grouped Conventional Commits, and feature-branch work. Created isolated `feat/managed-ollama`; `main` is unchanged. Planning agents reviewed runtime/download protocol and Settings. A research agent returned Qwen3.5 in place of requested Qwen3.8; lead verified the exact Qwen3.8 publisher tag and corrected the catalog before implementation. No model substitution was implemented.

Source review found no acknowledged pause in stock Ollama and a cancellation race in its unbuffered progress callback. User permits a reviewed custom Ollama build if needed. At initial planning, live compatibility remained a gate. Backend baseline executed against ara-test: 74 passed, Ruff clean. Frontend baseline was being checked. npm reported seven high-severity dependency advisories at installation; preserve output for separate triage rather than silently performing breaking dependency upgrades. No secrets were printed.

### Runtime compatibility and actual 7B execution (ARA-044)

Stock Ollama 0.40.1 downloaded the authorized IFM K2 Horizon 7B Q4_K_M artifact into an isolated validation volume, but real chat failed with `unknown model architecture: 'k2-horizon'`. The pinned stock source uses llama.cpp b11351. The runtime owner built the user-authorized custom image using upstream b11454 (`4625240437c6821ee5c2da99e12d4817c6a8f07f`), reviewed Ollama's existing hooks and adapted the CLEF patch where newer upstream already supplied decision declarations/implementation. K2 support comes from upstream. The [upstream issue demonstration](https://github.com/ollama/ollama/issues/18698#issuecomment-6024936344) agrees with the compatible b11454 baseline.

The first ARM64 build failed because GCC12 lacked the required ARMv9.2/SME support. Switching the pinned build/runtime bases to Trixie/GCC14 allowed the CPU image to build. Auto-selected 12 inference threads under a four-CPU container quota caused severe throttling in an exploratory request; explicit four-thread configuration produced usable measured output. Neither incident justifies replacing the requested model or freezing feature work.

Real 7B pause/resume retained a nonzero range checkpoint and completed the network transfer in 95.28 seconds including pause/resume. Two runner mistakes were corrected: treating the intentionally canceled pull stream as a failed download despite successful pause acknowledgment, and comparing a prefixed SHA256 string against Ollama's bare manifest hex. The corrected runner independently checked the 5,592,217,984-byte model blob hash and pinned manifest. Final revalidation reused retained weights; it did not perform another real download.

The final reviewed CPU image is `sha256:f0c8e95243f7acbe5fdbc510830e1dd5622ae054a4fce1979db692cd80db14a5`. It passed real streamed final answers with `done_reason=stop`, JSON-schema output and default/disabled thinking. Thinking remained in `message.thinking`, separate from answer content. Native low/medium/high probes returned unsupported errors even though the template has corresponding branches, so the app advertises only proven Model default/None for this model. Final first content arrived at 9.56 seconds including an 8.94-second cold load; steady container usage was about 6.52 GiB and cgroup peak 10.30 GiB under the 12 GiB ceiling. A separate test paused synthetic registry traffic while real 7B inference completed, without restarting the daemon.

The memory ceiling is not startup allocation or resident usage. It proved sufficient for the measured 7B workload; it does not prove Qwen27B fits. Only ARM64 CPU 7B weights were authorized and live-tested. Native amd64 CPU and patched NVIDIA/AMD targets are provided but untested on hardware. No 3.7B/27B inference, additional decision-model regression or GPU performance is inferred from fixtures. Pinned sources, license inclusion, build commands and measured limits are recorded in [the runtime README](../docker/ollama/README.md).

### Independent runtime review and protocol correction

The runtime reviewer requested changes for two source-level cancellation defects: preparation held the global blob-manager mutex across an unrelated registry HEAD, and a backpressured pull response could block pause acknowledgment. The owner added deterministic tests and observed both failures before changing the implementation. Preparation and transfer/checkpoint joins now run outside the manager mutex, with per-digest ready/released state and reference ownership. A joined request-scoped write-deadline watcher releases blocked response writes.

The first immediate response deadline introduced a real `unexpected EOF` for an actively reading client. A reading-client regression reproduced it. A 100 ms drain grace fixed the ordinary client path while keeping blocked writers cancellable. This is measured behavior, not a universal pause deadline for every disk or registry.

Restart recovery exposed a conflict with the original unknown-operation 404 response. The lead ruled that an unknown valid UUID pause must atomically establish a canceled tombstone, acknowledge 200, and reject a late same-UUID pull with 409. Fresh-daemon, concurrent pause/late-pull and registry-capacity tests first failed against the old behavior, then passed. Tombstones last one daemon lifetime; the backend must re-establish settlement on the current runtime. A 404 never proves a stopped operation. The final ten control tests passed three race-enabled repetitions in 16.312 seconds, the full Ollama server suite passed in 8.600 seconds, and the final CPU image build passed. Scoped runtime re-review approved the corrected implementation and revised ruling.

### Durable installation and native generation (ARA-045–046)

The backend owner added migration `0005_local_models`, catalog/installation DTOs, globally unique operation identities, persistent jobs/progress, inference leases, model routes and separate worker queues. Test-first failures covered missing contracts, expired-lease recovery, authoritative progress rollback, pause replay, metadata outages spending transfer retries, deadline cleanup, broker initialization and readiness. The model worker reconciles inventory before transfer, keeps manual pause intent and verifies artifact/runtime/capabilities before availability. Deletion confirms inventory absence and preserves defaults/history.

Independent backend review reproduced three SQL defects: retrying a superseded job changed a newer installation, a pause/verification race released maintenance admission, and daemon restart made unknown-operation settlement fail permanently. Six owner regression cases failed before correction and then passed; the reviewer's unchanged three-case harness passed afterward. A further pair of failures exposed current and abandoned attempt identities needing settlement together. Recovery and pause now acknowledge both before releasing ownership, and every transition checks the current installation owner. Unconfirmed pause remains retryable rather than being reported as safely paused.

Native Ollama generation uses a separate process/event-loop client, no hosted key or dollar reservation and no paid fallback. It preserves request UUID replay, selected-document citations and provider/artifact/runtime/effective-settings provenance. Interactive busy admission returns 429 before SSE headers; background local summaries wait on their queue. Hosted behavior remains covered by regressions.

Independent generation review reproduced three defects: completed reduction groups were not checkpointed before later contention, two valid 3,000-byte outputs could not combine within the local input bound, and chat added an uncounted separator byte. The owner reproduced each before implementing fixes. Each completed group now persists its output/cursor and cleared in-flight flag before releasing admission. Bounded compression sends complete intermediate sections and retains required source markers; three noncompliant attempts fail explicitly. Chat concatenates already terminated passages and validates the actual prompt before persistence. Scoped re-review confirmed the original boundary now fits exactly 5,632 bytes and completed reductions are not replayed after busy/503 recovery. Fixtures establish deterministic coverage and persistence; live semantic quality remains a separate application check.

One mandatory backend run had 145 passes and one failure because a URL-guard test assumed development while Compose set `APP_ENV=test`. Its environment was made explicit, and the full rerun passed. After both backend and generation review fixes, `python3 scripts/test-stack.py test` passed 169 tests in 31.38 seconds with image build, real-service startup, migration, bucket initialization and Ruff. This is the verified pre-reload-follow-up result, not a claim for later source changes.

### Settings, browser review and worker reload incident (ARA-047–048)

Settings now separates local installation controls from default selection. Missing models remain visible; unavailable picker rows explain the reason and link to Settings. Model jobs appear in Activity. Downloads never auto-select, and deletion preserves a local saved default while blocking unavailable generation.

The first background/navigation and pause/reload/resume journeys passed. The default-deletion test passed its saved-preference and unavailable-state checks but used the wrong final model locator. The locator was corrected to the paper workspace. A later browser review found three actual UI defects: the model anchor did not scroll, inherited query options disabled focus refresh, and the stage live region disappeared on terminal states. Three focused regressions failed first; the corrected anchor focus/scroll, always-on focus refetch and persistent stage status passed the eleven focused tests.

During a fixture browser run, a resumed model job stalled at inventory. The model worker logged three SIGHUPs within roughly 100 ms, then Stopping/Killing without a new worker boot. Dramatiq's watcher sent a signal for each source event; a second signal during shutdown can interrupt its lifecycle. The exact earlier swallowed exception was not available, so the diagnosis records the observed failed reload instead of inventing an exception. Restarting only the isolated E2E model worker allowed the existing job to recover through its lease/outbox state and complete about 56 seconds later. No DB edit, lease adjustment, reset or development-volume mutation was used.

A safe diagnostic regression ensures model-job logs retain exception class/code, caller location and job identity without exception text, private URLs or secrets. A debounced subprocess wrapper replaces direct Dramatiq watch: it stops the prior process tree before replacement and force-cleans surviving children at its deadline. Its draft real-process tests passed for burst-write restart and an uncooperative child/grandchild tree; final production wrapper, Compose and repeated recovery-chain validation are still being completed by the backend/lead.

The latest frontend check passed strict TypeScript, ESLint and 354 Vitest tests across 54 files. The production build passed with the existing PDF/KaTeX chunk-size warnings. All four new fixture-based local-model Playwright journeys passed in 1.3 minutes: background/browser closure, pause/reload/resume, default deletion and local grounded summary/Q&A persistence. These prove HTTP/UI behavior against a deterministic model provider, not live model quality. Final full backend rerun, repeated recovery review, full application live7B checks and branch integration remain pending at this entry. `main` is unchanged and no GitHub push was made.

### Documentation and baseline dependency triage (ARA-049–050)

The documenter inspected the actual Compose configuration, catalog, migration, DTOs/routes, native adapter boundaries and scoped reports, then replaced deferred local-serving instructions in README, AGENTS, the API contract and implementation plan. Issue acceptance uses Given/When/Then and milestone statuses remain in progress until final integration evidence arrives. The reviewed private tombstone semantics supersede the old 404 behavior. Public records summarize actual prompts/failures/corrections; private raw logs, screenshots, weights and uploaded PDFs remain excluded.

The baseline npm audit reported seven high-severity findings through the shadcn development-tool chain, rooted in [braces stack exhaustion](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm). Its suggested semver-major change was shadcn1.0.0, while the project uses shadcn4.21.4. ARA-050 tracks reachability and compatible remediation. No automatic force upgrade/downgrade was applied, and runtime exploitability has not been established by this audit record.

Documentation source-check correction: the GitHub page renderer omitted the referenced comment, and host Python could not verify its TLS certificate. Fetching the public comment with curl and normal TLS verification succeeded; its b11454 3.7B example supports the engine baseline without adding a local 3.7B test claim. The documenter also corrected an initial ignored-file search by using explicit no-ignore discovery for the private review reports. Documentation JSON/link/source audit and `git diff --check` passed; no application suite was rerun by the documenter.

The next isolated backend run passed 172 tests after a polling-observer correction; infrastructure unittest passed all four tests. Independent re-review subsequently reproduced three failures involving repeated-restart acknowledgment identity loss and a queued-to-claimed pause race. The owner is extending durable recovery to retain every unresolved runtime attempt identity; that correction and its final checks remain in progress. The full browser run then completed: all 12 Playwright tests passed in 2.0 minutes, including the four local-model journeys and five mandatory workflows. Desktop 1440 px and mobile 390 px captures in both themes showed no horizontal overflow. A visible whole-section anchor outline was refined to heading focus while preserving scroll behavior. None of these checks proves GPU or native amd64 compatibility.

### Full application check and final branch review

The lead used an isolated `ara-local-live` Compose project with the reviewed real runtime, retained 7B weights and an empty OpenAI key. Installation verification, PDF ingestion, a stored summary covering all three document chunks and a cited streamed answer passed. The summary took 36.30 seconds; Q&A took 14.36 seconds and emitted 124 SSE events. Manual source inspection matched Orion-12, twelve synthetic examples and 86 percent accuracy; these are fixture facts, not published research claims. PostgreSQL stored the exact artifact/runtime/effective generation settings, with zero hosted reservations. Peak memory reached 11.85 GiB and steady usage about 6.65 GiB, with zero OOM events. Restarting PostgreSQL, MinIO, Ollama, API and both workers preserved histories, defaults, the byte-identical PDF and verified installation.

The lead found that an unsuccessful settings request inherited an available paid-model fallback. A regression failed with Luna selected after HTTP503. Automatic selection now requires successfully loaded settings; an unavailable saved local model keeps its identity. The two new provider tests passed, followed by strict TypeScript, ESLint, all 356 frontend tests and production build. The complete browser suite passed 12 scenarios before the final backend failure-path corrections.

The UI reviewer corrected one piece of its evidence: its first visibility event did not bubble to TanStack's window listener, so that request-count probe was invalid. The code and lead's observed failing focus regression still established the defect. Its corrected browser probe confirmed the fix. Desktop/mobile light/dark inspection found no horizontal overflow; one confirmation pass verified heading focus after removing the oversized section outline. The design retained the established shadcn/Geist interface.

The final branch reviewer reproduced two additional failures. Ordinary stalled/timed-out pulls could release ownership without preserving an unacknowledged attempt; the backend owner is correcting settlement on those exits as well as crash recovery. A permitted model deletion after the last summary generation also cleared artifact/runtime provenance before final persistence. Three real-SQL tests failed for deletion, effective-setting drift and old checkpoints without provenance. The summary now snapshots configuration under admission before its durable in-flight checkpoint, reuses it at persistence and rejects changed/unknown settings rather than inventing provenance. All 25 AI integration tests then passed. The independent deletion-race probe confirmed exact non-null artifact/runtime identity. Reopening the older LLM agent reached the tool's thread limit; the lead completed this scoped fix directly while the backend owner worked independently.

An all-files whitespace check flagged literal blank-line prefixes and Go tabs inside unified patch artifacts. A narrowly scoped `.gitattributes` rule preserves the patch format; application source keeps normal whitespace checks. `.superpowers` was also excluded from Docker build contexts so private review artifacts cannot enter images. Final settlement review, full backend regression and grouped commits remain the last gates.

The ordinary Compose build/start then passed in a fresh `ara-feature` project, using alternate host ports and matching CORS origins. Core readiness did not depend on model installation. All three local rows were missing/unavailable; Ollama reported no installed or loaded models and used about 20.91 MiB under its 12 GiB ceiling. No weights were fetched at startup. CPU, NVIDIA and AMD Compose configurations validated syntactically; this does not add GPU hardware validation. Explicit alternate ports required matching Origin configuration, as documented. The existing `ara` development project and its volumes were left intact.

### Final verified outcome

The failure-path fix retained every unacknowledged UUID in a durable settlement stage and blocked competing local admission. Cleanup does not repeat pulls or spend another transfer attempt. Six SQL scenarios passed for stalled/deadline/exhausted/malformed transfers, queued pause and multiple cleanup obligations; the broader targeted model suite passed 38 cases. The independent original failure probe confirmed retained IDs and acknowledged cleanup with unchanged attempts. The lead's full real-service backend check passed all 185 tests. The full fresh-stack Playwright rerun passed all 12 tests in 2.0 minutes.

A subsequent real summary attempt exposed another actual quality limitation: the model omitted usable source markers, and the application rejected it with UNGROUNDED_OUTPUT. The uncited response was not stored as a valid summary or automatically replayed. Unlike verification probes, normal local calls had inherited provider sampling defaults. A controlled same-paper/prompt probe with temperature 0 produced three valid citations. Two regressions failed for absent explicit sampling and absent saved temperature. Local requests now specify 0.0 and record it in provenance; hosted arguments are unchanged. All 185 backend tests passed again in 38.77 seconds. A full real application rerun generated a cited three-chunk summary in 38.32 seconds and a cited answer in 10.41 seconds (49 SSE events), with zero hosted reservations. The stored summary matched its generation-time checkpoint snapshot. These observations support the chosen default, not a guarantee that every model output is grounded. The citation guard remains strict.

The final reviewer approved the sampling change after 38 adapter tests and a deletion-race provenance probe. The final frontend check passed 356 tests, strict TypeScript/ESLint and production build. Activity describes the private settlement stage as “Stopping download”; its descriptive-label regression failed before the copy correction. Original private review artifacts, model data, generated PDFs and screenshots stay ignored. Focused Conventional Commits group model persistence/control, native AI generation, reviewed runtime/development infrastructure, UI, browser fixtures and documentation; the temperature correction has its own fix commit. `main` remains at c403662 and GitHub publication remains deferred.

After refreshing the fixture workers to load the final sampling configuration, the default-deletion and local summary/chat browser scenarios passed again (two tests, 43.8 seconds). The isolated feature worktree's ignored configuration now selects `ara-feature`, ports 5191/8003 and matching origins, preserving copied credentials and the original `ara` development project. Ordinary `docker compose up` from that worktree started the healthy preview without fetching weights.

Final persistence was rechecked after the temperature correction by restarting all six state/application services again; histories, default, original PDF and verified installation survived. The lead's documentation audit verified links, issue dependencies without cycles, related files and existing commit references, excluded environment secrets, conventional commit trailers and the unchanged main ref. ARA-022 and ARA-044–049 are completed on the feature branch; hardware/models explicitly listed as untested remain runtime-dependent, and ARA-050 remains a separate observed issue.

### Thinking-discovery correction — ARA-051

The user pointed to [Ollama's thinking documentation](https://docs.ollama.com/capabilities/thinking). Inspection exposed a legacy-field assumption in the adapter and its fixtures. Read-only inspection of the installed IFM 3.7B also found absent runtime thinking metadata. The previous explanation conflated discovery and serving limitations. ARA-051 records both; this investigation changed no behavior and ran no new inference.


### User correction: reasoning effort belongs to the selected model — ARA-051

The user corrected the implementation's capability assumption: “GPT models will accept xhigh and max etc. I think we do need to code effortLevel per model.” The backend had a shared hosted `EFFORTS` list, while the local discovery adapter also used a fixed set of known names and the obsolete `thinking_levels` field. The lead's earlier explanation did not adequately separate each model's advertised controls from the pinned runtime's recognition failure. The user supplied Ollama's current thinking documentation and explicitly requested resolution before merge.

The correction changes the design in two places. Native models use valid `thinking.values` and `thinking.default` metadata from their verified runtime, with an exact mapping from UI selection to Boolean or model-defined string. Hosted models receive explicit capability entries keyed by model ID. Current official [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) and [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) pages were fetched again; all three currently document none, low, medium, high, xhigh and max. Their matching lists are recorded individually rather than treated as a rule for every model. No paid API call was needed to check the documentation.

The lead delegated native runtime recognition and Python capability contracts to separate agents. A third frontend delegation failed because the tool's agent thread limit had been reached; the lead handled the small UI change directly. Initial frontend regressions failed twice because Boolean thinking-on lacked its reader-facing label. After adding “On,” both surfaces passed their regression tests. A native unit-test run reported twelve failures before the parser correction and thirty passing cases afterward; the delegated database tests initially exposed seven failures in settings validation, provenance and capability freshness. Full integration verification and review remain pending at this entry. These are observed development results, not claims that live controls already work.

Suggested reflection evidence: the user's documentation link and per-model correction; the obsolete parser and shared effort list; the failing canonical-metadata tests; and the eventual model-specific menu and real 7B verification. Omit credentials and private tool scratch files from screenshots.


### ARA-051 tests exposed additional discrepancies

The native runtime tests first confirmed the missing capability gate. The retained 7B and read-only 3.7B metadata contained the same complete template hash. Its low, medium and high suffixes differed, but the unpatched Ollama runtime advertised no thinking metadata and rejected named controls before inference. The scoped fix publishes the canonical descriptor only for that exact native GGUF architecture/template identity. A peer review then exposed `/api/generate` raw/custom-template/suffix requests bypassing the verified template despite accepting named controls. Nine failing cases preceded the narrow bypass guard.

The Python peer reviewer reproduced a separate settings defect: legacy stored lists could still save an unsupported local level although generation correctly required revalidation. Four real PostgreSQL regressions failed for stale schema, absent verified mapping, mismatched raw mapping and malformed metadata. The corrected DTO, settings validation and provenance derive controls from current-schema canonical metadata plus successful exact-value probes. The complete isolated backend run then passed 243 tests in 38.05 seconds. This discrepancy would have survived the original fixture checks without the user's capability correction and cross-review.

Real 7B inference also challenged the new validation assertions. The native rendered prompt omits a textual BOS token, so the first full-prompt comparison was corrected to the actual native representation. Low mode returned a correct final answer without reasoning tokens; requiring nonempty thinking for every enabled mode was too strong. The test now records token counts while retaining exact prompt-mode, complete-answer and private-field separation checks. Medium mode then returned an empty final answer despite a completed stream. Raw completion and native output established an actual upstream parser defect: the selected medium prefix was followed by a different legitimate IFM closing tag, leaving the correct answer inside the reasoning field. The runtime owner is adding a focused parser regression and correction; live verification remains unfinished at this entry.

The first browser run timed out on a detached provider-menu item while source generation was still active. Its trace showed a second Vite connection. An unchanged test against a stable source tree passed, followed by all 12 browser scenarios in 2.0 minutes. The expanded local workflow saved a low-effort summary and switched to medium for a cited streamed chat, checking both persisted IDs. All 359 frontend tests, TypeScript, ESLint and production build passed. A single batched desktop/mobile light/dark inspection showed the six native options and no horizontal overflow. Those HTTP-fixture results establish application behavior; they do not replace the outstanding native medium-mode check.

Dedicated review-agent reopening reached the environment's thread limit. The two current implementers cross-reviewed each other's components, and the lead inspected integration and the UI. This is recorded as cross-review, rather than claiming a fresh reviewer was deployed. A first infrastructure discovery command matched no files and reported zero tests; the corrected directory discovery ran and passed all four tests. No test-success claim uses the zero-test invocation.


### ARA-052: real medium chat used a different citation wrapper

After the reviewed parser correction, retained-only native checks passed all six controls and named-level schema output. The lead then ran the full app with the hosted key empty. Installation verification completed, and a low-effort paper summary completed. The medium-effort chat answered with the correct Orion-12 dataset and twelve examples, but wrapped a supplied chunk ID as `【source:UUID】`. The existing ASCII-only citation parser found no usable citation, so the message was marked failed with `UNGROUNDED_OUTPUT`. It was not promoted to a grounded answer, and no request was replayed automatically.

This is a formatting compatibility failure, distinct from the earlier thinking parser defect. ARA-052 tracks narrow normalization of the observed wrapper into the existing `[source:UUID]` form, followed by unchanged chunk/document membership validation and canonical final persistence. The lead resumed the Python agent for failing unit and real-database regressions. Unknown, foreign and malformed IDs must still fail, and a final SSE event must replace partial streamed text with canonical content. The failed message remains evidence of the actual development outcome. Native controls passing does not substitute for the paper workflow passing.


### Verified resolution of ARA-051 and ARA-052

The native parser correction passed 24 incremental C++ cases, the full pinned upstream chat suite, the Go server/transport/parser suites and race checks. The final `0.40.1-ara.2` ARM64 CPU image passed all six retained 7B control modes and named-level schema output. The corrected medium stream separated its thinking field and returned a clean answer. A later successful resume of the existing Python reviewer enabled an additional independent parser review; the earlier failed review-agent creation attempts remain part of the record.

For citation formatting, twelve unit failures and thirteen database failures preceded normalization. Four more failures exposed already-generated Unicode sections entering resumed prompts/checkpoints without validation. The fix covers both new output and active owned caches, while preserving the paid-call interruption guard and old failed attempts. The final backend suite passed 279 tests in 39.54 seconds; the peer reviewer independently passed all 36 citation tests. The final browser fixture deliberately emitted the observed Unicode form for medium responses, and the local-default/deletion plus selected-level summary/chat scenarios passed in 48.7 seconds. Frontend TypeScript/ESLint and three standalone HTTP-fixture tests passed after the fixture change; the earlier complete 359-test frontend and 12-scenario browser runs remain accurately scoped.

The lead's final real 7B application run reused the already verified installation and retained weights. A low-effort summary cited all three physical pages in 44.39 seconds. A medium-effort answer cited page 2 in 14.73 seconds with 54 SSE events. Manual inspection matched the fixture's Orion-12 dataset, twelve examples and 86 percent result. PostgreSQL stored canonical citations plus the exact descriptor, effective low/medium values, runtime/artifact identity, temperature 0.0, four threads and context/output limits. Hosted reservations stayed zero, and the original failed-format chat stayed failed. Peak memory was 11.773 GiB with zero OOM events.

Restarting all six state/application services preserved summary/chat histories, default, model controls and the original PDF checksum. The first scratch persistence check mistakenly requested `/file` instead of the actual `/download` route and received 404; correcting that test path required no product change. A read-only check of the user's installed 3.7B on the upgraded runtime returned the canonical controls with default high. Its weights were retained, and application verification must refresh the old capabilities before selection. No 3.7B/27B/GPU inference or new weight download occurred.

Focused Conventional Commits group the user's correction (6e3bb42), UI choices (6b0b5c9), per-model contracts (a8f3238), runtime compatibility (c220415) and Unicode citations (55962c4). Both issues are complete. The work remains on `feat/managed-ollama`; `main` remains c403662 and publication is still deferred.
### ARA-019: access-aware PDF retrieval planning

The user asked whether automatic PDF retrieval should explain publisher access barriers and allow retry from a university network. The discussion expanded the existing public-PDF backlog to include observed authentication/blocked/missing-link outcomes, explicit network retry, and publisher/Semantic Scholar browser access followed by upload. Official Semantic Scholar documentation confirms its website institutional sign-in/GetFTR/LibKey flow; that does not establish access through our Graph API key or backend HTTP client.

The user then requested an implementation plan, reiterated “always TDD-first,” and required the new worktree to start from the local-model WIP branch to reduce later integration work. Read-only Git inspection found `feat/managed-ollama` at `ddced814df3de60cd05e926b5a91915360ff2470`, with additional uncommitted ARA-053 readiness changes. Orca created `/Users/bcakar/orca/workspaces/hw1/ara-019-fulltext` on branch `ara-019-fulltext` from that exact commit. The other worktree's edits were not copied, stashed, committed, or modified. The plan requires integrating later committed model work before allocating the migration and before final checks.

Planning decisions: retain both providers' per-copy metadata; use exact DOI alternatives; prefer reported open PDFs; persist attempts separately from extraction; use a dedicated bounded downloader with validated-IP/TLS-hostname pinning; preserve UUID replay, lease ownership, original PDFs and current/historical document bindings. Users retain network retry and browser/upload options. Generic 403 or HTML is not proof of a paywall. No browser extension or university credentials are part of this proposed scope.

The code audit found the current test helper's shared `ara-test` project, fixed browser ports, and shared image tags. The plan uses isolated ARA-019 projects, images and ports so execution does not stop or replace the local-model agent's services. No baseline or feature application tests were run during this documentation-only turn, and no production code was written.

Actual planning corrections: initial source reads used nonexistent AnalysisGate/PaperWorkspace paths; `rg --files` resolved ReaderGate/PaperWorkspacePage. Self-review moved browser fixtures and failing UI acceptance checks before the UI task, moved a shared result type ahead of its consumers, and selected one host Playwright invocation to remove an ambiguous container/host URL instruction. Expected test assertions in the plan are instructions for future execution, not recorded passing or failing runs.

Planning verification: `git diff --check` returned exit 0. A Python document audit passed tracker JSON/status, local links, tasks 0–7 in order, all execution boxes still open, ancestry from the selected local-model base, and the four-file documentation-only scope. These are documentation checks, not application test results.

### ARA-019 implementation: branch, baseline and provider discovery

The user authorized implementation and requested a new branch. Created `feat/fulltext-access` in the existing planned worktree and merged the committed local-model work through `459290d`; its owner’s checkout was untouched. The baseline used private generated configuration, unique images and `ara019-test` volumes. Backend: 365 passed in 46.50s. Frontend: 375 passed; strict tsc/ESLint and production build passed, retaining the pre-existing large-chunk warning.

Task 1 actual TDD evidence: nine normalization/DOI assertions failed on absent metadata/lookup (0.29s); then 18 passed including existing research tests. Three real-database discovery assertions failed on empty candidate results (1.12s); then 28 focused tests passed. The first draft included ranking constraints before their dedicated test; those constraints were removed, the OA-first ranking assertion failed (0.48s), and ranking/deduplication/cap behavior was implemented after that red. This correction is not presented as test-first work in the original draft. Full backend after Task 1: 378 passed in 43.47s. Ruff formatting and import fixes ran after behavior verification. New exact-DOI copies remain on the saved paper, manual metadata is preserved, and provider failures retain stored links. No live provider or paid generation claim is made from these fixtures.
