# Retrieval and conversation context overhaul — design

Status: Gate G0 measurements recorded (2026-10-09); implementation in progress. Issues: ARA-021 (epic: ARA-070 to ARA-075) and ARA-043 (epic: ARA-076 to ARA-079). Branch `feat/rag-context`, based on `feat/managed-ollama` at `6b53fd1`.

## 1. Problem

Paper Q&A works but is naive:

- **Parsing:** PyMuPDF extracts flat text from each page (`app/jobs/pdf_parser.py`).
- **Chunking:** `app/services/ingestion.py` cuts fixed 3,200-character windows inside each page. The windows ignore sections, tables and captions, and never cross a page boundary.
- **Retrieval:** Postgres `ts_rank` full-text search returns the top chunks. Five evenly spaced "coverage" chunks are added to every question, relevant or not.
- **Prompt:** one flattened string with `[source:UUID]` markers. History is whatever fits in 4,000 *bytes*.
- **Token counting:** it counts UTF-8 bytes, roughly 3–4× too many. Hosted prompts are capped at 32k bytes. Local models run at 8,192 context, which leaves about 1.5k real tokens of evidence.
- **Missing:** there are no embeddings, reranking or memory. Old answers that still carry `[source:…]` markers can trigger `UNGROUNDED_OUTPUT`.

## 2. Goals and non-goals

Goals:
- structure-aware parsing and chunking from off-the-shelf components;
- hybrid keyword and vector retrieval scoped to one paper;
- selectable embedding models;
- optional local reranking;
- verifiable citations with section and page provenance;
- token-accurate, model-aware conversation memory that keeps 8k local models useful;
- power-user controls that stay out of the way.

Non-goals:
- backward compatibility for existing chunks (all documents are re-ingested);
- dataset-based retrieval evaluation (removed by the user);
- multi-paper or library-wide Q&A;
- extra infrastructure services.

## 3. Constraints decided by the user

- **Infrastructure:** exactly one PostgreSQL instance and one Ollama instance. No vector database, parser service or second model runtime.
- **Components:** prefer off-the-shelf components and documented integrations. LlamaIndex is the framework family.
- **Parser:** PyMuPDF4LLM with its layout model on. Docling was rejected as too slow on CPU.
- **Default embeddings:** OpenAI `text-embedding-3-large`. Qwen3 Embedding 4B and 8B (`qwen3-embedding:4b-q4_K_M`, `qwen3-embedding:8b-q4_K_M`) are served by the existing Ollama. Power users choose per paper.
- **Reranker:** through Ollama if feasible; otherwise deferred under its own ticket (ARA-074).
- **Retrieval:** always used for Q&A. No full-paper context mode.
- **Privacy:** a local chat on a paper indexed with OpenAI embeddings may send its search queries to OpenAI for embedding. No extra disclosure is needed.
- **Process:** TDD first for every production change. Commits carry no Co-Authored-By trailer.

## 4. Architecture

### 4.1 Parsing and chunking (ARA-071)

- **Packages:** `pymupdf4llm==1.28.2`, `pymupdf==1.28.2` and `pymupdf_layout==1.28.2`, pinned together. All three are AGPL-3.0 or Artifex commercial; this was checked against the wheel's COPYING file on 2026-10-09.
- **Process:** the existing isolated child process, with its scrubbed environment, runs `pymupdf4llm.to_markdown(path, page_chunks=True, header=False, footer=False)` in layout mode. Each page returns Markdown (headings, tables, reading order, no page furniture) plus `page_boxes`: layout regions with class, bbox and exact character offsets. Empty display-formula regions are filled with PyMuPDF's clipped text. Phase 0 rejected the documented `LlamaMarkdownReader`, because it uses the legacy heading heuristic and found only the title.
- **Chunking:** in the worker, LlamaIndex `MarkdownNodeParser` builds sections with `header_path` metadata. `SentenceSplitter` then caps chunks at about 512 tiktoken tokens with about 64 tokens of overlap.
- **One whole-paper Document:** the page Markdown is concatenated into a single LlamaIndex `Document` (no metadata), so the heading stack survives page breaks. Our only glue maps each chunk's character range back to pages and layout boxes.
- **Each chunk stores:**
  - `text`, the Markdown shown to users;
  - `context_text`, the title plus heading path plus text, used for embeddings and keyword search;
  - `page` (first page) and `page_end`;
  - `kind`, one of `front_matter`, `text`, `table` or `references`;
  - `token_count`.

  Chunks under a references or bibliography heading are excluded from default retrieval.
