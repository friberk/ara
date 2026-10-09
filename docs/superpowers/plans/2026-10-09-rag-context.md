# Retrieval and Conversation Context Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking. REQUIRED for every task: superpowers:test-driven-development. Write the failing test, run it and record the red output before writing any implementation.

**Goal:** Replace naive page-text retrieval with structure-aware parsing, hybrid keyword+vector retrieval, selectable embedding profiles, optional local reranking, verifiable short-handle citations, and token-accurate conversation memory.

**Architecture:**
- **Parsing and chunking:** PyMuPDF4LLM's layout `to_markdown(page_chunks=True)` parses PDFs inside the existing isolated child process, with tuned threads. LlamaIndex node parsers produce section-aware chunks from one whole-paper Document.
- **Storage and retrieval:** chunks, embeddings and memory live in the single existing Postgres, which gains pgvector. Retrieval runs LlamaIndex retrievers over our own AsyncSessions, fuses their results with RRF, optionally reranks through the single existing Ollama, and packs evidence by real token budgets.
- **Chat:** chat sends a role-separated message list with a running summary, recent turns, recalled turns and `[S#]`-labelled evidence. The server maps handles back to canonical `[source:<uuid>]` markers.

**Tech stack:**
- Backend: Python 3.13, FastAPI, Pydantic v2, async SQLAlchemy + psycopg 3, Alembic, Dramatiq/Redis, `pymupdf4llm==1.28.2` (with `pymupdf_layout==1.28.2`), `llama-index-core`, `llama-index-embeddings-openai`, `llama-index-embeddings-ollama`, `tiktoken`, `pgvector` (Python), `pgvector/pgvector` Postgres 17 image.
- Frontend: React, TypeScript strict, TanStack Query, shadcn, Vitest/RTL, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-09-rag-context-design.md`. Issues: `issue_tracker/ARA-070.json` to `ARA-079.json`; epics ARA-021 and ARA-043.

## Global Constraints

- **Infrastructure:** exactly one PostgreSQL service (`postgres`) and one Ollama service (`ollama`). Add no vector DB, parser service, reranker service or second runtime.
- **Off-the-shelf first:** prefer documented LlamaIndex and PyMuPDF4LLM APIs over custom code. Our own parsing code is limited to child-process tuning, formula-box filling (Task 8) and chunk-to-page/box offset mapping (Task 9).
- **Persistence:** Alembic owns all schema. LlamaIndex must never create tables (no `PGVectorStore`, no LlamaIndex chat stores).
- **Sessions and processes:** every request, actor and parallel task opens its own `AsyncSession` via `resources.sessions()`. PyMuPDF/PyMuPDF4LLM run only in the child process `python -m app.jobs.pdf_parser`.
- **Paid calls:** generation calls never retry. Embedding calls may retry at most 2 times with backoff, because they are idempotent and cheap. Every OpenAI call reserves budget through `reserve()`.
- **Local chats:** a local chat never triggers hosted *generation* (the planner and compaction use the chat's own local model). Query embedding through OpenAI is allowed when the paper's profile is OpenAI, without UI disclosure (user decision).
- **Replay safety:** request UUID replay must never re-run planning, retrieval, reranking or generation. Citations must belong to the chat's immutable `document_id`.
- **Commits:** Conventional Commits with ARA IDs (e.g. `feat(rag): … (ARA-073)`). **No `Co-Authored-By` trailer.**
- **Copy:** sentence case, plain language, no internal jargon in UI copy. Raw model ids appear in mono only as secondary lines (`DESIGN.md`).
- **Tests:** backend via `python3 scripts/test-stack.py test --project-name <unique>`; frontend via `docker compose exec frontend npm run check` and `npm run build`. Never run destructive fixtures against development data.
- **Scope:** no dataset evaluation, no QASPER, no full-paper context mode.

## Gate G0 values (filled from the Phase 0 spikes before any agent starts)

| Name | Value | Source |
|---|---|---|
| `PGVECTOR_IMAGE` | `pgvector/pgvector:0.8.7-pg17-bookworm@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d` (PostgreSQL 17.11, pgvector 0.8.7) | S2 Part B |
| Child parser `RLIMIT_AS` / `RLIMIT_CPU` | 1.5 GiB / 150 s, with tuned threads (mandatory) | S2 Part A |
| Worker `mem_limit` | 2g (unchanged), one parse child at a time | S2 Part A |
| `OLLAMA_MAX_LOADED_MODELS` default | 3, plus `LLAMA_ARG_CACHE_RAM=0` and `memswap_limit = mem_limit` (done in Wave 1) | S1 §3 |
| `OLLAMA_CONTEXT_WINDOW` default | 8192 (unchanged); `local_input_budget_tokens` 3072 | S1 §4 |
| `OLLAMA_FLASH_ATTENTION` / `OLLAMA_KV_CACHE_TYPE` | default (already enabled) / unchanged f16 (q8_0 doubles prefill) | S1 §4 |
| Local token estimate | o200k_base × 1.05 (IFM 0.974×, Qwen3 1.018× of o200k) | S1 §5 |
| Hosted tiktoken encoding | o200k_base (exact; +6 framing tokens per request) | S1 §6 |
| Qwen3 embed 4B / 8B digests | `df5bd2e3c74cd8d069d21dc038f1b359fcdc9458fce1c99bd43c9eb1518ff907` / `64b933495768fbd3b87c20583d379728a07471e0c66733a9df87cd1901b3c44b`; embedder `num_ctx` 2048, `keep_alive` 10m | S1 §1 |
| Reranker model id + digest, go/no-go | `dengcao/Qwen3-Reranker-0.6B:F16`, `d9cf33bea10fd318434af5b09425a3b7d1b9988b130899612bf3836aed13c013`; **deferred** (54 s / 30 candidates) | S1 §2 |
| Reranker 30-candidate latency budget | n/a while deferred (10–15 candidates ≈ 18–27 s) | S1 §2 |

## Review Focus

1. **Scanned or text-light PDFs** (e.g. a paper whose body is images): the existing `OCR_REQUIRED` path must still fire. The layout model's own OCR must stay disabled (`use_ocr=False`), because OCR is out of scope and slow. Test it in Task 8.
2. **A paper with no detectable headings** (plain report, slides): it must still become ready with page-level chunks and a non-empty `context_text`, never zero chunks. Test it in Task 9.
3. **Switching a paper's index model while a question is streaming:** the in-flight answer keeps the evidence it already packed. The next question uses whichever index is `ready`; it never sees a half-built index. Test it in Task 14.
4. **Model output with odd citation forms** (`[S1, S3]`, `【S2】`, `[S12]` split across two stream deltas, `[S99]` unknown, a handle inside a code block): known handles map, unknown ones fail as `UNGROUNDED_OUTPUT`, and split markers are never emitted half-mapped. Test it in Task 25.
5. **A very long single question or a huge prior answer** with a small 8k local model: assembly drops history before evidence and truncates an oversized prior turn. It raises `CONTEXT_LIMIT` (413) only when the question alone cannot fit with the evidence floor. Test it in Task 19.

---

## File structure

**Backend, new:**
- `app/models/retrieval.py`: `DocumentSection`, `ChunkEmbedding`, `RetrievalIndex`.
- `app/models/memory.py`: `ChatMemory`, `ChatTurnEmbedding`.
- `app/schemas/retrieval.py`: retrieval API DTOs.
- `app/integrations/tokens.py`: `TokenCounter`, `TiktokenCounter`, `RatioCounter`, `count_messages`.
- `app/integrations/context_registry.py`: `ContextProfile`, `context_profile()`.
- `app/integrations/embedding_catalog.py`: `EmbeddingProfile`, `PROFILES`, `DEFAULT_PROFILE`.
- `app/integrations/embeddings.py`: `Embedder` adapters over LlamaIndex `OpenAIEmbedding` / `OllamaEmbedding`.
- `app/rag/chunking.py`: `build_chunk_plan()` (LlamaIndex parsers plus the header carry).
- `app/rag/retrievers.py`: `PgLexicalRetriever`, `PgVectorRetriever`, `chunk_node()`.
- `app/rag/fusion.py`: `reciprocal_rank_fusion()`.
- `app/rag/rerank.py`: `OllamaQwenRerank` (LlamaIndex postprocessor).
- `app/rag/packing.py`: `Passage`, `pack_evidence()`.
- `app/rag/citations.py`: `HandleMap`, `HandleTransducer`, `INSUFFICIENT`.
- `app/rag/pipeline.py`: `retrieve_evidence()`.
- `app/rag/indexing.py`: `run_embed_job()`, `ensure_index()`, `effective_profile()`.
- `app/services/context.py`: `allocate()`, `assemble_answer_prompt()`.
- `app/services/memory.py`: `plan_query()`, `run_compact_job()`, `maybe_enqueue_compaction()`, `recall_turns()`, `run_embed_turn_job()`.
- `app/routes/retrieval.py`: retrieval settings, profiles, paper retrieval and chat memory endpoints.
- `scripts/reindex.py`: re-ingest all documents.

**Backend, modified:**
- `app/models/research.py`: `DocumentChunk` reshaped, plus `Paper.retrieval_profile`, `Document.parser`/`chunk_set` and `ChatMessage.retrieval`/`context`/`grounding`.
- `app/jobs/pdf_parser.py`: PyMuPDF4LLM layout `to_markdown`, with tuned child threads and the legacy fallback.
- `app/services/ingestion.py`: chunk persistence plus the embed-job enqueue.
- `app/services/chat.py`: split `prepare`, status events, transducer.
- `app/services/summarization.py`: new chunks and handles.
- `app/integrations/llm.py` and `app/integrations/ollama_llm.py`: message lists and context profiles.
- `app/integrations/model_catalog.py`: `kind`, embedding and reranker specs.
- `app/services/local_models.py` and `app/integrations/ollama.py`: kind-specific verification.
- `app/repositories/local_models.py`: `retrieval` use slot.
- `app/repositories/jobs.py`: `continue_locked`.
- `app/jobs/actors.py`: `embed`, `embed_turn` and `compact_chat` kinds.
- `app/schemas/ai.py`: Citation, Message and Model fields.
- `app/main.py`: router.
- `alembic/versions/0006_retrieval_context.py`.

**Infrastructure:** `compose.yaml`, `compose.test.yaml`, `compose.e2e.yaml`, `docker/backend.Dockerfile` (tiktoken cache), `scripts/test-stack.py`, `src/backend/pyproject.toml` + `uv.lock`, `tests/fixtures/server.py`, `tests/fixtures/ollama_fixture.py`, `docker/ollama/runtime-fixture.py`, `tests/fixtures/create_structured_pdf.py`.

**Frontend:**
- `src/api/generated.ts` (regenerated) and `src/api/sse.ts`.
- `src/hooks/queries/retrieval.ts`.
- `src/features/settings/RetrievalSettingsSection.tsx`.
- `src/features/workspace/SearchIndexPanel.tsx`, mounted in `DetailsPanel.tsx`.
- `src/features/chat/AnswerDetails.tsx`, `src/features/chat/MemoryNote.tsx` and `src/features/chat/use-chat-stream.ts`.
- `src/features/content/remark-citations.ts`, `SourceList.tsx` and `CitationChip.tsx`.

---

## Wave 1: foundation (lead only; ARA-070)

### Task 1: Isolated test-stack project names

**Files:** Modify `scripts/test-stack.py`. Test: `tests/infrastructure/test_test_stack.py`.

**Interfaces:** Produces `python3 scripts/test-stack.py <action> [--project-name NAME]`, where `NAME` defaults to `ara-test` and must match `^ara-[a-z0-9-]+-test$|^ara-test$`. `reset` keeps requiring `--reset-data`.

- [ ] **Step 1: Write the failing tests**

```python
    def test_given_project_name_when_config_then_compose_uses_it(self):
        script = Path(__file__).resolve().parents[2] / "scripts/test-stack.py"
        result = subprocess.run(
            [sys.executable, str(script), "config", "--project-name", "ara-rag-a-test", "--dry-run"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--project-name ara-rag-a-test", result.stdout)

    def test_given_unsafe_project_name_when_requested_then_refused(self):
        script = Path(__file__).resolve().parents[2] / "scripts/test-stack.py"
        result = subprocess.run(
            [sys.executable, str(script), "config", "--project-name", "ara"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("project name", result.stderr)
```

- [ ] **Step 2: Run** `python3 -m unittest tests/infrastructure/test_test_stack.py -v`. Expected: 2 FAIL (unknown arguments).
- [ ] **Step 3: Implement.** Add `parser.add_argument("--project-name", default="ara-test")` and `parser.add_argument("--dry-run", action="store_true")` (print the commands, run nothing). Validate with `re.fullmatch(r"ara-test|ara-[a-z0-9-]+-test", args.project_name)`; otherwise call `parser.error("project name must be ara-test or ara-<name>-test")`. Replace the literal `"ara-test"` in `compose` with `args.project_name`.
- [ ] **Step 4: Run** the tests. Expected: all PASS.
- [ ] **Step 5: Commit** `test(infra): isolate test stacks by project name (ARA-070)`.

### Task 2: pgvector image on the single Postgres and configurable Ollama residency

**Files:** Modify `compose.yaml`, `compose.e2e.yaml` (if it pins postgres), `.env.example`. Test: `tests/infrastructure/test_compose_retrieval.py` (new).

**Interfaces:**
- Produces `services.postgres.image == PGVECTOR_IMAGE`.
- Produces `services.ollama.environment.OLLAMA_MAX_LOADED_MODELS == ${OLLAMA_MAX_LOADED_MODELS:-<G0>}`, plus `OLLAMA_FLASH_ATTENTION` and `OLLAMA_KV_CACHE_TYPE` per G0.
- Exactly one service whose image contains `postgres` or `pgvector`, and exactly one Ollama service.

- [ ] **Step 1: Write the failing test**

```python
"""Retrieval must reuse the single Postgres and the single Ollama service."""
import json, os, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def compose_config(**env):
    environment = {**os.environ, "POSTGRES_PASSWORD": "fixture-only-password",
                   "REDIS_PASSWORD": "fixture-only-redis", "MINIO_ROOT_PASSWORD": "fixture-only-minio", **env}
    result = subprocess.run(["docker", "compose", "config", "--format", "json"], cwd=ROOT,
                            env=environment, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["services"]

class ComposeRetrievalTests(unittest.TestCase):
    def test_single_postgres_uses_pinned_pgvector_image(self):
        services = compose_config()
        databases = [n for n, s in services.items() if "postgres" in s.get("image", "") or "pgvector" in s.get("image", "")]
        self.assertEqual(databases, ["postgres"])
        self.assertRegex(services["postgres"]["image"], r"^pgvector/pgvector:[\w.-]+@sha256:[0-9a-f]{64}$")

    def test_single_ollama_with_configurable_residency(self):
        services = compose_config(OLLAMA_MAX_LOADED_MODELS="3")
        runtimes = [n for n, s in services.items() if "ollama" in s.get("image", "")]
        self.assertEqual(runtimes, ["ollama"])
        self.assertEqual(services["ollama"]["environment"]["OLLAMA_MAX_LOADED_MODELS"], "3")
```

- [ ] **Step 2: Run** `python3 -m unittest tests/infrastructure/test_compose_retrieval.py -v`. Expected: FAIL (the image is `postgres:17.9`; residency is the literal `"1"`).
- [ ] **Step 3: Implement.**
  - Set `services.postgres.image: PGVECTOR_IMAGE` (G0).
  - In `ollama.environment`: `OLLAMA_MAX_LOADED_MODELS: ${OLLAMA_MAX_LOADED_MODELS:-<G0>}`, `OLLAMA_FLASH_ATTENTION: ${OLLAMA_FLASH_ATTENTION:-<G0>}`, `OLLAMA_KV_CACHE_TYPE: ${OLLAMA_KV_CACHE_TYPE:-<G0>}`.
  - Set the `OLLAMA_CONTEXT_WINDOW` default to G0.
  - Document the new variables in `.env.example` and the README environment table.
- [ ] **Step 4: Run** the test, plus `python3 -m unittest discover tests/infrastructure`. Expected: PASS.
- [ ] **Step 5: Verify the volume carries over** on a throwaway copy, not dev data:

```bash
docker compose -p ara-rag-g0 up -d postgres && docker compose -p ara-rag-g0 exec postgres psql -U ara -c "select count(*) from papers"
```

  Run it once on the old image and once on the new. Record both outputs in the journal.
- [ ] **Step 6: Commit** `feat(infra): serve pgvector from the single Postgres (ARA-070)`.

### Task 3: Dependencies and the tiktoken cache

**Files:** Modify `src/backend/pyproject.toml`, `src/backend/uv.lock`, `docker/backend.Dockerfile`. Test: `src/backend/tests/test_dependencies.py` (new).

**Interfaces:**
- Produces importable `pymupdf4llm` (1.28.2), `llama_index.core`, `llama_index.embeddings.openai`, `llama_index.embeddings.ollama`, `tiktoken`, `pgvector.sqlalchemy`.
- `tiktoken.get_encoding("<G0 encoding>")` and `get_encoding("cl100k_base")` work offline, with `TIKTOKEN_CACHE_DIR=/opt/tiktoken`.

- [ ] **Step 1: Write the failing test**

```python
import os, subprocess, sys

def test_retrieval_dependencies_import_without_network():
    code = ("import tiktoken, pgvector.sqlalchemy, llama_index.core, llama_index.embeddings.openai, "
            "llama_index.embeddings.ollama; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')")
    env = {**os.environ, "NO_PROXY": "*", "HTTPS_PROXY": "http://127.0.0.1:9"}  # any download attempt fails
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

def test_parser_dependency_only_in_child():
    # pymupdf4llm must be importable for the child process, but app modules must not import it.
    import importlib, pkgutil, app
    for module in pkgutil.walk_packages(app.__path__, "app."):
        if module.name == "app.jobs.pdf_parser":
            continue
        importlib.import_module(module.name)
    assert "pymupdf4llm" not in sys.modules and "pymupdf" not in sys.modules
```

- [ ] **Step 2: Run** `python3 scripts/test-stack.py test --project-name ara-rag-lead-test` (or the targeted pytest in the api container). Expected: FAIL (ModuleNotFoundError).
- [ ] **Step 3: Implement.**
  - `uv add "pymupdf4llm==1.28.2" "llama-index-core>=0.14,<0.15" "llama-index-embeddings-openai" "llama-index-embeddings-ollama" "tiktoken>=0.9" "pgvector>=0.4"`, pinning exact resolved versions in the lock.
  - In the Dockerfile, after dependency install: `ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken` and `RUN python -c "import tiktoken; [tiktoken.get_encoding(e) for e in ('o200k_base','cl100k_base')]"`.
  - Pin `pymupdf` and `pymupdf_layout` to `1.28.2` explicitly.
- [ ] **Step 4: Run** the tests. Expected: PASS. Record the image size delta in the journal.
- [ ] **Step 5: Commit** `build(backend): add retrieval dependencies (ARA-070)`.

### Task 4: Migration 0006 and ORM models

**Files:** Create `alembic/versions/0006_retrieval_context.py`, `app/models/retrieval.py`, `app/models/memory.py`. Modify `app/models/research.py`, `app/models/__init__.py`, `tests/conftest.py` (cleanup order). Test: `tests/test_retrieval_schema_integration.py` (new).

**Interfaces (exact; later tasks rely on these names):**

```python
# app/models/research.py — DocumentChunk replaces the old shape (no char_start/char_end/token_estimate)
class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_set", "ordinal", name="uq_document_chunk_ordinal"),
        CheckConstraint("kind IN ('front_matter','text','table','references')", name="chunk_kind"),
        Index("ix_chunk_search", "search_vector", postgresql_using="gin"),
        Index("ix_chunk_document", "document_id", "chunk_set", "ordinal"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_set: Mapped[str] = mapped_column(String(80))
    ordinal: Mapped[int]
    section_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_sections.id", ondelete="SET NULL"))
    section_path: Mapped[list] = mapped_column(JSONB, default=list)   # ["Results", "Open-domain QA"]
    heading: Mapped[str] = mapped_column(Text, default="")            # " > ".join(section_path)
    kind: Mapped[str] = mapped_column(String(20), default="text")
    page: Mapped[int]                                                 # first page (1-based)
    page_end: Mapped[int]
    text: Mapped[str] = mapped_column(Text)                           # Markdown shown to users
    context_text: Mapped[str] = mapped_column(Text)                   # title + heading + text, embedded
    bboxes: Mapped[list] = mapped_column(JSONB, default=list)         # [[page,x0,y0,x1,y1], ...] (empty until to_chunks)
    token_count: Mapped[int]
    search_vector: Mapped[str] = mapped_column(TSVECTOR, Computed(
        "setweight(to_tsvector('english', heading), 'A') || setweight(to_tsvector('english', text), 'B')",
        persisted=True))

# Paper: retrieval_profile: Mapped[str | None] = mapped_column(String(40))
# Document: parser: Mapped[str | None] = mapped_column(String(40)); chunk_set: Mapped[str | None] = mapped_column(String(80))
# ChatMessage: retrieval: Mapped[dict] = mapped_column(JSONB, default=dict)
#              context: Mapped[dict] = mapped_column(JSONB, default=dict)
#              grounding: Mapped[str | None] = mapped_column(String(20))  # 'supported' | 'insufficient'

# app/models/retrieval.py
from pgvector.sqlalchemy import HALFVEC
class DocumentSection(Base):
    __tablename__ = "document_sections"
    __table_args__ = (UniqueConstraint("document_id", "chunk_set", "ordinal", name="uq_section_ordinal"),
                      CheckConstraint("role IN ('front_matter','body','references')", name="section_role"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_set: Mapped[str] = mapped_column(String(80))
    ordinal: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    level: Mapped[int]
    path: Mapped[list] = mapped_column(JSONB, default=list)
    role: Mapped[str] = mapped_column(String(20), default="body")
    page: Mapped[int]
    page_end: Mapped[int]

class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (Index("ix_embedding_document_profile", "document_id", "profile"),)
    chunk_id: Mapped[UUID] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), primary_key=True)
    profile: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    embedding = mapped_column(HALFVEC())           # dimension varies by profile
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class RetrievalIndex(Base):
    __tablename__ = "retrieval_indexes"
    __table_args__ = (UniqueConstraint("document_id", "profile", "chunk_set", name="uq_retrieval_index"),
                      CheckConstraint("state IN ('queued','embedding','ready','failed','unavailable')",
                                      name="retrieval_index_state"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    profile: Mapped[str] = mapped_column(String(40))
    chunk_set: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(20), default="queued")
    embedded: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    model_digest: Mapped[str | None] = mapped_column(String(80))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("background_jobs.id", ondelete="SET NULL"))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# app/models/memory.py
class ChatMemory(Base):
    __tablename__ = "chat_memories"
    __table_args__ = (UniqueConstraint("session_id", "version", name="uq_chat_memory_version"),
                      UniqueConstraint("session_id", "through_message_id", name="uq_chat_memory_through"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    version: Mapped[int]
    through_message_id: Mapped[UUID] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"))
    summary: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int]
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(20))
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ChatTurnEmbedding(Base):
    __tablename__ = "chat_turn_embeddings"
    message_id: Mapped[UUID] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True)
    profile: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    embedding = mapped_column(HALFVEC())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 1: Write the failing integration test** (it runs against the migrated test DB):

```python
import pytest
from sqlalchemy import text
pytestmark = pytest.mark.integration

async def test_given_migrated_database_then_vector_and_new_tables_exist(resources):
    async with resources.sessions() as session:
        extensions = set((await session.scalars(text("select extname from pg_extension"))).all())
        assert "vector" in extensions
        tables = set((await session.scalars(text(
            "select tablename from pg_tables where schemaname='public'"))).all())
        assert {"document_sections", "chunk_embeddings", "retrieval_indexes",
                "chat_memories", "chat_turn_embeddings"} <= tables
        columns = set((await session.scalars(text(
            "select column_name from information_schema.columns where table_name='document_chunks'"))).all())
        assert {"chunk_set", "section_path", "heading", "kind", "page", "page_end", "context_text",
                "bboxes", "token_count", "search_vector"} <= columns
        assert not {"char_start", "char_end", "token_estimate"} & columns

async def test_given_chunk_text_when_searching_then_heading_weighs_more(resources):
    # Insert one paper/document/two chunks with the same body term; heading match ranks first.
    ...  # use ORM inserts; assert ts_rank_cd order via websearch_to_tsquery('english','attention')
```

  Write the second test in full with ORM inserts of `Paper`, `Document` (fill the required columns: `object_key`, `sha256`, `original_filename`, `byte_size`, `request_id`) and two `DocumentChunk` rows: heading `"Attention"` versus body-only `"attention"`. Assert the first chunk ranks first.
- [ ] **Step 2: Run** `python3 scripts/test-stack.py test --project-name ara-rag-lead-test`. Expected: FAIL (`vector` missing, tables missing).
- [ ] **Step 3: Implement the migration.**
  - `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`.
  - Drop and recreate `document_chunks` (existing chunks are discarded; the reindex in Task 11 rebuilds them).
  - Create the new tables. Add the new columns to `papers`, `documents` and `chat_messages`.
  - Declare the halfvec column type as `pgvector.sqlalchemy.HALFVEC()`.
  - Downgrade drops the new objects and restores the 0005 `document_chunks` shape (empty).
  - Update the models and `tests/conftest.py` cleanup: delete `ChatTurnEmbedding`, `ChatMemory`, `ChunkEmbedding`, `RetrievalIndex` and `DocumentSection` before `Paper`.
- [ ] **Step 4: Run** the suite. Expected: the new tests PASS. Old tests that reference `char_start`, `token_estimate` or the old chunk shape FAIL; list them in the journal. They are fixed in Tasks 10, 23 and 27, not here. Mark them `xfail(strict=True, reason="reshaped in ARA-071/073")` with the owning task.
- [ ] **Step 5: Commit** `feat(db): add retrieval and memory schema (ARA-070)`.

### Task 5: Shared API contracts

**Files:** Modify `app/schemas/ai.py`. Create `app/schemas/retrieval.py`, `app/routes/retrieval.py` (endpoints return 501 until Tasks 15 and 30). Modify `app/main.py`, `docs/api-contract.md`, `src/frontend/src/api/generated.ts`. Test: `tests/test_contracts_retrieval.py`.

**Interfaces (exact):**

```python
# app/schemas/ai.py additions
class Citation(DTO):
    chunk_id: UUID
    document_id: UUID
    page: int = Field(ge=1)
    page_end: int | None = None
    section: str | None = None
    kind: Literal["front_matter", "text", "table", "references"] | None = None
    bboxes: list[list[float]] = Field(default_factory=list)
    excerpt: str

class RetrievalSummary(BaseModel):
    mode: Literal["hybrid", "keyword"]
    profile: str | None = None
    reranked: bool = False
    standalone_query: str | None = None
    search_queries: list[str] = Field(default_factory=list)
    passages_found: int = 0
    passages_used: int = 0
    limited_by_context: bool = False
    note: str | None = None          # plain-language reason, e.g. "Search index is still building."

class ContextUsage(BaseModel):
    window: int
    input_tokens: int
    output_reserved: int
    summary_version: int | None = None
    recent_turns: int = 0
    recalled_turns: int = 0
    truncated: bool = False

class Message(DTO):   # existing fields plus:
    retrieval: RetrievalSummary | None = None
    context: ContextUsage | None = None
    grounding: Literal["supported", "insufficient"] | None = None

class Model(DTO):     # existing fields plus:
    kind: Literal["chat", "embedding", "reranker"] = "chat"

# app/schemas/retrieval.py
class EmbeddingProfileOut(BaseModel):
    key: str
    provider: Literal["openai", "ollama"]
    model_id: str
    display_name: str
    dimensions: int
    status: Literal["available", "unavailable"]
    unavailable_reason: str | None = None
    local_model_key: str | None = None

class EmbeddingProfilePage(BaseModel):
    items: list[EmbeddingProfileOut]
    default_profile: str

class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embedding_profile: str = "openai-3-large"
    reranker_enabled: bool = True

class RetrievalIndexOut(BaseModel):
    profile: str
    state: Literal["queued", "embedding", "ready", "failed", "unavailable"]
    embedded: int
    total: int
    updated_at: datetime | None = None
    error: JobError | None = None

class PaperRetrieval(BaseModel):
    paper_id: UUID
    document_id: UUID | None
    effective_profile: str
    source: Literal["default", "paper"]
    parser: str | None
    chunk_count: int
    section_count: int
    mode: Literal["hybrid", "keyword", "unavailable"]
    mode_note: str | None = None
    indexes: list[RetrievalIndexOut]

class PaperRetrievalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str | None              # None = follow the global default
    request_id: UUID

class RebuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID

class ChatMemoryOut(BaseModel):
    version: int
    summary: str
    summarized_messages: int
    model: str
    created_at: datetime

class ChatMemoryState(BaseModel):
    memory: ChatMemoryOut | None
    total_messages: int
```

Routes, all under `/api/v1`:
- `GET /retrieval/profiles` returns `EmbeddingProfilePage`.
- `GET /retrieval/settings` and `PUT /retrieval/settings` return `RetrievalSettings`.
- `GET /papers/{paper_id}/retrieval` and `PUT /papers/{paper_id}/retrieval` return `PaperRetrieval`.
- `POST /papers/{paper_id}/retrieval/rebuild` returns `PaperRetrieval` (202).
- `GET /chats/{chat_id}/memory` returns `ChatMemoryState`.
- SSE adds `event: message.status` with `data: {"message_id": str, "stage": "planning"|"retrieving"|"reranking"|"generating"}`.

- [ ] **Step 1: Write the failing test.** It uses FastAPI's `app.openapi()` and needs no DB:

```python
from app.main import create_app

def test_openapi_exposes_retrieval_contracts():
    spec = create_app().openapi()
    paths = spec["paths"]
    for path in ["/api/v1/retrieval/profiles", "/api/v1/retrieval/settings",
                 "/api/v1/papers/{paper_id}/retrieval", "/api/v1/papers/{paper_id}/retrieval/rebuild",
                 "/api/v1/chats/{chat_id}/memory"]:
        assert path in paths, path
    schemas = spec["components"]["schemas"]
    assert {"retrieval", "context", "grounding"} <= set(schemas["Message"]["properties"])
    assert {"page_end", "section", "kind", "bboxes"} <= set(schemas["app__schemas__ai__Citation"]["properties"])
    assert "kind" in schemas["Model"]["properties"]
```

  Check the app factory name in `app/main.py`, and the actual schema key names in the current OpenAPI (`app__schemas__ai__Citation` per `src/frontend/src/api/types.ts`).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the schemas and the route stubs (`raise AppError(501, "NOT_IMPLEMENTED", "Retrieval controls are not available yet.")`). Regenerate `generated.ts` inside Compose (`npm run generate:api`) and update `src/api/types.ts` aliases. Document the contracts in `docs/api-contract.md`.
- [ ] **Step 4: Run** the backend test and `docker compose exec frontend npm run check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): freeze retrieval and context contracts (ARA-070)`.

### Task 6: Deterministic fixtures

**Files:**
- Modify `tests/fixtures/server.py`: `POST /v1/embeddings`.
- Modify `docker/ollama/runtime-fixture.py` and `tests/fixtures/ollama_fixture.py`: `/api/embed`, reranker `/api/generate` with `logprobs`, `/api/show` for the embedding and reranker kinds.
- Create `tests/fixtures/create_structured_pdf.py`.
- Test: `tests/infrastructure/test_fixtures_retrieval.py` and `src/backend/tests/test_fixture_vectors.py`.

**Interfaces:**
- `fixture_vector(text: str, dims: int) -> list[float]`, defined identically in both fixture servers and in `src/backend/tests/support/vectors.py`. It is a deterministic bag-of-words hashing embedding: tokens are lowercased `[a-z0-9]+` words; each word hashes with `sha256(word)` to an index modulo `dims`; values are added and the result is L2-normalized. Paraphrases with shared words are therefore close, which makes dense-retrieval tests meaningful.
- The OpenAI fixture `/v1/embeddings` accepts `input: str | list[str]` and `dimensions`, and returns `{"data":[{"embedding":…, "index":i}], "usage":{"prompt_tokens": n, "total_tokens": n}}`.
- The Ollama fixture `/api/embed` accepts `input` and returns `{"embeddings":[…], "prompt_eval_count": n}` with `dims` per model id (`qwen3-embedding:4b-q4_K_M` gives 2560; `…8b…` gives 4096).
- The Ollama fixture `/api/generate` for the reranker model id, with `raw: true`, scores relevance by word overlap between `<Query>` and `<Document>`. It returns `{"response": "yes"|"no", "done": true, "logprobs": [{"token": "yes", "logprob": lp_yes, "top_logprobs": [{"token": "yes", "logprob": lp_yes}, {"token": "no", "logprob": lp_no}]}]}`.
- `create_structured_pdf.py OUT` writes a 4-page PDF with PyMuPDF:
  - page 1: title "Sparse Retrieval for Scientific QA", authors, "Abstract" heading plus a paragraph;
  - page 2: "1 Introduction" (larger bold font), then "2 Method", with the Method paragraph continuing onto page 3;
  - page 3: a 3×3 table under "3 Results" ("Model | Recall@10 | Latency (ms)");
  - page 4: "References" with 3 entries.

  Headings use 14 pt bold; body uses 10 pt.

- [ ] **Step 1: Write the failing tests.** Example for the OpenAI fixture (start the server on an ephemeral port as the existing infrastructure tests do):

```python
def test_openai_embeddings_fixture_is_deterministic_and_normalized(self):
    first = post(f"{base}/v1/embeddings", {"model": "text-embedding-3-large", "input": ["dense retrieval", "dense retrieval"], "dimensions": 64})
    a, b = (item["embedding"] for item in first["data"])
    self.assertEqual(a, b)
    self.assertAlmostEqual(sum(x * x for x in a), 1.0, places=5)
    self.assertEqual(len(a), 64)
```

  Also cover reranker logprob ordering (relevant above irrelevant), `/api/embed` dims per model, and the structured PDF: 4 pages, heading text present, and the table detectable by `page.find_tables()`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the fixtures (stdlib only in `server.py` and `runtime-fixture.py`; PyMuPDF only in `create_structured_pdf.py`).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `test(fixtures): add embedding, reranker and structured PDF fixtures (ARA-070)`.

**Wave 1 exit:** the lead runs the full backend suite (only the documented strict xfails fail), the frontend check, and `docker compose config`. Merge to `feat/rag-context`, then create agent worktrees from that commit:

```bash
git worktree add ../rag-<name> -b feat/rag-<name> feat/rag-context
```

---

## Wave 2, Agent A: ingest (ARA-071)

### Task 7: Job continuation helper

**Files:** Modify `app/repositories/jobs.py`. Test: `tests/test_job_continuation_integration.py`.

**Interfaces:** Produces `continue_locked(session, job: BackgroundJob, *, stage: str, progress: int) -> None`. It sets `state="queued"`, `stage`, `progress`, `attempts=0`, `generation += 1`, clears the lease, sets `available_at=now()`, and adds a `JobOutbox` row. Long embedding jobs use it to yield without spending retry attempts.

- [ ] **Step 1: Write the failing test.**
  - Given a claimed job, when `continue_locked` runs under its fence, then the job is queued at the next generation with `attempts == 0` and exactly one new outbox row.
  - Given the stale generation's token, then a subsequent `claim(..., old_generation)` returns `None`.
- [ ] **Step 2: Run.** Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** as specified, next to `retry_locked`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(jobs): let long jobs continue without spending attempts (ARA-071)`.

### Task 8: PyMuPDF4LLM child parser (layout `to_markdown`)

S2 measured this design (`scratchpad/spikes/s2/REPORT.md`). `LlamaMarkdownReader` is NOT used: it runs the legacy heading heuristic and found only the title, whereas layout `to_markdown` found 22/22 headings on Attention and 29/29 on RAG.

**Files:** Modify `app/jobs/pdf_parser.py` and `app/services/ingestion.py` (`parse_in_child` environment and limits). Test: `tests/test_pdf_parser_structured.py` (unit). It generates the fixture PDF with `tests/fixtures/create_structured_pdf.py` (copy that generator to `tests/support/structured_pdf.py`, because backend tests cannot import repo-root fixtures) and runs the real child via `parse_in_child`.

**Interfaces.** The child JSON output, consumed by Tasks 9 and 10:

```python
{
  "metadata": {"title": str|None, "authors": list[str], "year": int|None, "doi": str|None, "abstract": str|None},
  "pages": [{"page": 1,
             "text": "<plain text, PyMuPDF get_text(sort=True)>",       # unchanged: DocumentPage + fallback
             "printed_label": str|None,
             "markdown": "<pymupdf4llm layout Markdown for this page>",
             "boxes": [{"class": "section-header", "bbox": [x0, y0, x1, y1], "start": 268, "end": 309}]}],
  "warnings": [str],
  "extractor_version": "pymupdf4llm-1.28.2+layout" | "pymupdf4llm-1.28.2+legacy",
  "parser": "pymupdf4llm-layout" | "pymupdf4llm-legacy",
}
```

Child rules:
- **Pre-checks:** keep every existing check and error code: password, the 200-page limit, `PDF_TEXT_LIMIT`, `OCR_REQUIRED` and invalid PDF. They run with plain `pymupdf` before pymupdf4llm is imported.
- **Thread and memory tuning, set before importing pymupdf4llm (mandatory).** Without it, the import hangs under any RLIMIT_AS of 1–2 GiB.
  - Set `os.environ["OPENBLAS_NUM_THREADS"]="1"`, `os.environ["MALLOC_ARENA_MAX"]="2"` and `OMP_NUM_THREADS="2"`.
  - Install an `onnxruntime.InferenceSession` subclass whose `__init__` forces `SessionOptions(intra_op_num_threads=2, inter_op_num_threads=1)`, then assign it to `onnxruntime.InferenceSession`. The parent also passes these environment variables through its scrubbed environment.
- **Layout pass:** `pymupdf4llm.to_markdown(path, page_chunks=True, header=False, footer=False, use_ocr=False, show_progress=False)`. Each page dict gives `markdown = page["text"]` and `boxes` from `page["page_boxes"]` (`class`, `bbox`, `start`, `end` from `pos`).
- **Display formulas** (S2: layout renders them as empty `\n\n`): for each box with class `formula` whose slice is blank, insert `page.get_text("text", clip=bbox).strip()` from plain PyMuPDF into that slice, wrapped as `\n\n$$ {text} $$\n\n`. Then recompute the `start`/`end` offsets of the later boxes.
- **Fallback:** if the layout pass raises, run a **fresh** child invocation with `--legacy`. That invocation sets `sys.modules["pymupdf.layout"] = None` before importing pymupdf4llm and calls `to_markdown(path, page_chunks=True)`. `use_layout(False)` is not enough: it still loads ONNX, at 3.1 GiB VmPeak. The fallback output has `parser="pymupdf4llm-legacy"` and `boxes=[]`. The parent retries with `--legacy` once on a non-timeout parse error.
- **Limits:** `RLIMIT_AS = 1.5 GiB` and `RLIMIT_CPU = 150 s`. The parent's wall deadline stays at 120 s. The worker runs one parse child at a time (`mem_limit` stays 2g).

- [ ] **Step 1: Write the failing tests:**

```python
from support.structured_pdf import create_structured_pdf

async def test_given_structured_pdf_when_parsed_then_layout_markdown_has_headings_table_boxes(tmp_path):
    pdf = create_structured_pdf(tmp_path / "s.pdf")
    parsed = await parse_in_child(pdf.read_bytes())
    assert parsed["parser"] == "pymupdf4llm-layout"
    pages = parsed["pages"]
    assert [p["page"] for p in pages] == [1, 2, 3, 4]
    joined = "\n".join(p["markdown"] for p in pages).replace("**", "")
    assert "# " in joined and "2 Method" in joined and "References" in joined
    assert "|Model|Recall@10|Latency (ms)|" in joined.replace(" ", "")
    for page in pages:   # boxes tile the page Markdown exactly
        spans = sorted((b["start"], b["end"]) for b in page["boxes"])
        assert spans[0][0] == 0 and spans[-1][1] == len(page["markdown"])
        assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))
    assert any(b["class"] == "section-header" for p in pages for b in p["boxes"])

async def test_given_layout_failure_when_parsed_then_legacy_fallback(tmp_path, monkeypatch):
    pdf = create_structured_pdf(tmp_path / "s.pdf")
    monkeypatch.setenv("ARA_PARSER_FORCE_LAYOUT_ERROR", "1")    # test-only hook honoured only when APP_ENV=test
    parsed = await parse_in_child(pdf.read_bytes())
    assert parsed["parser"] == "pymupdf4llm-legacy" and parsed["pages"][0]["boxes"] == []
    assert "2 Method" in "\n".join(p["markdown"] for p in parsed["pages"])

async def test_given_image_only_pdf_then_ocr_required(tmp_path):
    import pymupdf
    document = pymupdf.open(); page = document.new_page()
    page.insert_image(pymupdf.Rect(50, 50, 300, 300), pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), 0))
    path = tmp_path / "image.pdf"; document.save(path)
    parsed = await parse_in_child(path.read_bytes())
    assert parsed["error"]["code"] == "OCR_REQUIRED"

async def test_given_parse_when_child_runs_then_it_fits_tuned_limits(tmp_path):
    # A 40-page concatenation of the fixture must parse under RLIMIT_AS 1.5 GiB within the deadline.
    ...
```

  Write the last test fully: build a 40-page PDF by `insert_pdf` of the fixture ten times, then assert a `parser` of `pymupdf4llm-layout` and no `error`. `parse_in_child` passes `ARA_PARSER_FORCE_LAYOUT_ERROR` through only when `APP_ENV=test`.
- [ ] **Step 2: Run.** Expected: FAIL (no `markdown`/`boxes` keys).
- [ ] **Step 3: Implement** per the rules above.
- [ ] **Step 4: Run.** Expected: PASS. Record the per-page time and the child `ru_maxrss` for the fixture in the journal.
- [ ] **Step 5: Commit** `feat(parser): parse PDFs with PyMuPDF4LLM layout (ARA-071)`.

### Task 9: Chunk plan with LlamaIndex parsers

**Files:** Create `app/rag/__init__.py` and `app/rag/chunking.py`. Test: `tests/test_chunking.py` (unit, no DB).

**Interfaces:**

```python
CHUNK_SET = "pymupdf4llm-1.28.2-layout:md-sentence-512-64:v1"   # bump on any parameter change

@dataclass(frozen=True)
class SectionDraft:
    ordinal: int; title: str; level: int; path: list[str]; role: str; page: int; page_end: int

@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int; section_ordinal: int | None; section_path: list[str]; heading: str; kind: str
    page: int; page_end: int; bboxes: list[list[float]]; text: str; context_text: str; token_count: int

@dataclass(frozen=True)
class ChunkPlan:
    chunk_set: str; sections: list[SectionDraft]; chunks: list[ChunkDraft]

def build_chunk_plan(pages: list[dict], *, title: str | None, chunk_tokens: int = 512,
                     overlap_tokens: int = 64, counter: TokenCounter | None = None) -> ChunkPlan
```

Algorithm. Everything is LlamaIndex except the offset mapping:
1. **One Document for the whole paper.** Concatenate the page Markdown with `"\n\n"` and record `page_offsets[i] = (start, end)` in the concatenation. The Document has **no metadata**; S2 found PDF metadata costs about 110 tokens per chunk. A single Document makes MarkdownNodeParser keep the heading stack across page breaks, which avoids S2's "one level short" carry problem.
2. `IngestionPipeline(transformations=[MarkdownNodeParser(), SentenceSplitter(chunk_size=chunk_tokens, chunk_overlap=overlap_tokens, tokenizer=tiktoken.get_encoding("o200k_base").encode)])`, run with `.run(documents=[doc])`. No docstore, cache or vector store.
3. **Section path:** take the `metadata["header_path"]` segments (the parents) plus the node's own heading when its first line starts with `#`. Strip `#`, `**`, `_`, `<sup>…</sup>` and whitespace from every segment. `level` is the number of `#` in the own heading.
4. **Heading-only nodes:** a node whose text is only its heading line merges into the following node in the same section, so no chunk under 50 tokens is just a heading.
5. **Offsets:** locate each chunk's text in the concatenation with a monotonic cursor (`text.find(chunk, cursor_start)`, where `cursor_start` = previous chunk start + 1, to tolerate overlaps). If it isn't found, fall back to the parent node's offset.
   - `page` is the page containing the chunk start; `page_end` is the page containing its end.
   - `bboxes` is `[[page, x0, y0, x1, y1]]` for every page box whose `[start, end)` (shifted by the page offset) overlaps the chunk range, excluding classes `page-header`, `page-footer` and `picture`.
6. **Sections:** each distinct path in reading order becomes a `SectionDraft`. `role` is `references` when the last segment matches `(?i)^(\d+\.?\s*)?(references|bibliography|works cited)$`, `front_matter` for chunks before the first heading, otherwise `body`.
7. **Kind:** `references` if in a references section; `table` if ≥2 lines match `^\|.*\|\s*$`; `front_matter` if in front matter; otherwise `text`.
8. **Text fields:** `heading = " > ".join(path)`; `context_text = "\n".join(filter(None, [title, heading, text]))`; `token_count = counter.count(text)`.
9. **No headings at all:** chunks still exist, with `section_path=[]` and `heading=""`, and `context_text` starts with the title.

- [ ] **Step 1: Write the failing tests** with literal pages (no PDF needed):

```python
PAGES = [
    {"page": 1, "markdown": "# **Sparse Retrieval**\n\n## Abstract\n\nWe study sparse retrieval.\n\n", "boxes": []},
    {"page": 2, "markdown": "## **2 Method**\n\n### 2.1 Indexing\n\nWe index passages with BM25 and", "boxes": []},
    {"page": 3, "markdown": "continue with dense vectors.\n\n## 3 Results\n\n|Model|Recall@10|\n|---|---|\n|BM25|0.61|\n\n",
     "boxes": [{"class": "table", "bbox": [72, 300, 540, 360], "start": 50, "end": 100}]},
    {"page": 4, "markdown": "## References\n\n- [1] Robertson. BM25.", "boxes": []},
]

def test_continuation_keeps_full_heading_stack_across_pages():
    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    cont = next(c for c in plan.chunks if "continue with dense" in c.text)
    assert cont.section_path[-2:] == ["2 Method", "2.1 Indexing"] and cont.page == 2 and cont.page_end == 3

def test_headings_are_clean_and_heading_only_nodes_merge():
    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    assert all("**" not in s.title for s in plan.sections)
    assert not any(c.text.strip() in {"## **2 Method**", "## 2 Method"} for c in plan.chunks)

def test_table_kind_with_box_and_references_excluded_role():
    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    table = next(c for c in plan.chunks if c.kind == "table")
    assert "Recall@10" in table.text and table.bboxes and table.bboxes[0][0] == 3
    assert any(s.role == "references" for s in plan.sections)
    assert any(c.kind == "references" for c in plan.chunks)

def test_context_text_prefixes_title_and_heading():
    plan = build_chunk_plan(PAGES, title="Sparse Retrieval")
    chunk = next(c for c in plan.chunks if "BM25 and" in c.text)
    lines = chunk.context_text.splitlines()
    assert lines[0] == "Sparse Retrieval" and lines[1].endswith("2 Method > 2.1 Indexing")

def test_no_headings_still_chunks_within_budget():
    plan = build_chunk_plan([{"page": 1, "markdown": "plain text " * 400, "boxes": []}], title=None)
    assert plan.chunks and all(c.context_text and c.section_path == [] for c in plan.chunks)
    assert max(c.token_count for c in plan.chunks) <= 512

def test_long_section_respects_token_budget():
    long = [{"page": 1, "markdown": "## Intro\n\n" + ("Sentence about retrieval. " * 600), "boxes": []}]
    plan = build_chunk_plan(long, title="T")
    assert all(c.token_count <= 512 for c in plan.chunks) and len(plan.chunks) > 3
```

- [ ] **Step 2: Run** `pytest tests/test_chunking.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** per the algorithm. Use `TokenCounter` from Task 17 if merged, otherwise a local `tiktoken.get_encoding("o200k_base")` (switch when Task 17 lands; agent C owns `tokens.py`).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(rag): build section-aware chunks with LlamaIndex (ARA-071)`.

### Task 10: Ingestion persistence

**Files:** Modify `app/services/ingestion.py` and `app/routes/documents.py` (chunk source endpoint: new fields). Test: update `tests/test_research_integration.py` (remove the Task 4 xfails it owns) and add `tests/test_ingestion_chunks_integration.py`.

**Interfaces:**
- Consumes `build_chunk_plan()` and the child JSON from Task 8.
- Produces, in the same fenced transaction that marks the document ready:
  - `document_sections` and `document_chunks` rows for `CHUNK_SET`;
  - `documents.parser` and `documents.chunk_set`.
- Then calls `ensure_index(session, document_id, profile_key)` (Task 14 interface; until Task 14 merges, call a stub that writes nothing; agent B replaces it).
- The chunk source endpoint returns `page`, `page_end`, `section` (heading), `kind` and the full text.

- [ ] **Step 1: Write the failing integration test.**
  - Given the structured fixture PDF uploaded through the existing upload helper, when the ingest job runs, then:
    - ≥4 sections and ≥4 chunks exist for `CHUNK_SET`;
    - one chunk has `kind == "table"`;
    - the `2 Method` continuation has `page == 3` and the `2 Method` heading;
    - `documents.parser == "pymupdf4llm-layout"`.
  - Given the job is delivered twice, then the chunk rows are not duplicated (unique ordinal per chunk set).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Replace the 3,200-character window loop with the plan persistence. Keep `DocumentPage` rows (page text) for the viewer and fallback. Delete the old chunks/sections for the document before inserting.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ingest): persist structured chunks (ARA-071)`.

### Task 11: Reindex command

**Files:** Create `scripts/reindex.py` (host wrapper) and `app/services/reindex.py` (`async def enqueue_reindex(resources) -> int`). Test: `tests/test_reindex_integration.py`.

**Interfaces:** For every `Document` with status `ready` and a `chunk_set` different from `CHUNK_SET`, enqueue a new `ingest` job (reusing `run_ingest_job`) and return the count. Run it with `docker compose exec api python -m app.services.reindex`.

- [ ] **Step 1: Write the failing test.** Given two ready documents with an old chunk set, when `enqueue_reindex` runs twice, then exactly two jobs are queued (idempotent while queued).
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ingest): re-ingest documents for the new chunk set (ARA-071)`.

