# Phase0 verification evidence

Actual delegated commands/results on2026-10-08. Phase0 passed before subsequent feature implementation. Reports are preserved here for reflection evidence; no externalprovider/hostedmodel success is implied.


# PyMuPDF PDF local skill implementation

Scope: created only `.agents/skills/pymupdf-pdf/**` in the repository. Existing writing skills, backend, root documentation, Compose, and assignment files were untouched. No commits or subagents.

Files: SKILL.md; references/pymupdf-notes.md; executable scripts/pymupdf_parse.py; its uv-generated pymupdf_parse.py.lock; tests/test_parser.py.

CLI: `./scripts/pymupdf_parse.py input.pdf --format md|json|both --images --tables --outroot ./pymupdf-output --lang en`, run from the skill directory. Default format is md. Equivalent explicit command `uv run --script scripts/pymupdf_parse.py input.pdf`; `--locked` was exercised successfully.

Outputs: per input basename, `output.md` (numbered page boundaries), `output.json` (filename, language hint, metadata, count and numbered pages with bbox/text, optional image objects), `images/` (embedded raster images), and `tables.json` (page, bbox, rows). Only requested formats/options are emitted.

Dependency: PEP 723 exact `pymupdf==1.26.7`, Python >=3.11,<3.15, adjacent script lockfile containing public PyPI URLs and hashes. No global package installation. Local extraction uses documented `get_text`, `get_images`, `extract_image`, and `find_tables(strategy="lines")` APIs; official documentation links are in the reference.

Invariants: input opened read-only; no remote document access or document-driven shell commands; rejected existing output (including destination symlinks); per-basename lock prevents cooperating concurrent parser instances; complete output staged on same filesystem and renamed into place; ordinary failures remove staging/lock. No partial destination for malformed/encrypted failures. Password-required PDFs fail clearly, without password bypass. Images have generated relative paths with a validated extension. Output root must be trusted against deliberate concurrent external filesystem mutation.

Observed red: before implementation, six tests / seven cases failed with FileNotFoundError for the absent parser (exit 1). This was an actual behavior run, not a simulated agent interaction.

Observed green: `uv run --with pymupdf==1.26.7 python -m unittest discover -s .agents/skills/pymupdf-pdf/tests -v` -> `Ran 6 tests in 1.050s; OK`. Covered synthetic two-page text/metadata, default Markdown boundaries, JSON-only mode, both output mode, language hint, embedded image decode, ruled table rows, encrypted/malformed inputs, repeated collision preserving original bytes, and symlink safety. Tests use disposable synthetic inputs only.

Validation: `quick_validate.py` initially failed under system python3 with ModuleNotFoundError: yaml. Corrected by isolated `uv run --with pyyaml python .../quick_validate.py .agents/skills/pymupdf-pdf`, output `Skill is valid!` (exit 0). Ruff first reported unsorted imports and subprocess.run missing explicit check; corrected and formatted. `uv run --with ruff ruff check --isolated .../scripts .../tests` -> `All checks passed!`; reran six behavior tests successfully after correction.

Actual explicit CLI smoke: `uv run --locked --script .agents/skills/pymupdf-pdf/scripts/pymupdf_parse.py /tmp/ara-pymupdf-smoke-3x4mon6h/smoke.pdf --format both --images --tables --lang en --outroot /tmp/ara-pymupdf-smoke-3x4mon6h/results` -> exit 0, published `/private/tmp/ara-pymupdf-smoke-3x4mon6h/results/smoke`. JSON assertions confirmed language en, one page, expected text, empty tables; output artifacts verified: images, output.json, output.md, tables.json. PyMuPDF itself emitted an optional pymupdf_layout recommendation; no additional package installed.