- **Child tuning and fallback:** the child sets `OPENBLAS_NUM_THREADS=1` and `MALLOC_ARENA_MAX=2`, and gives ONNX Runtime 2 intra-op threads. With this, a 200-page PDF fits RLIMIT_AS 1.5 GiB in about 45 s; untuned, the import hangs under 1–2 GiB. If layout parsing fails, a fresh child blocks the `pymupdf.layout` import and uses the legacy path. The existing pre-checks and error codes (password, page and text limits, no text) remain.
- **Upgrade path:** PyMuPDF4LLM's `to_chunks(...).to_llama_nodes()` exists on GitHub main for PyMuPDF 2.0 but is not on PyPI. It provides layout-aware chunking with section paths, page ranges, bounding boxes, kept-together captions and diagnostics. Chunk columns mirror its metadata (`section_path`, `page_start`/`page_end`, `bboxes`, `types`), so adopting it later replaces only the chunking step. Highlight boxes stay empty until then; the evidence jump uses the page plus the existing sentence text-matching.

### 4.2 Storage and search on the single Postgres (ARA-070)

- **Image:** the `postgres` service changes to the official `pgvector/pgvector` Postgres 17 bookworm image, pinned by digest. It shares the official Postgres base, so the existing volume carries over. Phase 0 verifies this on a copy.
- **Vectors:** embeddings are stored as `halfvec`. Search is an exact scan inside one document's chunks (`ORDER BY embedding <=> $q`), filtered by a btree on `document_id`. Retrieval is paper-scoped, so no ANN index is needed and recall is exact.
- **Keyword search:** native full-text search over a generated weighted tsvector (heading path weight A, text weight B) with a GIN index, queried with `websearch_to_tsquery` and ranked with `ts_rank_cd`.

### 4.3 Embedding profiles and indexes (ARA-072)

- **Profile registry:** `app/integrations/embedding_catalog.py` maps each key to a provider, model id, dimensions, maximum input, query and document instructions, and price.
  - `openai-3-large` is the default.
  - `qwen3-embed-4b` and `qwen3-embed-8b` take the query prefix `Instruct: Given a question about a scientific paper, retrieve passages of the paper that answer it\nQuery: `.
- **Selection:** the effective profile is the paper's override (`papers.retrieval_profile`) or the global default (Settings).
- **`embed` job:**
  - runs on a new `retrieval` queue, in batches (64 for OpenAI, 16 for Ollama);
  - upserts each batch inside a lease-fenced transaction keyed by (chunk, profile), so duplicate deliveries and resumes are safe;
  - charges OpenAI cost through `reserve()`;
  - allows bounded retries, because embedding is idempotent and cheap. This exception to the generation no-retry rule is documented.
- **`retrieval_indexes`:** a blue/green state machine (`queued → embedding → ready | failed | unavailable`) per (document, profile, chunk set), with progress. The previous ready index serves until the new one is ready.
- **Unavailable profiles:** a missing key or an uninstalled local model degrades to keyword-only retrieval with a visible reason.
- **Local models:** they join `model_catalog.py` with `kind` set to `embedding` or `reranker`. Verification depends on kind: embedding models need the `embedding` capability plus an `/api/embed` dimension probe; the reranker needs a log-probability ordering probe. Digests are pinned.

### 4.4 Single Ollama runtime

The existing `ollama` service and `ollama-models` volume serve chat, embedding and reranker models.
- `OLLAMA_MAX_LOADED_MODELS` becomes configurable, with its default taken from Phase 0. Embed and rerank requests set their own `keep_alive`.
- Retrieval inference gets its own short-lease slot in `model_uses`. It runs alongside the single generation slot and obeys the same fences: no use while a model operation is settling or a download or delete is processing (`acquire_use`).

### 4.5 Retrieval pipeline (ARA-073, ARA-074) — `app/rag/`

