# AI Research Assistant

Single-user CS 59300 homework application. `hw1.md` is the assignment authority; `docs/implementation-plan.md` is the approved project plan. Required workflows: academic search, persistent library, PDF upload/metadata, content-grounded summaries, paper-grounded Q&A. Homework due October 10, 11:59 PM; app 60%, reflection 40%.

## Architecture

- `src/backend`: Python 3.13, FastAPI/Pydantic v2, async SQLAlchemy/psycopg 3, Alembic, httpx, Dramatiq/Redis, PyMuPDF. Separate routes/schemas/models/repositories/services/integrations/jobs.
- `src/frontend`: React/Vite, strict TypeScript, Tailwind v4/shadcn, React Router, TanStack Query; React Hook Form/Zod for forms. No initial Zustand.
- Compose runs frontend, api, worker, model-worker, Ollama, PostgreSQL, Redis and MinIO plus migration/bucket-init gates. Default local inference uses CPU; NVIDIA/AMD overrides are optional and require compatible Linux hosts.
- PDFs belong in MinIO; metadata, pages/chunks, jobs, summaries and chats belong in PostgreSQL. Complete and partial model weights belong in the `ollama-models` named volume; startup downloads and loads no weights. Core readiness is independent of Ollama.
- Every request/actor/parallel task owns its AsyncSession. Engines/clients belong to one process/event loop. PyMuPDF runs in child processes, never concurrent threads or the API event loop.
- PostgreSQL job/outbox state is authoritative; duplicate deliveries must be safe. Chat request UUIDs must not replay paid generation. Page citations must belong to the selected document.
- Local model mutations and global inference admission use durable PostgreSQL ownership. Pause is complete only after the managed runtime acknowledges settled work; recovery must settle every unresolved current or previous operation UUID before releasing ownership. Unknown valid UUID pause establishes a per-daemon canceled tombstone, so late same-UUID pull is rejected. Never infer safe settlement from 404 or restart the daemon to pause.
- Unconfirmed transfer failures remain fenced in durable `settling` cleanup until acknowledgment; do not admit inference or another mutation while pending UUIDs exist. Summary provenance is checkpointed under admission, not reread after generation. Native sampling explicitly uses temperature 0.0.
- Local selection requires verified artifact/runtime/context capabilities. Preserve defaults and histories when deleting weights; never fall back from a local request to paid generation. Only IFM 7B has live ARM64 CPU evidence in ARA-022; fixtures do not prove 3.7B/27B or GPU feasibility. The 12g ceiling is not startup resident memory and does not accommodate 27B by itself.
- Reasoning controls belong to each model. Hosted entries are keyed by model ID; native entries use verified `thinking.values`/`thinking.default` and exact Boolean/string mappings. Never infer named levels from HTTP 200 or obsolete `thinking_levels`. Capability-schema/runtime changes require verification using retained weights.
- Canonicalize the observed `【source:UUID】` wrapper before final citation validation, persistence and active-checkpoint reuse. IDs and document membership remain strict; malformed/foreign sources fail. Do not promote failed generations or replay requests while correcting formatting.

## Workflow

The verified core implementation is on `main`; managed local models are verified on `feat/managed-ollama` and remain unmerged at the user’s request. Retain `feat/ai-research-assistant` as an archive at `526ef68`. The chat-centred UI overhaul (ARA-033 to ARA-040) was fast-forwarded into `main` at `dd9a96d`; retain `feat/ui-overhaul` and its agent branches (`feat/ui-api`, `feat/ui-content`, `feat/ui-conversation`, `feat/ui-workspace`, `feat/ui-research`, `feat/ui-evidence`) as archives. Use new feature branches for subsequent changes. Commit messages carry no Co-Authored-By trailer. The initial checkout had no HEAD, so implementation began in place; that historical limitation is recorded in the journal. Do not modify `hw1.md`, `hw1.pdf`, or existing writing skills.

Use Given/When/Then acceptance criteria and practical red-green-refactor cycles. Log actual failures and corrections; never invent interactions or claim a test passed without output. Track work in `issue_tracker/` using `ARA-*` IDs. Record relevant prompts, decisions, errors and evidence in `docs/agent-development-log.md`.

Completing the mandatory workflows is a milestone; continue the intended P1/P2 iterations. Do not recommend a scope freeze from unvalidated human-hour estimates or the homework baseline alone. Base forecasts on observed agent throughput, task dependencies, and measured technical/resource constraints. The user decides scope and iteration limits. Submission preparation can proceed alongside feature work. See ARA-041 for the actual premature-freeze feedback.

Use `uv`/npm lockfiles, Ruff, pytest/pytest-asyncio, ESLint/strict tsc, Vitest/RTL, Playwright. Prefer generated OpenAPI TypeScript contracts. Alembic owns schema changes; no startup `create_all`. Commit identifiers where practical; one agent owns migrations/shared contracts. Independent agents may write disjoint modules; lead verifies integration.

ARA-022 implementation uses `feat/managed-ollama` and the approved specification in `docs/plans/ARA-022-managed-local-models.md`; integration into `main` remains a separate step. Use Conventional Commits with ARA IDs. Worker development reload uses `app.jobs.development_worker`, which debounces source events and settles the old process tree; do not add Dramatiq `--watch` to it.

## Commands

Bootstrap: `python3 scripts/bootstrap.py`. Start: `docker compose up --build`. Logs: `docker compose logs --tail 100 api worker model-worker ollama`. Migrate: `docker compose run --rm migrate`. Backend tests: `python3 scripts/test-stack.py test` against isolated real services; never run destructive integration fixtures on development data. Frontend: `docker compose exec frontend npm run check` and `npm run build`. Browser fixtures, GPU overrides and the opt-in isolated 7B runner are in README. Stop: `docker compose down` without `--volumes` to preserve data and weights.

## Definition of Done

Acceptance met; relevant tests executed successfully; no critical regression; contract/migration docs current; Compose/reload works; data survives restart; issue and genuine agent evidence updated. External fixtures prove deterministic behavior, not live provider access. Source is AGPL-3.0; GitHub pushing is deferred by the user. No credentials, uploaded PDFs, generated output or private interaction logs in commits.