Limitations: no OCR; language hint is recorded only. Basic Markdown does not reconstruct visual layout or math. Images are embedded raster objects; separate transparency masks are recorded but not composited, and vector figures are not exported. Line-based tables are rough and need review. Native parser has no standalone resource caps. Nix troubleshooting guidance directs use of existing project environment and avoids global/system changes. Abrupt termination may leave hidden staging/lock; manual cleanup requires verifying no parser is running. No uploaded PDFs or generated outputs are in the skill bundle.


# ARA-003 infrastructure evidence

Owned files: compose.yaml, compose.test.yaml, docker/{backend,frontend,minio}.Dockerfile, .dockerignore, .env.example, scripts/{bootstrap,test-stack}.py, tests/infrastructure.

- Official MinIO sources inspected: pinned commit go.mod requires Go 1.24/toolchain 1.24.8; buildscripts/gen-ldflags.go defines version/commit/release constants. Source archive fetched with curl TLS verification; SHA256 71794c2df26aad0cc99e8421c58b7aa2dd55969f979b0e7d1e931042e9fabcd6. GitHub commit date 2026-02-12T20:18:48Z.
- docker buildx imagetools inspect resolved multiarch OCI index digests for Python3.13.12, Node24.14.0, PostgreSQL17.9, Redis8.2.4, Go1.24.13, uv0.10.8. Digests captured directly in checked-in Dockerfiles/Compose. No upstream MinIO image used.
- docker build --file docker/minio.Dockerfile --tag ara-minio:7aac2a2c5b7c . : PASS on linux/arm64. Build verifies archive SHA256 and go mod verify, CGO_ENABLED=0/GOOS=linux/TARGETARCH. Build log /tmp/ara-minio-build.log (no secrets).
- docker run --rm ara-minio:7aac2a2c5b7c --version : reports pinned commit, explicit DEVELOPMENT.2026-02-12T20-18-48Z, Go1.24.13 linux/arm64.
- Initial python3 -m unittest discover -s tests/infrastructure -v: FAIL two bootstrap assertions because script absent. After implementation: PASS2/2.
- Initial reset-helper acceptance check: FAIL because helper absent; after implementation full unittest discovery PASS3/3.
- python3 scripts/bootstrap.py : generated private mode0600 ignored .env. Values not printed; independent tests prove generated passwords differ, are >=32chars and existing env content preserved.
- docker compose config --quiet : PASS. docker compose --project-name ara-test --file compose.yaml --file compose.test.yaml config --quiet : PASS. python3 scripts/test-stack.py config : PASS.
- docker compose up --detach --wait postgres redis minio : PASS, all three healthy. No infrastructure hostports; frontend/API loopback-only.
- docker compose build api frontend : PASS. Locked uv/npm deps stay in /opt/venv and frontend container node_modules.
- uv tool run --from ruff==0.15.5 ruff check scripts/bootstrap.py scripts/test-stack.py tests/infrastructure : PASS.
- docker compose run --rm --no-deps -T api uv run --frozen python - (Minio SDK via backend Settings): generated synthetic PDF-like bytes, uploaded foundation-checksum-canary to research-pdfs, restored original SHA256: PASS.

Storage restart follow-up, full main stack/migration/reload, isolated backend integration, and database persistence still pending at this interim write. No live academic or hosted-model access claimed. Lead owns docs/issues and user reference files remain untouched.

## Final integration follow-ups

