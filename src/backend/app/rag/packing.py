"""Evidence packing by real tokens, with short `[S#]` handles in document order (ARA-073).

Several papers (ARA-088) follow docs/plans/retrieval-orchestration.md, steps 6 and 7: papers
the question names come first, then each paper in relevance order gets a floor of FLOOR
passages while floors fit, and relevance shares the rest; the others add nothing to this turn.
Passages are grouped under a short paper header, the strongest groups at both ends (step 9).
"""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import groupby
from uuid import UUID

from llama_index.core.schema import BaseNode, NodeWithScore

from app.integrations.tokens import TokenCounter
from app.rag.selection import FIRST_PASS_PASSAGES, FLOOR

SEPARATOR = "\n"


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


def ends_first(ranked: Sequence[str]) -> list[str]:
    """Strongest first, second strongest last, the weakest in the middle: models use the start
    and end of a long context best (Liu et al., "Lost in the Middle", TACL 2024), and reordering
    retrieved passages this way helps long-context RAG (Jin et al., ICLR 2025). LlamaIndex's
    LongContextReorder places nodes the same way."""
    return [*ranked[::2], *reversed(ranked[1::2])]


def pack_evidence(
    nodes: Sequence[NodeWithScore],
    *,
    budget: int,
    counter: TokenCounter,
    neighbours: Mapping[str, Sequence[BaseNode]] | None = None,
    max_passages: int = FIRST_PASS_PASSAGES,
    headers: Mapping[str, str] | None = None,
    kept: Collection[str] = (),
    reach: int | None = 1,
) -> list[Passage]:
    """Floors first, then the most relevant passages, then each chunk's section around it.

    Papers are taken with the `kept` ones (named by the question) first, then in relevance order
    (their best candidate's rank). Each gets its first FLOOR candidates that fit; a named paper
    with fewer candidates takes what it has. The first other paper whose floor does not fit, and
    every paper after it, is left out. The first paper always keeps whatever of its floor fits.
    A passage that does not fit is skipped whole, never truncated. Passages and headers are
    costed with the widest handle and their separator, so the rendered evidence stays within
    `budget`. With `headers`, each paper's passages form one group in page order, and the groups
    are ordered by their best candidate's rank with the strongest at both ends.

    `neighbours` maps a candidate to chunks of its section; they are added `reach` ordinals away
    at most (1: the neighbours; None: the whole section), nearest first.
    """
    widest = f"S{max_passages}"
    separator = counter.count(SEPARATOR)
    headers = headers or {}
    chosen: dict[str, Passage] = {}
    spent: Counter = Counter()
    remaining = budget

    def size(node: BaseNode) -> int:
        return counter.count(node_passage(node, widest).render()) + separator

    def header_size(document: str) -> int:
        return counter.count(render_header(headers[document])) + separator if headers else 0

    def add(node: BaseNode, share: int | None = None) -> None:
        nonlocal remaining
        if node.node_id in chosen or len(chosen) >= max_passages:
            return
        cost, document = size(node), node.metadata["document_id"]
        if cost <= remaining and (share is None or spent[document] + cost <= share):
            chosen[node.node_id] = node_passage(node, widest)
            remaining -= cost
            spent[document] += cost

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
        spent[document] += header_size(document)
        for node in floor:
            add(node)
    if not answering and candidates:
        best = order[0]
        if header_size(best) <= remaining:
            answering.append(best)
            remaining -= header_size(best)
            spent[best] += header_size(best)
    for item in nodes:
        if item.node.metadata["document_id"] in answering:
            add(item.node)
    # Small-to-big (step 8): every selected chunk grows by one step on each side before any grows
    # by two, and each paper only within an equal share of the budget, so one long section
    # cannot take the room of the others.
    share = budget // max(1, len(answering))
    selected = [(key, chosen[key].ordinal) for key in chosen]
    around = {key: (neighbours or {}).get(key, ()) for key, _ in selected}
    furthest = max(
        (abs(node.metadata["ordinal"] - own) for key, own in selected for node in around[key]),
        default=0,
    )
    for distance in range(1, min(furthest, reach or furthest) + 1):
        for key, own in selected:
            for node in around[key]:
                if abs(node.metadata["ordinal"] - own) == distance:
                    add(node, share)
    # Groups open and close with the strongest papers (step 9); pages stay in order within each.
    strength = list(dict.fromkeys(item.node.metadata["document_id"] for item in nodes))
    groups = {document: rank for rank, document in enumerate(ends_first(strength))}
    ordered = sorted(
        chosen.values(),
        key=lambda item: (groups.get(str(item.document_id), 0), item.page, item.ordinal),
    )
    return [replace(item, handle=f"S{number}") for number, item in enumerate(ordered, start=1)]
