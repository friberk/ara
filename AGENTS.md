# AGENTS.md

ara. is a single-user research assistant. It searches OpenAlex and Semantic Scholar, keeps a persistent paper library, reads uploaded or retrieved PDFs, and writes summaries and answers that cite the pages they came from. A React SPA talks to a FastAPI backend with Dramatiq workers, PostgreSQL (with pgvector), Redis and MinIO, all run by Docker Compose.

The app is Homework 1 for Purdue's CS 59300. The application is 60% of the grade and a reflection report on working with coding agents is 40%, so the development record matters as much as the code.

- `hw1.md` is the assignment and the final word on scope. It is kept locally and not committed. [`docs/implementation-plan.md`](docs/implementation-plan.md) is the approved plan.
- [`README.md`](README.md) is the plain-language overview. [`docs/reference.md`](docs/reference.md) covers every setting, limit and test fixture.
- The source is AGPL-3.0 and public at [`friberk/ara`](https://github.com/friberk/ara). CI deploys `main` to the demo server.
- `AGENTS.md` and `CLAUDE.md` are identical copies of this guide: Codex and most agents read the first, Claude Code the second. Make every change in both, in the same commit. `tests/infrastructure/test_agent_guides.py` fails when they differ.

## Commands

The stack runs in Docker. The host needs Docker with Compose and Python 3; browser tests also need Node 24 and `uv`.

```bash
python3 scripts/bootstrap.py               # create a private .env (keeps existing values)
docker compose up --build                  # app on :5173, API docs on :8000/docs
docker compose logs --tail 100 api worker
docker compose run --rm migrate            # apply Alembic migrations
docker compose down                        # stop; data and model weights survive
```

Source edits reload on their own (Vite HMR, Uvicorn reload and a debounced worker wrapper). Rebuild after changing dependencies or a Dockerfile.

Checks (CI runs these, then Playwright and an API-contract check):

```bash
python3 scripts/test-stack.py test         # Ruff + pytest against real services in the isolated ara-test project
docker compose exec frontend npm run check # tsc, ESLint, Vitest
docker compose exec frontend npm run build
python3 -m unittest discover -s tests/infrastructure -v
```

Once a full backend run has left the test services up, rerun one file:

```bash
docker compose -p ara-test -f compose.yaml -f compose.test.yaml \
  run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest tests/test_chat_cost.py
```

Playwright journeys run against a separate fixture stack, `ara-e2e`, with open models on; see [the reference](docs/reference.md#verify) for the steps. After changing an API schema, start that stack and regenerate the frontend types from it, as CI does:

```bash
cd src/frontend && npx openapi-typescript http://127.0.0.1:8001/openapi.json -o src/api/generated.ts
```

CI fails when `src/frontend/src/api/generated.ts` drifts. Don't use `npm run generate:api` for the committed file: it reads the development API, whose routes differ.

## Repository map

| Path | Contents |
| --- | --- |
| `src/backend/app/` | FastAPI app, layered as `routes/` → `services/` → `repositories/`, with `schemas/` (Pydantic), `models/` (SQLAlchemy), `integrations/` (providers and model catalogs), `jobs/` (Dramatiq actors) and `rag/` (chunking, retrieval, packing, citations). |
| `src/backend/alembic/versions/` | Schema migrations. |
| `src/backend/tests/` | pytest. `*_integration.py` files need the real services. |
| `src/frontend/src/` | React app: `features/` holds screens, `components/ui/` holds shadcn primitives, `api/` holds the client and generated types. |
| `src/frontend/e2e/` | Playwright journeys. |
| `compose*.yaml`, `docker/` | Compose stacks (development, test, e2e, deploy, GPU) and images. |
| `scripts/` | Bootstrap, the isolated test stack, deployment and the demo recording. |
| `issue_tracker/` | One `ARA-NNN.json` per issue. |
| `docs/` | Plan, API contract, reference, development journal, archive-branch list. |
| `report/` | The reflection report and its PDF build. |
| `PRODUCT.md`, `DESIGN.md` | Product brief and design system for UI work. |

## Architecture rules

These hold across the codebase. Most exist because a failure here loses data, double-charges a paid model or breaks a citation.

**Storage**
1. Original PDFs live in MinIO. Metadata, pages, chunks, jobs, summaries and chats live in PostgreSQL.
2. Alembic owns the schema, and nothing calls `create_all` at startup. Add a new revision rather than editing an existing one; `0007_feature_merge` joins two branches without rewriting them for this reason.
3. A chunking change re-ingests old chunk sets through startup jobs. Citation snapshots stored on past answers must stay readable.

**Concurrency and jobs**
4. Every request, actor and parallel task opens its own `AsyncSession`. Engines and HTTP clients belong to one process and its event loop.
5. PyMuPDF runs only in child processes, never in threads or on the API's event loop: it is not thread-safe and blocks.
6. PostgreSQL job and outbox state is authoritative; Redis only delivers. Deliveries can repeat, so every actor must be safe to run twice.
7. A chat request UUID never replays paid generation.
8. The development worker reloads through `app.jobs.development_worker`, which debounces edits and stops the old process tree. Don't add Dramatiq's `--watch`.

**Models**
9. Every model-backed feature goes through a catalog (`integrations/hosted_catalog.py`, `embedding_catalog.py`, `reranker_catalog.py`). Settings store a catalog key, and logic never hardcodes a model ID.
10. Reasoning levels come from each model's catalog entry. Keep saved preferences even when they are unavailable, keep raw API compatibility and keep the settings recorded on past answers. Never save a display normalization automatically.
11. Extra calls made on a chat's behalf, such as query rewriting and summarizing older turns, use that chat's current model and reasoning effort.

**Citations and retrieval**
12. A page citation must belong to the summarized document, or to a paper attached to the chat.
13. Canonicalize the model's `【source:UUID】` wrapper before validating, persisting or reusing a checkpoint. IDs and document membership stay strict: a malformed or foreign source fails the answer. Never promote a failed generation or replay a request to fix formatting.
14. A search index belongs to one embedding model. Vectors from different models can't be compared, so never mix them in one index.
15. Context and history budgets are computed from each model's catalog window and price tier. Derive new sizes from them instead of adding standalone constants.
16. Retrieval thresholds and budgets follow published practice. Cite the source in code or in [`docs/plans/retrieval-orchestration.md`](docs/plans/retrieval-orchestration.md); don't invent a number.

## Open models (experimental, frozen)

Local models (Ollama, `model-worker`, local embeddings and reranking) are frozen. They are off by default; to turn them on, set both `EXPERIMENTAL_OPEN_MODELS=true` and `COMPOSE_PROFILES=open-models` in `.env`. Design new features for hosted models, don't extend open-model code unless the user lifts the freeze, and keep its tests passing with the flag on. Read [`docs/open-models-invariants.md`](docs/open-models-invariants.md) before touching that code.

## Code style

- Backend: Python 3.13, FastAPI, Pydantic v2, async SQLAlchemy with psycopg 3, `httpx`. Keep routes, schemas, models, repositories, services, integrations and jobs in their own modules. Ruff settings are in `src/backend/pyproject.toml`.
- Frontend: React with Vite, strict TypeScript, React Router, TanStack Query for server state, React Hook Form with Zod for forms, Tailwind v4 with shadcn components. Ask before adding a client-state library such as Zustand.
- API types come from the generated OpenAPI file; `src/frontend/src/api/types.ts` only aliases them. Don't hand-write response shapes.
- Manage dependencies through `uv` and npm lockfiles.
- When a change replaces a behaviour, delete the old path instead of keeping both behind a flag. Code reachable only by old internal data can go too, as long as that data still fails safely. The open-models flag is the one exception.
- Prefer established tools (LlamaIndex, pgvector, PyMuPDF) over custom infrastructure.
- Interface copy describes what the user can do, not how the system works inside.

## Testing

- Write the test first. Run it and see it fail for the expected reason, then implement and refactor. Record the order truthfully.
- Write acceptance criteria as Given/When/Then.
- `scripts/test-stack.py` only accepts `ara-test` or `ara-<name>-test` projects. Point integration fixtures at those, never at the development stack (`ara`), which holds the user's papers and chats.
- An autouse guard rejects requests to real external hosts, and providers are replaced by HTTP fixtures. A passing fixture proves deterministic behaviour, not live provider access.
- Open-model tests turn the flag on through the `open_models` pytest marker or a mocked `/features` reply in Vitest.

## Workflow

- The root checkout is shared with the user's development stack and other sessions, so don't switch its branch. Work on a new branch in a worktree under `.superpowers/worktrees/`, named like `feat/ara-NNN-short-name`. A new worktree has no `.env`, so run `python3 scripts/bootstrap.py` in it before using Compose.
- Before merging into `main`, check the root's branch with `git branch --show-current`. If the root has `main` checked out, merge there; otherwise merge in a temporary worktree of `main`. `main` moves often, so expect a real merge rather than a fast-forward, and check `git status` for conflicts before anything else runs.
- Merged branches stay as archives. Don't delete them, and add each new one to [`docs/archive-branches.md`](docs/archive-branches.md).
- Commit with Conventional Commits and the issue ID, for example `fix(jobs): retry failed section summaries at startup (ARA-105)`. Add `[skip ci]` to documentation-only commits on `main` so they don't redeploy.
- Track work in `issue_tracker/` (format in [its README](issue_tracker/README.md)). Take the next free ID, never renumber, and record the commits that close an issue.
- Record prompts, decisions, failures and evidence in [`docs/agent-development-log.md`](docs/agent-development-log.md) as they happen. The reflection report is built from it.
- With several agents, one owns migrations and shared contracts at a time, the others write disjoint modules, and the lead verifies the integration.
- The user decides scope and when to stop iterating. Finishing the five required workflows is a milestone, and the P1/P2 backlog continues after it; submission work runs alongside. Don't recommend a scope freeze because the homework minimum is met or from guessed human-hour estimates. Base forecasts on observed agent throughput, dependencies and measured limits.

## Deployment

CI's `deploy` job ships `main` to <https://vps-eb56b28c.vps.ovh.us> once `verify` passes. Caddy admits Purdue's AS17 addresses without a password and asks everyone else for the demo login. Purdue's VPN is split-tunnel, so VPN users don't count as campus.

```bash
SITE_HOST=vps-eb56b28c.vps.ovh.us scripts/deploy.sh ara-deploy@15.204.210.41   # manual deploy
ssh ara-deploy@15.204.210.41 'cd /opt/ara && docker compose logs --tail 100 api worker caddy'
```

Provider keys live only in the server's `/opt/ara/.env`, which `deploy.sh` never syncs. After a check that creates data on the server, reset its PostgreSQL, Redis and MinIO volumes and keep `ara_caddy-data`, which holds the TLS certificates.

## Boundaries

**Ask first**
- Merging into `main` or pushing: a push to `main` redeploys the public demo.
- Adding a Compose service, image or major dependency.
- Any work that extends open models.

**Never**
- Modify `hw1.md`, `hw1.pdf` or the writing skills in `.agents/skills/`.
- Commit credentials, `.env`, uploaded PDFs, model weights, generated evidence (`docs/evidence/generated/`) or private interaction logs.
- Run `docker compose down --volumes` on the development stack or the server. It deletes papers, chats and model weights; reset test data with `python3 scripts/test-stack.py reset --reset-data`.
- Delete, rebase or force-push a merged branch.
- Add `Co-Authored-By` trailers to commits.
- Invent an interaction, a result or evidence, or claim a test passed without its output.

## Definition of done

- The acceptance criteria are met, and the relevant checks ran and passed with their output recorded.
- Nothing critical regressed, and the five required workflows still work: academic search, the persistent library, PDF upload with metadata, content-grounded summaries and paper-grounded Q&A.
- Migrations, [`docs/api-contract.md`](docs/api-contract.md) and the generated types are current.
- Compose starts and reloads, and data survives a restart.
- The issue and the development journal are updated with real evidence.