---

## Wave 2, Agent B: index (ARA-072, ARA-070 catalog pieces)

### Task 12: Embedding catalog and adapters

**Files:** Create `app/integrations/embedding_catalog.py` and `app/integrations/embeddings.py`. Test: `tests/test_embeddings.py` (MockTransport) and `tests/test_embeddings_integration.py` (fixture servers).

**Interfaces:**

```python
@dataclass(frozen=True)
class EmbeddingProfile:
    key: str
    provider: Literal["openai", "ollama"]
    model_id: str
    display_name: str
    dimensions: int
    max_input_tokens: int
    batch_size: int
    query_instruction: str | None = None
    price_per_million: Decimal = Decimal("0")
    local_model_key: str | None = None

QWEN_QUERY = ("Instruct: Given a question about a scientific paper, retrieve passages of the paper "
              "that answer it\nQuery: ")
PROFILES: dict[str, EmbeddingProfile] = {
    "openai-3-large": EmbeddingProfile("openai-3-large", "openai", "text-embedding-3-large",
                                       "OpenAI text-embedding-3-large", 3072, 8191, 64,
                                       price_per_million=Decimal("0.13")),
    "qwen3-embed-4b": EmbeddingProfile("qwen3-embed-4b", "ollama", "qwen3-embedding:4b-q4_K_M",
                                       "Qwen3 Embedding 4B", 2560, 32768, 16, QWEN_QUERY,
                                       local_model_key="qwen3-embedding-4b"),
    "qwen3-embed-8b": EmbeddingProfile("qwen3-embed-8b", "ollama", "qwen3-embedding:8b-q4_K_M",
                                       "Qwen3 Embedding 8B", 4096, 32768, 16, QWEN_QUERY,
                                       local_model_key="qwen3-embedding-8b"),
}
DEFAULT_PROFILE = "openai-3-large"
def embedding_profile(key: str) -> EmbeddingProfile  # raises AppError(422, "INVALID_EMBEDDING_PROFILE", ...)

class Embedder(Protocol):
    profile: EmbeddingProfile
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_queries(self, texts: list[str]) -> list[list[float]]: ...
    async def close(self) -> None: ...

def create_embedder(resources, profile: EmbeddingProfile) -> Embedder
```

