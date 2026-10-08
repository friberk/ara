# AI Research Assistant

A local research workspace for CS59300. Search Semantic Scholar or OpenAlex, save papers, upload PDFs, and use paper content for summaries and questions. The architecture is a React SPA and a modular FastAPI backend with durable workers and persistent storage.

## Start locally

Requirements: Docker with Compose, enough memory for approximately six small services, and Python3 for the environment bootstrap. Dockerfiles target ARM64 and x86_64; the verified build is ARM64 on an M3 Pro using OrbStack. GPU inference is optional.

```bash
python3 scripts/bootstrap.py
```

This creates an ignored, private `.env` with random internal credentials and preserves existing configuration. Set `OPENAI_API_KEY` there for hosted summaries/questions. Academic credentials are optional; Semantic Scholar can rate-limit anonymous access. Never paste keys into the application or commit `.env`.

```bash
docker compose up --build
```

Open <http://localhost:5173>. API documentation is at <http://localhost:8000/docs>. Change `FRONTEND_PORT`, `API_PORT` and `CORS_ORIGINS` together when using different local ports. Browser calls use the Vite `/api` proxy; credentials remain on the backend. PostgreSQL, Redis and MinIO have no host ports by default.

Default startup initializes the private PDF bucket and runs Alembic before starting the API/worker. It works without LLM credentials; analysis then reports missing model access. No model weights download during startup.

Source edits use Vite HMR, Uvicorn reload and Dramatiq watch. Rebuild images after dependency or Dockerfile changes. PostgreSQL, Redis and MinIO named volumes survive normal shutdown:

```bash
docker compose down
docker compose up
docker compose logs --tail 100 api worker
docker compose run --rm migrate
```

Redis is job transport; PostgreSQL stores durable execution state and outbox records. Dispatch/recovery runs in API lifespan, so pending work resumes when the API returns. PDF parsing runs in an isolated child process. MinIO stores original bytes; PostgreSQL stores bibliographic data, pages/chunks, jobs and analysis history.

## Verify

```bash
python3 scripts/test-stack.py test
docker compose exec frontend npm run check
docker compose exec frontend npm run build
python3 -m unittest discover -s tests/infrastructure -v
python3 -m unittest discover -s tests/fixtures -v
```

The backend helper forces a separate `ara-test` Compose project/database/buckets. It runs Ruff and pytest against real PostgreSQL, Redis and MinIO. Fixtures replace only external academic/LLM HTTP services. They demonstrate deterministic behavior; live provider/model checks are separate.

Browser test environment:

```bash
uv run --with pymupdf==1.26.7 python tests/fixtures/create_pdf.py /tmp/ara-fixtures/research.pdf
docker compose -p ara-e2e -f compose.yaml -f compose.test.yaml -f compose.e2e.yaml up --build -d
cd src/frontend
npx playwright install chromium
npx playwright test
```

The fixture UI uses port5180 and API8001. Wait for the frontend/API health checks before browser tests; inspect them with the same Compose files and `ps`. Test fixtures explicitly use synthetic papers and delayed model streaming; they are never activated by normal startup. The browser commands require Node24/npm and uv on the host. Development and test data are isolated.

Test data reset is explicit and affects only `ara-test`:

```bash
python3 scripts/test-stack.py reset --reset-data
```

For development data reset, inspect the project and back up original PDFs/database first; `docker compose down --volumes` deliberately deletes the project's persistent volumes. Ordinary shutdown uses `down` without that flag.

## Models and source grounding

Hosted IDs: `gpt-5.6-luna` (default), `gpt-5.6-terra`, `gpt-5.6-sol`. Supported reasoning controls come from backend capabilities. Missing keys, provider outages and unavailable models are reported. Metadata-only papers require a processed PDF before analysis.

Lexical retrieval stays within the selected document and preserves page references. Conversation history and summaries persist locally. Each assistant response records its model and reasoning effort. Model text is generated; citation controls show source passages and link to the original PDF page. Citation validation checks source identity; readers should verify factual support. Prompt instructions embedded in PDFs are treated as untrusted source text.

Optional local inference is deferred: this Mac cannot use an ordinary CUDA Compose container for Metal GPU inference. Qwen3.8 Q4_K_M would use a separately verified host-native llama.cpp endpoint; NVIDIA vLLM serving would use a separate opt-in profile. See the implementation plan for exact compatibility findings. OCR is also optional.

## Agent skill and project records

The installed local skill is `.agents/skills/pymupdf-pdf/SKILL.md`. Its executable parser supports Markdown, JSON, images and rough ruled-table output. It is independent of the application's parser. Generated output is ignored; the script has a pinned uv lockfile. Run the skill command from its directory or use `uv run --locked --script` with the parser path.

Architecture, traceability, priorities and milestones: [implementation plan](docs/implementation-plan.md). Exact API shapes: [API contract](docs/api-contract.md). Actual development observations: [agent journal](docs/agent-development-log.md). Stable issues: `issue_tracker/ARA-*.json`. Current delivery status and verification: [execution progress](docs/execution-progress.md) and [verification record](docs/verification-final.md).

A live five-workflow recording is available locally at `docs/evidence/generated/live-demo/live-demo.webm`; generated evidence is ignored by Git. The [submission checklist](docs/submission-checklist.md) supports the student's own reflection and final submission. GitHub publishing is deferred at the user's request; the workflow under `.github/workflows/ci.yaml` is prepared but has not run remotely.

## License and third-party dependencies

Project source is licensed under AGPL-3.0; see LICENSE. MinIO community is archived and source-only. The custom image builds pinned upstream source, retains its license/source references, and is intended for this local homework environment. PyMuPDF has AGPL/commercial licensing. See `docs/third-party-notices.md`. Credentials, original uploaded papers and generated private data are excluded from version control.