1. **Planner** (follow-up turns only; see 4.6): produces a standalone question plus 1–3 search queries.
2. **Retrieve:** `PgLexicalRetriever` and `PgVectorRetriever` are LlamaIndex `BaseRetriever` subclasses over our AsyncSession, always filtered by the chat's immutable `document_id`. Their results are fused with reciprocal rank fusion (k = 60).
3. **Rerank** (ARA-074, if the Phase 0 gate passes): `OllamaQwenRerank`, a LlamaIndex `BaseNodePostprocessor`, scores the top ~30 using Qwen3-Reranker's template and the next-token P(yes) against P(no).
4. **Expand:** neighbour and section expansion while budget remains.
5. **Pack:** passages are added in document order up to the evidence budget, labelled `[S1]…[Sn]` with section path and page.

`prepare()` is split in two:
- **Inside the transaction:** replay and UUID checks, inserting the user message and the leased assistant message, and the budget reservation.
- **Outside the transaction:** planning, retrieval and reranking, so no row lock is held across network calls.

Supporting behaviour:
- **Status events:** a new SSE event, `message.status`, reports planning, retrieving, reranking and generating.
- **Trace:** a retrieval trace (queries, per-retriever ranks, RRF and rerank scores, selected passages, budget, timings) is persisted on the assistant message.
- **Citation mapping:** a stream transducer maps `[S#]` to canonical `[source:<chunk-uuid>]` while streaming, so the frontend marker contract is unchanged. The ARA-052 bracket variants are normalized. Unknown or foreign handles fail with `UNGROUNDED_OUTPUT`.
- **Insufficient evidence:** an `[insufficient-evidence]` sentinel sets a typed `grounding` flag, replacing the `"insufficient" in content` heuristic.
- **Summaries:** they move to section-aware batches with handles and token budgets, keeping their checkpoint and paid-call semantics.

### 4.6 Context and memory (ARA-076, ARA-077)

- **Registry:** each model gets `context_window`, `max_output`, a thinking allowance, a tokenizer and a working cap.
  - Hosted models: tiktoken counting (encoding confirmed in Phase 0), capped by `HOSTED_WORKING_CONTEXT_TOKENS` (default 64k).
  - Local models: a per-model `num_ctx` validated against `/api/show` and measured memory, counted with a chars-per-token ratio calibrated from Ollama's `prompt_eval_count`, plus a 10% margin.
- **Allocator order:** instructions, then question, then the evidence floor, then summary, recent turns and recall. Unused shares roll into evidence.
- **Message list:** a real role-separated list, sent through `HostedLLM` (a Responses `input` list) and `OllamaLLM` (`messages`). Prior assistant turns are resent with citations rendered as "(p. N)". Only the current turn carries evidence. The stable prefix benefits prompt caching.
- **Compaction:** `chat_memories` holds versioned, anchored running summaries. A `compact_chat` job runs after a completed turn once the unsummarized tokens pass a threshold.
  - It is idempotent per (session, `through_message_id`).
  - Local chats compact with their local model and hosted chats with Luna; local conversations are never sent to a hosted model.
  - If the summary is late, the request trims and sets `context.truncated`.
- **Recall:** completed turns are embedded into `chat_turn_embeddings` and retrieved within the recall share.
- **Planner:** a structured-output call returning `{standalone_question, search_queries[1-3], needs_paper_evidence}`.
  - Hosted chats use Luna with effort `none`; local chats use the same local model with thinking off.
  - It falls back to the deterministic heuristic on failure.
  - It is persisted under the request UUID, so replays never re-run it.

### 4.7 What each question sends to models