Implementation notes:
- **OpenAI:** wrap `llama_index.embeddings.openai.OpenAIEmbedding(model=..., api_key=..., api_base=settings.openai_base_url, dimensions=None, max_retries=2, timeout=60)`. Reserve cost before each batch via `reserve_embedding(resources, profile, tokens)`, a new helper in `llm.py` that reuses the `GenerationReservation` ledger with model key `embedding:<profile>`. Use `aget_text_embedding_batch` for documents and `aget_query_embedding` for queries.
- **Ollama:** wrap `llama_index.embeddings.ollama.OllamaEmbedding(model_name=..., base_url=settings.ollama_base_url, query_instruction=QWEN_QUERY, text_instruction=None, keep_alive=<G0>)`. Wrap each call in `retrieval_inference_slot(resources, local_model_key)` (Task 16).
- **Both:** L2-normalize the returned vectors and validate the length against `profile.dimensions`, raising `AppError(502, "EMBEDDING_INVALID", …)`.

- [ ] **Step 1: Write the failing tests.**
  - Query vs document instruction: the Qwen query text sent to `/api/embed` starts with `Instruct:`, and document texts are sent bare (assert on the MockTransport request body).
  - A dimension mismatch raises `EMBEDDING_INVALID`.
  - OpenAI reservation: given a $0 budget, `DAILY_BUDGET_EXCEEDED` is raised before any HTTP call.
  - Normalization: every returned vector has norm ≈ 1.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(rag): add embedding profiles and adapters (ARA-072)`.

### Task 13: Local catalog kinds and verification

**Files:** Modify `app/integrations/model_catalog.py`, `app/integrations/ollama.py` (`verify`), `app/services/local_models.py` (`model_dto`, list filtering) and `app/routes/ai.py` (`/models` returns all kinds; the composer filters chat). Test: `tests/test_local_model_kinds.py` and the integration tests against `runtime-fixture`.

**Interfaces:**
- `LocalModelSpec` gains `kind: Literal["chat","embedding","reranker"] = "chat"` and `embedding_dimensions: int | None = None`.
- New specs, using G0 digests and sizes:
  - `qwen3-embedding-4b` (`qwen3-embedding:4b-q4_K_M`, dims 2560)
  - `qwen3-embedding-8b` (`qwen3-embedding:8b-q4_K_M`, dims 4096)
  - `qwen3-reranker-0.6b` (G0 model id)
- `OllamaRuntime.verify(spec, context_window=...)` branches on `spec.kind`:
  - **chat:** unchanged.
  - **embedding:** requires `"embedding" in capabilities`, then an `/api/embed` probe of `"probe"` whose returned length equals `spec.embedding_dimensions`. No chat probe.
  - **reranker:** an `/api/generate` raw probe with one relevant and one irrelevant pair. It requires `logprobs` and P(yes) relevant > irrelevant; otherwise `MODEL_VALIDATION_FAILED`.
- `model_dto` returns `kind`. Settings shows all kinds; the composer `ModelSwitcher` filters `kind === "chat"` (agent E).

- [ ] **Step 1: Write the failing tests.**
  - Verifying an embedding spec against fixture `/api/show` with `capabilities=["embedding"]` passes and records `embedding_dimensions`.
  - Wrong dims fail with `MODEL_VALIDATION_FAILED`.
  - A reranker without logprobs fails.
  - `/models` items include `kind`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS, and the existing local-model suites still pass.
- [ ] **Step 5: Commit** `feat(models): manage embedding and reranker models in the single runtime (ARA-072)`.

### Task 14: Embed job and blue/green indexes

**Files:** Create `app/rag/indexing.py`. Modify `app/jobs/actors.py` (kind `embed`) and `app/services/ingestion.py` (replace the Task 10 stub). Test: `tests/test_indexing_integration.py`.

**Interfaces:**

```python
async def effective_profile(session, paper: Paper) -> tuple[str, Literal["default", "paper"]]
    # paper.retrieval_profile, else ModelConfiguration["retrieval"].embedding_profile, else DEFAULT_PROFILE

