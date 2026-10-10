"""Evidence for one answer: hybrid search, fusion, reranking, expansion and packing (ARA-073).

Retrieval stays inside the chat's papers, each to its immutable pinned document and that
document's current chunk set. A chat may have any number of papers (ARA-088): one keyword and one
vector search span them, filtered per document, a comparison's sub-questions (at most five) are
searched within their own paper, and the papers the question names get one shared search. So the
statements an answer runs, and the candidate pool, do not grow with the number of papers
(docs/plans/retrieval-orchestration.md, steps 1-9). Without a ready index a paper is searched by
keywords and the note says why; a half-built index is never read.
"""

import asyncio
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from sqlalchemy import case, func, or_, select, tuple_

from app.core.errors import AppError
from app.integrations.embedding_catalog import PROFILES, embedding_profile
from app.integrations.embeddings import cl100k, create_embedder
from app.integrations.open_models import KEYWORD_NOTE, offered
from app.integrations.tokens import TokenCounter
from app.models.research import DocumentChunk
from app.models.retrieval import RetrievalIndex
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.packing import (
    SEPARATOR,
    Passage,
    node_passage,
    pack_evidence,
    render_evidence,
    render_header,
)
from app.rag.rerank import rerank_candidates
from app.rag.retrievers import PgLexicalRetriever, PgVectorRetriever, chunk_node
from app.rag.selection import FIRST_PASS, FLOOR, RETRY_PASS, EvidencePass, prune
from app.schemas.ai import RetrievalSummary

TOP_K = 30
# Sub-questions enter evidence headers cut to this length, so headers stay short and bounded.
SUB_QUESTION_CHARS = 300
SUB_QUESTION_LABEL = "\nSub-question: "
BUILDING_NOTE = "Searched by keywords until the search index is built."
UNAVAILABLE_NOTE = "Searched by keywords because the search index is unavailable."
SOME_BUILDING_NOTE = (
    "Searched {count} of {total} papers by keywords until their search index is built."
)
SOME_UNAVAILABLE_NOTE = (
    "Searched {count} of {total} papers by keywords because their search index is unavailable."
)
MODEL_DOWN_NOTE = "Searched by keywords because the search model is unavailable right now."
OPENING_NOTE = "No passage matched the question, so the paper's opening passages were used."
SOME_OPENING_NOTE = (
    "No passage matched in {count} papers the question names, so their opening passages were used."
)
ROUTED_NOTE = "Only the {count} most relevant papers fit in the context for this answer."
# Without an OpenAI key the default reranker cannot run at all; Settings already says why.
QUIET_RERANK_SKIPS = {"MODEL_NOT_CONFIGURED"}


@dataclass(frozen=True)
class Scope:
    """One paper of the chat: the PDF pinned for it and that PDF's current chunk set."""

    document_id: UUID
    chunk_set: str
    # The paper's one-line evidence header; empty when the chat has one paper.
    header: str = ""

    @property
    def key(self) -> tuple[UUID, str]:
        return self.document_id, self.chunk_set


