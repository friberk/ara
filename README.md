# AI Research Assistant

A local research workspace for CS59300. Search Semantic Scholar or OpenAlex, save papers, retrieve or upload PDFs, and use paper content for summaries and questions. The architecture is a React SPA and a modular FastAPI backend with durable workers and persistent storage.

## Features

The interface is a chat-centred workspace built with shadcn components, using the default neutral black-and-white theme in light and dark (it follows your system setting; switch in the sidebar or Settings).

- **Search.** The home screen is one composer. Type a topic and choose OpenAlex or Semantic Scholar. Results show title, authors, year, abstract and DOI or PDF links. Each result can be saved to the library, and papers already saved show "In library".
- **Library.** Saved and uploaded papers persist across restarts. Filter by title, and see each paper's PDF status.
- **Upload.**
  - Choose or drop a PDF (up to 25 MB) on the home page, in the library or in a paper. The upload starts at once and shows its real progress.
  - You land in the paper's workspace, where one step list runs from Uploading through Reading pages and Finding paper details to Ready.
  - The library accepts several PDFs at once. Each becomes its own paper with its own progress row.
  - A PDF already in the library opens that paper with a note instead of an error.
  - If an upload turns out to be a paper already in your library (same DOI or arXiv ID, or a strictly matched title), it joins that paper instead of creating a duplicate:
    - If that paper has no PDF, the upload is attached and you land on it.
    - If it has one, you choose Replace PDF or Cancel. Nothing paid starts while the choice waits.
    - Library rows carry their own choice, and earlier undecided uploads are listed under "Needs your choice".
    - An upload into a specific paper stays there, and Details names any other paper that owns its DOI.
  - While a saved paper's PDF is being retrieved automatically, the header says "Getting PDF", the composer says questions open once it is ready, and uploading your own copy becomes the secondary option.
  - While a paper is being read, it is shown by its file name.
- **Accurate metadata.**
  - Titles come from the first page when the PDF's built-in title is a file name or tool output, such as `paper.dvi` or `Microsoft Word - draft.docx`.
  - The PDF's XMP metadata (title, creators, DOI, venue, publication date) ranks above its Info dictionary.
  - The existing model step still fills a missing title or authors, with the saved default model and effort.
  - After the PDF is readable, the app looks the paper up in OpenAlex, or in Semantic Scholar if you choose it under Settings → Metadata source. It searches by DOI or arXiv ID first, then by title.
  - A title match is used only when an author or the year also agrees.
  - The catalog's title, authors, year, venue and abstract replace the values read from the PDF, which stay as the fallback. Details you edited are never replaced.
  - If both catalogs are rate limited, reading is not blocked. The lookup retries in the background, honouring Retry-After, at most three times. Details can then start it again.
