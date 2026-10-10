"""Evidence packing by real tokens, with short `[S#]` handles in document order (ARA-073).

Several papers (ARA-088) follow docs/plans/retrieval-orchestration.md, steps 6 and 7: papers
the question names come first, then each paper in relevance order gets a floor of FLOOR
passages while floors fit, and relevance shares the rest; the others add nothing to this turn.
Passages are grouped under a short paper header.
"""

from collections.abc import Collection, Mapping, Sequence
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
    kept: Collection[str] = (),
) -> list[Passage]:
    """Floors first, then the most relevant passages, then same-section neighbours.

    Papers are taken with the `kept` ones (named by the question) first, then in relevance order
    (their best candidate's rank). Each gets its first FLOOR candidates that fit; a named paper
    with fewer candidates takes what it has. The first other paper whose floor does not fit, and
    every paper after it, is left out. The first paper always keeps whatever of its floor fits.
    A passage that does not fit is skipped whole, never truncated. Passages and headers are
    costed with the widest handle and their separator, so the rendered evidence stays within
    `budget`. With `headers`, groups follow their order (the chat's order).
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
    order = sorted(candidates, key=lambda document: document not in kept)
    answering = []
    for document in order:
        ranked = candidates[document]
        need, floor = header_size(document), []
        for node in ranked:
            if len(floor) == FLOOR:
                break
            if need + size(node) <= remaining:
                floor.append(node)
                need += size(node)
        # A named paper answers with what it has; any other paper needs its whole floor, and one
        # with fewer candidates than that is skipped.
        if document not in kept and len(ranked) < FLOOR:
            continue
        needed = min(FLOOR, len(ranked)) if document in kept else FLOOR
        if len(floor) < needed or len(chosen) + len(floor) > max_passages:
            if document in kept:
                continue
            break
        answering.append(document)
        remaining -= header_size(document)
        for node in floor:
            add(node)
    if not answering and candidates:
        best = order[0]
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