@dataclass
class EvidenceResult:
    passages: list[Passage]
    summary: RetrievalSummary
    trace: dict
    ranked: list[NodeWithScore] = field(default_factory=list)
    neighbours: dict[str, list[TextNode]] = field(default_factory=dict)
    counter: TokenCounter | None = None
    # One vector per query, then per sub-question, in `summary.profile`; None for keywords only.
    vectors: list[list[float]] | None = None
    # Document id -> evidence header, in the chat's paper order; empty for one paper.
    headers: dict[str, str] = field(default_factory=dict)
    documents: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Documents of the papers the question names, which answer first.
    kept: set[str] = field(default_factory=set)
    # The reranker's relevance per candidate id; empty when results were not reranked.
    scores: dict[str, float] = field(default_factory=dict)
    # The limits of the attempt being packed: the first pass, or the one wider retry.
    evidence_pass: EvidencePass = FIRST_PASS
    question_type: str = "lookup"

    @property
    def reach(self) -> int | None:
        """How far chunks grow in their section: a broad question takes the whole section."""
        return None if self.question_type == "broad" else self.evidence_pass.reach

    def pack(self, budget: int) -> list[Passage]:
        """Prune, then pack within the pass's caps and `budget` (the evidence ceiling E)."""
        limits = self.evidence_pass
        pruned = prune(self.ranked, self.scores, ratio=limits.prune_ratio, kept=self.kept)
        if limits.max_tokens is not None:
            budget = min(budget, limits.max_tokens)
        self.passages = pack_evidence(
            pruned.kept,
            budget=budget,
            counter=self.counter,
            neighbours=self.neighbours,
            max_passages=limits.max_passages,
            headers=self.headers,
            kept=self.kept,
            reach=self.reach,
        )
        chosen = {str(item.chunk_id) for item in self.passages}
        self.summary.passages_used = len(self.passages)
        self.summary.pruned = pruned.pruned
        self.summary.evidence_tokens = (
            self.counter.count(render_evidence(self.passages, self.headers)) if self.counter else 0
        )
        self.summary.limited_by_context = any(
            item.node.node_id not in chosen for item in pruned.kept[: limits.max_passages]
        )
        used = Counter(str(item.document_id) for item in self.passages)
        candidates = {item.node.metadata["document_id"] for item in self.ranked}
        answering = sum(1 for document in self.documents if used[document])
        routed = len(candidates) > answering > 0
        notes = [*self.notes, *([ROUTED_NOTE.format(count=answering)] if routed else [])]
        self.summary.note = " ".join(notes) or None
        self.trace["selected"] = {item.handle: str(item.chunk_id) for item in self.passages}
        self.trace["papers"] = dict(used)
        self.trace["papers_in_scope"] = len(self.documents)
        self.trace["routed_out"] = len(candidates) - answering
        self.trace["budget"] = budget
        self.trace["pass"] = limits.name
        self.trace["prune"] = {
            "ratio": limits.prune_ratio,
            "top": pruned.top,
            "bar": pruned.bar,
            "pruned": pruned.pruned,
        }
        self.trace["selected_scores"] = {
            item.handle: self.scores[str(item.chunk_id)]
            for item in self.passages
            if str(item.chunk_id) in self.scores
        }
        return self.passages

    def block(self, budget: int) -> str:
        """The `evidence_block` for answer assembly, which may grant less than retrieval used."""
        return render_evidence(self.pack(budget), self.headers)


