# ARA frontend implementation report

Owner: frontend_application. Scope: src/frontend/** only, no commits or subagents. Backend API contract from docs/api-contract.md. Existing approved quiet academic visual system retained. No fake product data or credentials.

## Delivered
- /search: React Hook Form/Zod topic/provider validation, OpenAlex/Semantic Scholar selection, query URLs, nullable fields, canonical POST save, saved-paper link, cursor load-more, provider errors including 429, loading and empty states.
- /library: persistent backend library, title filter, offset paging, accessible PDF chooser, max25MiB client validation, multipart upload with requestUUID/optional paperID, durable accepted job poll and paper link.
- /papers/:id: bibliography/status/provenance display, validated metadata editor/PATCH, original PDF, PDF attachment, processing polls, metadata-only/processing/failed analysis gates, capability-aware exact modelID/reasoning controls, summary job requests/history, saved conversation list/new conversation, immutable document source/history, POST fetch SSE, Stop, authoritative history refresh, no automatic generation retry.
- Citations: scoped citation buttons, Radix dialog with focus handling, authoritative chunk GET, genuine excerpt, original PDF #page link. Mismatched citations are withheld and show a visible error.
- Safe generated Markdown: skip HTML, HTTP(S)-only links, remote image suppression, heading hierarchy. No dangerouslySetInnerHTML.
- /settings: saved model defaults and server-reported model availability/capabilities. /jobs: actual durable state/progress/errors and explicit retry.
- Responsive styles, visible focus, accessible labels/tabs/status/errors, chat scroll preservation, unmount abort. Paper workspace lazy-loaded.

## Actual failures and corrections
1. Initial focused Vitest red: 10 failures across missing search/save/provider-rate-limit/upload/readiness/model UI plus parser returning no events or accepting malformed frames.
2. Added conversation red: ready paper workspace not present, citation/streaming test failed.
3. Additional regression red: completed JobProgress onSettled repeated after parent rerender; fixed with per-job/state once guard.
4. Additional parser red: final heartbeat followed by incomplete event incorrectly ignored; fixed final fragment validation to permit comment-only fragments.
5. Safe Markdown red: Results heading not structured; implemented safe Markdown component and verified inert HTML/unsafe links.
6. Metadata provenance red: source disclosure missing; added readable per-field provider/manual source disclosure.
7. Metadata edit red: updating only title incorrectly sent all fields and would mark provider fields manual; now PATCH includes only dirty fields and untouched provider provenance remains.
8. Build initially emitted >500KB warning; lazy PaperPage reduced main chunk to467KB, no warning on subsequent builds.

## Actual final verification (2026-10-08)
- npm run check: strict tsc, ESLint, entire Vitest suite passed, 5files/19tests.
- npm run build: passed. Main467.58KB/gzip145.05KB; deferred Paper173.52KB/gzip54.02KB; CSS24.04KB.
- Impeccable detector once: changed App/pages/components/index.css returned [] (exit0).
- npm install react-markdown: npm audit0 vulnerabilities; optional fsevents script remains unapproved; no install-script approval performed.

## Files
src/App.tsx; src/index.css; src/api/client.ts; src/api/types.ts (generated schema aliases); src/api/generated.ts; src/api/sse.ts; src/api/sse.test.ts; src/components/Feedback.tsx; src/components/ModelControls.tsx; src/components/JobProgress.tsx; src/components/JobProgress.test.tsx; src/components/Upload.tsx; src/components/Citations.tsx; src/components/MetadataEditor.tsx; src/components/SummaryPanel.tsx; src/components/ChatPanel.tsx; src/components/GeneratedContent.tsx; src/components/GeneratedContent.test.tsx; src/pages/SearchPage.tsx; src/pages/LibraryPage.tsx; src/pages/PaperPage.tsx; src/pages/JobsPage.tsx; src/pages/SettingsPage.tsx; src/pages/workflows.test.tsx; package.json; package-lock.json.

## Remaining integration/limitations
- Original binding contract gap (missing job retry) was reported and resolved by the lead/backend owner. Latest actual teststack OpenAPI includes POST /api/v1/jobs/{job_id}/retry and regenerated types now include it.
- Generated src/api/generated.ts from the real full teststack API http://127.0.0.1:8001/openapi.json using installed openapi-typescript7.13.0. Replaced handwritten DTOs with generated schema aliases. Save/Patch/settings/generation payloads use generated types; no any.
- Lead owns src/frontend/e2e/** and playwright.config.ts. I did not run browser screenshots/live Compose flows; desktop1440/mobile390, keyboard, source sheet and overflow still require lead verification.
- External HTTP stubs prove frontend behavior, not provider/model access or durable PostgreSQL persistence. No configured paid-model proof claimed.
- Existing PRODUCT.md schema drift reported by Impeccable; no context files modified.

## Targeted visual correction follow-up (2026-10-08)
- Root captures showed raw backend source UUID markers in generated prose. Added exact lowercase `[source:UUID]` display filtering only; the persisted content and validated Citation controls remain intact. Malformed and differently-cased marker text stays visible.
- Observed two real failing regressions before implementation: direct generated prose had markers, and composed conversation answer retained marker text. After correction both pass; the composed conversation still opens Page2 source and original PDF link.
- Corrected singular search count to `1 result`.
- Refreshed generated API from actual teststack API8001 using installed openapi-typescript7.13.0.
- Final actual verification: targeted2files/12tests passed; full npm check strictTS+ESLint+Vitest5files/20tests passed; production build passed (main467.62KB, paper173.64KB, CSS24.24KB).
- No root E2E/config changes or second detector. Root owns browser captures and integration.

## Per-response model visibility correction (2026-10-08)
- Root live-demo review found assistant history/drafts omitted stored model and reasoning effort. Added shared response metadata display to both persisted and draft assistant articles using message.model/reasoning_effort, never the current form selection; absent values are labelled as not recorded.
- Observed two real rendering failures before implementation: persisted Luna/low label missing while model control was Terra/high; streaming partial Luna/low label also missing.
- Corrected both and ran complete npm check: strict TypeScript, ESLint, 5files/21tests passed. npm build passed (main467.62KB, deferred paper173.96KB, CSS24.24KB).
- Only src/components/ChatPanel.tsx and src/pages/workflows.test.tsx changed for this correction. No new dependencies, root E2E/script edits, or paid generation runs.

## UI overhaul (2026-10-08, ARA-033 to ARA-040)

The user rejected the first frontend and pinned a chat-centred shadcn workspace in the class of ChatGPT, Claude, Elicit and Undermind. They asked for shadcn's default neutral black-and-white palette, light and dark themes following the system, an in-app PDF viewer, and a sleek model switcher.

### Process
The work ran on `feat/ui-overhaul` with git worktrees and agents that owned disjoint parts of the code:
- a backend history API agent
- content (Markdown, math, citations)
- conversation (chat and summary)
- workspace (PDF reader and evidence jump)
- research (search, library, activity, settings)
- a later evidence fix after the review

The lead built the foundation and the cross-module contracts, integrated each branch, and ran the serial E2E suite. The user required TDD-first. Where work had been tested after the fact, the agents audited it, labelled it test-after and verified it with mutation checks.

### Result
- **Shell:** shadcn radix-nova with neutral oklch tokens and self-hosted Geist. A collapsible sidebar lists papers and recent chats and searches. There is a ⌘K palette.
- **Home:** one composer that searches OpenAlex or Semantic Scholar, or asks a library paper.
- **Search:** results render as a research thread that shows each paper's saved state.
- **Library and Activity:** the library filter is kept in the URL, and the upload dialog opens from the library. Activity shows readable stages and offers retry.
- **Settings:** default model, reasoning effort and theme.
- **Paper workspace:** a resizable split between a pdf.js reader and the conversation. The summary is the first card. Answers stream with inline page chips. A chip jumps to the page and marks the supporting sentence character-precisely. On mobile, the workspace becomes Chat/PDF/Details tabs.

### Verification
- Vitest 338/338.
- ESLint 0 problems and strict tsc clean.
- Playwright 8/8 on a fresh e2e database.
- Impeccable detector 0 findings.
- A fresh-context finish review scored every material UI fix resolved. Details are in docs/agent-development-log.md and ARA-033 to ARA-040.
- First-paint JS is about 550 KB raw (172 KB gzip). The workspace and pdf.js load lazily.