async def ensure_index(session, document_id: UUID, profile_key: str, *, rebuild: bool = False) -> RetrievalIndex
    # Upserts the (document, profile, documents.chunk_set) row; if not ready (or rebuild), enqueues an
    # `embed` job {"index_id": ..., "document_id": ..., "profile": ...} unless one is queued/processing.

async def ready_index(session, document_id: UUID, preferred: str) -> RetrievalIndex | None
    # The preferred profile's ready index for the current chunk set; else the most recently ready
    # index of another profile for the same chunk set (blue/green); else None.

async def run_embed_job(resources, job_id, generation, token, payload) -> None
```

`run_embed_job` loop:
1. Load the chunks of the index's chunk set that have no `ChunkEmbedding` for the profile.
2. Embed them in profile batches using each chunk's `context_text`.
3. Upsert each batch (`INSERT … ON CONFLICT (chunk_id, profile) DO NOTHING`), then update `embedded` and `progress` under `fence()`.
4. After ~240 s of work, call `continue_locked(stage="embedding")` and return.
5. When finished, set the index to `ready` and the job to completed.

Error handling:
- An unavailable profile (no key, model not ready) sets the index `unavailable` with the code and completes the job without retry.
- Any other error goes through `fail()`.

- [ ] **Step 1: Write the failing tests** (fixture OpenAI embeddings):
  - A ready document gives a ready index with `embedded == total == chunk count`, and one `ChunkEmbedding` per chunk.
  - A duplicate delivery (run twice with stale generation) writes no duplicates and the lost-lease write is rejected.
  - A continuation (patch the time budget to 0) gives generation+1 with `attempts == 0`, then completes.
  - Switching profile: the old ready index keeps serving `ready_index()` until the new one is ready.
  - A missing OpenAI key makes the index `unavailable` with `MODEL_NOT_CONFIGURED`.
  - **Review Focus 3:** given a question streaming during a profile switch, `ready_index()` returns the old ready index until the new one completes.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(rag): build resumable blue-green embedding indexes (ARA-072)`.

