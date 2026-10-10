# Retrieval orchestration for N papers and any context window

Status: approved by the user on 2026-10-10. Implemented by ARA-093 (budgets from the catalog), ARA-088 (multi-paper chats) and ARA-094 (relevance-driven evidence, section summaries and a wider retry).

## Principles

- **Retrieval always.** Every answer is built from retrieved passages; the app never sends whole papers. The user chose this to keep the value of the hybrid retrieval stack.
- **One implementation.** No feature flags or parallel "old/new" paths. A change replaces the previous behaviour.
- **Every size derives from the model's window X.** Fixed numbers are defaults for large windows, always capped by a share of the budget.
- **Follow published practice.** Each threshold below cites its source. Change a number only with a new source or observed evidence, and record the reason in the journal.
- **Answers stay grounded.** Every claim cites a passage handle, citations are validated against the chat's documents, and unsupported answers say so.

## Budget (ARA-093)

```
W  = min(X − answer_reserve − reasoning_reserve − safety, price_tier_cap)
F  = instructions + question                 (if no evidence room remains: "question too long")
H  = min(H_target, 25% of W)                 (H_target = 32K; history beyond H is summarised)
E  = W − F − H                               (evidence ceiling)
```

- X, the answer reserve, reasoning headroom and the price-tier boundary come from the model's catalog entry. For GPT-5.6, input beyond 272K tokens is billed at a higher rate, so `price_tier_cap` = 272K.
- `HOSTED_WORKING_CONTEXT_TOKENS` (64K) is retired.
- History is append-only after the instructions. With OpenAI prompt caching, prefixes of 1,024 tokens or more are cached automatically, and GPT-5.6 cached reads are about 90% cheaper, so earlier turns are mostly cache reads.

## Evidence (ARA-094; ARA-088 for several papers)

1. **Plan.** Rewrite the question as a standalone query; classify it as lookup, broad or comparative; emit per-paper sub-questions for comparisons. Pattern: LlamaIndex Sub-Question Query Engine.
2. **Candidates.** Hybrid lexical plus dense search over the chat's papers, filtered by document and fused with RRF. Section summaries (ARA-079) are candidates beside chunks.
3. **Rerank** the pool, as in Anthropic Contextual Retrieval, where a reranker narrows about 150 candidates to 20.
4. **Prune, never pad.** Drop passages far below the top score. Retrieved hard negatives degrade long-context generation (Jin et al., ICLR 2025).
5. **First pass is conservative.** Use at most 24 passages and at most min(16K, E) tokens, close to OpenAI file search's defaults: up to 20 chunks of 800 tokens, a 16K retrieval budget for GPT-4-class models.
6. **Per-paper floor.** In multi-paper chats each paper gets a floor of about 2 passages before relevance shares the rest. If the papers in scope exceed what fits (m = E1 / floor), route to the most relevant papers. On small windows, comparisons go map-reduce: one call per paper, then a synthesis.
7. **Expand** selected chunks to neighbours or their section while the paper's share allows (small-to-big).
8. **Order.** Group passages by paper with a short header; within each paper, order by page; put the strongest passages at the start and end. This is the retrieval-reordering finding of Jin et al., ICLR 2025, which builds on "lost in the middle".
9. **Retry once.** If the model reports the evidence insufficient, retry with a lower prune bar, about twice the cap and section expansion, up to E. This adapts Self-Route (Li et al., EMNLP 2024 Industry), which escalates only when the model judges the evidence insufficient. Here the escalation is wider retrieval, not whole documents.
10. **Observable.** Each answer records passage count, evidence tokens, pruned count, scores and whether it retried. "Details" and the context meter show them.

## Several papers as built (ARA-088)

ARA-088 implements steps 1, 2, 3, 6, 7 and the grouping of step 8 for several papers. Pruning (4), the 24-passage first pass (5), strongest-first-and-last order (8), the retry (9) and section summaries stay with ARA-094; packing keeps today's cap of 16 passages until then.

- **Scope.** A chat holds up to 5 papers (the user's default for ARA-088), each pinned to the PDF that was active when it joined.
- **Search.** One keyword and one vector search span the pinned PDFs, filtered per document, and each returns every paper's own top 30 (the existing `TOP_K`), so one long paper cannot fill the candidate list (per-document metadata filtering, LlamaIndex multi-document pattern). The any-word keyword fallback runs per paper. One query embedding per text serves every paper, since the library uses one embedding model (ARA-091); a paper without a ready index of that model is searched by keywords and the note says so.
- **Sub-questions (step 1).** With several papers the planner runs even on a first question. For a comparison it returns one standalone sub-question per paper it needs (LlamaIndex Sub-Question Query Engine); each is searched only within its paper and fused with the shared searches. The planner's output allowance grows by 80 tokens per paper, twice a one-sentence question in its JSON object. The synthesis is the one answer call over the grouped evidence.
- **Rerank head (step 3).** The reranker scores only its first candidates (40 for OpenAI Decisions), so the papers take turns in that head. Without reranking, fusion order compares passages across papers.
- **Floors and routing (step 6).** Papers are taken in relevance order (their best candidate's rank). Each gets its first 2 candidates that fit, with its header; the first paper whose floor does not fit, and every less relevant paper, is left out, and the note says how many papers answered. The most relevant paper always keeps what fits. Relevance then shares the rest among the answering papers, then same-section neighbours (step 7) while the budget allows.
- **Grouping (step 8).** Passages are grouped by paper in the chat's order under a short header, `Paper N: title (first author et al., year)`, with titles cut at 150 characters and a comparison's sub-question cut at 300; within a paper they follow page order. The system prompt lists the papers with the same bounded fields and asks a comparison to cite each paper's own passages. Paper summaries never enter prompts.
- **Small windows.** Map-reduce per paper is not built: multi-paper chats refuse local models while open models are frozen (ARA-090), and hosted budgets fit five floors.
- **Not measured.** As above, these follow published practice and the design, not measurements on the user's papers.

## Window sizes (all derived)

| | Local 16K | 128K | 1M (GPT-5.6) |
|---|---|---|---|
| W | ~12.5K | ~123K | 272K (tier cap) |
| H | ~3K | 31K | 32K |
| E | ~8K | ~90K | ~238K |
| First pass | ~8K | ≤16K | ≤16K |
| Retry | map-reduce | widen to E | widen to E |

Open models remain frozen behind `EXPERIMENTAL_OPEN_MODELS`. The design must still work for any catalog X, and is tested with synthetic entries at 16K, 128K and 1M.

## Not measured

The user decided against a calibration or check set. These choices follow published practice but are not measured on the user's papers, and tickets and the journal must say so.

## Sources

- Li et al., *Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach*, EMNLP 2024 Industry — https://arxiv.org/abs/2407.16833
- Jin et al., *Long-Context LLMs Meet RAG: Overcoming Challenges for Long Inputs in RAG*, ICLR 2025 — https://arxiv.org/abs/2410.05983
- Liu et al., *Lost in the Middle: How Language Models Use Long Contexts*, TACL 2024 — https://arxiv.org/abs/2307.03172
- Anthropic, *Introducing Contextual Retrieval* (September 2024) — https://www.anthropic.com/news/contextual-retrieval
- OpenAI file search defaults (800-token chunks, 400 overlap, up to 20 results, 16K budget) — https://community.openai.com/t/token-budget-in-file-search-tool/806175
- OpenAI prompt caching — https://developers.openai.com/api/docs/guides/prompt-caching
- LlamaIndex multi-document and sub-question patterns — https://developers.llamaindex.ai/python/examples/query_engine/multi_doc_auto_retrieval/multi_doc_auto_retrieval/