- **Get or find a PDF.** Saved papers offer retrieval in the PDF and Details views. The app checks both providers, including exact DOI alternatives, and tries reported open copies first. Retrieval continues in the background, then hands the original to PDF processing. Reported open access does not guarantee a working download.
- **Paper workspace.** The PDF reader sits beside the conversation. The latest summary is the first card. Ask your own questions or use the suggested ones; answers stream in with inline page citations. Clicking a citation scrolls the PDF to the cited passage and highlights it. The supporting sentences get a strong highlight, the rest of the cited excerpt a dotted underline. If the text cannot be matched, the reader outlines the passage from the citation's stored layout boxes instead, and only then falls back to showing the page. On phones, the workspace switches between Chat, PDF and Details tabs.
- **Chats over several papers.** Type @ in the home or chat composer, or use the @ button, to add library papers with a processed PDF to a conversation, up to five; choose an added paper again to remove it. The papers show as chips above the chat. A chip opens that paper's summary, and its × removes the paper (never the last one); earlier answers keep their citations to it. A chat appears under every paper it includes and lives at its first paper's address. Answers search each paper's PDF, give every paper at least two passages before the most relevant ones fill the rest, and split a comparison into one question per paper. Citations name their paper, as in "Karpukhin 2020 · p. 4", and a citation to another paper opens its PDF in a new reader tab. Multi-paper chats use hosted models only.
- **Context and cost ring.** In an open chat, a hollow ring at the bottom left of the question box shows how much of the selected model's input budget the latest answer used. Hover, focus or tap it for used and total tokens with the percentage, the model's full window when it is larger, and what the chat has cost so far in USD, split into answers, follow-up planning, conversation summaries, query embeddings and reranking. Costs come from the model catalogs at the tokens each call recorded; the shared paper summary is not part of a chat's cost, and answers from before this was recorded are noted as untracked rather than estimated. The total follows the model selected in the composer.
- **Retrieval.** Each PDF is split into section-aware passages. Questions and summaries use the passages that best match the question, found by keyword and embedding search, reranked, and packed to fit the model's context. Settings chooses one embedding model for the whole library (OpenAI `text-embedding-3-large` by default at $0.13 per million tokens, or `text-embedding-3-small` at $0.02) and the reranker (OpenAI by default, or off). Vectors from different models cannot be compared, so switching asks first, then re-embeds every paper in the background; questions keep using each paper's current index until its new one is ready, and the old vectors are removed afterwards. The paper's Details tab has an advanced **Search index** panel that shows the state of the paper's index and rebuilds it. Each answer can show how its passages were found.
- **Long conversations.** Recent turns are sent verbatim; older turns fold into a running summary, and relevant earlier turns are recalled. Follow-up questions are rewritten into standalone searches. The composer notes when earlier messages are summarized. Chats summarize and plan with the model chosen in Settings (GPT-5.6 Luna by default).
- **Models.** A compact switcher chooses the model and reasoning effort for the next request. Settings stores defaults. Each answer records the model that produced it. Open (local) models are experimental and off by default; see [Experimental: open models](#experimental-open-models-frozen).
- **History.** The sidebar lists recent papers, searches and conversations. Conversations are titled from their first question and can be renamed or deleted. Press ⌘K (Ctrl+K) to find papers and chats.

## Start locally

Requirements: Docker with Compose and Python3 for the environment bootstrap. Compose runs the core services; the experimental open-model runtime and its worker start only when enabled.

```bash
python3 scripts/bootstrap.py
```

This creates an ignored, private `.env` with random internal credentials and preserves existing configuration. Set `OPENAI_API_KEY` there for hosted summaries/questions. Academic credentials are optional; Semantic Scholar can rate-limit anonymous access. Never paste keys into the application or commit `.env`.

```bash
docker compose up --build
```

Open <http://localhost:5173>. API documentation is at <http://localhost:8000/docs>. Change `FRONTEND_PORT`, `API_PORT` and `CORS_ORIGINS` together when using different local ports. Browser calls use the Vite `/api` proxy; credentials remain on the backend. PostgreSQL, Redis and MinIO have no host ports by default.

Default startup initializes the private PDF bucket and runs Alembic before starting the API/workers. It works without LLM credentials. Analysis reports unavailable model access until a hosted key is configured. Core API readiness never depends on the open-model runtime.

Source edits use Vite HMR, Uvicorn reload and a debounced worker subprocess wrapper. The wrapper stops the previous worker process tree before starting its replacement. Rebuild images after dependency or Dockerfile changes. PostgreSQL, Redis, MinIO and model-weight named volumes survive normal shutdown:

```bash
docker compose down
docker compose up
docker compose logs --tail 100 api worker
docker compose run --rm migrate
```

Redis is job transport; PostgreSQL stores durable execution state and outbox records. Dispatch/recovery runs in API lifespan, so pending work resumes when the API returns. PDF parsing runs in an isolated child process. MinIO stores original bytes; PostgreSQL stores bibliographic data, pages/chunks, jobs and analysis history.

PDFs come only from OpenAlex's stored copies. Saving a paper with an OpenAlex record or a DOI starts retrieval without a click, and a paper saved earlier starts once when its workspace opens. Retrieval looks the work up by its OpenAlex ID or DOI (free) and, when OpenAlex reports a stored PDF, downloads it from `content.openalex.org` (about $0.01 each against the API key's daily allowance; a free key gives $1 a day). Set `OPENALEX_API_KEY` to enable this; without a key nothing is downloaded. When OpenAlex has no copy (not stored, paywalled or no matching work), has no key or cannot be reached, no other host is contacted: the workspace links the DOI (`https://doi.org/<doi>`) and asks you to download and upload the PDF; a paper without a DOI shows only the upload. A refused request (HTTP 429, or a spent daily allowance) reports OpenAlex's own wait, up to a day, before Try again. A failed retrieval is never retried automatically.

When any PDF (downloaded or uploaded) first becomes ready, one summary starts with the saved default model and effort. If that model is local and not ready, hosted generation is unconfigured or today's budget is spent, nothing starts and the summary card shows Generate summary with the reason; there is no fallback to another model. Automatic summaries with a hosted default use the daily budget.