### Task 15: Retrieval settings and paper retrieval APIs

**Files:** Modify `app/routes/retrieval.py` (implement the Task 5 stubs except memory). Test: `tests/test_retrieval_api_integration.py`.

**Behavior:**
- `GET /retrieval/profiles` lists `PROFILES`. Status is `available` when OpenAI is configured, or when the local model is installed, ready and verified. Otherwise `unavailable_reason` is plain language, e.g. "Add an OpenAI API key on the server." or "Download Qwen3 Embedding 4B in Settings."
- `GET`/`PUT /retrieval/settings` stores `ModelConfiguration["retrieval"]`. `PUT` validates the profile key and does not require availability.
- `GET /papers/{id}/retrieval` reports `mode`:
  - `hybrid` when `ready_index()` exists;
  - `keyword` when chunks exist but no ready index, with `mode_note` such as "Search index is building (42%)." or "Search index unavailable: …";
  - `unavailable` when there is no ready document.
- `PUT /papers/{id}/retrieval` uses the request UUID for idempotency, reusing the `ModelRequest` pattern (store it in a new JSON row under `ModelConfiguration["retrieval_request:<uuid>"]`; replay returns the same body). It sets `papers.retrieval_profile` and calls `ensure_index`.
- `POST …/rebuild` calls `ensure_index(rebuild=True)`. It deletes the profile's embeddings for the current chunk set only after the rebuilt index is ready (blue/green: the rebuild writes into a new `RetrievalIndex` row keyed by a rebuild suffix of the chunk set, e.g. `chunk_set + "#r<n>"`).