- Original MinIO object survived `docker compose restart minio` with the same SHA256; temporary object removed: PASS.
- Safe in-memory Compose JSON assertions verified ara-test project, database ara_test, bucket research-pdfs-test, all volume names prefixed ara-test_, no published ports, and hosted/academic API-key env vars empty: PASS.
- `docker compose up --detach --build --wait` : PASS. Six persistent services running (five explicit healthchecks healthy; worker running and functional); migrate/storage-init exited0. Fresh frontend-node-modules volume populated from rebuilt Vite8.3.4 frontend image.
- HTTP GET /health/ready on API8000 and Viteproxy5173: PASS, database/storage/Redis each ok.
- API POST /api/v1/jobs/canary then polling terminal state: PASS completed with stored expected result through actual PostgreSQL outbox, Redis broker and Dramatiq worker. Canary UUID stored only in /tmp/ara-foundation-canary.json.
- Actual concurrent backend edits naturally triggered API WatchFiles reload/new server startup and worker SourceChangesHandler SIGHUP/new worker process ready. Logs observed; no backend/frontend source edited by infrastructure agent.
- Synthetic S3 bytes and Redis persistence marker written, `docker compose down` then `docker compose up --detach --wait` (no --volumes): PASS, completed PostgreSQL canary retained, S3 SHA256 retained, Redis AOF marker retained. S3/Redis temporary fixtures removed afterward.
- Initial isolated backend test run: RuffPASS, pytest9passed1failed. Failure test_environment_overrides_dotenv_and_secrets_are_redacted inherited MINIO_SECRET_KEY from container while expecting dotenv value; backend owner corrected fixture with monkeypatch.delenv.
- Test-helper repeat startup actually failed with `container ara-test-migrate-1 exited (0)`: Compose up--wait directly targeting one-shot jobs can reject successful completion. Corrected helper to build backend, health-wait only postgres/redis/minio, then explicitly run migrate/storage-init and check their exit codes before tests.
- Backend owner's direct isolated pytest subsequently PASS12/12; helper repeat `python3 scripts/test-stack.py test` also PASS12/12 in6.26s after fix. Real-service integration tests enabled via ARA_INTEGRATION=1 and dedicated ARA_TEST_DATABASE_URL. Log /tmp/ara-test-helper-final.log.
- Infrastructure final `python3 -m unittest discover -s tests/infrastructure -v`: PASS3/3. Final infrastructure RuffPASS.
- `docker compose exec -T frontend npm run check` during ongoing frontend edits: typecheckPASS, ESLintFAIL unused _response/_onEvent in newly created src/api/sse.ts stub. Source owner notified; no infrastructure-source fix attempted. Log /tmp/ara-container-frontend-check.log.
- Frontend HMR update proof is still pending; Vite ready log observed but no actual hot update captured yet. Lead requested source-owner coordination before timestamp-only probe.

Development stack remains running and healthy. Test infrastructure remains running with own volumes; test API/worker remain stopped (repository tests own state). No credentials printed, no user reference files modified, no commits made.


# ARA-004 / ARA-008 backend Phase 0 foundation

Owned only `src/backend/**`; no commits, root infrastructure edits, or docs/tracker edits. Worked in the authorized feature checkout; no linked worktree because checkout initially has no HEAD. Assignment/writing-skill files preserved. Lead should reconcile this report into the tracked journal/issues.

Implemented Python 3.13 uv project+lock; FastAPI/Pydantic Settings; redacted JSON logs; bounded process-owned engine, httpx, Redis and MinIO resources; request UUID and structured safe errors; liveness/readiness without external credentials; nullable `Job.error` contract; database-backed job list/detail and development-only canary creation. Production canary returns404 and is omitted from OpenAPI. Readiness checks Alembic revision0001_jobs plus job tables, bucket existence and Redis ping.

Alembic owns `background_jobs`/`job_outbox`, including state/attempt/progress constraints and unique job/generation outbox. Dispatcher is API lifespan task, two-second default poll, startup/thirty-second recovery, own sessions, SKIP LOCKED, publish-before-delivered commit, synchronous Redis publish in a thread with five-second socket/connect deadlines. Job claim increments attempt atomically, generation+token+unexpired lease fences completion/failure/heartbeats. Lease60seconds, heartbeat10seconds, three total attempts, PostgreSQL retry generation/backoff+jitter, stale duplicate claims no-op, expired-processing and delivered-unclaimed recovery. Broker outage preserves pending state. Dramatiq AsyncIO worker resources created after fork on its own loop and disposed in reverse middleware shutdown before loop stops. Actor max_retries0; canary handler verifies pipeline.

