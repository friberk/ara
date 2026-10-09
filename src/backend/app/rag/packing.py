"""Evidence packing by real tokens, with short `[S#]` handles in document order (ARA-073)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from uuid import UUID

from llama_index.core.schema import BaseNode, NodeWithScore

from app.integrations.tokens import TokenCounter

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


def render_evidence(passages: Sequence[Passage]) -> str:
    return SEPARATOR.join(item.render() for item in passages)


def pack_evidence(
    nodes: Sequence[NodeWithScore],
    *,
    budget: int,
    counter: TokenCounter,
    neighbours: Mapping[str, Sequence[BaseNode]] | None = None,
    max_passages: int = 16,
) -> list[Passage]:
    """Most relevant first, then same-section neighbours while budget remains.

    A passage that does not fit is skipped whole, never truncated. Each one is costed with the
    widest handle and its separator, so the rendered evidence stays within `budget`.
    """
    widest = f"S{max_passages}"
    separator = counter.count(SEPARATOR)
    chosen: dict[str, Passage] = {}
    remaining = budget

    def add(node: BaseNode) -> None:
        nonlocal remaining
        if node.node_id in chosen or len(chosen) >= max_passages:
            return
        candidate = node_passage(node, widest)
        size = counter.count(candidate.render()) + separator
        if size <= remaining:
            chosen[node.node_id] = candidate
            remaining -= size

    for item in nodes:
        add(item.node)
    for key in list(chosen):
        for neighbour in (neighbours or {}).get(key, ()):
            add(neighbour)
    ordered = sorted(chosen.values(), key=lambda item: (item.page, item.ordinal))
    return [replace(item, handle=f"S{number}") for number, item in enumerate(ordered, start=1)]