- [ ] **Step 1: Write the failing tests.** Each behavior above, including request-UUID replay and invalid profile 422.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): expose retrieval settings and paper indexes (ARA-072)`.

### Task 16: Retrieval inference admission slot

**Files:** Modify `app/repositories/local_models.py` and `app/services/local_models.py`. Test: `tests/test_retrieval_slot_integration.py`.

**Interfaces:** Produces `retrieval_inference_slot(resources, key)`, an async context manager. It is the same as `local_inference_slot`, except it uses `ModelUse` slot `"retrieval"` and a 30 s lease, and it allows concurrency with the `"inference"` slot. It obeys the same fences: `pending_owner`, processing download/delete jobs, and installation ready.

- [ ] **Step 1: Write the failing tests.**
  - A retrieval slot can be held while a generation slot is held.
  - It is refused during a processing `model_download` job.
  - Two concurrent retrieval holders: the second gets `LOCAL_MODEL_BUSY`, and callers retry once after 1 s (embedding only).
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(models): admit retrieval inference alongside generation (ARA-072)`.

---

## Wave 2, Agent C: context (ARA-076)

### Task 17: Token counters

**Files:** Create `app/integrations/tokens.py`. Test: `tests/test_tokens.py`.

**Interfaces:**

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...

class TiktokenCounter:
    def __init__(self, encoding: str): ...
    def count(self, text: str) -> int        # len(enc.encode(text, disallowed_special=()))
    def encode(self, text: str) -> list[int]

class RatioCounter:
    def __init__(self, chars_per_token: float, margin: float = 1.10): ...
    def count(self, text: str) -> int        # ceil(len(text) / chars_per_token * margin)

MESSAGE_OVERHEAD = 4
def count_messages(counter: TokenCounter, messages: Sequence[PromptMessage]) -> int
    # sum(counter.count(m.content) + MESSAGE_OVERHEAD) + 3
```

- [ ] **Step 1: Write the failing tests.**
  - `TiktokenCounter("o200k_base").count("hello world") == 2`.
  - RatioCounter on 1,000 chars at 3.5 chars/token with a 1.10 margin gives 315.
  - `count_messages` adds the overhead.
  - Both counters return far fewer tokens than `len(text.encode())` for English prose (≥3× fewer on a 2,000-character sample).
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(context): count real tokens (ARA-076)`.

### Task 18: Model context registry

**Files:** Create `app/integrations/context_registry.py`. Modify `app/integrations/llm.py` (`model_limits` delegates to the registry; `generation_configuration` records window, output and thinking allowance) and `app/core/config.py` (`hosted_working_context_tokens: int = 64000`, `ollama_thinking_tokens: int = <G0>`, `local_chars_per_token: float = <G0>`). Test: `tests/test_context_registry.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class ContextProfile:
    model: str
    provider: Literal["openai", "ollama"]
    window: int              # hosted: 1_050_000; local: settings.ollama_context_window
    max_output: int          # answer allowance (hosted OUTPUT_LIMIT; local settings.ollama_max_output_tokens)
    thinking_allowance: int  # local: settings.ollama_thinking_tokens when effort enables thinking, else 0; hosted 0
    safety: int              # 512
    input_budget: int        # min(window - max_output - thinking_allowance - safety, working cap)
    counter: TokenCounter

def context_profile(resources, model: str, effort: str) -> ContextProfile
```

- Hosted: `counter = TiktokenCounter(<G0 encoding>)` and `input_budget = min(window - max_output - safety, settings.hosted_working_context_tokens)`.
- Local: `counter = RatioCounter(settings.local_chars_per_token)`. `OllamaLLM.parameters` sets `num_predict = max_output + thinking_allowance` and checks `count_messages(...) <= input_budget`.

- [ ] **Step 1: Write the failing tests.**
  - The hosted Luna profile has an input budget of 64,000 (cap).
  - Local 7B with `effort="none"`: `input_budget == window - max_output - 512`.
  - With a thinking effort: the budget shrinks by `ollama_thinking_tokens`, and `num_predict` grows by the same amount.
  - `generation_configuration` includes `window`, `max_output`, `thinking_allowance` and `input_budget`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS, and the existing chat/summary tests are updated where they asserted byte budgets (list them in the journal).
- [ ] **Step 5: Commit** `feat(context): give every model a real context profile (ARA-076)`.

### Task 19: Budget allocator and answer prompt assembly

**Files:** Create `app/services/context.py`. Test: `tests/test_context_assembly.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class PromptMessage:
    role: Literal["system", "user", "assistant"]
    content: str

@dataclass(frozen=True)
class Allocation:
    evidence: int; summary: int; recent: int; recall: int

MIN_EVIDENCE = 512
def allocate(available: int, *, summary_need: int, recent_need: int, recall_need: int) -> Allocation
    # summary <= 10%, recent <= 25%, recall <= 7% of `available`; each takes min(need, cap);
    # evidence = available - summary - recent - recall (always >= 58% of available)

@dataclass(frozen=True)
class PaperHeader:
    title: str | None; authors: list[str]; year: int | None

@dataclass(frozen=True)
class AssembledPrompt:
    messages: list[PromptMessage]; usage: ContextUsage; allocation: Allocation

INSTRUCTIONS_VERSION = "2"
def answer_instructions(paper: PaperHeader) -> str   # the system message shown in spec §4.7

def render_history_turn(message: ChatMessage) -> str
    # assistant content with [source:<uuid>] replaced by "(p. N)" using message.citations; drops the sentinel

def assemble_answer_prompt(*, profile: ContextProfile, paper: PaperHeader, history: list[ChatMessage],
                           memory_summary: tuple[int, str] | None, recalled: list[tuple[str, str]],
                           evidence_block: Callable[[int], str], question: str,
                           retrieved_for: str | None) -> AssembledPrompt
```

Assembly rules:
- Message order: system instructions; the summary system message, if any; recent completed turns, newest kept first within `allocation.recent`, rendered via `render_history_turn` and with a single turn over the recent budget truncated to its last `recent` tokens; the user message.
- The user message is `"Paper passages (retrieved for: \"{retrieved_for or question}\"):\n\n" + evidence_block(allocation.evidence) + "\n\nQuestion: " + question`.
- Raise `LLMError("CONTEXT_LIMIT", ..., 413)` only if `available < MIN_EVIDENCE`, where `available = profile.input_budget - tokens(instructions + question + wrappers)`.

- [ ] **Step 1: Write the failing tests.**
  - The allocator properties: the sum ≤ available, evidence ≥ 58%, and needs below the caps are fully granted.
  - A history assistant message with `[source:<uuid>]` renders as "(p. 6)".
  - The assembled prompt for an 8k local profile with a 6,000-token prior answer stays within `input_budget` (counted via `count_messages`) and keeps the evidence.
  - **Review Focus 5:** a 7,000-token question on the 8k profile raises `CONTEXT_LIMIT`; a 2,000-token question succeeds with evidence ≥ `MIN_EVIDENCE`.
  - The hosted profile keeps more turns than the local one.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(context): allocate budgets and assemble role-separated prompts (ARA-076)`.

### Task 20: Providers accept message lists

**Files:** Modify `app/integrations/llm.py` (`HostedLLM.stream_messages`, `HostedLLM.complete_messages`) and `app/integrations/ollama_llm.py` (same). Test: `tests/test_provider_messages.py` (MockTransport for both).

**Interfaces:**
- `async def stream_messages(model, effort, messages: list[PromptMessage]) -> AsyncIterator[str]`
- `async def complete_messages(model, effort, messages, *, schema=None, max_output_tokens=None) -> Completion`

Request shapes:
- Hosted: `instructions = messages[0].content` (it must be a system message). `input = [{"role": m.role, "content": m.content} for m in messages[1:]]`, with additional system messages sent as role `developer`. Keep `store=False`, no retries, and the existing error mapping.
- Ollama: `messages = [{"role": m.role, "content": m.content} …]`, with options from the context profile (`num_ctx = window`, `num_predict = max_output + thinking_allowance`).
- Size check: `count_messages(profile.counter, messages) <= profile.input_budget`, else `CONTEXT_LIMIT`.

The existing `stream`/`complete` stay as thin wrappers (`[system(instructions), user(prompt)]`), so summaries keep working until Task 27.

- [ ] **Step 1: Write the failing tests.** Assert the exact JSON bodies sent for a 4-message list to each provider, plus the size-limit rejection.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(llm): send role-separated message lists (ARA-076)`.

---

## Wave 2, Agent E: ui-a (ARA-075 part 1)

Read `DESIGN.md` §§ shell, composer and colour rules, and `PRODUCT.md`, first. Use the existing shadcn primitives (`collapsible`, `dialog`, `radio`-style lists from `SettingsPage`, `badge`, `progress`). No new colours; status uses the existing badge styles.

### Task 21: Retrieval hooks and the Settings Retrieval section

**Files:** Create `src/hooks/queries/retrieval.ts` and `src/features/settings/RetrievalSettingsSection.tsx`. Modify `SettingsPage.tsx` and `lib/query-keys.ts`. Test: `src/features/settings/retrieval-settings.test.tsx`.

**Interfaces:**

```ts
export function useEmbeddingProfiles(): UseQueryResult<EmbeddingProfilePage>
export function useRetrievalSettings(): UseQueryResult<RetrievalSettings>
export function useSaveRetrievalSettings(): UseMutationResult<RetrievalSettings, ApiError, RetrievalSettings>
export function usePaperRetrieval(paperId: string): UseQueryResult<PaperRetrieval>   // refetchInterval 1500 while any index is queued|embedding
export function useUpdatePaperRetrieval(paperId: string): UseMutationResult<PaperRetrieval, ApiError, { profile: string | null }>
export function useRebuildPaperRetrieval(paperId: string): UseMutationResult<PaperRetrieval, ApiError, void>
```

The mutations generate `request_id` with `crypto.randomUUID()` once per user action.

Section layout:
- Heading "Search and retrieval".
- A radio list "Default search model" with `display_name`, a mono `model_id` secondary line, and the unavailable reason with a link to Local models.
- A switch-style toggle "Rerank results with a local model", disabled with a reason when the reranker isn't installed.
- "Save" follows the existing defaults pattern.

- [ ] **Step 1: Write the failing tests** (`mockApi` routes):
  - Renders three profiles with OpenAI selected by default.
  - An unavailable Qwen shows "Download Qwen3 Embedding 4B in Settings" and is still selectable.
  - Save sends `PUT /retrieval/settings` with the chosen key.
  - The reranker toggle is disabled with its reason when unavailable.
- [ ] **Step 2: Run** `docker compose exec frontend npx vitest run src/features/settings/retrieval-settings.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.** **Step 4: Run.** Expected: PASS, plus `npm run check`.
- [ ] **Step 5: Commit** `feat(ui): choose the default search model in Settings (ARA-075)`.

### Task 22: Paper "Search index" Advanced panel

**Files:** Create `src/features/workspace/SearchIndexPanel.tsx`. Modify `DetailsPanel.tsx` (mount at the bottom, collapsed by default). Test: `src/features/workspace/search-index.test.tsx`.

**Behavior:**
- A collapsed `Collapsible` labelled "Search index" with a muted "Advanced" text.
- Expanded, it shows:
  - "Searching with {display_name}" plus "(default)" or "(this paper)";
  - state: Ready, Building 42% with a progress bar, Unavailable with the reason, or Failed with "Rebuild";
  - "{chunk_count} passages · {section_count} sections";
  - buttons "Change model" (a dialog with the profile radio list plus "Use default") and "Rebuild index".
- While building, the note "Answers use keyword search until the index is ready."

- [ ] **Step 1: Write the failing tests.**
  - Collapsed by default.
  - Expands to show Ready.
  - Change model to Qwen 4B sends `PUT` with `profile: "qwen3-embed-4b"` and shows Building with polling.
  - Use default sends `profile: null`.
  - The failed state shows Rebuild.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS, plus `npm run check`.
- [ ] **Step 5: Commit** `feat(ui): show and change a paper's search index (ARA-075)`.