The content endpoint redirects to a temporary signed link in OpenAlex's Cloudflare R2 storage; redirects may only reach `content.openalex.org` and the R2 hosts that OpenAlex documents for its PDF bucket. The key goes only to OpenAlex, and neither the key nor a signed link is logged or stored. Downloads are capped at 25 MiB, four redirects and 45 seconds; the job has a 420-second deadline. Encoded or non-PDF responses are rejected, and the downloader checks public DNS destinations and TLS names on every hop.

## Verify

```bash
python3 scripts/test-stack.py test
docker compose exec frontend npm run check
docker compose exec frontend npm run build
python3 -m unittest discover -s tests/infrastructure -v
uv run --with pymupdf==1.28.2 python -m unittest discover -s tests/fixtures -v
```

The backend helper forces a separate `ara-test` Compose project/database/buckets; `--project-name ara-<name>-test` runs a second isolated copy beside it. An autouse test guard refuses any request to a real external host, so a test that silently fell back from an unreachable provider still fails. It runs Ruff and pytest against real PostgreSQL, Redis and MinIO. HTTP fixtures replace academic and LLM providers. These commands do not build the inference runtime or download weights. Fixtures demonstrate deterministic behavior; live provider/model checks are separate.

Browser test environment:

```bash
uv run --with pymupdf==1.26.7 python tests/fixtures/create_pdf.py /tmp/ara-fixtures/research.pdf
uv run --with pymupdf==1.26.7 python tests/fixtures/create_pdf.py --second /tmp/ara-fixtures/second.pdf
docker compose -p ara-e2e -f compose.yaml -f compose.test.yaml -f compose.e2e.yaml up --build -d
cd src/frontend
npx playwright install chromium
npx playwright test
```

The research journey runs first because it saves the fixture paper through the UI; start from a fresh `ara-e2e` database (`docker compose -p ara-e2e -f compose.yaml -f compose.test.yaml -f compose.e2e.yaml down --volumes` removes only test data). The fixture UI uses port5180 and API8001. Wait for the frontend/API health checks before browser tests; inspect them with the same Compose files and `ps`. PDF fixtures cover OpenAlex's content endpoint and signed storage: stored copies by work ID and DOI, a temporary limit followed by a retry, a spent allowance, HTML and unsafe redirects, and the DOI fallback with 390px keyboard upload. Upload journeys cover a home upload into the workspace, several library uploads with a repeat, and the metadata-source setting. The multi-paper journey uploads the second synthetic PDF (`E2E_SECOND_PDF_PATH`, default `/tmp/ara-fixtures/second.pdf`) as its own paper and compares it with the fixture paper. Compose mounts the generated synthetic PDF from `/tmp/ara-fixtures/research.pdf`; set `E2E_PDF_PATH` for a different absolute path in both Compose and Playwright. The test-only resource factory relays OpenAlex's content and storage hosts to the fixture server without weakening production public-host checks. Fixtures prove deterministic behavior; a live download needs a real OpenAlex key. The browser commands require Node24/npm and uv on the host. Development and test data are isolated.

Test data reset is explicit and affects only `ara-test`:

```bash
python3 scripts/test-stack.py reset --reset-data
```

For development data reset, inspect the project and back up original PDFs/database first; `docker compose down --volumes` deliberately deletes the project's persistent volumes, including downloaded model weights. Ordinary shutdown uses `down` without that flag.

## Models and source grounding

Hosted IDs: `gpt-5.6-luna` (default), `gpt-5.6-terra`, `gpt-5.6-sol`. Supported reasoning controls come from backend capabilities; the GPT-5.6 catalog records `none`, `low`, `medium`, `high`, `xhigh` and `max` separately for Sol, Terra and Luna. Missing keys, provider outages and unavailable models are reported. Metadata-only papers require a processed PDF before analysis.

Retrieval stays within the selected document and preserves page references. PyMuPDF4LLM's layout model turns each PDF into Markdown in the isolated child process, and LlamaIndex parsers split it into passages of at most 512 tokens that keep their section path, pages and layout boxes. Search fuses PostgreSQL full-text ranking with pgvector embeddings (exact scans within the paper) by reciprocal rank fusion; the selected reranker then orders the leading 40 candidates. When an embedding index or the reranker is unavailable, answers fall back to keyword search or fused order and report why. The model sees short passage handles that the server maps back to stored passages; a handle outside the supplied passages fails the answer with `UNGROUNDED_OUTPUT`, and the model can answer that the passages do not contain the evidence. Budgets count tokens with tiktoken against each model's context window: hosted requests use at most `HOSTED_WORKING_CONTEXT_TOKENS` (64,000). Older turns are summarized once they pass `MEMORY_COMPACTION_RATIO` (0.6) of the recent-turns budget.