def elapsed(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def ranks(items: Sequence[NodeWithScore], limit: int = TOP_K) -> list:
    return [[item.node.node_id, rank, item.score] for rank, item in enumerate(items[:limit], 1)]


async def keyword_note(session, scopes: Sequence[Scope], preferred: str, total: int) -> str:
    states = await session.scalars(
        select(RetrievalIndex.state).where(
            tuple_(RetrievalIndex.document_id, RetrievalIndex.chunk_set).in_(
                [scope.key for scope in scopes]
            ),
            RetrievalIndex.profile == preferred,
        )
    )
    unavailable = any(state in {"failed", "unavailable"} for state in states)
    if len(scopes) == total:
        return UNAVAILABLE_NOTE if unavailable else BUILDING_NOTE
    note = SOME_UNAVAILABLE_NOTE if unavailable else SOME_BUILDING_NOTE
    return note.format(count=len(scopes), total=total)


async def embed_queries(resources, profile: str, queries: list[str]) -> list[list[float]]:
    embedder = create_embedder(resources, embedding_profile(profile))
    try:
        return await embedder.embed_queries(queries)
    finally:
        await embedder.close()


def scoped(scopes: Sequence[Scope]):
    return select(DocumentChunk).where(
        tuple_(DocumentChunk.document_id, DocumentChunk.chunk_set).in_(
            [scope.key for scope in scopes]
        ),
        DocumentChunk.kind != "references",
    )


def header_bound(counter, scopes: Sequence[Scope]) -> int:
    """The most the first pass's evidence headers can cost: one per group, at most one group per
    passage, the longest headers with a sub-question of the longest length."""
    if len(scopes) < 2:
        return 0
    longest = SUB_QUESTION_LABEL + "x" * SUB_QUESTION_CHARS
    # A token is at least one character, so the cut sub-question costs at most its length.
    costs = sorted(
        (
            counter.count(render_header(scope.header)) + counter.count(SEPARATOR) + len(longest)
            for scope in scopes
        ),
        reverse=True,
    )
    return sum(costs[: FIRST_PASS.max_passages])


async def evidence_ceiling(session, scopes: Sequence[Scope], counter) -> int:
    """The most evidence the first pass can choose: the costliest passages, at most its passage
    cap, and the papers' headers, within its token cap. A retry reserves for itself."""
    limit = FIRST_PASS.max_passages
    chunks = await session.scalars(
        scoped(scopes)
        .order_by(DocumentChunk.token_count.desc(), DocumentChunk.ordinal)
        .limit(limit)
    )
    widest = f"S{limit}"
    total = header_bound(counter, scopes) + sum(
        counter.count(node_passage(chunk_node(chunk), widest).render()) + counter.count(SEPARATOR)
        for chunk in chunks
    )
    return min(total, FIRST_PASS.max_tokens)


async def opening_nodes(resources, scopes: Sequence[Scope]) -> list[NodeWithScore]:
    """The first passages of up to the first pass's answering papers in order, in one query:
    each paper's share of its passage cap, at least its floor."""
    limit = FIRST_PASS.max_passages
    scopes = list(scopes)[: FIRST_PASS.answering_papers]
    share = max(FLOOR, -(-limit // len(scopes)))
    position = func.row_number().over(
        partition_by=DocumentChunk.document_id, order_by=DocumentChunk.ordinal
    )
    ranked = scoped(scopes).add_columns(position.label("position")).subquery()
    chunk = select(DocumentChunk).join(ranked, ranked.c.id == DocumentChunk.id)
    order = case(
        {scope.document_id: index for index, scope in enumerate(scopes)},
        value=DocumentChunk.document_id,
    )
    async with resources.sessions() as session:
        chunks = await session.scalars(
            chunk.where(ranked.c.position <= share)
            .order_by(order, DocumentChunk.ordinal)
            .limit(limit)
        )
        return [NodeWithScore(node=chunk_node(chunk), score=0.0) for chunk in chunks]


async def section_nodes(
    resources, scopes: Sequence[Scope], ranked: Sequence[NodeWithScore]
) -> dict[str, list[TextNode]]:
    """Each candidate's section around it, nearest first, for small-to-big expansion (step 8).

    A section is the chunks sharing the candidate's heading; a candidate without a heading gets
    only the passages just before and after it that have none either.
    """
    chunk_sets = {str(scope.document_id): scope.chunk_set for scope in scopes}
    sections = {
        (UUID(item.node.metadata["document_id"]), item.node.metadata["section"])
        for item in ranked
        if item.node.metadata["section"]
    }
    nearby = {
        (UUID(item.node.metadata["document_id"]), item.node.metadata["ordinal"] + step)
        for item in ranked
        if not item.node.metadata["section"]
        for step in (-1, 1)
    }
    key = (DocumentChunk.document_id, DocumentChunk.chunk_set)
    found_by = []
    if sections:
        wanted = [(document, chunk_sets[str(document)], title) for document, title in sections]
        found_by.append(tuple_(*key, DocumentChunk.heading).in_(wanted))
    if nearby:
        wanted = [(document, chunk_sets[str(document)], ordinal) for document, ordinal in nearby]
        found_by.append(tuple_(*key, DocumentChunk.ordinal).in_(wanted))
    if not found_by:
        return {}
    async with resources.sessions() as session:
        rows = await session.scalars(
            select(DocumentChunk).where(or_(*found_by), DocumentChunk.kind != "references")
        )
        grouped: dict[tuple[str, str], list[DocumentChunk]] = {}
        for chunk in rows:
            grouped.setdefault((str(chunk.document_id), chunk.heading), []).append(chunk)
    found = {}
    for item in ranked:
        metadata = item.node.metadata
        document, own, heading = metadata["document_id"], metadata["ordinal"], metadata["section"]
        same = sorted(
            (
                chunk
                for chunk in grouped.get((document, heading), ())
                if chunk.ordinal != own and (heading or abs(chunk.ordinal - own) == 1)
            ),
            key=lambda chunk: (abs(chunk.ordinal - own), chunk.ordinal),
        )
        if same:
            found[item.node.node_id] = [chunk_node(chunk) for chunk in same]
    return found


def interleaved(nodes: Sequence[NodeWithScore]) -> list[NodeWithScore]:
    """Papers take turns, each in its fused order, so the reranker's head (it scores only the
    first candidates) holds every paper's best passages: a per-document quota on the reranked
    pool (docs/plans/retrieval-orchestration.md, steps 3 and 6). One paper keeps its order."""
    queues: dict[str, list[NodeWithScore]] = {}
    for item in nodes:
        queues.setdefault(item.node.metadata["document_id"], []).append(item)
    longest = max((len(queue) for queue in queues.values()), default=0)
    return [
        queue[turn] for turn in range(longest) for queue in queues.values() if turn < len(queue)
    ]


def floor_candidates(ranked: Sequence[NodeWithScore], kept: Collection[str]) -> list:
    """The first FLOOR candidates of the papers that can answer: the named ones, then the most
    relevant, as many as the widest pass (the retry) admits."""
    order = list(dict.fromkeys(item.node.metadata["document_id"] for item in ranked))
    papers = sorted(order, key=lambda document: document not in kept)
    papers = papers[: RETRY_PASS.answering_papers]
    seen: Counter = Counter()
    found = []
    for item in ranked:
        document = item.node.metadata["document_id"]
        if document in papers and seen[document] < FLOOR:
            seen[document] += 1
            found.append(item)
    return found


async def ready_profiles(session, scopes: Sequence[Scope], preferred: str, usable) -> dict:
    """Each document's serving profile among `usable`, in one query: the preferred one when its
    index is ready for the current chunk set, else the latest ready one."""
    position = func.row_number().over(
        partition_by=RetrievalIndex.document_id,
        order_by=((RetrievalIndex.profile == preferred).desc(), RetrievalIndex.updated_at.desc()),
    )
    ranked = (
        select(RetrievalIndex.document_id, RetrievalIndex.profile, position.label("position"))
        .where(
            tuple_(RetrievalIndex.document_id, RetrievalIndex.chunk_set).in_(
                [scope.key for scope in scopes]
            ),
            RetrievalIndex.state == "ready",
            RetrievalIndex.profile.in_(list(usable)),
        )
        .subquery()
    )
    rows = await session.execute(
        select(ranked.c.document_id, ranked.c.profile).where(ranked.c.position == 1)
    )
    return dict(rows.all())


def query_tokens(profile: str, queries: list[str]) -> int:
    """Input tokens a hosted embedder bills for the queries, as the daily ledger counts them."""
    if PROFILES[profile].provider != "openai":
        return 0
    return sum(len(cl100k().encode(query.replace("\n", " "))) for query in queries)


async def retrieve_evidence(
    resources,
    *,
    scopes: Sequence[Scope],
    preferred_profile: str,
    queries: list[str],
    question: str,
    budget: int,
    counter: TokenCounter,
    reranker: str | None = None,
    sub_questions: Sequence[tuple[int, str]] = (),
    kept: Collection[int] = (),
    on_stage: Callable[[str], Awaitable[None]] | None = None,
    question_type: str = "lookup",
) -> EvidenceResult:
    """`queries` are searched in every paper; each (scope index, text) of `sub_questions` only in
    its paper; the `kept` scope indexes (papers the question names) share one more search with
    the standalone `question` and answer first. The reranker judges passages against `question`.

    `reranker` is a catalog profile key, or None for off; `on_stage` hears "reranking".
    """
    started = time.monotonic()
    timings = {}
    asked = [(index, text) for index, text in sub_questions if 0 <= index < len(scopes)]
    summary = RetrievalSummary(
        mode="keyword",
        search_queries=list(queries),
        sub_questions=[text for _, text in asked],
        question_type=question_type,
    )
    notes: list[str] = []
    usable = offered(resources.settings, PROFILES)
    profile, searched = None, []
    async with resources.sessions() as session:
        # An open model while open models are off: keywords, never a paid profile (ARA-090).
        if preferred_profile not in usable:
            notes.append(KEYWORD_NOTE)
        else:
            profiles = await ready_profiles(session, scopes, preferred_profile, usable)
            ready = [
                profiles[scope.document_id] for scope in scopes if scope.document_id in profiles
            ]
            # One embedding model spans the papers (ARA-091): the library's, else the one the
            # first ready paper still serves.
            profile = preferred_profile if preferred_profile in ready else next(iter(ready), None)
            searched = [
                scope
                for scope in scopes
                if profile is not None and profiles.get(scope.document_id) == profile
            ]
            if missing := [scope for scope in scopes if scope not in searched]:
                notes.append(await keyword_note(session, missing, preferred_profile, len(scopes)))
    keep = [scopes[index] for index in sorted(set(kept)) if 0 <= index < len(scopes)]
    # A named paper with a sub-question already has its own search.
    named = [scope for scope in keep if scope not in {scopes[index] for index, _ in asked}]
    texts = [*queries, *(text for _, text in asked), *([question] if named else [])]
    vectors, billed = None, {}
    if searched:
        clock = time.monotonic()
        try:
            vectors = await embed_queries(resources, profile, texts)
        except AppError:
            notes = [MODEL_DOWN_NOTE]
            searched = []
        else:
            summary.mode, summary.profile = "hybrid", profile
            if tokens := query_tokens(profile, texts):
                billed["embedding"] = {"profile": profile, "tokens": tokens}
            if profile != preferred_profile:
                notes.append(
                    f"Searched with {PROFILES[profile].display_name} until "
                    f"{PROFILES[preferred_profile].display_name} is ready."
                )
        timings["embed"] = elapsed(clock)
    clock = time.monotonic()
    searches = []

    def search(kind: str, text: str, paper: int | None, within: Sequence[Scope], vector=None):
        keys = [scope.key for scope in within]
        if kind == "keyword":
            found = PgLexicalRetriever(resources.sessions, keys, top_k=TOP_K).aretrieve(text)
        else:
            retriever = PgVectorRetriever(resources.sessions, keys, profile, top_k=TOP_K)
            found = retriever.aretrieve(QueryBundle(query_str=text, embedding=vector))
        searches.append((kind, text, paper, found))

    for position, query in enumerate(queries):
        search("keyword", query, None, scopes)
        if searched:
            search("vector", query, None, searched, vectors[position])
    for offset, (index, text) in enumerate(asked):
        scope = scopes[index]
        search("keyword", text, index + 1, [scope])
        if scope in searched:
            search("vector", text, index + 1, [scope], vectors[len(queries) + offset])
    if named:
        # One shared search over the named papers, so each has candidates for its floor.
        search("keyword", question, None, named)
        if within := [scope for scope in named if scope in searched]:
            search("vector", question, None, within, vectors[-1])
    # Each retriever call opens its own session, so the searches run in parallel.
    results = await asyncio.gather(*(found for *_, found in searches))
    timings["search"] = elapsed(clock)
    fused = reciprocal_rank_fusion(results)
    if reranker is not None and fused and on_stage is not None:
        await on_stage("reranking")
    reranked = await rerank_candidates(
        resources, query=question, nodes=interleaved(fused), reranker=reranker
    )
    timings["rerank"] = reranked.elapsed_ms
    summary.reranked = reranked.reranked
    if reranked.skipped and reranked.skipped not in QUIET_RERANK_SKIPS:
        notes.append(f"Reranking was unavailable, so results use the {summary.mode} order.")
    if reranked.billed_tokens and reranked.reranker:
        billed["rerank"] = {"profile": reranked.reranker, "tokens": reranked.billed_tokens}
    # Without reranking, fusion order compares passages across papers.
    ranked = list(reranked.nodes if reranked.reranked else fused)
    matched = {item.node.metadata["document_id"] for item in ranked}
    # Opening passages stand in when nothing matched, or for named papers nothing matched.
    silent = [scope for scope in keep if str(scope.document_id) not in matched]
    if not ranked:
        silent = [*keep, *(scope for scope in scopes if scope not in keep)]
    if silent:
        ranked += await opening_nodes(resources, silent)
        notes.append(OPENING_NOTE if not matched else SOME_OPENING_NOTE.format(count=len(silent)))
    summary.passages_found = len(fused)
    kept_documents = {str(scope.document_id) for scope in keep}
    floors = floor_candidates(ranked, kept_documents)
    expand = {item.node.node_id: item for item in [*ranked[: RETRY_PASS.max_passages], *floors]}
    neighbours = await section_nodes(resources, scopes, list(expand.values()))
    width = TOP_K
    trace = {
        "queries": list(queries),
        "sub_questions": [{"paper": index + 1, "question": text} for index, text in asked],
        "kept": [scopes.index(scope) + 1 for scope in keep],
        "mode": summary.mode,
        "profile": summary.profile,
        "lists": [
            {
                "retriever": kind,
                "query": text,
                **({"paper": paper} if paper else {}),
                "results": ranks(found, width),
            }
            for (kind, text, paper, _), found in zip(searches, results, strict=True)
        ],
        "fused": [[item.node.node_id, item.score] for item in fused[:width]],
        "rerank": {
            "profile": reranker,
            "query": question,
            "skipped": reranked.skipped,
            "scores": reranked.scores,
            "elapsed_ms": reranked.elapsed_ms,
        },
        "timings_ms": timings,
        "billed": billed,
    }
    headers = {}
    if len(scopes) > 1:
        questions = {index: text for index, text in asked}
        for index, scope in enumerate(scopes):
            header = scope.header
            if text := questions.get(index):
                cut = text if len(text) <= SUB_QUESTION_CHARS else text[: SUB_QUESTION_CHARS - 1]
                header += SUB_QUESTION_LABEL + cut + ("" if cut == text else "…")
            headers[str(scope.document_id)] = header
    result = EvidenceResult(
        [],
        summary,
        trace,
        ranked,
        neighbours,
        counter,
        vectors,
        headers=headers,
        documents=[str(scope.document_id) for scope in scopes],
        notes=notes,
        kept=kept_documents,
        scores=dict(reranked.scores) if reranked.reranked else {},
        question_type=question_type,
    )
    result.pack(budget)
    timings["total"] = elapsed(started)
    return result