Also in Task 22: `ModelSwitcher` filters `models.filter(m => m.kind === "chat")`, and Settings Local models shows a kind badge ("Search" for embedding, "Reranker"). Add these assertions to the existing `ModelSwitcher.test.tsx` and `settings.test.tsx` (failing first).

---

## Wave 3, Agent F: retrieval (ARA-073, ARA-074)

### Task 23: Postgres retrievers (LlamaIndex)

**Files:** Create `app/rag/retrievers.py`. Test: `tests/test_retrievers_integration.py`.

**Interfaces:**

```python
def chunk_node(chunk: DocumentChunk) -> TextNode
    # TextNode(id_=str(chunk.id), text=chunk.text, metadata={"page": chunk.page, "page_end": chunk.page_end,
    #          "section": chunk.heading, "kind": chunk.kind, "ordinal": chunk.ordinal,
    #          "document_id": str(chunk.document_id)})

class PgLexicalRetriever(BaseRetriever):
    def __init__(self, sessions, document_id: UUID, chunk_set: str, *, top_k: int = 30,
                 include_references: bool = False): ...
    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]
        # websearch_to_tsquery('english', q); ORDER BY ts_rank_cd(search_vector, query, 32) DESC, ordinal
        # if no rows: fall back to OR of the query's words (to_tsquery with ' | ')
    def _retrieve(self, query_bundle): raise NotImplementedError("async only")

class PgVectorRetriever(BaseRetriever):
    def __init__(self, sessions, document_id: UUID, chunk_set: str, profile: str, *, top_k: int = 30,
                 include_references: bool = False): ...
    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]
        # requires query_bundle.embedding; JOIN chunk_embeddings ON chunk_id AND profile;
        # ORDER BY embedding <=> CAST(:q AS halfvec) ; score = 1 - distance
```

Both filter `document_id`, `chunk_set` and `kind <> 'references'` unless `include_references`, and each opens its own session.

- [ ] **Step 1: Write the failing tests.**
  - Fixture data: two documents with chunks and fixture-vector embeddings.
  - Lexical: "BM25 recall" returns the Results table chunk first.
  - Vector: a paraphrase query embedded with `fixture_vector` returns the Method chunk in the top 3.
  - Isolation: a query matching only the other document's chunks returns nothing.
  - References are excluded by default.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(rag): retrieve with LlamaIndex over Postgres (ARA-073)`.

### Task 24: Fusion, expansion and packing

**Files:** Create `app/rag/fusion.py` and `app/rag/packing.py`. Test: `tests/test_fusion_packing.py`.

**Interfaces:**

```python
def reciprocal_rank_fusion(ranked: Sequence[Sequence[NodeWithScore]], *, k: int = 60) -> list[NodeWithScore]
    # score(node) = sum(1 / (k + rank)) over lists (rank from 1); ties -> lower ordinal first; ids deduped

@dataclass(frozen=True)
class Passage:
    handle: str; chunk_id: UUID; document_id: UUID; page: int; page_end: int; section: str; kind: str; text: str
    def render(self) -> str
        # f"[{handle}] {section or 'Untitled section'} · p. {page}{'–'+str(page_end) if page_end != page else ''}\n{text}\n"

def pack_evidence(nodes: Sequence[NodeWithScore], *, budget: int, counter: TokenCounter,
                  neighbours: Mapping[str, Sequence[TextNode]] | None = None, max_passages: int = 16) -> list[Passage]
    # Greedy by fused/rerank order; skip a node that doesn't fit; then add neighbours (same section)
    # while budget remains; finally sort by (page, ordinal) and assign handles S1..Sn in that order.
```

- [ ] **Step 1: Write the failing tests.**
  - RRF on two lists ranks a node present in both above singletons.
  - The fusion is deterministic.
  - `pack_evidence` never exceeds the budget (the counter sums rendered passages).
  - Handles are assigned in document order.
  - Neighbours are added only when budget remains.
  - Oversized single nodes are skipped, not truncated.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(rag): fuse rankings and pack evidence by tokens (ARA-073)`.

### Task 25: Short handles, the stream transducer and the insufficient-evidence sentinel

**Files:** Create `app/rag/citations.py`. Test: `tests/test_handle_transducer.py`.

**Interfaces:**

```python
INSUFFICIENT = "[insufficient-evidence]"

class HandleMap:
    def __init__(self, passages: Sequence[Passage]): ...
    def resolve(self, handle: str) -> Passage | None

class HandleTransducer:
    """Feed model deltas; emit text with [S#] (and 【S#】, [S1, S3]) mapped to [source:<uuid>]."""
    def __init__(self, handles: HandleMap): ...
    def feed(self, delta: str) -> str      # holds back an unterminated '[' / '【' tail (≤ 24 chars)
    def flush(self) -> str
    unknown: set[str]                      # handles not in the map
    insufficient: bool                     # sentinel seen (removed from output)
```

Mapping rules:
- `[S3]` becomes `[source:<uuid3>]`; `[S1, S3]` and `[S1][S3]` become two markers; `【S2】` maps the same way. Matching is case-insensitive on `S`.
- The sentinel `[insufficient-evidence]` is removed and sets `insufficient`.
- Text inside fenced code blocks is not mapped.

At completion, `chat.py` fails with `UNGROUNDED_OUTPUT` if `unknown` is non-empty. It completes with `grounding="insufficient"` if the sentinel was seen. It fails with `UNGROUNDED_OUTPUT` if there are no citations and no sentinel.

- [ ] **Step 1: Write the failing tests** (**Review Focus 4**):

```python
def test_split_marker_across_deltas():
    t = HandleTransducer(handle_map("S12"))
    out = t.feed("Recall improves [S1") + t.feed("2] overall.") + t.flush()
    assert out == f"Recall improves [source:{uid('S12')}] overall."

def test_grouped_and_unicode_handles():
    t = HandleTransducer(handle_map("S1", "S3", "S2"))
    out = t.feed("A [S1, S3] and B 【S2】.") + t.flush()
    assert out.count("[source:") == 3 and "【" not in out

def test_unknown_handle_recorded():
    t = HandleTransducer(handle_map("S1"))
    t.feed("Claim [S99].") ; t.flush()
    assert t.unknown == {"S99"}

def test_sentinel_removed_and_flagged():
    t = HandleTransducer(handle_map("S1"))
    out = t.feed("[insufficient-evidence] The paper does not report latency.") + t.flush()
    assert t.insufficient and out.startswith("The paper")

def test_code_block_untouched():
    t = HandleTransducer(handle_map("S1"))
    out = t.feed("```\nx = [S1]\n```") + t.flush()
    assert "[S1]" in out
```

- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(rag): map short citation handles while streaming (ARA-073)`.

### Task 26: Pipeline and chat integration

**Files:** Create `app/rag/pipeline.py`. Modify `app/services/chat.py` and `app/routes/chat.py`. Test: update `tests/test_ai_integration.py` and `tests/test_citation_markers_integration.py` (owned xfails), and add `tests/test_chat_retrieval_integration.py`.

**Interfaces:**

```python
@dataclass
class EvidenceResult:
    passages: list[Passage]; summary: RetrievalSummary; trace: dict

async def retrieve_evidence(resources, *, document_id: UUID, chunk_set: str, preferred_profile: str,
                            queries: list[str], budget: int, counter: TokenCounter,
                            rerank: bool) -> EvidenceResult
```

`retrieve_evidence` does the following:
1. Gets `ready_index()` (Task 14).
2. If there is one, embeds the queries (Task 12) and runs lexical plus vector per query in parallel (separate sessions). Otherwise runs lexical only, with `mode="keyword"` and a note.
3. Applies RRF across all lists.
4. Applies the optional `OllamaQwenRerank` (Task 28) to the top 30.
5. Fetches neighbours.
6. Calls `pack_evidence`.
7. Builds the trace:
   - `queries`;
   - per-list `[(chunk_id, rank, score)]` for the top 30;
   - `fused` top 30;
   - `reranked`;
   - `selected` handles mapped to chunk ids;
   - `budget`;
   - `timings_ms`.

`chat.py` changes:
- `prepare()` (in its transaction): replay/UUID checks, the processing guard, model validation, document ready, insert the user and assistant rows, reserve the budget using the Task 18 profile's `input_budget + max_output`. It returns no prompt.
- `stream_answer()`:
  1. Emit `message.started` and `message.status{planning}`.
  2. Call `plan_query()`, owned by agent G. Until G merges, use the deterministic fallback `QueryPlan(standalone_question=question, search_queries=[question], needs_paper_evidence=True, source="fallback")`.
  3. Emit `status{retrieving}`, then call `retrieve_evidence`.
  4. Emit `status{reranking}` when applicable.
  5. Call `assemble_answer_prompt`, which needs memory from G or `None`.
  6. Persist `retrieval`, `context` and `configuration` on the assistant row before the provider call.
  7. Emit `status{generating}` and stream through `HandleTransducer` (save checkpoints of the transduced text).
  8. Finalize: `validate_citations(content, passages_as_chunks, document_id)`, then `grounding`, then `message.completed` with `retrieval`, `context` and `grounding`.
- **Replay:** the existing replay branch returns the stored message, so no planner, retrieval or generation runs. Assert this with call counters.

- [ ] **Step 1: Write the failing tests:**
  - A streamed answer cites `[S1]` and persists a canonical source plus `retrieval.mode == "hybrid"` (fixture embeddings ready).
  - With no ready index, `mode == "keyword"` and the note mentions building.
  - Status events arrive in order: planning, retrieving, generating.
  - A replayed UUID makes zero calls to `retrieve_evidence` or the provider (monkeypatched counters).
  - A foreign handle fails with `UNGROUNDED_OUTPUT`.
  - The sentinel completes with `grounding == "insufficient"`.
  - An old assistant answer in history containing `[source:<uuid>]` from a previous turn no longer causes `UNGROUNDED_OUTPUT` (regression for the old bug).
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS, and all previously passing chat tests pass or are deliberately updated (listed in the journal).
- [ ] **Step 5: Commit** `feat(chat): answer from hybrid retrieval with status events (ARA-073)`.

### Task 27: Summaries on structured chunks

**Files:** Modify `app/services/summarization.py`. Test: update the summary tests in `tests/test_ai_integration.py`.

**Interfaces:**
- Map batches follow section boundaries in chunk-set order, packed by `profile.input_budget` (Task 18), with `[S#]` handles per batch through `Passage`/`HandleMap`.
- Partial summaries keep canonical markers after transduction; the reduce step keeps canonical markers.
- Checkpoint and paid-call semantics are unchanged.

- [ ] **Step 1: Write the failing tests.**
  - A summary of the structured fixture cites chunks from ≥2 sections with canonical markers.
  - A batch never splits a section unless the section alone exceeds the budget.
  - The local profile uses the smaller budget.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(summary): summarize by section with short handles (ARA-073)`.

### Task 28: Ollama reranker (ARA-074; only if G0 says go)

**Files:** Create `app/rag/rerank.py`. Test: `tests/test_rerank.py` (MockTransport) and the integration test against the fixture.

**Interfaces:**

```python
RERANK_TEMPLATE = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and "
                   "the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n"
                   "<|im_start|>user\n<Instruct>: Given a question about a scientific paper, retrieve passages "
                   "of the paper that answer the question\n<Query>: {query}\n<Document>: {document}<|im_end|>\n"
                   "<|im_start|>assistant\n<think>\n\n</think>\n\n")

class OllamaQwenRerank(BaseNodePostprocessor):
    top_n: int = 12
    def __init__(self, resources, model_key: str, *, top_n: int = 12, concurrency: int = <G0>): ...
    async def _apostprocess_nodes(self, nodes, query_bundle) -> list[NodeWithScore]
    def _postprocess_nodes(self, nodes, query_bundle=None): raise NotImplementedError("async only")

