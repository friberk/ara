"""Evidence packing by real tokens, with short `[S#]` handles in document order (ARA-073).

Several papers (ARA-088) follow docs/plans/retrieval-orchestration.md, step 6: each paper in
scope gets a floor of FLOOR passages before relevance shares the rest, and when not every
floor fits, the most relevant papers answer. Passages are grouped under a short paper header.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import groupby
from uuid import UUID

from llama_index.core.schema import BaseNode, NodeWithScore

from app.integrations.tokens import TokenCounter

SEPARATOR = "\n"
# "About 2 passages" per paper before relevance shares the rest: the design's per-paper floor,
# a per-document quota so one long paper cannot crowd out the others (LlamaIndex's
# multi-document pattern; docs/plans/retrieval-orchestration.md, step 6).
FLOOR = 2


@dataclass(frozen=True)
class Passage:
    handle: str
    chunk_id: UUID
    document_id: UUID
    page: int
    page_end: int
    section: str
    kind: str
    text: str
    ordinal: int = 0
    bboxes: list[list[float]] = field(default_factory=list)

    def render(self) -> str:
        pages = f"{self.page}–{self.page_end}" if self.page_end != self.page else str(self.page)
        return f"[{self.handle}] {self.section or 'Untitled section'} · p. {pages}\n{self.text}\n"


def node_passage(node: BaseNode, handle: str) -> Passage:
    metadata = node.metadata
    return Passage(
        handle=handle,
        chunk_id=UUID(node.node_id),
        document_id=UUID(metadata["document_id"]),
        page=metadata["page"],
        page_end=metadata["page_end"],
        section=metadata["section"],
        kind=metadata["kind"],
        text=node.get_content(),
        ordinal=metadata["ordinal"],
        bboxes=metadata.get("bboxes", []),
    )


def render_header(header: str) -> str:
    return header + "\n"


def render_evidence(passages: Sequence[Passage], headers: Mapping[str, str] | None = None) -> str:
    """Passages in order; with `headers` (document id -> header), each paper's group follows its
    header line."""
    if not headers:
        return SEPARATOR.join(item.render() for item in passages)
    blocks = []
    for document, group in groupby(passages, key=lambda item: str(item.document_id)):
        blocks.append(render_header(headers[document]))
        blocks.extend(item.render() for item in group)
    return SEPARATOR.join(blocks)


def pack_evidence(
    nodes: Sequence[NodeWithScore],
    *,
    budget: int,
    counter: TokenCounter,
    neighbours: Mapping[str, Sequence[BaseNode]] | None = None,
    max_passages: int = 16,
    headers: Mapping[str, str] | None = None,
) -> list[Passage]:
    """Floors first, then the most relevant passages, then same-section neighbours.

    Papers are taken in relevance order (their best candidate's rank). Each gets its first FLOOR
    candidates that fit; the first paper whose floor does not fit, and every less relevant
    paper, is left out. The most relevant paper always keeps whatever of its floor fits. A
    passage that does not fit is skipped whole, never truncated. Passages and headers are costed
    with the widest handle and their separator, so the rendered evidence stays within `budget`.
    With `headers`, groups follow their order (the chat's paper order).
    """
    widest = f"S{max_passages}"
    separator = counter.count(SEPARATOR)
    headers = headers or {}
    chosen: dict[str, Passage] = {}
    remaining = budget

    def size(node: BaseNode) -> int:
        return counter.count(node_passage(node, widest).render()) + separator

    def header_size(document: str) -> int:
        return counter.count(render_header(headers[document])) + separator if headers else 0

    def add(node: BaseNode) -> None:
        nonlocal remaining
        if node.node_id in chosen or len(chosen) >= max_passages:
            return
        cost = size(node)
        if cost <= remaining:
            chosen[node.node_id] = node_passage(node, widest)
            remaining -= cost

    candidates: dict[str, list[BaseNode]] = {}
    for item in nodes:
        candidates.setdefault(item.node.metadata["document_id"], []).append(item.node)
    answering = []
    for document, ranked in candidates.items():
        need, floor = header_size(document), []
        for node in ranked:
            if len(floor) == FLOOR:
                break
            if need + size(node) <= remaining:
                floor.append(node)
                need += size(node)
        if len(floor) < min(FLOOR, len(ranked)) or len(chosen) + len(floor) > max_passages:
            break
        answering.append(document)
        remaining -= header_size(document)
        for node in floor:
            add(node)
    if not answering and candidates:
        best = next(iter(candidates))
        if header_size(best) <= remaining:
            answering.append(best)
            remaining -= header_size(best)
    for item in nodes:
        if item.node.metadata["document_id"] in answering:
            add(item.node)
    for key in list(chosen):
        for neighbour in (neighbours or {}).get(key, ()):
            add(neighbour)
    groups = {document: rank for rank, document in enumerate(headers)}
    ordered = sorted(
        chosen.values(),
        key=lambda item: (groups.get(str(item.document_id), 0), item.page, item.ordinal),
    )
    return [replace(item, handle=f"S{number}") for number, item in enumerate(ordered, start=1)]