Private MinIO initialization is `uv run --frozen python -m app.core.storage_init`: creates bucket idempotently and removes anonymous policies. SDK calls use bounded semaphore/to_thread with connect5/read10 timeouts. Original byte read checks maximum size and always closes/releases response.

Exact runtime contract: APP_ENV=development; DATABASE_URL=postgresql+psycopg://...; REDIS_URL=redis://:password@redis:6379/0; MINIO_ENDPOINT=minio:9000; MINIO_ACCESS_KEY; MINIO_SECRET_KEY; MINIO_BUCKET=research-pdfs; MINIO_SECURE=false; CORS_ORIGINS JSON array. Optional BROKER_NAMESPACE defaultdramatiq. Environment > optional dotenv > defaults; explicit constructor overrides only for tests. uv environment /opt/venv in containers, cwd/app. Commands `uv run --frozen alembic upgrade head`, `uv run --frozen uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`, `uv run --frozen dramatiq app.jobs.actors --processes 1 --threads 2 --watch app`.

Actual red/green evidence:
- `/tmp/ara-backend-red.txt`: initial six tests failed ModuleNotFoundError because application did not exist; 6failed0passed.
- First editable wheel was built before app/__init__.py existed; rebuilding editable package with `uv sync --reinstall-package ai-research-assistant-backend` corrected local import mapping. Fresh container build unaffected.
- Production hidden canary initially returned405 through dynamic GET route; test expected404. Added explicit hidden404 handler; green.
- Nullable `Job.error` contract test first failed KeyError:error, then computed DTO error implemented and green.
- Infra's first real run failed dotenv test because inherited MINIO_SECRET_KEY correctly overrode dotenv; test now explicitly removes that env var while verifying APP_ENV override.
- Test helper first exited1 before pytest because Compose up--wait rejected successful migrate exit0; reported to infra owner. Ran direct isolated Compose command against healthy, migrated test infrastructure.
- Host `uv run --project src/backend ruff check src/backend`: All checks passed.
- Host `uv run --project src/backend pytest src/backend/tests -q`: 7passed5skipped (realservices explicitly unavailable on host, never fake).
- Real isolated command `docker compose --project-name ara-test --file compose.yaml --file compose.test.yaml run --rm --no-deps -e ARA_INTEGRATION=1 api uv run --frozen pytest -q`: latest `12 passed in 6.40s`; all 7units/5integrations, zero skips. `/tmp/ara-backend-real-pytest.txt`.
- Real container Ruff: All checks passed.
- Real migrated database `... run --rm --no-deps migrate uv run --frozen alembic check`: `No new upgrade operations detected.` exit0.
- Actual main stack GET /health/live200, GET /health/ready200 database/storage/redis allok; POST /api/v1/jobs/canary202 then completed100 attempts1 result{"message":"phase0-canary"}. Job UUID b75e9725-22bc-4833-bc21-78a479e5bd8b.

Real integrations require ARA_INTEGRATION1 and ARA_TEST_DATABASE_URL whose DB name contains test; fixture uses dedicated DB, RedisDB15, unique broker namespace, UUID private buckets; cleans canary rows/test objects. They verify schema/health/private S3 SHA256, atomic competing claim/duplicates/fenced final write, expired generation recovery/three attempt cap, pending outbox on broker outage, and actual child Dramatiq worker through actual Redis.

Limits: Phase0 only, canary execution. Paid generation/document handlers and eligible explicit retry route await next phases. No claim of hosted provider access, metadata extraction, or fiveworkflow completion. Exactly-once paid inference remains impossible across ambiguous failures; future handlers must checkpoint and apply fencing to all domain writes. API downtime pauses recovery/dispatch; worker delivery already queued proceeds. Schema revision readiness constant must advance with future migrations. Infrastructure owner still verifies full reload/restart gates and test-helper correction.