def yes_probability(logprobs_entry: dict) -> float   # softmax over yes/no top_logprobs; 0.5 when neither present
```

- Each node becomes a `/api/generate` request (`raw: true`, `options: {temperature: 0, num_predict: 1}`, `logprobs: true`, `top_logprobs: 20`, `keep_alive: <G0>`) inside `retrieval_inference_slot`, with document text truncated to 512 tokens.
- Results are sorted by the score.
- On any error, return the input order unchanged and set `trace["rerank_skipped"] = <code>`.

- [ ] **Step 1: Write the failing tests.**
  - `yes_probability` math.
  - Fixture ordering: the relevant passage moves to the top.
  - Runtime unavailable: the order is unchanged and the skip is recorded.
  - The disabled setting means no calls.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(rag): rerank locally with Qwen3-Reranker through Ollama (ARA-074)`.

If G0 is no-go: skip this task, set ARA-074 to `deferred` with the S1 evidence, and keep `rerank=False` in the pipeline.

---

## Wave 3, Agent G: memory (ARA-077)

### Task 29: Query planner

**Files:** Create `app/services/memory.py` (`plan_query`). Test: `tests/test_query_planner.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class QueryPlan:
    standalone_question: str; search_queries: list[str]; needs_paper_evidence: bool
    source: Literal["model", "fallback", "first_turn"]

async def plan_query(resources, *, model: str, effort: str, history: list[ChatMessage],
                     memory_summary: str | None, question: str) -> QueryPlan
```

- First turn (no completed history): return `source="first_turn"` with `[question]` and no model call.
- Follow-ups: call `complete_messages` with a JSON schema `{standalone_question: str, search_queries: array[1..3] of str, needs_paper_evidence: bool}`.
  - Hosted chats use `gpt-5.6-luna`, effort `none`, and reserve budget.
  - Local chats use the same local model, with effort `none` if supported, otherwise its lowest effort.
  - Input: short instructions, the summary, and the last 2 turns rendered via `render_history_turn`, then the question.
- On any error, or invalid JSON: the fallback heuristic (current `retrieval_query` behavior), with `source="fallback"`.

- [ ] **Step 1: Write the failing tests.**
  - The first turn makes no call.
  - A follow-up "How did it compare to the baselines?" after a turn about RAG produces queries containing "RAG" (fixture model returns structured output).
  - A local chat never calls the hosted client (MockTransport for the hosted client raises if hit).
  - Invalid JSON falls back.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(memory): rewrite follow-ups into standalone queries (ARA-077)`.

### Task 30: Running summary compaction

**Files:** Modify `app/services/memory.py` (`maybe_enqueue_compaction`, `run_compact_job`, `latest_memory`), `app/jobs/actors.py` (kind `compact_chat`) and `app/routes/retrieval.py` (`GET /chats/{id}/memory`). Test: `tests/test_compaction_integration.py`.

**Interfaces:**

```python
COMPACTION_PROMPT_VERSION = "1"
# settings.memory_compaction_ratio: float = 0.6 (core/config.py; E2E lowers it via env MEMORY_COMPACTION_RATIO)
async def latest_memory(session, chat_id: UUID) -> ChatMemory | None
async def maybe_enqueue_compaction(session, chat_id: UUID, model: str) -> BackgroundJob | None
    # after a completed assistant turn: unsummarized = completed messages after latest.through_message_id;
    # if count_messages(unsummarized) > settings.memory_compaction_ratio * allocation cap for `recent`
    # enqueue compact_chat {"chat_id", "through_message_id": <oldest-half boundary id>, "model"}
    # unless a compact_chat job for (chat_id, through_message_id) exists
async def run_compact_job(resources, job_id, generation, token, payload) -> None
    # new summary = complete_messages(previous summary + evicted turns rendered via render_history_turn)
    # into sections "User goals", "Established facts (with pages)", "Questions asked", "Open threads",
    # "Preferences/corrections"; insert ChatMemory(version=prev+1, through_message_id) — unique
    # constraints make a duplicate delivery a no-op; local chat -> same local model; hosted -> luna/none
```

- [ ] **Step 1: Write the failing tests.**
  - Below the threshold, nothing is enqueued.
  - Above it, one job is enqueued; enqueueing again is a no-op.
  - Running the job twice produces one `ChatMemory` row (version 1).
  - Version 2 includes version 1's text as input (assert on the fixture request body).
  - A local chat makes no hosted call.
  - `GET /chats/{id}/memory` returns the summary and `summarized_messages`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(memory): keep a versioned running summary (ARA-077)`.

### Task 31: Turn recall

**Files:** Modify `app/services/memory.py` (`run_embed_turn_job`, `recall_turns`) and `app/jobs/actors.py` (kind `embed_turn`). Test: `tests/test_recall_integration.py`.

**Interfaces:**
- `run_embed_turn_job` embeds the `"Q: {question}\nA: {render_history_turn(answer)}"` text using the paper's effective profile, and upserts `ChatTurnEmbedding`. It is enqueued after each completed assistant message.
- `async def recall_turns(resources, *, chat_id, profile, query_vector, exclude_ids: set[UUID], limit: int = 3) -> list[tuple[str, str]]` returns `(question, answer)` pairs older than the recent window, by cosine similarity, above 0.3 similarity.

- [ ] **Step 1: Write the failing tests.** With fixture vectors: turn 2 about "datasets" is recalled for "which datasets again?" at turn 30, and turns inside the recent window are excluded.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(memory): recall relevant earlier turns (ARA-077)`.

### Task 32: Memory in the answer path

Starts only after Task 26 is merged into `feat/rag-context` (both edit `chat.py`).

**Files:** Modify `app/services/chat.py`; agent G coordinates with F through the lead. Test: `tests/test_long_conversation_integration.py`.

**Interfaces:** `stream_answer` uses:
- `plan_query` (Task 29);
- `latest_memory`, passed as `memory_summary=(version, summary)`;
- `recall_turns` with the first search query's vector, when an index is ready;
- after completion, `maybe_enqueue_compaction` and enqueueing `embed_turn`.

`ContextUsage` is filled with `summary_version`, `recent_turns`, `recalled_turns` and `truncated`.

- [ ] **Step 1: Write the failing test.** A 40-turn fixture conversation on the 8k local profile:
  - The fact stated in turn 2 ("the user's project uses Natural Questions") appears in the summary passed to the answer request at turn 40.
  - The request stays within `input_budget`.
  - `context.summary_version >= 1`.
  - The original messages are unchanged.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(chat): answer with running summary and recall (ARA-077)`.

---

## Wave 3, Agent H: ui-b (ARA-075 part 2, ARA-078)

### Task 33: Status events and SSE schema

**Files:** Modify `src/api/sse.ts` and `src/features/chat/use-chat-stream.ts`. Test: the existing `ConversationPane*.test.tsx` plus `sse.test.ts`.

**Behavior:** the zod schema accepts `message.status`, and the `message.completed` schema includes `retrieval`, `context` and `grounding` (passthrough of the generated types). The draft row shows "Searching the paper…" for planning, retrieving and reranking, then "Writing the answer…", in the existing sr-only live region and as muted text above the streaming answer.

- [ ] **Step 1: Write the failing tests.** The status events update the visible text and the live region in order; an unknown stage is ignored.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): show retrieval progress while answering (ARA-078)`.

### Task 34: Chunk-level citations

**Files:** Modify `remark-citations.ts` (dedupe per chunk id, not page), `SourceList.tsx` (one chip per chunk; label `p. N` or `p. N–M`; chips on the same page get the section heading in the hover card), `CitationChip.tsx` (hover shows `section` above the excerpt; table kind shows "Table") and the Playwright selectors (`/^Source, page \d+/`). Test: the existing content tests plus new cases.

- [ ] **Step 1: Write the failing tests.** Two citations on page 6 from different chunks render two chips; the hover shows "Results > Open-domain QA"; `page_end` renders "p. 5–6".
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS, plus `npm run check`.
- [ ] **Step 5: Commit** `feat(ui): cite individual passages with their sections (ARA-075)`.

### Task 35: "How this answer was found" popover

**Files:** Create `src/features/chat/AnswerDetails.tsx`. Modify `Messages.tsx` (meta line). Test: `answer-details.test.tsx`.

**Behavior:** a small "Details" text button on the meta line opens a popover showing:
- "Searched for: {standalone_query or first search query}";
- "Search: Keyword and meaning" (hybrid) or "Keyword only" with the note;
- "Reranked: yes/no";
- "Used {passages_used} of {passages_found} relevant passages", plus "(limited by {model}'s context)" when `limited_by_context`;
- "Context: {input_tokens} of {window} tokens", plus "earlier messages summarized" when `summary_version`.

Hidden for messages without `retrieval`.

- [ ] **Step 1: Write the failing tests.** Hybrid and keyword renderings, limited-context wording, and hidden for old messages.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): explain how an answer was found (ARA-075)`.

### Task 36: Memory footnote

**Files:** Create `src/features/chat/MemoryNote.tsx`. Modify `ConversationThread.tsx` (composer footnote slot) and `src/hooks/queries/retrieval.ts` (`useChatMemory(chatId)`, refetched after each completed message). Test: `memory-note.test.tsx`.

**Behavior:** when `memory` exists, the footnote reads "Earlier messages are summarized to fit {model display name}." with a "View summary" button that opens a popover with the summary text, rendered as Markdown without citation chips. Nothing renders when there is no memory.

- [ ] **Step 1: Write the failing tests.** **Step 2: Run.** Expected: FAIL. **Step 3: Implement.** **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): show when earlier messages are summarized (ARA-078)`.

---

## Wave 4: integration (lead)

### Task 37: Merge, full suites and E2E

- [ ] Merge the agent branches into `feat/rag-context` in order: A, B, C, E, then F, G, H. Resolve conflicts in `chat.py` (F+G) by keeping both call sites per Task 32.
- [ ] Run `python3 scripts/test-stack.py test --project-name ara-rag-test`. All tests must pass and the Task 4 xfail list must be empty (`grep -R "reshaped in ARA-07" src/backend/tests` returns nothing).
- [ ] Run the frontend checks: `docker compose -p ara-rag exec frontend npm run check && npm run build`.
- [ ] Playwright, failing first:
  - **E2E-RAG-1:** upload the structured fixture, ask "What recall did BM25 reach?", and get a chip "p. 3" that highlights the table row.
  - **E2E-RAG-2:** in Details → Search index → Change model → Qwen3 4B (fixture), Building appears, then Ready.
  - **E2E-RAG-3:** in a 6-turn conversation (fixture compaction threshold lowered via `APP_ENV=test` setting `MEMORY_COMPACTION_RATIO=0.01`), the memory footnote appears.
  - Update the existing selectors changed by Task 34.
- [ ] Regenerate OpenAPI and byte-compare `generated.ts`.
- [ ] Commit `test(e2e): cover structured retrieval and memory (ARA-021, ARA-043)`.

### Task 38: Live verification, docs and closure

- [ ] On the `ara-rag` stack (dev data, not test fixtures):
  1. Reindex the existing papers (`python -m app.services.reindex`).
  2. Upload a real paper and record the parse ms/page.
  3. Luna Q&A with citations, checked visually in the PDF.
  4. Switch the paper to Qwen3 4B; record the indexing time.
  5. A local IFM chat within budget; record `context.input_tokens`.
  6. A 20-turn conversation shows the summary.
  7. `docker compose down` then `up`; the data persists.

  Capture screenshots privately in `.superpowers/sdd/ARA-021/`, never committed.
- [ ] Update:
  - `README.md` (services, env vars, memory notes);
  - `docs/api-contract.md`, `docs/implementation-plan.md`, `docs/ai-report.md`;
  - `docs/third-party-notices.md` (PyMuPDF, PyMuPDF4LLM, pymupdf-layout AGPL-3.0; LlamaIndex MIT; pgvector PostgreSQL License; Qwen3 Apache-2.0; tiktoken MIT);
  - the issue verification fields with actual counts.
- [ ] Request a whole-branch review (superpowers:requesting-code-review). Fix the findings with TDD.
- [ ] Update `docs/agent-development-log.md` with the actual red/green counts, corrections and commit SHAs. Merging into `feat/managed-ollama` or `main` is the user's decision.