1. **Planner** (follow-ups only): short instructions, the summary, the last ~2 turns as plain text, and the question.
2. **Query embedding:** the search queries only. Qwen receives them with its instruction prefix; OpenAI receives the bare text.
3. **Reranker** (local): about 30 single-passage prompts.
4. **Answer:** system instructions with the paper header, then the summary (when present), the recent turns verbatim, and finally the evidence passages with handles and the question.
5. **Background:** compaction (previous summary plus the evicted turns), paper summaries (all chunks, map-reduce), upload metadata (first two pages) and indexing (each chunk's `context_text`).

The PDF file, other papers and the full paper on normal questions are never sent.

**Budget examples** (real tokens):

| Part | Local 8k model | Hosted model |
|---|---|---|
| Output | 2,048 | 4,000 |
| Safety margin | 512 | 512 |
| Instructions and paper header | ~400 | ~400 |
| Summary | ≤ 500 | ≤ 2,000 |
| Recent turns | ≤ 1,200 | ≤ 12,000 |
| Evidence | ~3,400 (about 5–6 passages) | up to ~16 passages, cut by relevance |

### 4.8 Interface (ARA-075, ARA-078)

- **Settings:** a Retrieval section with the default embedding model (radio list with install status) and a reranker toggle. Local retrieval models appear under Local models with a kind badge.
- **Paper Details tab:** a collapsible "Search index" (Advanced) section with profile, state, passage count and progress, a "Change model" dialog and "Rebuild index". Nothing is added to the composer or thread chrome.
- **Answers:** a "How this answer was found" popover on the metadata line, chunk-level citation chips showing section headings, and status text ("Searching the paper…").
- **Composer:** a footnote, "Earlier messages are summarized to fit {model}", with a popover showing the summary.

## 5. Data model (Alembic 0006+, lead-owned)

- **New tables:**
  - `document_sections`
  - `document_chunks`, recreated with `chunk_set`, `section_id`, `section_path`, `heading`, `kind`, `text`, `context_text`, `page`/`page_end`, `bboxes`, `token_count`, a weighted tsvector with GIN, and a btree on `document_id`
  - `chunk_embeddings` (PK chunk and profile, `halfvec`)
  - `retrieval_indexes`
  - `chat_memories`
  - `chat_turn_embeddings`
- **New columns:** `papers.retrieval_profile`; `documents.parser` and `documents.chunk_set`; `chat_messages.retrieval` and `chat_messages.context` (JSONB) and `chat_messages.grounding`.
- **Extension:** `CREATE EXTENSION vector`.
- **API:**
  - `GET /retrieval/profiles`
  - `GET`/`PUT /retrieval/settings` (`embedding_profile`, `reranker_enabled`), kept separate from the model defaults in `/settings`
  - `GET`/`PUT /papers/{id}/retrieval` (request-UUID idempotent) and `POST /papers/{id}/retrieval/rebuild`
  - `GET /chats/{id}/memory`
  - `Message.retrieval`, `Message.context` and `Message.grounding`; `Model.kind`
  - `Citation` gains `section`, `page_end`, `bboxes` and `kind`
  - SSE `message.status`

## 6. Phase 0 measurements (Gate G0)

### S2: parsing and pgvector (2026-10-09)

Setup: a throwaway backend-image container limited to 2 GB and 2 CPUs, on OrbStack arm64. Test papers: Attention, RAG, BERT, the RAG survey and DPR (13–21 pages), plus a 200-page synthetic document.

- **Parser output:**
  - Layout `to_markdown` recovered 22/22 headings on Attention and 29/29 on RAG, and 33/49 on the survey, where IEEE run-in labels were missed.
  - Real table grids: 4–9 tables per paper, against 0–3 in legacy mode.
  - `page_boxes` offsets tile each page's Markdown exactly, on 84 of 84 pages.
  - Display formulas were dropped (hence the formula-box filling).
  - `LlamaMarkdownReader` found only the title.
- **Speed and memory, with tuned threads:**
  - 167–300 ms per page, 5.5–9.2 CPU-s per paper, 0.37–0.49 GiB peak RSS.
  - 200 pages in 42–46 s wall time, 0.84–0.88 GiB peak RSS.
  - Untuned: virtual memory peaked at 3.6–3.8 GiB, and the import hung under 1–2 GiB limits.
  - Chosen limits: RLIMIT_AS 1.5 GiB, RLIMIT_CPU 150 s, a 120 s wall deadline, one parse at a time in the 2 GB worker.
- **Chunking** (one Document per page with `MarkdownNodeParser` and a 512/64 `SentenceSplitter`):
  - 45–94 chunks per paper, median 209–380 tokens.
  - The heading stack reset at every page; carrying it across pages raised the number of chunks with a two-level path from 2–12 to 43–93. Hence the design uses one whole-paper Document.
  - PDF metadata would cost about 110 tokens per chunk, so Documents carry no metadata.
- **pgvector:**
  - Image `pgvector/pgvector:0.8.7-pg17-bookworm@sha256:ac08538c…` (PostgreSQL 17.11, pgvector 0.8.7, same glibc and ICU as before). It starts on an existing 17.9 volume with identical data and no collation warnings. Once `vector` is used, the old 17.9 image can no longer read those objects.
  - Exact per-document search: about 1 ms for 150 chunks and 4–8 ms for 2,000 chunks at 2560–4096 dimensions. About 8 KB per 4096-dimension vector, stored in TOAST.
  - HNSW is impossible above 4,000 dimensions and is not used by per-document queries.
  - Weighted full-text search: 0.3–0.4 ms. 196 of 300 queries had zero AND-matches, so an OR fallback is required.

### S1: models and Ollama (2026-10-09)

Setup: `ara-ollama:0.40.1-ara.2` with 4 CPUs and a 12 GiB cap, on OrbStack arm64.

- **Embedders:**
  - Qwen3 Embedding 4B indexes at 51 tok/s and 8B at 29 tok/s; a 60k-token paper takes about 20 minutes on the 4B. Warm queries take 0.22 s and 0.40 s.
  - Both ranked all 12 probe pairs correctly.
  - `num_thread` must always be sent: without it a batch took 515 s instead of 153 s.
  - Pinned digests: 4B `df5bd2e3…`, 8B `64b93349…`.
- **OpenAI `text-embedding-3-large`:** 64 passages in 2.1 s, 3072 dimensions. `usage` equals the cl100k token count.
- **Reranker through Ollama:**
  - It works: this build returns log-probabilities in raw `/api/generate` mode.
  - `dengcao/Qwen3-Reranker-0.6B:Q8_0` is broken (uniform logits, also on stock Ollama).
  - The 0.6B F16 tag ranked 12/12 correctly, but 30 candidates took 54 s. The 4B took 180 s, and parallel requests gave no gain.
  - ARA-074 is deferred, and `reranker_enabled` defaults to false.
- **Co-residency (one container):**
  - With `MAX_LOADED_MODELS=3`, the chat model, the 4B embedder and the 0.6B reranker stay resident: 8.3 GiB with the 3.7B chat model, 10.6 GiB with the 7B.
  - 7B plus the 8B embedder does not fit: it swapped 7.7 GiB, or was OOM-killed with swap off.
  - `MAX_LOADED_MODELS=1` reloads the chat model after every retrieval call (+5–18 s).
  - Weights are not memory-mapped on CPU.
  - The llama-server prompt cache grows about 265 MiB per new prompt; `LLAMA_ARG_CACHE_RAM=0` disables it.
  - Compose now sets `MAX_LOADED_MODELS=3`, `LLAMA_ARG_CACHE_RAM=0` and `memswap_limit = mem_limit`.
- **Local context:**
  - An 11.5k-token prompt took 432–543 s to process at 16k or 32k context (21–27 tok/s), and generation ran at about 4 tok/s. Larger local windows are therefore not interactive, and `OLLAMA_CONTEXT_WINDOW` stays 8192.
  - Flash attention is already enabled. A q8_0 KV cache halves KV memory but more than doubles prefill time.
  - The local input budget is capped at 3,072 tokens.
- **Token calibration** (2,000 words): o200k 2,650; OpenAI 2,650 + 6 framing tokens; cl100k 2,685; IFM 2,582; Qwen3 2,698. o200k with a 1.05 factor is used for local models.

## 7. Testing

TDD first: every production change starts with an observed failing Given/When/Then test, recorded in the journal. The backend runs `scripts/test-stack.py` on real Postgres, Redis and MinIO with OpenAI and Ollama fixtures. The frontend runs `npm run check`, `npm run build`, Vitest/RTL and Playwright. Key cases are listed per issue in `issue_tracker/ARA-070.json` to `ARA-079.json`. Live verification uses an `ara-rag` stack: upload, Luna Q&A with citations, a Qwen 4B re-index, a local IFM chat within budget, a 20-turn conversation with a summary, and a restart showing persistence.

## 8. Risks

- **Memory:** single-Ollama co-residency at 12g. Qwen 8B may need to swap with the chat model; the default OpenAI path avoids this.
- **Layout model on CPU:** measured at 0.17–0.30 s per page with tuned threads, inside the "no seconds per page" requirement. The fallback is the legacy path with the layout import blocked.
- **Layout parser limits:** some heading false positives (bullets, author lines), flat IEEE heading levels, occasional two-column order errors, and display formulas recovered only as plain text.
- **Community reranker GGUF:** pinned by digest and gated by the probe.
- **Concurrent work:** `feat/managed-ollama` (catalog) and ARA-019 (`feat/fulltext-access`, ingestion) are active in parallel. Issue IDs ARA-070 to ARA-079 are reserved for this work to avoid collisions.