After an upgrade, the API re-ingests documents from an older chunk set at startup, including every document from before the retrieval overhaul; questions about a paper say it is being prepared until its re-ingest finishes. Missing search indexes are queued at startup and when the library embedding model changes, so adding an OpenAI key (with a restart) also indexes existing papers. The same re-ingest can be queued by hand:

```bash
docker compose exec api python -m app.services.reindex
``` Conversation history and summaries persist locally. Each assistant response records its model and reasoning effort. Model text is generated; citation controls show source passages and link to the original PDF page. Citation validation checks source identity; readers should verify factual support. Prompt instructions embedded in PDFs are treated as untrusted source text.

## Experimental: open models (frozen)

Open (local) models are the Ollama runtime with its IFM K2 Horizon and Qwen chat models, the Qwen3 embedding models and the Qwen3 reranker. They are experimental, and their development is frozen as of 2026-10-09 (ARA-090). Their code and tests stay, and the tests run with the flag on, but nothing new is built on them unless the freeze is lifted.

They are off by default. The app then offers only hosted OpenAI chat, embedding and reranking; Settings has no Local models section; Activity shows no model jobs; and `docker compose up --build` starts neither `ollama` nor `model-worker`. To turn them on, add both lines to `.env` and restart:

```bash
EXPERIMENTAL_OPEN_MODELS=true
COMPOSE_PROFILES=open-models
```

`EXPERIMENTAL_OPEN_MODELS` switches the API and workers; the `open-models` Compose profile (or `docker compose --profile open-models up --build`) starts the runtime and its worker. Downloaded weights stay in the `ollama-models` volume while the flag is off; `docker compose down` without `--volumes` keeps them. After upgrading a stack that ran open models before, `docker compose stop ollama model-worker` stops their old containers.

With the flag off, stored open-model state stays readable and never switches to a paid model:

- Answers and summaries from local models keep their stored model name.
- A saved local default model shows as unavailable; the composer and summaries ask for a hosted model instead of choosing one.
- A saved local library search model shows as unavailable in Settings, which offers the hosted models. Until one is chosen, papers are searched by keywords and Details says why.
- A saved local reranker means no reranking, and Settings shows it as unavailable.
- Unsettled model downloads, deletions and local summaries wait untouched until the flag is on again.

### Tests

The backend and frontend suites run with open models off, as shipped. Open-model tests turn them on: backend tests through the `open_models` pytest marker, frontend tests through a mocked `/features` reply. Test Compose pins `EXPERIMENTAL_OPEN_MODELS=false`, uses an empty offline Ollama fixture and disables the model worker; `python3 scripts/test-stack.py config` checks that Ollama and the model worker run only under the `open-models` profile. Browser Compose turns open models on and runs the model worker against a deterministic model provider; its model tests cover background progress, navigation, pause/reload/resume and default preservation after deletion.

Everything below applies only while open models are on.

### Runtime and budgets

The runtime starts without weights; generating locally needs additional disk and memory. The verified local-model host is Linux ARM64 in OrbStack on an M3 Pro. Native x86_64 CPU and NVIDIA/AMD configurations are provided; their hardware validation remains separate. Ollama starts without downloading or loading weights, and core API readiness does not depend on it. Logs: `docker compose logs --tail 100 model-worker ollama`.

Local prompts use at most `LOCAL_INPUT_BUDGET_TOKENS` (3,072), with o200k counts scaled by `LOCAL_TOKEN_FACTOR` (1.05). Local conversations are summarized by their own local model, only once the chat has been idle for a minute, and are never sent to a hosted model for summarization. Local models cost $0.00 in the context and cost ring. Settings can choose Qwen3 Embedding 4B or 8B as the search model and the local Qwen3 reranker, which orders the leading 12 candidates; a local embedding model that finishes verifying also queues the missing indexes it serves.

### Managed local models

Open **Settings → Local models** to download an exact curated Q4_K_M artifact:

| Model | Runtime reference | Catalog download bytes |
| --- | --- | ---: |
| IFM K2 Horizon 3.7B | `hf.co/IFM/K2-Horizon-3.7B-GGUF:Q4_K_M` | 3,156,599,066 |
| IFM K2 Horizon 7B | `hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M` | 5,592,218,900 |
| Qwen 3.8 27B | `qwen3.8:27b-q4_K_M` | 17,741,872,132 |
| Qwen3 Embedding 4B | `qwen3-embedding:4b-q4_K_M` | 2,496,704,041 |
| Qwen3 Embedding 8B | `qwen3-embedding:8b-q4_K_M` | 4,676,805,193 |
| Qwen3 Reranker 0.6B (Q8_0) | `fanyx/Qwen3-Reranker-0.6B-Q8_0:latest` | 639,152,466 |

Downloads continue when you leave Settings or close the browser. Activity links back to the model controls. Pause remains pending while the runtime settles its transfer and checkpoints; **Paused** appears after acknowledgment. A manually paused job stays paused across restart. Resume uses retained partial files when the registry supports ranges. Bytes may decrease after a restart if the runtime reports an earlier durable checkpoint. A finished transfer must also pass artifact, streaming and structured-output verification before selection becomes available. Download completion does not change your selection or saved default.

Installed models prepare automatically after a runtime, capability-schema or context change. **Preparing model** runs in the background using retained weights; leave Settings and return later. Selection becomes available after the check succeeds, with your saved model and reasoning preference preserved. Failed operations offer **Retry download**, **Retry preparation** or **Retry deletion**. If previously installed weights disappeared, **Download** starts a new transfer only when you request it. **Delete weights** confirms removal and preserves conversations, summaries and the saved default. Generation with a deleted default stays blocked until you reinstall it or choose another model. The app never switches a local request to a paid provider. Shared blobs and retained partial files mean deletion does not promise to reclaim the full catalog size. `OLLAMA_NOPRUNE=true` retains partials for recovery; the app does not perform broad orphan cleanup.

The default runtime uses a Linux CPU container on supported Docker hosts; it also works without GPU passthrough on macOS. It limits context to 8,192 tokens, output to 2,048 tokens, concurrent local generation to one and idle keep-alive to two minutes. Up to three models stay loaded (`OLLAMA_MAX_LOADED_MODELS`), so a chat model, an embedder and the reranker can serve one question without reloading; thinking efforts get a separate `OLLAMA_THINKING_TOKENS` (1,024) allowance. The `12g` memory ceiling is a limit, not memory reserved or consumed at startup. Configure `OLLAMA_MEMORY_LIMIT`, `OLLAMA_CPUS`, `OLLAMA_CONTEXT_WINDOW`, `OLLAMA_MAX_OUTPUT_TOKENS` and `OLLAMA_NUM_THREADS` in `.env`; the default four threads match the four-CPU quota. Context changes require revalidation. Local requests use temperature 0.0 and retain the applied settings with their responses; citation checks still reject unsupported output. A busy interactive local request returns a retryable message; background local summaries wait on their separate queue.

The 7B artifact passed live engine checks under the 12 GiB ceiling: roughly 6.52 GiB steady container usage and 10.30 GiB peak in the retained-weight run. Full application checks reached up to 11.85 GiB peak and about 6.65 GiB steady usage, with zero OOM events; leave additional host/VM memory for the other services. Those readings include cache and do not predict every workload. Qwen's approximately 17.74 GB download exceeds the default ceiling before KV cache and other overhead; raise the container and host/VM limits before attempting it. Each installed artifact must pass its own readiness checks. The final `0.40.1-ara.2` runtime passed six raw 7B controls: `default`, `none`, `on`, `low`, `medium` and `high`. Settings and the composer show **None**, **Low**, **Medium** and **High**. Earlier stock-runtime rejection of named controls is documented in the development journal.

Retrieval models share this runtime. With three models loaded, a chat model, Qwen3 Embedding 4B and the reranker measured 8.3 GiB with the 3.7B and 10.6 GiB with the 7B. **IFM K2 Horizon 7B and Qwen3 Embedding 8B do not fit together under the default 12 GiB limit.** In Phase 0 the pair swapped 7.7 GiB; Compose now disables swap (`memswap_limit` equals the memory limit), so the kernel kills the Ollama container instead, failing the answer and any running local jobs. The app does not prevent this combination. With the 7B, use Qwen3 Embedding 4B or the default OpenAI embeddings, or raise `OLLAMA_MEMORY_LIMIT` together with the host/VM memory. Memory-aware model loading is tracked in ARA-080.

Automatic preparation was verified with retained 7B weights through application restart and browser closure, without a download request. The user's installed 3.7B also passed background readiness and became selectable with the same verified raw controls and four displayed effort levels; this establishes installation compatibility, rather than a full 3.7B paper-quality evaluation. No 27B or GPU inference is claimed. Malformed runtime metadata produces a visible failed preparation with safe error text and explicit recovery.

Native Linux GPU overrides:

```bash
EXPERIMENTAL_OPEN_MODELS=true docker compose --profile open-models -f compose.yaml -f compose.nvidia.yaml up --build
EXPERIMENTAL_OPEN_MODELS=true docker compose --profile open-models -f compose.yaml -f compose.amd.yaml up --build
```

NVIDIA requires NVIDIA Container Toolkit. AMD requires supported ROCm hardware/drivers and the host's `OLLAMA_VIDEO_GID`/`OLLAMA_RENDER_GID`; set `OLLAMA_AMDGPU_TARGETS` for the device. Both overrides build the patched runtime. GPU acceleration and native amd64 execution are provided configurations, with no hardware test claim.

The managed image pins Ollama 0.40.1 and llama.cpp b11454. Stock 0.40.1 rejected the real 7B artifact with `unknown model architecture: 'k2-horizon'`. The custom build uses upstream architecture support, reviewed Ollama hook/CLEF adaptations and operation-scoped pull controls. See [runtime provenance, licenses and measured evidence](docker/ollama/README.md). An external `OLLAMA_BASE_URL` must provide the reviewed control protocol for acknowledged pause; stock endpoints cannot promise it.

Reasoning controls belong to each model. IFM offers **None**, **Low**, **Medium** and **High**; None disables thinking. Its native preset and Boolean enabled control both resolve to High, so old `default`/`on` preferences display as High and future UI requests use that explicit level. Displaying the preference does not save a change. Models that only support Boolean reasoning use a **Reasoning** toggle. Past responses retain their original settings: older `default` and `on` records read **Runtime preset** and **Reasoning enabled**. Automatic preparation refreshes stale controls without downloading weights or changing your saved default, conversations or summaries. Missing models are never downloaded automatically; manually paused or failed operations require their explicit resume or retry action.

Opt-in live engine validation downloads only 7B into a labeled isolated volume and preserves that volume:

```bash
python3 scripts/test-local-models.py --resume --volume ara-ollama-validation-new-run --output /tmp/ara-local-model-result.json
```

Use a fresh validation volume to exercise a real resumed transfer. This engine check is separate from the fixture-based browser suite and full application summary/Q&A checks. OCR remains optional.

To check an existing labeled validation volume without making any pull request, use `--retained-only` instead of `--resume`. The command fails if the retained 7B artifact is missing:

```bash
python3 scripts/test-local-models.py --retained-only --volume ara-ollama-validation-existing --output /tmp/ara-local-thinking-result.json
```

## Agent skill and project records

The installed local skill is `.agents/skills/pymupdf-pdf/SKILL.md`. Its executable parser supports Markdown, JSON, images and rough ruled-table output. It is independent of the application's parser. Generated output is ignored; the script has a pinned uv lockfile. Run the skill command from its directory or use `uv run --locked --script` with the parser path.

Architecture, traceability, priorities and milestones: [implementation plan](docs/implementation-plan.md). Exact API shapes: [API contract](docs/api-contract.md). Actual development observations: [agent journal](docs/agent-development-log.md). Stable issues: `issue_tracker/ARA-*.json`. Current delivery status and verification: [execution progress](docs/execution-progress.md) and [verification record](docs/verification-final.md).

A live five-workflow recording is available locally at `docs/evidence/generated/live-demo/live-demo.webm`; generated evidence is ignored by Git. The [submission checklist](docs/submission-checklist.md) supports the student's own reflection and final submission. GitHub publishing is deferred at the user's request; the workflow under `.github/workflows/ci.yaml` is prepared but has not run remotely.

## License and third-party dependencies

Project source is licensed under AGPL-3.0; see LICENSE. MinIO community is archived and source-only. Its custom image builds pinned upstream source and retains license/source references. PyMuPDF, PyMuPDF4LLM and pymupdf-layout have AGPL/commercial licensing. LlamaIndex, tiktoken and pgvector-python use MIT; the pgvector extension uses the PostgreSQL License. Ollama and llama.cpp use MIT; curated model artifacts, including the Qwen3 embedding and reranker models, have separate Apache-2.0 licenses and are downloaded only at the user's request. See [third-party notices](docs/third-party-notices.md) and [runtime provenance](docker/ollama/README.md). Credentials, original uploaded papers, weights and generated private data are excluded from version control.
